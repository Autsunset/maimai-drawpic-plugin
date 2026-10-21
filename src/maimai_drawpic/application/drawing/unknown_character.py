"""未知角色的联网查证。

群友可能让 bot 画库里没有的虚拟主播。这里在绘制前搜一次外观资料，再让 LLM
把中文描述压成英文提示词标签，交给图像模型。

约束：
  - 只在内置库没命中时才走这条路，避免每次绘图都联网。
  - 搜索结果没提到外观（发色/瞳色/萌点等）就放弃，宁可不补也不要瞎编。
  - 任何一步失败都返回空串，让绘图照常进行，不能因为查证失败就画不出来。
"""

from __future__ import annotations

import re
from typing import Any

# 只有提示词里出现这些词，才认为用户真的在要求画某个角色。
DRAW_INTENT_PATTERN = re.compile(r"画|绘|生成|来一张|来张|出图|立绘")

# 结果必须是逗号分隔的英文标签，且不能残留非 ASCII 字符。
NON_ASCII_PATTERN = re.compile(r"[^\x00-\x7f]")

APPEARANCE_TRANSLATE_PROMPT = (
    "你是图像生成提示词的整理器。下面是从网上搜到的某个虚拟主播的外观资料，"
    "请把外观特征提炼成可直接用于 Stable Diffusion / Qwen-Image 的英文标签。\n"
    "要求：\n"
    "1. 只保留外观：发色、发型、瞳色、耳朵尾巴等非人特征、体型、气质。\n"
    "2. 不要写服装、不要写场景、不要写性格故事、不要写身高体重数字。\n"
    "3. 只用英文小写单词和英文逗号分隔，不要任何中文或 Markdown。\n"
    "4. 以 1girl, solo 开头。\n"
    "5. 资料没提到的特征不要编造。\n"
    "6. 只输出一行标签。\n"
    "\n"
    "角色名：{name}\n"
    "外观资料：\n{material}"
)


class UnknownCharacterMixin:
    """未知角色的联网查证职责。"""

    def should_lookup_unknown_character(self, prompt: str) -> bool:
        """判断是否值得为这个提示词联网查角色外观。"""

        if not prompt or not prompt.strip():
            return False
        if not DRAW_INTENT_PATTERN.search(prompt):
            return False
        # 提示词已经很长时，多半用户自己写了详细描述，不需要再补。
        return len(prompt.strip()) <= 60

    async def lookup_character_appearance(
        self,
        enhancer: Any,
        name: str,
        task_id: str = "",
    ) -> str:
        """搜索角色外观并转成英文标签；任何失败都返回空串。"""

        try:
            result = await __import__("asyncio").to_thread(enhancer.lookup_appearance, name)
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.warning(
                "角色外观搜索失败: task_id=%s name=%s error=%s", task_id, name, exc
            )
            return ""

        if not result.ok:
            self.ctx.logger.info(
                "角色外观未查到，按原提示词绘制: task_id=%s name=%s reason=%s",
                task_id,
                name,
                result.error,
            )
            return ""

        labels = await self._translate_appearance_to_labels(name, result.text)
        if labels:
            self.ctx.logger.info(
                "未知角色形象已补全: task_id=%s name=%s labels=%s",
                task_id,
                name,
                labels[:160],
            )
        return labels

    async def _translate_appearance_to_labels(self, name: str, material: str) -> str:
        """让 LLM 把中文外观资料压成英文标签。"""

        prompt = APPEARANCE_TRANSLATE_PROMPT.format(name=name, material=material[:800])
        for attempt in range(2):
            try:
                response = await self.ctx.llm.generate(
                    prompt,
                    model="replyer",
                    temperature=0.0,
                    max_tokens=300,
                )
            except Exception as exc:  # noqa: BLE001
                self.ctx.logger.warning("角色标签翻译失败: name=%s error=%s", name, exc)
                return ""

            text = self._extract_llm_text(response)
            text = self._normalize_labels(text)
            if text and not NON_ASCII_PATTERN.search(text) and len(text) >= 10:
                return text
            if attempt == 1:
                break
        return ""

    @staticmethod
    def _extract_llm_text(response: Any) -> str:
        """从 LLM 响应里取出正文，兼容 dict 与字符串两种返回。"""

        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            for key in ("content", "text", "response", "message"):
                value = response.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            choices = response.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message") or {}
                    if isinstance(message, dict) and isinstance(message.get("content"), str):
                        return message["content"]
        return str(response or "")

    @staticmethod
    def _normalize_labels(text: str) -> str:
        """清理包装符号，统一成逗号分隔的单行标签。"""

        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)
        cleaned = cleaned.strip().strip("\"'`").strip()
        cleaned = re.sub(r"\s*\n\s*", ", ", cleaned)
        cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        return cleaned.strip(" ,")
