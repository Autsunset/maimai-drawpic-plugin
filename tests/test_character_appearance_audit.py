"""Regression checks for the 2026-10-25 official-image appearance audit."""

import importlib

import pytest

from test_workspace import _PACKAGE


characters = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.application.drawing.character_prompt")
profiles = {profile.key: profile for profile in characters.PROFILES}
actor_keys = (
    "星瞳", "嘉然", "向晚", "贝拉", "乃琳", "心宜", "思诺",
    "恬豆", "梨安", "沐霂", "又一", "雫lulu", "永雏塔菲",
    "七海", "阿梓", "早稻叽", "艾尔莎", "菜菜子", "中国绊爱",
    "扇宝", "东爱璃", "白神遥", "牧牧白", "花花",
)


@pytest.mark.parametrize("key", actor_keys)
def test_every_audited_actor_still_resolves_and_enriches_once(key):
    enhancer = characters.CharacterPromptEnhancer()
    text, matched = enhancer.enhance(f"画一张{key}的立绘")
    assert matched == [key]
    assert text.count(profiles[key].marker) == 1
    assert profiles[key].marker in profiles[key].appearance
    repeated, matched = enhancer.enhance(text)
    assert repeated == text
    assert matched == [key]


@pytest.mark.parametrize("key,required,forbidden", [
    ("永雏塔菲", ("pastel pink hair", "golden amber eyes", "ahoge", "side ponytail"),
     ("heart-shaped pupils", "spiral eyes", "goggles", "blonde two-tone hair")),
    ("向晚", ("lavender purple", "twin tails", "light blue eyes"), ("drill", "spiral drill")),
    ("贝拉", ("dark indigo purple", "violet eyes"), ("red bow",)),
    ("雫lulu", ("silvery white", "blue aqua eyes"), ("light purple eyes",)),
    ("艾尔莎", ("icy light blue", "golden amber eyes", "wolf ears"), ("ice blue eyes",)),
    ("白神遥", ("white hair fading to pastel pink at the tips", "wine red eyes"), ("pink roots",)),
    ("花花", ("brown", "violet purple eyes"), ("amber brown eyes",)),
])
def test_corrected_core_features_do_not_regress(key, required, forbidden):
    appearance = profiles[key].appearance
    assert all(term in appearance for term in required)
    assert not any(term in appearance for term in forbidden)


def test_xingtong_appearance_is_preserved_exactly():
    assert profiles["星瞳"].appearance == (
        "1girl, solo, Xing Tong (QQ Xuanwu) virtual idol, "
        "(silver white short hair:1.4), short bob hair, ahoge, "
        "(bright blue eyes:1.3), clear azure pupils, fair skin, "
        "gentle cute expression, slender petite figure, idol stage presence"
    )


def test_verified_unchanged_fan_theme_is_preserved():
    appearance = profiles["扇宝"].appearance
    assert "peach pink hair" in appearance
    assert "red eyes" in appearance
    assert "fan-shaped hair ornament" in appearance


def test_asoul_official_romanized_names_match_reference_cards():
    assert profiles["心宜"].marker == "Fiona (A-SOUL)"
    assert profiles["思诺"].marker == "Gladys (A-SOUL)"


def test_audited_defaults_do_not_force_costumes_or_expression_toggles():
    for key in actor_keys:
        appearance = profiles[key].appearance
        assert not any(term in appearance for term in (
            "goggles on head", "bow tie", "thigh ring", "oversized long sleeves",
            "future-style idol outfit", "heart-shaped pupils", "spiral eyes",
            "158cm", "loli-like", "pink theme color",
        )), key


def test_user_requested_costume_and_optional_accessory_are_not_removed():
    prompt = "画塔菲，戴护目镜，穿红色外套"
    text, matched = characters.CharacterPromptEnhancer().enhance(prompt)
    assert matched == ["永雏塔菲"]
    assert text.startswith(prompt)
    assert "goggles on head" not in text
