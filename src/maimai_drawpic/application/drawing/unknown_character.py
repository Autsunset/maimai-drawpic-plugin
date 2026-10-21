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


# 提示词里描述角色外观的词。合并用户原话与 LLM 改写时，这些词所在的短语
# 一律以用户原话为准——LLM 编造的「长发」不能留下来和角色的「短发」打架。
_APPEARANCE_WORDS = (
    "头发", "发型", "长发", "短发", "卷发", "直发", "马尾", "双马尾", "呆毛",
    "刘海", "发色", "银发", "金发", "黑发", "白发", "棕发", "粉发", "蓝发",
    "瞳", "眼睛", "眼眸", "眼瞳", "瞳孔",
)

# 服装/场景/风格这类短语抽不出来也不该丢，保留 LLM 的版本。
_STYLE_WORDS = (
    "风格", "画风", "构图", "背景", "场景", "氛围", "光", "光晕", "画质",
    "高清", "细节", "插画", "立绘", "服装", "裙", "衣服", "礼服", "配饰",
)


def _split_clauses(text: str) -> list[str]:
    """按中英文标点把提示词切成短语，并去掉 @提及。"""

    cleaned = re.sub(r"@\S+", " ", text)
    return [part.strip() for part in re.split(r"[，,。；;、\n]+", cleaned) if part.strip()]


def _is_appearance_clause(clause: str) -> bool:
    """判断短语是否在描述外貌。"""

    return any(word in clause for word in _APPEARANCE_WORDS)


def _is_style_clause(clause: str) -> bool:
    """判断短语是否在描述风格、服装或场景。"""

    return any(word in clause for word in _STYLE_WORDS)


def _merge_user_words_and_style(user_text: str, llm_prompt: str) -> str:
    """以用户原话为准重建提示词，只保留 LLM 写的风格与场景部分。

    典型场景：用户说「画个星瞳」，LLM 改写成「银白色长发……深蓝礼服……
    星空氛围，高清」。长发和角色库的短发冲突，必须丢掉；礼服、氛围、画质
    是用户没说的有效补充，保留。所以按短语拆开，外貌短语一律以用户原话为准。
    """

    user_clauses = _split_clauses(user_text)
    kept: list[str] = list(user_clauses)
    for clause in _split_clauses(llm_prompt):
        if _is_appearance_clause(clause):
            # 外貌描述可能包含角色名，但用户原话里已经有；整条丢掉。
            continue
        if clause in kept:
            continue
        # 与用户原话高度重合的短语也不要重复。
        if any(clause in existing for existing in kept):
            continue
        kept.append(clause)
    return ", ".join(kept)


class UnknownCharacterMixin:
    """未知角色的联网查证职责。"""

    # -- 用户原话兜底 ---------------------------------------------------

    async def recover_character_from_recent_messages(
        self,
        prompt: str,
        enhancer: Any,
        stream_id: str,
        task_id: str = "",
    ) -> tuple[str, list[str]]:
        """从最近聊天消息里找回被 chat LLM 丢掉的角色名。

        实测问题：群友说「画个星瞳」，chat LLM 把提示词改写成
        「二次元美少女角色立绘，银白色长发……」，「星瞳」三个字直接消失。
        角色库只认名字，名字没了就永远补不上，而且 LLM 自己编的「长发」
        还与角色库的「短发」矛盾，画出来必然走样。

        工具说明已经要求 LLM 原样传原话，但那是软约束。这里在插件层兜底：
        提示词没命中任何内置角色时，读最近几条消息，看用户原话里有没有角色名；
        有就以用户原话为准，用原话重新走一次补全。

        读消息失败、没有历史消息、原话里也没有角色名时，静默返回原提示词。
        """

        try:
            messages = await self._recent_message_texts(stream_id)
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.debug(
                "读取最近消息失败，跳过角色名找回: task_id=%s error=%s", task_id, exc
            )
            return prompt, []

        # 从新到旧找第一条提到内置角色的用户消息。
        for text in reversed(messages):
            if not text:
                continue
            recovered, matched = enhancer.enhance(text)
            if not matched:
                continue
            self.ctx.logger.info(
                "从用户原话找回角色名: task_id=%s characters=%s llm_prompt=%s user_text=%s",
                task_id,
                ",".join(matched),
                prompt[:80],
                text[:80],
            )
            # 以用户原话为基准重建提示词，再补上 LLM 写的风格/场景部分。
            # 直接把原话追在 LLM 的编造描述后面会同时留下「长发」和「短发」。
            merged = _merge_user_words_and_style(text, prompt)
            merged_prompt, merged_matched = enhancer.enhance(merged)
            return merged_prompt, merged_matched or matched
        return prompt, []

    async def _recent_message_texts(self, stream_id: str) -> list[str]:
        """读取最近若干条消息的纯文本，按时间正序返回。"""

        if not stream_id:
            return []
        result = await self.ctx.call_capability(
            "message.get_recent",
            chat_id=stream_id,
            limit=6,
            include_binary_data=False,
        )
        messages = self._unwrap_messages(result)
        texts: list[str] = []
        for message in messages:
            text = self._message_plain_text(message)
            if text:
                texts.append(text)
        return texts

    @staticmethod
    def _unwrap_messages(result: Any) -> list[dict[str, Any]]:
        """兼容运行时包装层，提取消息列表。"""

        if isinstance(result, list):
            return [m for m in result if isinstance(m, dict)]
        if not isinstance(result, dict):
            return []
        for key in ("messages", "result"):
            value = result.get(key)
            if isinstance(value, list):
                return [m for m in value if isinstance(m, dict)]
            if isinstance(value, dict):
                nested = value.get("messages")
                if isinstance(nested, list):
                    return [m for m in nested if isinstance(m, dict)]
        return []

    @staticmethod
    def _message_plain_text(message: dict[str, Any]) -> str:
        """取出消息正文。兼容常见字段名与结构化消息段。"""

        for key in ("plain_text", "text", "content", "message"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                parts = []
                for segment in value:
                    if isinstance(segment, dict):
                        seg_text = segment.get("text") or segment.get("content")
                        if isinstance(seg_text, str):
                            parts.append(seg_text)
                    elif isinstance(segment, str):
                        parts.append(segment)
                joined = "".join(parts).strip()
                if joined:
                    return joined
        return ""

    # -- 联网查证 -------------------------------------------------------

    def should_lookup_unknown_character(self, prompt: str) -> bool:
        """判断是否值得为这个提示词联网查角色外观。

        联网查证慢且不可靠（SearXNG 会把别的角色资料混进来），只在提示词
        **几乎就是一句「画XX」** 时才值得试。用户自己写了详细形象描述时，
        那些描述比搜索结果可信，补一条查来的标签反而可能打架。
        """

        text = (prompt or "").strip()
        if not text:
            return False
        if not DRAW_INTENT_PATTERN.search(text):
            return False
        # 超过 20 字基本就是在描述画面了，不再猜角色名。
        return len(text) <= 20

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
