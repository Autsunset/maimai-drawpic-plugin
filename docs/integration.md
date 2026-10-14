# 当前 MaiBot 实例内的插件联动

绘图插件 ID：`maimai-drawpic-plugin`。以下 API 版本均为 `1`。调用由 SDK 经当前 Host 转发，插件不创建 HTTP 路由、端口或跨实例客户端，不需要配置令牌。

调用方的 manifest 需要声明 `api.call`；如需发现接口，再按需声明 `api.list` 或 `api.get`。建议使用完整 API 名称，避免短名冲突。

## 提交与查询

```python
from typing import Any, Dict
import asyncio

async def call_drawpic(self, name: str, **kwargs: Any) -> Dict[str, Any]:
    response = await self.ctx.api.call(
        f"maimai-drawpic-plugin.{name}", version="1", **kwargs
    )
    # 当前 Host 对 SDK API 调用返回 success/result 包装。
    if not response["success"]:
        raise RuntimeError(response["error"])
    return response["result"]

async def draw_and_wait(self, prompt: str, request_id: str) -> Dict[str, Any]:
    submitted = await call_drawpic(
        self, "drawpic_submit", prompt=prompt, request_id=request_id
    )
    # 只返回任务 ID，生成与审核在后台继续。请限制轮询频率和总等待时间。
    for _ in range(120):
        result = await call_drawpic(self, "drawpic_task", task_id=submitted["task_id"])
        if result["status"] in {"completed", "failed", "rejected"}:
            return result
        await asyncio.sleep(5)
    raise TimeoutError(f"绘图仍在执行: {submitted['task_id']}")
```

上例普通函数的 `self` 是调用方插件。超时后保留任务 ID 继续查询。提交重试应使用相同 `request_id` 与完全相同的参数；同 ID 不同参数会被拒绝。幂等范围为保留的任务记录，当前最多 500 条，不是永久任务键。

## API 一览

| 名称 | 参数 | 主要返回 |
| --- | --- | --- |
| `drawpic_models` | 无 | `models`：名称、平台实例名、上游模型名、`draw`/`edit_image` 能力和编辑限制原因；`default_model` |
| `drawpic_submit` | 见下表 | `task_id`、`reused` |
| `drawpic_task` | `task_id` | 状态、模型、平台、任务类型、消息、时间、发送数量、图片元数据 |
| `drawpic_tasks` | `page=1`、`status=""`、`search=""` | `items`、`total`、`page`、`page_size=12`、状态计数 `counts` |
| `drawpic_image` | `task_id`、`index=0`、`kind="preview"`、`offset=0` | 缩略图/预览的 `data_url`，或原图分块 |
| `drawpic_cancel` | `task_id` | `task_id`、`cancelled` |
| `drawpic_presets` | `operation="list"`、`name=""`、`preset_json=""` | 预设列表、单个预设或保存结果 |

`task_id` 为当前实例生成的 12 位十六进制 ID。不存在的任务、非法 ID、非法状态/页码/图片索引会报错。状态是 `pending`、`running`、`completed`、`failed`、`rejected`；取消后状态为 `failed`，消息为“任务已取消”。查询只读取状态，不执行重新绘图。列表带缩略图，单任务结果不包含原始提示词、平台密钥或内部文件路径。

### drawpic_submit

| 参数 | 默认值与约束 |
| --- | --- |
| `prompt` | 必填字符串，1～16000 字符 |
| `model` | `""` 使用当前默认模型；必须归属已启用平台，优先使用 models 接口返回的完整“实例名 / 模型名” |
| `negative_prompt` | `""`，最多 16000 字符 |
| `style` | `""` 不套用风格；可填写已启用的预设名 |
| `task_type` | `"draw"` 或 `"edit_image"` |
| `stream_id` | `""` 仅保存结果；填写真实聊天流 ID 时发送到聊天并沿用聊天额度规则 |
| `source_images` | `None` 或真实图片 Base64 字符串列表，不接受文件路径；最多 8 张，每张编码最多 8 MiB，总解码大小最多 40 MiB |
| `request_id` | `""` 或 8～80 位字母、数字、下划线、横线，用于安全重试 |

文生图不能附源图，图生图必须附真实源图；能力、数量和本地输入形式在创建任务前校验。要求公网原图 URL 的模型不能从此 Base64 接口发起图生图。只支持 PNG/JPEG/WebP 等实际可解码图片，输出保留经过审核的图片。

不填写 `stream_id` 时仍沿用插件的提示词与图片审核，不扣聊天额度。填写时必须是当前实例已有的聊天流，不要自行计算 session_id。SDK 调用方自行负责用户授权、会话归属和滥用限制；不应把提交、取消或预设写接口无条件提供给普通聊天用户。

### 图片读取

`kind="thumbnail"` 返回小缩略图；`kind="preview"` 返回压缩预览，两者均包含 `data_url`、`index`、`width`、`height`、原文件 `size` 与 `mime`。

`kind="original"` 每次返回最多 192 KiB 原文件的 Base64，字段为 `data`、`offset`、`next_offset`、`size`、`mime`、安全文件名 `filename` 与 `done`。从 0 开始，严格使用返回的 `next_offset`；按顺序拼接到 `done=True`。调用方应限制读取总量并在工作线程中进行文件写入，不阻塞事件循环。索引从 0 开始。

旧任务可能只有状态而没有图片。接口只读取当前实例结果目录的受校验文件，不接受任意路径。网页原图仅提供预览；插件调用方可以把分块内容保存到自己获授的数据目录。

### 预设管理

`operation` 可取 `list`、`get`、`save`、`delete`。`get` 和 `delete` 用 `name` 选择已有预设；`save` 的 `name` 用于选择要替换的旧预设，留空表示新建，`preset_json` 是 JSON 对象字符串。

```python
import json

preset = {
    "name": "水彩",
    "enabled": True,
    "description": "柔和的透明水彩质感",
    "positive_prompt_template": "watercolor, {prompt}",
    "negative_prompt_template": "3d render, {negative_prompt}",
}
await call_drawpic(self, "drawpic_presets", operation="save",
                   preset_json=json.dumps(preset, ensure_ascii=False))
styles = await call_drawpic(self, "drawpic_presets", operation="list")
await call_drawpic(self, "drawpic_presets", operation="delete", name="水彩")
```

预设名 1～80 字符，不区分大小写检查重名，最多 100 个。重命名时传旧名称作为 `name`；不接受未知字段。删除默认风格时会清空默认风格选择。写操作立即持久化并应用于之后的新任务。

## 安全与错误边界

这些公开 API 仅供同一个 Host 管理的可信插件使用，不是用户身份鉴权系统。Host 按调用方插件身份转发，其他 MaiBot 实例无法把自身 SDK 调用转发到此实例。请不要自行搭建网络转发层。

公开接口不暴露平台配置、API Key、代理密码、原始日志或任意文件访问；平台与全局设置修改只绑定到本插件 WebUI 的私有 API。同一类型的平台可有多个命名实例，完整模型名称用于精确选择实例；旧模型短名仅在唯一匹配时可用。任务和源图都限制在当前实例，参数长度、模型能力、源图片、并发和读取分块有固定限制，不增加联动配置项。

参数错误、配置冲突、任务不存在、审核/平台失败应向调用者明确呈现。取消不保证上游平台停止计费；插件重启时会把未完成的旧任务标记为中断。配置变更后，执行中的任务继续使用提交时的服务，之后的新任务使用新配置。

生成图片与源图遵循 README 中的容量与过期清理策略，图片缓存默认 300 MB、日志默认 10 MB，由 MaiBot 插件配置页管理。新图片缓存在 SDK 临时目录，缩略图与预览使用 WebP；`data_url` 自带实际 MIME，调用方不应假定为 JPEG。任务状态可能仍存在而图片已清理，调用方应处理图片不可用；需要长期保存时及时复制到自己获授的数据目录。备选顺序和重试次数由工作台统一配置，公开 API 不能修改宿主网络代理、插件开关或缓存容量。
