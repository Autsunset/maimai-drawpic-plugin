"""绘图角色形象补全。

问题：群里常让 bot 画「星瞳」这类角色，但图像模型不认识角色名，会随机生成
（实测把星瞳画成了猫）。模型没有这些角色的知识，翻译或改写都救不回来——唯一
有效办法是在提示词里写清形象特征。

两条路径：
  1. 命中内置角色库：直接追加预先核对过的英文形象标签，快且稳定。
  2. 库中没有：用本地 SearXNG 搜一次该角色的外观描述，提炼成标签再画画。

补全必须发生在英文改写之前，否则中文角色名会被翻成拼音，信息量更少。

形象描述用英文：魔搭等渠道不做中文改写，英文标签是图像模型最稳的表达方式。
服装不写进角色库——用户说「穿红色衣服」时，衣服由中文原话交给模型。
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class CharacterProfile:
    """一个可识别的角色及其形象补全文本。"""

    key: str
    aliases: tuple[str, ...]
    appearance: str
    # 判断提示词是否已经补过本角色的唯一片段：取角色罗马名。
    # 不能用 appearance 的某一段通用标签，24 个角色的开头都是「1girl, solo」，
    # 拿它当标记会导致提示词里只要出现 solo 就整条跳过补全。
    marker: str
    # 计数标签用的角色类型：girl 计入「Ngirls」，other 计入「Nother」。
    # 非人类吉祥物必须用 other，否则多角色时会把它算成一个女孩。
    kind: str = "girl"
    # 紧邻别名前后出现这些字时，说明它是普通名词而不是角色名，跳过这次命中。
    # 「周围漂浮发光的小星星与星尘」里的「小星星」是背景星光；「小星星们」指粉丝群体。
    blocked_before: tuple[str, ...] = ()
    blocked_after: tuple[str, ...] = ()
    # 别名所在短语（逗号/句号分隔）里出现这些词时跳过命中。用来区分
    # 「周围漂浮发光的小星星」（星光）和「一个拟人化的小星星」（吉祥物）——
    # 两者的前一个字都是「的」，只能看更远的修饰词。
    blocked_clause_before: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# 内置角色库
#
# 优先核对本人 B 站头像、直播间形象与官方设定图，依据见 docs/character-appearance-audit.md。
# 不把特殊表情、限定服装或某一套皮肤的配件混进默认外貌；服装由用户指定。
# ---------------------------------------------------------------------------

PROFILES: tuple[CharacterProfile, ...] = (
    CharacterProfile(
        key="星瞳",
        aliases=("星瞳", "xingtong", "xing tong", "馬星瞳", "马星瞳"),
        marker="Xing Tong (QQ Xuanwu)",
        appearance=(
            "1girl, solo, Xing Tong (QQ Xuanwu) virtual idol, "
            "(silver white short hair:1.4), short bob hair, ahoge, "
            "(bright blue eyes:1.3), clear azure pupils, fair skin, "
            "gentle cute expression, slender petite figure, idol stage presence"
        ),
    ),
    # ---- A-SOUL ----
    CharacterProfile(
        key="嘉然",
        aliases=("嘉然", "diana", "嘉然Diana", "然然", "嘉然小姐"),
        marker="Diana (A-SOUL)",
        appearance=(
            "1girl, solo, Diana (A-SOUL) virtual idol, warm light brown long hair, soft peach-pink "
            "hair tips, bright blue eyes, ahoge, small star hair ornament"
        ),
    ),
    CharacterProfile(
        key="向晚",
        aliases=("向晚", "ava", "向晚Ava", "晚晚"),
        marker="Ava (A-SOUL)",
        appearance=(
            "1girl, solo, Ava (A-SOUL) virtual idol, lavender purple long hair, high twin tails "
            "with gently curled ends, light blue eyes, side-swept bangs"
        ),
    ),
    CharacterProfile(
        key="贝拉",
        aliases=("贝拉", "bella", "贝拉Bella", "拉姐"),
        marker="Bella (A-SOUL)",
        appearance=(
            "1girl, solo, Bella (A-SOUL) virtual idol, dark indigo purple hair, long straight "
            "hair, violet eyes, blunt bangs"
        ),
    ),
    CharacterProfile(
        key="乃琳",
        aliases=("乃琳", "eileen", "乃琳Eileen"),
        marker="Eileen (A-SOUL)",
        appearance=(
            "1girl, solo, Eileen (A-SOUL) virtual idol, pale ash-blonde silvery-beige hair, long "
            "softly wavy hair, clear blue eyes, side-parted bangs"
        ),
    ),
    CharacterProfile(
        key="心宜",
        aliases=("心宜", "心宜不是心仪"),
        marker="Fiona (A-SOUL)",
        appearance=(
            "1girl, solo, Fiona (A-SOUL) virtual idol, bright pink short bob hair, slightly wavy "
            "ends, pink eyes, small metal hair clips"
        ),
    ),
    CharacterProfile(
        key="思诺",
        aliases=("思诺", "思诺 snow"),
        marker="Gladys (A-SOUL)",
        appearance=(
            "1girl, solo, Gladys (A-SOUL) virtual idol, navy blue hair, long straight hair, blunt "
            "bangs, amber gold eyes, thin-framed glasses"
        ),
    ),
    # ---- 四禧丸子（B 站虚拟偶像女团）----
    CharacterProfile(
        key="恬豆",
        aliases=("恬豆", "bekki", "恬豆Bekki", "恬豆发芽了"),
        marker="Bekki (Si Xi Wanzi)",
        appearance=(
            "1girl, solo, Bekki (Si Xi Wanzi) virtual idol, light sky-blue shoulder-length hair, "
            "large curled forelock forming a spiral above the forehead, bright blue eyes"
        ),
    ),
    CharacterProfile(
        key="梨安",
        aliases=("梨安", "lian", "梨安Lian"),
        marker="Lian (Si Xi Wanzi)",
        appearance=(
            "1girl, solo, Lian (Si Xi Wanzi) virtual idol, silvery white long hair, rose pink "
            "eyes, straight bangs"
        ),
    ),
    CharacterProfile(
        key="沐霂",
        aliases=("沐霂", "queenie", "沐霂Queenie", "沐霂是MUMU呀"),
        marker="Queenie (Si Xi Wanzi)",
        appearance=(
            "1girl, solo, Queenie (Si Xi Wanzi) virtual idol, milk-tea light brown long hair, teal "
            "green eyes, a thin side braid, softly curved bangs"
        ),
    ),
    CharacterProfile(
        key="又一",
        aliases=("又一", "yoyi", "又一Yoyi"),
        marker="Yoyi (Si Xi Wanzi)",
        appearance=(
            "1girl, solo, Yoyi (Si Xi Wanzi) virtual idol, golden blonde long hair, twin tails, a "
            "cyan blue accent streak, amber golden eyes"
        ),
    ),
    # ---- 个人势 / 其他国内 B 站 VUP ----
    CharacterProfile(
        key="雫lulu",
        aliases=("雫lulu", "雫るる", "lulu", "雫露露", "雫Lulu", "露胖"),
        marker="Shizuku Lulu",
        appearance=(
            "1girl, solo, Shizuku Lulu virtual streamer, silvery white hair, long wavy hair in low "
            "twin tails, blue aqua eyes, soft bangs, butterfly hair clip"
        ),
    ),
    CharacterProfile(
        key="永雏塔菲",
        aliases=("永雏塔菲", "塔菲", "taffy", "永雛タフィー", "Ace Taffy"),
        marker="Ace Taffy",
        appearance=(
            "1girl, solo, Ace Taffy virtual idol, pastel pink hair, shoulder-length layered hair "
            "with a small side ponytail, multicolored highlights across the bangs, golden amber "
            "eyes, ahoge, crossed hairpins"
        ),
    ),
    # ---- 虚环（腾讯 CDD 的 V 圈养成游戏）登场主播 ----
    CharacterProfile(
        key="七海",
        aliases=("七海", "七海Nana7mi", "Nana7mi", "海子姐", "七海娜娜米"),
        marker="Nanami (VirtuaReal)",
        appearance=(
            "1girl, solo, Nanami (VirtuaReal) virtual streamer, brown hair, amber golden eyes, "
            "straight bangs, crossed hair clips, shark-themed design"
        ),
    ),
    CharacterProfile(
        key="阿梓",
        aliases=("阿梓", "阿梓Azusa", "Azusa", "阿梓从小就很可爱"),
        marker="Azusa",
        appearance=(
            "1girl, solo, Azusa virtual streamer, lavender blue long hair, twin tails, golden "
            "orange eyes, soft blunt bangs"
        ),
    ),
    CharacterProfile(
        key="早稻叽",
        aliases=("早稻叽", "阿叽"),
        marker="Waseda Ji",
        appearance=(
            "1girl, solo, Waseda Ji virtual streamer, sakura pink hair, braided twin tails, "
            "heterochromia, character's right eye golden and left eye pinkish red, small devil "
            "motif"
        ),
    ),
    CharacterProfile(
        key="艾尔莎",
        aliases=("艾尔莎", "艾尔莎Elza", "Elza"),
        marker="Elza Hodophilax York",
        appearance=(
            "1girl, solo, Elza Hodophilax York virtual streamer, icy light blue long wavy hair, "
            "golden amber eyes, fluffy wolf ears"
        ),
    ),
    CharacterProfile(
        key="菜菜子",
        aliases=("菜菜子", "菜菜子Nanako", "Nanako"),
        marker="Nanako",
        appearance=(
            "1girl, solo, Nanako virtual streamer, silvery white hair, short hair with curled side "
            "locks, pale gray-blue eyes"
        ),
    ),
    CharacterProfile(
        key="中国绊爱",
        aliases=("中国绊爱", "中國絆愛", "爱哥", "中國愛"),
        marker="Kizuna AI China",
        appearance=(
            "1girl, solo, Kizuna AI China virtual idol, dark brown long hair, blue teal eyes, pink "
            "looped ribbon headband"
        ),
    ),
    CharacterProfile(
        key="扇宝",
        aliases=("扇宝",),
        marker="Shanbao",
        appearance=(
            "1girl, solo, Shanbao virtual streamer, "
            "peach pink hair, long straight hair, red eyes, "
            "signature fan-shaped hair ornament, "
            "lively bright expression, idol stage presence"
        ),
    ),
    CharacterProfile(
        key="东爱璃",
        aliases=("东爱璃", "东爱璃Lovely", "Agari Raburi", "Lovely"),
        marker="Agari Raburi (Lovely)",
        appearance=(
            "1girl, solo, Agari Raburi (Lovely) virtual streamer, dark brown long hair, twin "
            "tails, pink inner hair and pink-tinted ends, bright blue eyes, choppy bangs, ahoge"
        ),
    ),
    CharacterProfile(
        key="白神遥",
        aliases=("白神遥", "白神遥Haruka", "Haruka"),
        marker="Shirakami Haruka",
        appearance=(
            "1girl, solo, Shirakami Haruka virtual streamer, fluffy short bob hair, white hair "
            "fading to pastel pink at the tips, wine red eyes, round seal hair clip"
        ),
    ),
    CharacterProfile(
        key="牧牧白",
        aliases=("牧牧白", "牧牧白miiu", "miiu"),
        marker="Mumubai (Miiu)",
        appearance=(
            "1girl, solo, Mumubai (Miiu) virtual streamer, rose pink long hair, turquoise blue "
            "eyes, small side hair bundle, ahoge"
        ),
    ),
    CharacterProfile(
        key="花花",
        aliases=("花花", "花花Haya", "Haya"),
        marker="Hana (Haya)",
        appearance=(
            "1girl, solo, Hana (Haya) virtual streamer, warm brown long softly wavy hair, violet "
            "purple eyes, side-swept bangs"
        ),
    ),
    # ---- 星瞳粉丝吉祥物 ----
    # 不是人类角色：脑袋是黄色五角星，身体是正常形状、整体黄色的小吉祥物。
    # kind="other" 让多角色计数写成 1girl+1other，而不是把它算成第二个女孩。
    #
    # 这条是角色库里唯一写死服装的：用户 2026-10-22 明确要求吉祥物要穿衣服，
    # 只写「黄色身体」时模型会画成没穿衣服的黄色人形。
    CharacterProfile(
        key="小星星",
        aliases=("小星星",),
        marker="Xiao Xingxing",
        appearance=(
            "1other, Xiao Xingxing mascot, "
            "(big yellow five-pointed star head:1.4), "
            "the head is a large flat five-pointed star shape, "
            "(all-yellow skin:1.3), normal humanoid body shape with yellow skin, "
            "wearing clothes, a small casual T-shirt and shorts on the body, "
            "simple dot eyes on the star face, cute mascot design, "
            "flat cel-shaded cartoon style"
        ),
        kind="other",
        # 「小星星们」「星星们」指粉丝群体；「漂浮发光的小星星」「闪的小星星」是背景星光，
        # 「小星星和星尘」同理。这些都不是要画吉祥物本人。注意不能把「和」「与」
        # 之类连词放进 blocked_after：「小星星和星瞳」是正经的双角色请求。
        # 「的」不在这里：它既出现在「漂浮的小星星」（背景星光），也出现在
        # 「拟人化的小星星」（要画的吉祥物），交给 blocked_clause_before 按修饰词判断。
        blocked_before=("着", "闪", "亮", "满", "缀", "挂", "飘", "落"),
        blocked_after=("们",),
        blocked_clause_before=("漂浮", "飘浮", "飘着", "发光", "闪烁", "闪亮", "洒满", "布满", "缀满", "挂满", "漫天", "满天", "星尘", "星光", "夜空", "夜幕"),
    ),
)
DEFAULT_PROFILES = PROFILES


# ---------------------------------------------------------------------------
# 别名匹配：中文没有词边界，必须防「花花绿绿」这类误命中
# ---------------------------------------------------------------------------

# 两字中文别名后面紧跟这些字时，说明它是普通词语的一部分，不是角色名。
# 例：「画一个花花绿绿的春日风景」里的「花花」、「又一个气球」里的「又一」、
# 「七海相连」里的「七海」。
#
# 这里刻意用「黑名单」而不是「白名单」：白名单要穷举角色名后面所有合法的
# 接续字（正、今、刚、已……），漏一个就会把「星瞳正在唱歌」判成没提角色，
# 结果画出一只猫——漏检的代价远大于误检。黑名单只需覆盖真正会组成常用词的
# 那几个后缀，万一误判，最坏也只是多贴一段形象标签。
_ALIAS_BLOCK_SUFFIX = frozenset({"绿", "草", "界", "个", "次", "相", "起", "样"})


# ---------------------------------------------------------------------------
# 联网查证：库里没有的角色，先搜一下长什么样
# ---------------------------------------------------------------------------

# 只有命中最近一条用户消息里的这些词，才认为是在要求画某个角色。
# 避免把普通聊天里的专有名词当成角色名去搜。
_DRAW_INTENT = re.compile(r"画|绘|生成|来一张|来张|出图|立绘|顺便画", re.IGNORECASE)

# 猜测角色名前先剥掉的绘图动词与量词，否则「画」「绘」会被当成名字的一部分。
_DRAW_VERBS = re.compile(
    r"(顺便)?(帮我|给我|可以|能不能)?\s*"
    r"(画一个|画个|画一张|画张|画一下|画|绘一个|绘个|绘制|生成|来一张|来张|出图|立绘)"
    r"|一[个张只支幅]|一下",
    re.IGNORECASE,
)

# 角色名候选：2-12 个中文/日文字符，或英文专名。
_NAME_CANDIDATE = re.compile(r"[一-鿿぀-ヿA-Za-z][一-鿿぀-ヿA-Za-z0-9·]{1,11}")

# 明确不是角色名的常见词，命中就跳过，避免无谓搜索。
_STOPWORDS = frozenset(
    {
        "图片", "画图", "绘图", "立绘", "一张", "生成", "帮我", "可以", "什么",
        "怎么", "为什么", "这个", "那个", "一下", "有没有", "是不是", "能不能",
        "好看", "可爱", "谢谢", "你好", "大家", "我们", "他们", "你们", "自己",
    }
)

_APPEARANCE_HINTS = (
    "发色", "头发", "发型", "瞳色", "眼睛", "身高", "萌点", "形象", "外观", "服装",
)

# 明显是普通名词而非专名的词，命中就不当角色名去搜。
_GENERIC_NOUN = re.compile(
    r"^(朵|只|个|张|幅|片|些|么|的|了|和|与|在|是)"
    r"|^(花|猫|狗|鸟|树|山|水|天|云|风景|人|女孩|男孩|女生|男生|妹子|帅哥)$"
)


@dataclass
class SearchResult:
    ok: bool
    text: str = ""
    error: str = ""


class SearxngClient:
    """调用容器网络内的 SearXNG，取回纯文本摘要。"""

    def __init__(self, base_url: str = "http://searxng:8080", timeout: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def search(self, query: str, max_results: int = 5) -> SearchResult:
        params = urllib.parse.urlencode(
            {"q": query, "format": "json", "language": "zh-CN"}
        )
        url = f"{self.base_url}/search?{params}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "MaiBot-Drawpic/1.0", "Accept": "application/json"},
        )
        try:
            # 本地 SearXNG 在国内网络内，不能走代理；显式禁用以免继承环境代理。
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            return SearchResult(ok=False, error=str(exc)[:200])

        results = payload.get("results") or []
        chunks: list[str] = []
        for item in results[:max_results]:
            title = str(item.get("title") or "").strip()
            content = str(item.get("content") or "").strip()
            if title or content:
                chunks.append(f"{title} {content}".strip())
        if not chunks:
            return SearchResult(ok=False, error="搜索结果为空")
        return SearchResult(ok=True, text="\n".join(chunks)[:2000])


class CharacterPromptEnhancer:
    """按关键词把角色形象追加到提示词。"""

    def __init__(
        self,
        profiles: Iterable[CharacterProfile] = DEFAULT_PROFILES,
        searcher: Optional[SearxngClient] = None,
    ) -> None:
        self._profiles: Sequence[CharacterProfile] = tuple(profiles)
        self._patterns: list[tuple[CharacterProfile, re.Pattern[str]]] = []
        for profile in self._profiles:
            alternation = "|".join(_alias_pattern(a) for a in profile.aliases)
            self._patterns.append((profile, re.compile(alternation, re.IGNORECASE)))
        self._searcher = searcher

    # -- 内置库 ---------------------------------------------------------

    def matched_profiles(self, prompt: str) -> list[CharacterProfile]:
        """返回提示词里提到的内置角色，按定义顺序去重。"""

        if not prompt:
            return []
        return [
            profile
            for profile, pattern in self._patterns
            if self._has_alias_hit(pattern, prompt, profile)
        ]

    def enhance(self, prompt: str) -> tuple[str, list[str]]:
        """补全内置角色。返回补全后的提示词和命中的角色名。"""

        profiles = self.matched_profiles(prompt)
        if not profiles:
            return prompt, []

        additions: list[CharacterProfile] = []
        for profile in profiles:
            if profile.marker and profile.marker.casefold() in prompt.casefold():
                continue
            additions.append(profile)

        if not additions:
            return prompt, [profile.key for profile in profiles]

        merged = ", ".join(
            [
                prompt.strip().rstrip(","),
                _compose_appearance(
                    [profile.appearance for profile in additions],
                    profiles,
                    prompt,
                ),
            ]
        )
        return merged.strip(", "), [profile.key for profile in profiles]

    # -- 联网查证 -------------------------------------------------------

    def guess_unknown_character(self, prompt: str) -> str:
        """从提示词里猜一个可能是角色名的词；猜不出返回空串。

        只有提示词带明确绘图意图时才猜，避免普通聊天触发搜索。做法是先剥掉
        绘图动词和量词，再从剩下的部分里找中文专名——直接在整个句子上匹配会把
        「画」「绘」这些动词一起吞进候选词里。
        """

        if not prompt or not _DRAW_INTENT.search(prompt):
            return ""

        known_aliases = {
            alias.casefold() for profile in self._profiles for alias in profile.aliases
        }

        # 剥掉绘图动词与常见量词，剩下的大概率就是角色名。
        stripped = _DRAW_VERBS.sub(" ", prompt)
        stripped = re.sub(r"[，,。.！!？?、\s]+", " ", stripped)
        # 去掉句末语气词，否则「画个李华吧」会猜出「李华吧」这种带尾巴的名字。
        stripped = re.sub(r"(吧|呢|啊|呀|哦|嘛|啦|哈)+$", "", stripped.strip())

        for match in _NAME_CANDIDATE.finditer(stripped):
            candidate = match.group(0).strip()
            if len(candidate) < 2:
                continue
            if candidate.casefold() in known_aliases:
                continue
            if candidate in _STOPWORDS or candidate.casefold() in _STOPWORDS:
                continue
            if _GENERIC_NOUN.search(candidate):
                continue
            return candidate
        return ""

    def lookup_appearance(self, name: str) -> SearchResult:
        """搜索一个角色的外观，返回可用于提示词的英文标签或空。"""

        if self._searcher is None:
            return SearchResult(ok=False, error="未配置搜索客户端")

        result = self._searcher.search(f"{name} 虚拟主播 形象 发色 瞳色 萌点", max_results=5)
        if not result.ok:
            return result

        if not any(hint in result.text for hint in _APPEARANCE_HINTS):
            return SearchResult(ok=False, error="搜索结果没有外观信息")

        return SearchResult(ok=True, text=self._condense_appearance(name, result.text))

    @staticmethod
    def _condense_appearance(name: str, raw: str) -> str:
        """把搜索原文压成一段精简的中文外观描述，交给 LLM 现场翻译成标签。

        直接截断会丢掉关键特征，所以优先挑含外观关键词的句子。
        """

        sentences = re.split(r"[\n。；;！!？?]", raw)
        picked = [s.strip() for s in sentences if any(h in s for h in _APPEARANCE_HINTS)]
        if not picked:
            picked = [raw[:400]]
        return "；".join(picked)[:600]

    @staticmethod
    def _has_alias_hit(pattern: re.Pattern[str], prompt: str, profile: CharacterProfile) -> bool:
        """判断别名是否作为独立的角色名出现，而不是普通词语的一部分。

        中文没有词边界，`re.search` 会让「花花」命中「花花绿绿」。这里逐个
        检查匹配位置前后那个字：如果它会把别名补成另一个常用词（绿、个、相
        等），就跳过继续找下一个匹配。

        先看全局黑名单后缀，再看角色自己的前后缀黑名单（例如「小星星」后面的
        「们」表示粉丝群体，前面的「的」表示背景星光）。
        """

        for match in pattern.finditer(prompt):
            following = prompt[match.end() : match.end() + 1]
            if following and following in _ALIAS_BLOCK_SUFFIX:
                continue
            if following and following in profile.blocked_after:
                continue
            preceding = prompt[match.start() - 1 : match.start()]
            if preceding and preceding in profile.blocked_before:
                continue
            if profile.blocked_clause_before and _clause_before_blocked(prompt, match.start(), profile):
                continue
            return True
        return False


_CLAUSE_PUNCTUATION = frozenset("，,。；;！!？?、\n")


def _clause_before_blocked(
    prompt: str, start: int, profile: CharacterProfile
) -> bool:
    """别名所在短语里，别名之前是否出现了表示背景/星光的修饰词。"""

    index = start - 1
    while index >= 0 and prompt[index] not in _CLAUSE_PUNCTUATION:
        index -= 1
    clause_head = prompt[index + 1 : start]
    return any(word in clause_head for word in profile.blocked_clause_before)


def _compose_appearance(
    additions: Sequence[str],
    profiles: Sequence[CharacterProfile] = (),
    prompt: str = "",
) -> str:
    """把一到多个角色的形象拼成一段，人数标签只出现一次。

    每个角色的 appearance 都以「1girl, solo」开头；两个角色直接拼接会得到
    两句「1girl, solo」，等于告诉模型「单人」两次，模型容易只画一个人。
    多角色时改成对应人数标签并去掉各自的单人标签。

    关键：用户原话里已经出现多角色线索（「和」「两个人」「对拜」等），但只有
    一个角色命中内置库时，绝不能沿用 appearance 自带的 `solo`。这正是
    「画星瞳和小星星对着磕头」出成两个星瞳的原因——库里当时只认得星瞳，
    提示词里仍带着 `1girl, solo`，模型只好把另一个角色也画成星瞳。
    """

    multi_hint = bool(_MULTI_SUBJECT.search(prompt)) if prompt else False
    # 人数按「命中的角色」算，不按「本次新追加的角色」算：已经带过标签的角色
    # 不再重复追加，但它依然在画面里，漏算会让双人图写成 solo。
    matched_count = len(profiles) if profiles else len(additions)

    if matched_count == 1 and not multi_hint:
        return _emphasize_details(", ".join(additions))

    bodies = _emphasize_details(
        ", ".join(_strip_group_tags(appearance) for appearance in additions)
    )

    if matched_count == 1:
        # 只认出一个角色，但用户明确要画多个人：只给多角色提示，不写人数。
        return f"multiple characters, {bodies}"

    girls = sum(1 for profile in profiles if profile.kind == "girl")
    others = sum(1 for profile in profiles if profile.kind != "girl")
    if not profiles:
        # 兼容只传 additions 的老调用：全部按 girls 计数。
        girls = len(additions)
    count_tags: list[str] = []
    if girls:
        count_tags.append("1girl" if girls == 1 else f"{girls}girls")
    if others:
        count_tags.append("1other" if others == 1 else f"{others}others")
    count_tags.append("multiple characters")
    return f"{', '.join(count_tags)}, {bodies}"


def _strip_group_tags(appearance: str) -> str:
    """去掉人数与 solo 标签，只留角色本身的特征。"""

    tags = [tag.strip() for tag in appearance.split(",")]
    kept = [tag for tag in tags if tag.casefold() not in _GROUP_TAGS]
    return ", ".join(kept)


# 角色的「萌点」标签：单个词，但决定像不像本人。模型认得这些标签，可它们
# 夹在几十个标签中间时权重会被稀释，出图时稳定出现和偶尔出现各占一半。
# 这里把每个换成「权重 + 自解释英文」，让模型无论是否认识标签都能画对。
#
# 实测（Qwen-Image-2.1-Turbo，同一提示词连出 4 张）：写成裸 ahoge 时 3/4 有
# 呆毛，加权重并补一句描述后稳定出现，且翘得更明显。
_FEATURE_HINTS: dict[str, str] = {
    "ahoge": "(ahoge:1.3), one strand of hair sticking up from the top of head",
    "hair ornament": "(hair ornament:1.2), decorative hair accessory",
    "hair ribbon": "(hair ribbon:1.2), ribbon tied in the hair",
    "hair band": "(hairband:1.2), headband on head",
    "deer antlers": "(deer antlers:1.3), antlers growing from head",
    "spiral eyes": "(spiral eyes:1.2), swirled hypnotic eyes",
    "goggles on head": "(goggles on head:1.2), goggles resting on top of head",
    "single side braid": "(single side braid:1.2), thin braid on one side of head",
    "twin tails": "(twintails:1.2), hair tied into two tails",
    "drill twin tails": "(drill twintails:1.3), spiral drill-shaped twin tails",
    # 用户只让画吉祥物时，模型会沿用星瞳的银发/蓝眼模板；显式写明「没有头发」
    # 才对。
    "xiao xingxing mascot": (
        "Xiao Xingxing mascot, (star-headed mascot with no hair on head:1.2)"
    ),
}


def _emphasize_details(appearance: str) -> str:
    """给决定性萌点标签加权，并补一句自解释描述。

    只改标签文本，不改角色库：24 个角色共用同一套规则，新增角色自动生效。
    已经是权重写法（含括号或冒号）的标签原样保留，避免重复加权。
    """

    tags = [tag.strip() for tag in appearance.split(",")]
    result: list[str] = []
    for tag in tags:
        if not tag:
            continue
        if "(" in tag or ":" in tag:
            result.append(tag)
            continue
        replacement = _FEATURE_HINTS.get(tag.casefold())
        result.append(replacement if replacement else tag)
    return ", ".join(result)


_GROUP_TAGS = frozenset(
    {
        "1girl", "1boy", "1other", "2girls", "2boys", "2others",
        "solo", "multiple girls", "multiple boys", "multiple others",
        "multiple characters", "2people", "two characters",
    }
)


# 用户原话里表明「画面不止一个人」的线索。用于纠正只命中一个角色时角色库
# 自带的 `solo`：否则模型会把用户点名的第二个角色也画成本人。
#
# 刻意不收裸的「和」「与」「跟」：「穿着和服」「与」出现在普通句子里的概率
# 太高，误判成双人会让单人立绘变两个人。只收明确指向两人的词。
_MULTI_SUBJECT = re.compile(
    r"两人|俩人|两个人|二人|双人|双方|互相|对拜|对视|拥抱|牵手|"
    r"合照|合影|并肩|各自|一起|分别在|两个人",
    re.IGNORECASE,
)


def _alias_pattern(alias: str) -> str:
    """把别名编译成不区分大小写的匹配片段；中文不需要词边界。"""

    escaped = re.escape(alias)
    if alias.isascii():
        return rf"\b{escaped}\b"
    return escaped
