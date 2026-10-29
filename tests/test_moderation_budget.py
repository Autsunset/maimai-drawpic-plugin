"""Moderation inherits Host budgets without weakening verdict validation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import base64
import importlib

from maibot_sdk.capabilities.llm import LLMCapability
import pytest

from test_workspace import _PACKAGE, DrawpicConfig, image_bytes


moderation = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.application.moderation")
prompts = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.application.drawing.prompts")


def make_service(response, *, enabled=True):
    config = DrawpicConfig(general={
        "prompt_review_enabled": enabled,
        "image_review_enabled": enabled,
        "prompt_review_prompt": "Text policy: {user_prompt}",
        "image_review_prompt": "Image policy: {user_prompt}",
    })
    bridge = SimpleNamespace(call_capability=AsyncMock(return_value=response))
    return moderation.DrawpicModerationService(config, SimpleNamespace(llm=LLMCapability(bridge))), bridge


async def review(service, kind):
    if kind == "prompt":
        return await service.review_prompt("A fictional horse-headed person eating a pomegranate")
    return await service.review_image("A fictional horse-headed person eating a pomegranate", image_bytes())


@pytest.mark.parametrize("kind,task", [("prompt", "replyer"), ("image", "vlm")])
@pytest.mark.parametrize("verdict", ["PASS", "REJECT"])
def test_review_uses_host_budget_and_preserves_structured_verdict(kind, task, verdict):
    service, bridge = make_service({
        "success": True, "response": f"CONCLUSION: {verdict}\nreason: fixture verdict",
        "reasoning": "CONCLUSION: REJECT" if verdict == "PASS" else "CONCLUSION: PASS",
    })
    result = asyncio.run(review(service, kind))
    assert result.passed is (verdict == "PASS")
    assert result.reason == "fixture verdict"
    bridge.call_capability.assert_awaited_once()
    call = bridge.call_capability.await_args
    assert call.args == ("llm.generate",)
    assert call.kwargs["model"] == task
    assert call.kwargs["temperature"] == 0.0
    assert "max_tokens" not in call.kwargs
    if kind == "image":
        content = call.kwargs["prompt"][0]["content"]
        assert "Image policy: " in content[0]["text"]
        assert content[1]["image_format"] == "png"
        assert base64.b64decode(content[1]["image_base64"]) == image_bytes()
    else:
        assert call.kwargs["prompt"].startswith("Text policy: ")


@pytest.mark.parametrize("kind", ["prompt", "image"])
def test_empty_final_response_is_not_replaced_by_reasoning_or_retried(kind):
    service, bridge = make_service({
        "success": True, "response": "", "reasoning": "CONCLUSION: PASS",
    })
    with pytest.raises(RuntimeError, match="审核模型返回了空结果"):
        asyncio.run(review(service, kind))
    bridge.call_capability.assert_awaited_once()


@pytest.mark.parametrize("kind", ["prompt", "image"])
@pytest.mark.parametrize("response", [
    {"success": False, "error": "fixture model failure"},
    {"success": True, "response": "This cannot pass the review."},
    {"success": True, "response": "CONCLUSION: PASS\nCONCLUSION: REJECT"},
])
def test_unavailable_or_invalid_verdict_still_fails_closed(kind, response):
    service, bridge = make_service(response)
    with pytest.raises(RuntimeError):
        asyncio.run(review(service, kind))
    bridge.call_capability.assert_awaited_once()


@pytest.mark.parametrize("kind", ["prompt", "image"])
def test_explicit_disabled_review_does_not_call_the_model(kind):
    service, bridge = make_service({"success": False}, enabled=False)
    result = asyncio.run(review(service, kind))
    assert result.passed and result.raw_response == "SKIPPED"
    bridge.call_capability.assert_not_awaited()


def test_empty_image_review_never_releases_an_image():
    service, bridge = make_service({"success": True, "response": "", "reasoning": "CONCLUSION: PASS"})
    drawing = SimpleNamespace(
        moderation_service=service,
        ctx=SimpleNamespace(logger=SimpleNamespace(warning=lambda *_: None)),
    )
    with pytest.raises(RuntimeError, match="审核模型返回了空结果"):
        asyncio.run(prompts.PromptReviewMixin.filter_reviewed_images(drawing, "fixture", [image_bytes()]))
    bridge.call_capability.assert_awaited_once()
