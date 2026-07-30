"""Text de-obfuscation for SAFETY DETECTION ONLY.

Attackers evade regex guardrails with Unicode and typographic tricks:
    ig<ZWSP>nore        zero-width characters
    іgnore              Cyrillic homoglyph (U+0456)
    ｉgnore              fullwidth forms
    i g n o r e         letter spacing
    1gn0re / k1ll       leetspeak
    ignore\u202e        bidi override

`normalize_for_detection()` folds all of these to plain lowercase ASCII so the
guardrail regexes see the real intent.

IMPORTANT: this output is used ONLY for matching. The user's original text is
what reaches the model and the archive, so nothing is corrupted or lost.
Detectors check raw text OR normalized text, so normalization can only ADD
coverage — it can never mask a match that already worked.
"""

from __future__ import annotations

import re
import unicodedata

# Invisible / formatting characters used to split keywords.
_INVISIBLE = dict.fromkeys(
    [
        0x00AD,  # soft hyphen
        0x200B, 0x200C, 0x200D, 0x200E, 0x200F,  # ZWSP, ZWNJ, ZWJ, LRM, RLM
        0x202A, 0x202B, 0x202C, 0x202D, 0x202E,  # bidi embedding/override
        0x2060, 0x2061, 0x2062, 0x2063, 0x2064,  # word joiner, invisible ops
        0x206A, 0x206B, 0x206C, 0x206D, 0x206E, 0x206F,
        0xFEFF,  # BOM / zero-width no-break space
    ]
)

# Confusable homoglyphs -> Latin. Covers the practical Cyrillic/Greek set.
_CONFUSABLES = str.maketrans({
    # Cyrillic lowercase
    "а": "a", "в": "b", "с": "c", "ԁ": "d", "е": "e", "ѕ": "s", "і": "i", "ј": "j",
    "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "т": "t", "у": "y", "х": "x",
    "ѐ": "e", "ё": "e", "ї": "i", "ӏ": "l", "ԛ": "q", "ѡ": "w", "ԝ": "w", "ց": "g",
    "ո": "n", "ս": "u", "ա": "w", "օ": "o", "ր": "r", "ք": "p", "ժ": "j",
    # Cyrillic uppercase
    "А": "a", "В": "b", "С": "c", "Е": "e", "Ѕ": "s", "І": "i", "Ј": "j", "К": "k",
    "М": "m", "Н": "h", "О": "o", "Р": "p", "Т": "t", "У": "y", "Х": "x",
    # Greek
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p",
    "τ": "t", "υ": "u", "χ": "x", "γ": "y", "η": "n", "ϲ": "c", "ѵ": "v",
    "Α": "a", "Β": "b", "Ε": "e", "Ι": "i", "Κ": "k", "Ο": "o", "Ρ": "p", "Τ": "t",
    # Misc lookalikes
    "ⅰ": "i", "ⅼ": "l", "ⅾ": "d", "ⅽ": "c", "ｍ": "m", "ⅿ": "m",
})

# Leetspeak / punctuation substitutions.
_LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g",
    "@": "a", "$": "s", "!": "i", "|": "l", "£": "e", "€": "e", "+": "t",
})

_PUNCT_FILLER = re.compile(r"[.\-_*~`'\"^:;,/\\()\[\]{}<>]+")
# 3+ single letters separated by spaces ("a l l", "i g n o r e").
_SPACED_LETTERS = re.compile(r"\b(?:[a-z]\s+){2,}[a-z]\b")
_WS = re.compile(r"\s+")


def _strip_invisible(text: str) -> str:
    return text.translate(_INVISIBLE)


def _strip_marks(text: str) -> str:
    """Drop combining marks (e.g. igno<U+0301>re -> ignore)."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _collapse_spaced_letters(text: str) -> str:
    """'i g n o r e  a l l' -> 'ignore all'.

    Wider gaps (2+ spaces) are treated as real word boundaries, so
    'i g n o r e  a l l' collapses to two words rather than one blob.
    """
    def join(match: re.Match) -> str:
        return match.group(0).replace(" ", "")

    chunks = re.split(r"\s{2,}", text)
    return " ".join(_SPACED_LETTERS.sub(join, chunk) for chunk in chunks)


def despace(text: str) -> str:
    """Normalized text with ALL whitespace removed.

    Catches uniformly spaced-out payloads ('i g n o r e a l l ...') where word
    boundaries are unrecoverable. Matched against compact keyword patterns.
    """
    return re.sub(r"\s+", "", normalize_for_detection(text))


def normalize_for_detection(text: str, *, fold_leet: bool = True) -> str:
    """Fold obfuscated text to plain lowercase ASCII for guardrail matching."""
    if not text:
        return ""
    # 1) compatibility fold: fullwidth/ligatures/superscripts -> ASCII
    out = unicodedata.normalize("NFKC", text)
    # 2) remove invisible separators and bidi controls
    out = _strip_invisible(out)
    # 3) remove combining diacritics
    out = _strip_marks(out)
    out = out.lower()
    # 4) map homoglyphs to Latin
    out = out.translate(_CONFUSABLES)
    # 5) leet/punctuation substitutions
    if fold_leet:
        out = out.translate(_LEET)
    # 6) drop punctuation used as filler inside words (i.g.n.o.r.e)
    out = _PUNCT_FILLER.sub("", out)
    # 7) rejoin deliberately spaced-out letters
    out = _collapse_spaced_letters(out)
    # 8) normalize whitespace (incl. NBSP already handled by NFKC)
    return _WS.sub(" ", out).strip()


def detection_variants(text: str) -> tuple[str, str]:
    """Return (raw_lowercased, normalized). Detectors should check both."""
    return (text or "").lower(), normalize_for_detection(text)
