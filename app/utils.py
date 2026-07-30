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
# and cost-amplification vector, so we truncate rather than process megabytes.
MAX_MESSAGE_CHARS = 4000


def clean_message(text: str, max_chars: int = MAX_MESSAGE_CHARS) -> str:
    """Trim, collapse whitespace, drop control chars, and cap the length."""
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
