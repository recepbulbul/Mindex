"""Forum advice as untrusted data (ADR-6, OWASP LLM01), its weights (C2/C3) and verification.

Pure functions; the runner binds them to the database (`mindex.forum.store`).

- `sanitise`: what a post may say. Unicode is normalised (NFKC), control and format characters
  are dropped, whitespace collapses, `<` and `>` go (so a post cannot forge the
  `<forum_post>` delimiters), absolute prices become `[fiyat]` (`PRICES`), real coin names
  become the experiment's `ASSET_x` codes (`REAL_NAMES`) and the text is cut to
  `POST_MAX_CHARS`.
- `injection_flags`: a simple pattern filter, run on the text as written and as it would be
  stored (`screen`); a flagged post is stored (`flagged`) but never shown to another agent. A
  post that is empty once cleaned is dropped.
- `weigh` (decision-v4): each read post's absolute weight `w` and the mean weighted stance per
  asset, `sum(w * stance) / n`. C2 gives every sender w = 1/2, C3 the reader's Beta trust in the
  sender, so trust matters even for a lone post (decision-v3 normalised the weights per asset,
  which made a single post weigh 1 whatever its sender's record). Exact fractions, rounded once:
  with neutral trust (no verdict yet, w = 1/2) C3 equals C2 bit for bit.
- `verdict`: whether advice held, from the close of its own day `j` and of `j + HORIZON_DAYS`
  only, read through the `MarketView` of the day it is checked (no look-ahead). An exactly
  unchanged close proves neither direction and is not judged.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from fractions import Fraction

from mindex.domain.decision import Asset
from mindex.domain.trust import BetaTrust
from mindex.sim.market import MarketView

HORIZON_DAYS = 5  # advice is judged on the close five days after it was posted
WINDOW_DAYS = 3  # a decision reads posts of the previous three days ...
MAX_READS = 8  # ... at most this many, newest first
POST_MAX_CHARS = 280
# Covers everything `screen` does to a post (patterns and anonymisation). v3: Turkish patterns
# typed without Turkish letters, "Sol" / "s o l" / "B.T.C" as names, absolute prices masked.
FILTER_VERSION = "forum-filter-v3"
EQUAL_WEIGHT = Fraction(1, 2)  # C2: every sender alike (the Beta prior's 0.5)
# Reads happen before the advice is judged, so every reader of a post is known at its verdict.
assert WINDOW_DAYS < HORIZON_DAYS  # noqa: S101


class Stance(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


SIGN = {Stance.BULLISH: 1, Stance.BEARISH: -1, Stance.NEUTRAL: 0}

# ------------------------------------------------------------------ untrusted text

# Real names, as the post-mortem check finds them (`postmortem.lesson.REAL_SYMBOLS`), mapped
# to the asset they name. Kept local: the lesson module imports the LLM agent, which imports
# this module.
_NAMES: tuple[tuple[str, Asset], ...] = (
    ("bitcoin", Asset.BTC),
    ("btc", Asset.BTC),
    ("ether", Asset.ETH),
    ("eth", Asset.ETH),
    ("solana", Asset.SOL),
    ("sol", Asset.SOL),
    ("ripple", Asset.XRP),
    ("xrp", Asset.XRP),
    ("binance", Asset.BNB),
    ("bnb", Asset.BNB),
)
_QUOTES = "usdt|usdc|busd|usd|try|eur|btc|eth"
_TICKERS = "|".join(a.value.lower() for a in Asset if a is not Asset.SOL)
# "sol" is also Turkish for "left". Unlike the lesson check, which rejects a whole lesson, a
# wrong guess here only swaps one word, while a missed name tells the reader which coin
# `ASSET_x` is. So the word on its own ("Sol güçlü", "sol'a girdim") is the coin, except
# before a direction noun ("sol taraf", "sol üst köşe", "sol omuz") or after "sağ ve".
# Suffixed forms without an apostrophe ("solda", "sola", "soldan") are the direction, as a
# coin's suffix takes one; all capitals ("SOLDA") is the coin.
_LEFT = r"taraf|omuz|köşe|kenar|eksen|(?:üst|alt|yan)(?:t[ae]|d[ae])?(?:n|ki)?\b|el\b"
_GAP = r"[\s._-]+"  # between the letters of a spelled-out ticker: "B T C", "b.t.c", "e-t-h"
_SPELLED = "|".join(_GAP.join(a.value.lower()) for a in Asset)
REAL_NAMES = re.compile(
    rf"\b(?:(?i:{_TICKERS})\w*"
    rf"|SOL\w*|(?i:sol)[/_-]?(?i:{_QUOTES})\b"
    rf"|(?<!(?i:sağ ve ))(?i:sol)(?!\w)(?!\s(?i:{_LEFT}))"
    r"|(?i:bitcoin|ether|solana|ripple|binance)\w*"
    rf"|(?i:{_SPELLED})\b)"
    "|\u20bf"  # the bitcoin sign
)
# A price level identifies the asset and the period as a name does ("65000 dolar"). Masked:
# an amount with a currency ("$65,000", "65 bin dolar", "0.52 USDT") and any bare number of
# four or more digits ("65000", "97.500"; the prompt's own data has none: percentages,
# indices and day counts are shorter). Percentages ("%1500") and decimals ("0.125") stay.
_NUM = r"\d+(?:[.,]\d+)*(?:\s?(?i:k|bin|milyon|milyar)\b)?"
_CURRENCY = r"(?:[$€₺]|(?i:dolar\w*|lira\w*|usdt?\b|usdc\b|tl\b|euro?\b))"
PRICES = re.compile(
    rf"(?<![%\w.,])(?:[$€₺]\s?{_NUM}|{_NUM}\s?{_CURRENCY}"
    r"|(?:[1-9]\d{0,2}(?:[.,]\d{3})+|\d{4,})(?:[.,]\d+)?(?!\d|\s?%))"
)
PRICE_MASK = "[fiyat]"
UNKNOWN_ASSET = "ASSET_?"  # a real coin outside the experiment has no code

_INJECTION: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        (
            "override",
            r"\b(ignore|disregard|forget|override)\b.{0,40}"
            r"\b(instruction|rule|prompt|previous|above|prior)",
        ),
        (
            "override-tr",
            r"([öo]nceki|yukar[ıi]daki|t[üu]m|b[üu]t[üu]n)\s.{0,30}"
            r"(talimat|kural|komut|y[öo]nerge)\w*.{0,30}(yok\s*say|unut|g[öo]rmezden|uyma)",
        ),
        (
            "override-tr2",
            r"(talimat|kural|y[öo]nerge)\w*\s.{0,20}"
            r"(yok\s*say|unut|g[öo]rmezden gel|bo[şs]\s*ver)",
        ),
        ("new-rule-tr", r"\byeni\s+(kural|talimat|y[öo]nerge|g[öo]rev)\w*\s*:"),
        (
            "system",
            r"\b(system|developer)\s*(prompt|message|instruction)|sistem\s*(talimat|mesaj|prompt|komut)",
        ),
        ("role", r"(^|\s)(system|assistant|user|developer)\s*:|<\|im_(start|end)\|>|\[/?INST\]"),
        ("persona", r"\byou are now\b|\bact as\b|\bpretend\b|\bartık sen\b|\bsen artık\b"),
        ("delimiter", r"</?\s*forum_post|forum_data"),
        ("schema", r"\ballocations\b|\"weight\"|\bconfidence\s*[:=]"),
        # An order to move everything somewhere ("portföyün tamamını ASSET_B'ye aktar");
        # "portföyün tamamını nakitte tutuyorum" is advice and passes.
        (
            "all-in",
            r"\ball[\s-]in\b|(portföy\w*|(tüm|bütün)\s+(parayı|nakdi))\s+(tamamını\s+|hepsini\s+)?"
            r"\S+\s+(aktar|yatır|bas|koy|gir)\w*",
        ),
    )
)

_SPACED = {"Cc"}  # control characters (newlines, NUL) become spaces ...
_DROPPED = {"Cf", "Co", "Cs"}  # ... format (zero-width, bidi), private and surrogate vanish


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(
        " " if unicodedata.category(c) in _SPACED else c
        for c in text
        if unicodedata.category(c) not in _DROPPED
    )
    return " ".join(text.split())


def injection_flags(text: str) -> list[str]:
    """Names of the injection patterns the text matches (empty: clean)."""
    plain = _plain(text)
    return [name for name, pattern in _INJECTION if pattern.search(plain)]


def _asset_named(word: str) -> Asset | None:
    if word == "\u20bf":
        return Asset.BTC
    low = re.sub(_GAP, "", word.lower())  # "B T C" -> "btc"
    return next((asset for name, asset in _NAMES if low.startswith(name)), None)


def anonymise_names(text: str, codes: Mapping[Asset, str]) -> str:
    """Replace real coin names (`BTC'ye`, `bitcoinde`, `eth/usdt`) with `ASSET_x`."""

    def code(m: re.Match[str]) -> str:
        asset = _asset_named(m.group(0))
        return codes.get(asset, UNKNOWN_ASSET) if asset is not None else UNKNOWN_ASSET

    return REAL_NAMES.sub(code, text)


def sanitise(text: str, codes: Mapping[Asset, str]) -> str:
    """The stored (and shown) form of a post: plain, anonymised and at most POST_MAX_CHARS."""
    plain = _plain(text).replace("<", "").replace(">", "")
    return anonymise_names(PRICES.sub(PRICE_MASK, plain), codes)[:POST_MAX_CHARS].strip()


@dataclass(frozen=True, slots=True)
class CleanPost:
    content: str
    flagged: bool
    flags: tuple[str, ...]


def screen(text: str, codes: Mapping[Asset, str]) -> CleanPost | None:
    """The stored form and its flags, or None when nothing is left to post. The patterns run
    on the text as written and as stored, so removing `<` `>` cannot unmask an instruction
    ("ig<nore all previous instructions")."""
    content = sanitise(text, codes)
    if not content:
        return None
    flags = sorted(set(injection_flags(text)) | set(injection_flags(content)))
    return CleanPost(content, bool(flags), tuple(flags))


# ------------------------------------------------------------------ weights (C2 / C3)


@dataclass(frozen=True, slots=True)
class ForumRead:
    """A post as a reader sees it, with the sender's trust in the reader's eyes."""

    message_id: object  # the row id (uuid in the runner); opaque here
    sender: str  # the sender's agent id (slug)
    day: date
    asset: Asset
    stance: Stance
    content: str
    trust: BetaTrust  # reader -> sender counts at decision time

    def weight(self, *, by_trust: bool) -> Fraction:
        """C3: the Beta score (a+1)/(a+b+2) as an exact fraction; C2: 1/2 for everyone."""
        if not by_trust:
            return EQUAL_WEIGHT
        a, b = self.trust.confirmed, self.trust.refuted
        return Fraction(a + 1, a + b + 2)


@dataclass(frozen=True, slots=True)
class Weighed:
    shown: tuple[float, ...]  # the weight w per read, as the prompt shows it
    consensus: dict[Asset, float]  # mean of w * stance per asset, in (-1, 1)
    weights: tuple[float, ...]  # w per read, stored in decision_forum_reads


def weigh(reads: Sequence[ForumRead], *, by_trust: bool, digits: int = 3) -> Weighed:
    """Absolute weights and the per-asset mean of `w * stance` (decision-v4).

    Not normalised by the weights: a lone post from a distrusted sender (w = 0.09) moves the
    consensus far less than one from a trusted sender (w = 0.91), where a normalised share
    would be 1 for both. Exact fractions, rounded once."""
    ws = [r.weight(by_trust=by_trust) for r in reads]
    consensus: dict[Asset, float] = {}
    for asset in sorted({r.asset for r in reads}):
        mine = [(w, r) for w, r in zip(ws, reads, strict=True) if r.asset == asset]
        net = sum((w * SIGN[r.stance] for w, r in mine), Fraction(0))
        consensus[asset] = round(float(net / len(mine)), digits)
    return Weighed(
        tuple(round(float(w), digits) for w in ws),
        consensus,
        tuple(round(float(w), 4) for w in ws),
    )


def read_order(reads: Sequence[ForumRead]) -> list[ForumRead]:
    """Newest first, then sender, asset and stance: never ids or insertion order."""
    return sorted(reads, key=lambda r: (-r.day.toordinal(), r.sender, r.asset, r.stance))


# ------------------------------------------------------------------ verification


def verdict(view: MarketView, posted_at: int, asset: Asset, stance: Stance) -> bool | None:
    """Whether advice of day index `posted_at` held, judged on the view of day `view.t`.

    None while the horizon has not ended (`posted_at + HORIZON_DAYS > view.t`) and for neutral
    advice (no direction to check). The view cannot see past its day, so neither can this.
    """
    if stance is Stance.NEUTRAL or posted_at + HORIZON_DAYS > view.t:
        return None
    closes = view.closes(asset, view.t - posted_at + 1)  # closes[0] is day `posted_at`
    change = closes[HORIZON_DAYS] / closes[0] - 1
    if change == 0:
        return None  # an unchanged close proves neither direction
    return change > 0 if stance is Stance.BULLISH else change < 0
