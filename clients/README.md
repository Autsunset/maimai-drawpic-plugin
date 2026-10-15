# 独立 DrawingClient

面向其他 MaiBot 插件开发者，封装短 RPC 的提交、查询、分块读取与保存。Python ≥3.12，仅依赖标准库；运行时注入自己的 `ctx.api`，不导入绘图插件内部目录。

## 复制使用

把本目录的 **`maimai_drawing_client/` 整个目录**复制到调用插件的 `vendor/` 中，保留随包的 AGPL-3.0 许可证：

```text
my_plugin/
  plugin.py
  vendor/
    maimai_drawing_client/
      __init__.py
      client.py
      transport.py
      images.py
      models.py
      LICENSE
```

在调用插件中使用显式相对导入：

```python
from .vendor.maimai_drawing_client import DrawingClient

# 在已注入 ctx 的插件后台协程中使用。
client = DrawingClient(self.ctx.api)
result = await client.generate(
    "海边的灯塔，水彩", request_id=saved_request_id, wait_seconds=120
)
```

`saved_request_id` 由调用方在首次请求前持久化；结果中的 task_id 也需要保存。完整运行函数、LLM 工具、图生图和超时恢复见[联动指南](../docs/integration.md)。

这是当前 `feat/webui` 分支提供的正式源码客户端，需要该分支的 **v2 任务接口**；没有宣称已发布到 PyPI，也不要求创建 pyproject.toml。复制代码与服务需要保持协议兼容，不自动回退至 v1。

## 方法

- `submit(prompt, request_id=..., **request)`：短调用，返回 `TaskHandle`，响应未知时保留请求键。
- `generate(..., wait_seconds=120, read_images=True)`：有限总预算内提交、等待并读取图片字节。
- `wait(handle_or_task_id, request_id=..., wait_seconds=120)`：只等待已有任务，不提交。
- `task(task_id)`、`cancel(task_id)`：读取结构化状态或请求取消。
- `read_image(task_id, index=0)`：校验并拼接原图分块。
- `save_image(task_id, destination, index=0, overwrite=False)`：在工作线程中写入调用方指定路径；默认不覆盖。

构造参数：单次 RPC 默认 8 秒（0～30），查询间隔默认 3 秒（0～60），单图上限 64 MiB、单次结果上限 128 MiB。`generate`/`wait` 的总预算需大于 0、最多 3600 秒，包括 RPC、sleep 与取图，不能突破外层组件超时。

保存使用同目录临时文件；默认通过排他硬链接建立目标，需要目标文件系统支持硬链接（常见 NTFS/ext4 支持）。显式 `overwrite=True` 原子替换目标。路径必须由调用方限制在自己的获授目录；不采用上游文件名拼路径。

## 结果与错误

`DrawingResult` 分别提供 `status`、`wait_expired`、`generation_completed`、`results_readable`、`delivery`、`task_id`、`request_id`、`image_references`、`images` 与 `error`。成功取图后读取 `result.images[0].data`；图片字节不会进入默认 repr。

业务终态（拒绝、失败、待确认、图片过期）通过 `result.status/error` 表达。无效提交等明确 API 错误抛 `DrawingError`，含 `code`、`retry_query`、`retry_submit` 和句柄。单独 `task/read_image/save_image` 的 RPC 失败抛 `DrawingTransportError`；提交响应未知返回 `submission_unknown`，不会自动重新提交。

等待结束不取消任务、不换新 request_id；外部取消协程时保留 asyncio 的取消语义。LLM 工具应使用 `submit` 并快速返回，通过后续工具取结果；不要在临近超时的工具中创建无人管理的后台任务。

相关文档：[API 与四类示例](../docs/integration.md) · [用户指南](../docs/usage.md)。
