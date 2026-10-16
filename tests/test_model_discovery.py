"""模型发现与 Agnes 使用隔离 HTTP 服务验证，不调用真实平台。"""

from contextlib import asynccontextmanager
from importlib import import_module
from io import BytesIO
from pathlib import Path
from types import ModuleType
from aiohttp import web
from PIL import Image
import asyncio
import base64
import json
import sys

import pytest

_PACKAGE = "drawpic_discovery_test"
package = ModuleType(_PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules[_PACKAGE] = package
discovery = import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.providers.model_discovery")
agnes = import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.providers.agnes")
storage = import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.storage.platforms")
routing = import_module(f"{_PACKAGE}.src.maimai_drawpic.application.routing")
proxy = discovery.HttpProxySettings.disabled()


@asynccontextmanager
async def server(handler, port):
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", port).start()
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


def test_discovery_uses_saved_or_draft_key_without_writing(tmp_path):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize(storage.DrawpicConfig().model_dump(mode="json"))
    saved = store.save_provider(
        {"kind": "agnes", "name": "Agnes", "config": {"api_key": "saved-fixture-key"}}, store.revision
    )
    before = store.path.read_bytes()
    revision = store.revision
    payload = {"id": saved["id"], "kind": "agnes", "config": {"api_key": "", "base_url": "https://example.test/v1"}}
    assert store.model_discovery_config(payload)["api_key"] == "saved-fixture-key"
    payload["clear_api_key"] = True
    assert store.model_discovery_config(payload)["api_key"] == ""
    payload["config"]["api_key"] = "draft-fixture-key"
    assert store.model_discovery_config(payload)["api_key"] == "draft-fixture-key"
    assert store.revision == revision and store.path.read_bytes() == before
    assert "fixture-key" not in json.dumps(store.public_snapshot())
    with pytest.raises(ValueError, match="类型不匹配"):
        store.model_discovery_config({**payload, "kind": "google"})
    with pytest.raises(ValueError, match="仅接受"):
        store.model_discovery_config({**payload, "config": {"enabled": True}})


def test_openai_and_agnes_model_discovery_is_read_only(unused_tcp_port):
    async def run():
        requests = []

        async def handler(request):
            requests.append((request.method, request.path, request.headers["Authorization"]))
            return web.json_response({"data": [{"id": "agnes-image-2.5-flash"}, {"id": "chat-model"}]})

        async with server(handler, unused_tcp_port) as base:
            for kind in ("openai", "agnes"):
                result = await discovery.fetch_models(kind, {"api_key": "fixture-key", "base_url": base}, proxy)
                assert result["models"] == [
                    {"id": "agnes-image-2.5-flash", "label": "agnes-image-2.5-flash", "image_candidate": True},
                    {"id": "chat-model", "label": "chat-model", "image_candidate": False},
                ]
            assert requests == [("GET", "/v1/models", "Bearer fixture-key")] * 2

    asyncio.run(run())


def test_google_discovery_preserves_pagination_and_header_auth(unused_tcp_port):
    async def run():
        seen = []

        async def handler(request):
            assert request.headers["x-goog-api-key"] == "fixture-key"
            assert "key" not in request.query and request.path == "/v1beta/models"
            seen.append(request.query.get("pageToken", ""))
            return web.json_response(
                {"models": [{"name": "models/gemini-image", "displayName": "Image"}], "nextPageToken": "next"}
                if len(seen) == 1
                else {"models": [{"name": "models/gemini-chat"}]}
            )

        async with server(handler, unused_tcp_port) as base:
            result = await discovery.fetch_models("google", {"base_url": base, "api_key": "fixture-key"}, proxy)
        assert seen == ["", "next"]
        assert [item["id"] for item in result["models"]] == ["gemini-image", "gemini-chat"]

    asyncio.run(run())


def test_aliyun_discovery_keeps_workspace_and_supported_image_families(unused_tcp_port):
    async def run():
        pages = []

        async def handler(request):
            assert request.path == "/workspace/api/v1/models" and request.query["capabilities"] == "IG"
            page = int(request.query["page_no"])
            pages.append(page)
            rows = [{"model": "qwen-image-3.0"}, {"model": "wan-image"}] if page == 1 else [{"model": "z-image-turbo"}]
            return web.json_response({"output": {"models": rows, "total": 3}})

        async with server(handler, unused_tcp_port) as base:
            result = await discovery.fetch_models(
                "aliyun", {"base_url": base + "/workspace/api/v1", "api_key": "fixture-key"}, proxy
            )
        assert pages == [1, 2]
        assert [item["id"] for item in result["models"]] == ["qwen-image-3.0", "z-image-turbo"]

    asyncio.run(run())


def test_discovery_reports_errors_and_redacts_unsaved_key(unused_tcp_port):
    async def run():
        async def handler(request):
            return web.json_response({"error": "fixture-secret-token"}, status=401)

        async with server(handler, unused_tcp_port) as base:
            with pytest.raises(ValueError, match="HTTP 401") as error:
                await discovery.fetch_models("agnes", {"base_url": base, "api_key": "fixture-secret-token"}, proxy)
        assert "fixture-secret-token" not in str(error.value)

    asyncio.run(run())


def test_discovery_rejects_broken_pagination_and_missing_lists(unused_tcp_port):
    async def run():
        async def handler(request):
            return web.json_response({"models": [], "nextPageToken": "repeated"})

        async with server(handler, unused_tcp_port) as base:
            with pytest.raises(ValueError, match="重复"):
                await discovery.fetch_models("google", {"base_url": base, "api_key": "fixture-key"}, proxy)
        with pytest.raises(ValueError, match="缺少模型列表"):
            discovery._models("agnes", None, "fixture-key")
        with pytest.raises(ValueError, match="有效的 HTTP"):
            discovery._endpoint("agnes", {"base_url": "https://user:password@example.test/v1"})

    asyncio.run(run())


def test_agnes_generates_and_edits_on_same_endpoint_without_dropping_images(unused_tcp_port):
    async def run():
        image = BytesIO()
        Image.new("RGB", (32, 32), "pink").save(image, "PNG")
        raw = image.getvalue()
        seen = []

        async def handler(request):
            assert request.path == "/v1/images/generations" and request.method == "POST"
            assert request.headers["Authorization"] == "Bearer fixture-key"
            seen.append(await request.json())
            return web.json_response({"data": [{"b64_json": base64.b64encode(raw).decode()}]})

        async with server(handler, unused_tcp_port) as base:
            provider = agnes.AgnesImage("fixture-key", base_url=base, default_size="2K", ratio="16:9")
            assert await provider.generate_images("风景", "agnes-image-2.5-flash") == [raw]
            assert await provider.edit_images("保留人物", "agnes-image-2.5-flash", [raw, raw]) == [raw]
            with pytest.raises(ValueError, match="至少一张"):
                await provider.edit_images("编辑", "agnes-image-2.5-flash", [])
        assert len(seen) == 2
        for payload in seen:
            assert payload["size"] == "2K" and payload["ratio"] == "16:9"
            assert "response_format" not in payload and "image" not in payload and "tags" not in payload
            assert payload["extra_body"]["response_format"] == "b64_json"
        assert "image" not in seen[0]["extra_body"]
        assert len(seen[1]["extra_body"]["image"]) == 2
        assert all(value.startswith("data:image/png;base64,") for value in seen[1]["extra_body"]["image"])

    asyncio.run(run())


def test_agnes_routing_keeps_model_specific_size():
    config = storage.DrawpicConfig()
    config.agnes.model_size_overrides = ["agnes-image-2.0-flash=1024x768"]
    router = routing.ProviderRouter(config)
    provider, kind = router.require_platform_for_model("agnes-image-2.0-flash")
    assert kind == "agnes" and isinstance(provider, agnes.AgnesImage)
    assert router.evaluate_model_task_capability("agnes-image-2.0-flash", "edit_image").allowed
    payload = agnes.build_agnes_payload(
        "画猫",
        "agnes-image-2.0-flash",
        size=provider._resolve_size("agnes-image-2.0-flash"),
        ratio="1:1",
        response_format="url",
        extra_parameters={},
    )
    assert payload["size"] == "1024x768" and "ratio" not in payload
    assert payload["extra_body"] == {"response_format": "url"}
    with pytest.raises(ValueError, match="不能覆盖"):
        agnes.build_agnes_payload(
            "画猫",
            "agnes-image-2.5-flash",
            size="1K",
            ratio="1:1",
            response_format="url",
            extra_parameters={"image": []},
        )
