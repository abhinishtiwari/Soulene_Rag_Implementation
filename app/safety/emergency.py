"""How Soulene refers to emergency help.

A specific emergency number is only asserted when an operator has declared the
locale that number was human-verified for. When the locale is unknown, wording
stays neutral ("your local emergency services"), because naming an inapplicable
number to someone in crisis creates false confidence and can cost time.

The verified-locale registry itself is deliberately NOT hardcoded here: emergency
resource correctness is a human/external validation responsibility, so it is
supplied through configuration and reviewed outside this repository.
"""

from __future__ import annotations

from app.types import Language

_NEUTRAL_REFERENCE = {
    Language.ENGLISH: "your local emergency services",
    Language.HINGLISH: "apne local emergency services",
    Language.HINDI: "अपनी local emergency services",
}


def emergency_reference(settings, language: Language) -> str:
    """Return the number to name, or neutral wording when locale is unverified."""
    if settings.emergency_contact_is_verified:
        return settings.emergency_number
    return _NEUTRAL_REFERENCE.get(language, _NEUTRAL_REFERENCE[Language.ENGLISH])
