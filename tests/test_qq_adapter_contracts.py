"""官方 QQ / SnowLuma-NapCat 统一适配器的标准消息与 SDK 发送契约。

对照上游 QQ 12a3194 与 SnowLuma a93a0ad；不运行网关或连接真实 QQ。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from test_drawing_client import DrawingClient, LocalAPI, module
from test_workspace import image_bytes, make_plugin as make_plugin
import asyncio
import base64
import pytest


images = module("interfaces.chat.message_images")
ChatStreamService = module("application.chat.service").ChatStreamService
Unconfirmed = module("application.chat.types").ImageDeliveryUnconfirmedError


@pytest.mark.parametrize("adapter,user_id,group_id", [
    ("qq_official", "41B8E83007B26E6011F3243A5D8ECB3A", "FAE50782C3464EBBCC519DF38F294422"),
    ("qq_official_private", "41B8E83007B26E6011F3243A5D8ECB3A", ""),
    ("qq_official_mapped", "12345", "67890"),
    ("snowluma", "12345", "67890"),
    ("napcat", "12345", "67890"),
])
def test_standard_inbound_identity_images_and_command_prefix(make_plugin, adapter, user_id, group_id):
    message = {
        "message_id": f"{adapter}-fixture", "session_id": "host-owned-session", "platform": "qq",
        "message_info": {"user_info": {"user_id": user_id},
                         "additional_config": {"self_id": "account", "platform_io_account_id": "shared-account"}},
        "raw_message": [
            {"type": "at", "data": {"target_user_id": "bot"}},
            {"type": "text", "data": "/绘图 图生图 一只猫"},
            {"type": "image", "data": "", "binary_data_base64": base64.b64encode(image_bytes()).decode("ascii")},
        ],
    }
    if group_id:
        message["message_info"]["group_info"] = {"group_id": group_id}
    plugin = make_plugin()
    context = plugin._extract_runtime_context(kwargs={"message": message})
    assert context == {"stream_id": "host-owned-session", "platform": "qq", "user_id": user_id, "group_id": group_id}
    assert plugin._extract_text_command_from_raw_message(message) == "/绘图 图生图 一只猫"
    source = images.extract_source_images_from_message(message)
    assert len(source) == 1 and images.decode_image_base64(source[0].base64_data) == image_bytes()
    assert source[0].url == ""  # 两个适配器当前均未在标准图片段中保留原始 URL。


def test_snowluma_quote_lookup_is_scoped_and_does_not_use_preview_as_image():
    async def run():
        images.clear_source_image_cache()
        calls = []
        quoted = {"message_id": "-123456", "raw_message": [{
            "type": "image", "data": "", "binary_data_base64": base64.b64encode(image_bytes()).decode("ascii"),
        }]}
        command = {"raw_message": [{"type": "reply", "data": {
            "target_message_id": "-123456", "target_message_content": "[图片描述：一只猫]",
        }}]}

        async def lookup(capability, **kwargs):
            calls.append((capability, kwargs))
            return {"success": True, "message": quoted}

        ctx = SimpleNamespace(call_capability=lookup)
        try:
            result = await images.collect_command_source_image_inputs(ctx, "actual-session", command)
            assert len(result) == 1 and images.decode_image_base64(result[0].base64_data) == image_bytes()
            assert calls == [("message.get_by_id", {"message_id": "-123456", "chat_id": "actual-session", "include_binary_data": True})]
            assert images.extract_source_images_from_message(command) == []
            # 官方适配器尚未输出引用段，插件不能从图片描述或用户文本伪造引用图。
            assert images.extract_reply_target_message_ids({"raw_message": [{"type": "text", "data": "[图片]"}]}) == []
        finally:
            images.clear_source_image_cache()
    asyncio.run(run())


@pytest.mark.parametrize("outcome", [False, {"sent": False, "message_id": None}, TimeoutError("fixture timeout")])
def test_unconfirmed_multi_image_never_switches_route_or_resends(outcome):
    async def run():
        send = AsyncMock(side_effect=[True, outcome] if isinstance(outcome, Exception) else None)
        if not isinstance(outcome, Exception):
            send.side_effect = [True, outcome]
        service = ChatStreamService(SimpleNamespace(send=SimpleNamespace(image=send), logger=Mock()))
        service.resolve_live_stream_id = AsyncMock(side_effect=["original-session", "different-account-session"])
        with pytest.raises(Unconfirmed) as raised:
            await service.send_generated_images_with_fallback("original-session", [image_bytes()] * 3)
        assert raised.value.sent_count == 1
        assert send.await_count == 2 and service.resolve_live_stream_id.await_count == 1
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["image", "text"])
def test_single_reply_unconfirmed_is_not_retried(kind):
    async def run():
        sender = SimpleNamespace(image=AsyncMock(return_value=False), text=AsyncMock(return_value=False))
        service = ChatStreamService(SimpleNamespace(send=sender, logger=Mock()))
        service.resolve_live_stream_id = AsyncMock(side_effect=["actual-session", "other-session"])
        if kind == "image":
            assert not await service.send_image_bytes_with_fallback(image_bytes(), "actual-session")
        else:
            assert not await service.send_text_with_fallback("fixture", "actual-session")
        assert getattr(sender, kind).await_count == 1
        assert service.resolve_live_stream_id.await_count == 1
    asyncio.run(run())


def test_public_api_uses_existing_session_across_qq_accounts(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            async def streams(platform="qq"):
                return {"success": True, "streams": [
                    {"session_id": "wrong-account", "platform": "qq", "user_id": "12345", "group_id": "67890"},
                    {"session_id": "correct-account", "platform": "qq", "user_id": "12345", "group_id": "67890"},
                ]}

            monkeypatch.setattr(plugin.ctx.chat, "get_all_streams", streams)
            sent = AsyncMock(return_value=True)
            monkeypatch.setattr(plugin.ctx.send, "image", sent)

            async def generate(**kwargs):
                return [image_bytes()]

            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            result = await DrawingClient(LocalAPI(plugin), poll_interval=0.001).generate(
                "cat", request_id="qq-account-request", stream_id="correct-account", wait_seconds=3,
            )
            assert result.status == "completed" and result.delivery["status"] == "sent"
            assert sent.await_count == 1 and sent.call_args.args[1] == "correct-account"
        finally:
            await plugin.on_unload()
    asyncio.run(run())
