"""Small text utilities: language detection, cleaning, markdown stripping."""

from __future__ import annotations

import re

from app.types import Language


_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_HINDI_SIGNAL = re.compile(r"\b(hai|hoon|kya|aap|tum|mujhe|maine|tha|thi|nahi|haan)\b", re.I)
_HINGLISH_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"\b(aaj|kal|kaise|kahan|kyun|kab|abhi|bahut|thoda)\b",
        r"\b(karo|karna|karun|bolo|batao|dekho|suno)\b",
        r"\b(mai|mein|yaar|bhai|baat|hoon|hai|kaam)\b",
    ]
]


# Hard cap on a single user message. Long enough for any real message a person
# types, short enough to bound CPU, tokens and cost. Oversized input is a DoS
# and cost-amplification vector, so the bound stays cheap and is applied first.
MAX_MESSAGE_CHARS = 4000


def exceeds_message_limit(text: str, max_chars: int = MAX_MESSAGE_CHARS) -> bool:
    """Report oversized input so callers can refuse it instead of truncating.

    Silent truncation is unsafe here: risk-relevant wording can sit after the
    retained prefix, so an oversized message must never be analyzed in part.
    """
    return len(text or "") > max_chars


def oversized_message_reply(text: str) -> str:
    """Bounded notice stating that nothing in the message was processed."""
    # Detect on the bounded prefix only: the full payload is deliberately unread.
    language = detect_language((text or "")[:MAX_MESSAGE_CHARS])
    if language == Language.HINDI:
        return ("आपका message बहुत लंबा है, इसलिए मैंने उसे पढ़ा नहीं — कुछ भी process "
                "नहीं हुआ। क्या आप उसे छोटे हिस्सों में भेज सकते हैं? अगर कुछ ज़रूरी है, "
                "तो पहले कुछ शब्दों में बता दीजिए।")
    if language == Language.HINGLISH:
        return ("Tumhara message bahut lamba hai, isliye main use padh nahi paya — kuch bhi "
                "process nahi hua. Thoda chhota karke bhej sakte ho? Agar kuch urgent hai to "
                "pehle few words mein bata do.")
    return ("Your message is too long for me to read, so none of it was processed. "
            "Could you send it in shorter parts? If something urgent is going on, "
            "tell me that first in a few words.")


def clean_message(text: str, max_chars: int = MAX_MESSAGE_CHARS) -> str:
    """Trim, collapse whitespace, drop control chars, and cap the length.

    The cap only bounds CPU for already-accepted input; callers that receive raw
    user input must reject oversized messages with `exceeds_message_limit` first.
    """
    if not text:
        return ""
    # Cap BEFORE the per-character work so a huge payload can't burn CPU.
    if len(text) > max_chars:
        text = text[:max_chars]
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    return re.sub(r"[ \t]+", " ", text).strip()


def detect_language(text: str) -> Language:
    text = text or ""
    if _DEVANAGARI.search(text):
        return Language.HINDI
    lower = text.lower()
    hinglish_hits = sum(1 for p in _HINGLISH_PATTERNS if p.search(lower))
    if hinglish_hits >= 2 or _HINDI_SIGNAL.search(lower):
        return Language.HINGLISH
    return Language.ENGLISH


def strip_markdown(text: str) -> str:
    """Remove common markdown markers while preserving meaning."""
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"```(?:[a-zA-Z0-9_+-]+)?\n([\s\S]*?)```", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^\s*#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*>\s?", "", cleaned)
    cleaned = re.sub(r"[*_`~]+", "", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
