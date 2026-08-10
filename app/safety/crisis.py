"""Deterministic, risk-aware crisis response planning.

Immediate safety actions are selected from a constrained taxonomy produced by
the pre-response risk assessor. Crisis correctness never depends on generation.
"""
from __future__ import annotations

from typing import Optional

from app.config.settings import Settings
from app.llm.client import LLMClient
from app.types import Language, RiskAssessment, SafetyLevel

_ACTIONS_EN = {
    "move_away_from_danger": "Please move away from the immediate danger and get to a safer place now.",
    "stop_hazard_and_get_to_safety": "Stop the hazardous situation if you safely can, then get to safety now.",
    "avoid_driving_or_more_substances": "Please do not drive or take anything more; stay with a sober person.",
    "reduce_access_to_means": "Put distance between you and anything you could use to hurt yourself.",
    "contact_trusted_person": "Call a trusted person and ask them to stay with you now.",
    "contact_emergency_services": "If the danger is immediate, call {number} now.",
    "seek_urgent_medical_help": "Please get urgent medical help now.",
    "keep_distance_from_others": "Step away from the other person and from anything that could cause harm.",
}

_ACTIONS_HI = {
    "move_away_from_danger": "Abhi danger se door hokar kisi safe jagah par jao.",
    "stop_hazard_and_get_to_safety": "Agar safely kar sakte ho to hazard roko, phir turant safe jagah jao.",
    "avoid_driving_or_more_substances": "Drive mat karo aur kuch aur mat lo; kisi sober person ke saath raho.",
    "reduce_access_to_means": "Jo cheez hurt kar sakti hai usse door ho jao.",
    "contact_trusted_person": "Abhi kisi trusted person ko call karke apne paas bulao.",
    "contact_emergency_services": "Agar danger immediate hai to abhi {number} call karo.",
    "seek_urgent_medical_help": "Abhi urgent medical help lo.",
    "keep_distance_from_others": "Dusre person aur harm karne wali cheezon se door ho jao.",
}

class CrisisHandler:
    def __init__(self, settings: Settings, client: Optional[LLMClient] = None):
        self.settings = settings
        self.client = client  # retained for constructor compatibility; not trusted here

    def respond(self, language: Language, user_message: str = "",
                session_id: str = "crisis", safety_level=None,
                assessment: Optional[RiskAssessment] = None) -> str:
        level = safety_level or (assessment.safety_level if assessment else
                                 SafetyLevel.SELF_HARM_CONCERN)
        actions = list(assessment.immediate_actions if assessment else [])
        if not actions:
            actions = (["move_away_from_danger", "contact_emergency_services"]
                       if level == SafetyLevel.PHYSICAL_DANGER
                       else ["reduce_access_to_means", "contact_trusted_person"])
        pool = _ACTIONS_HI if language in (Language.HINDI, Language.HINGLISH) else _ACTIONS_EN
        steps = []
        for key in actions[:2]:
            text = pool.get(key)
            if text:
                steps.append(text.format(number=self.settings.emergency_number))

        if language == Language.HINDI:
            opening = "मैं अभी आपके साथ हूँ। अभी safety सबसे ज़रूरी है।"
            question = "क्या आप अभी danger से दूर और किसी safe person के साथ हैं?"
        elif language == Language.HINGLISH:
            opening = "Main abhi tumhare saath hoon. Abhi safety sabse important hai."
            question = "Kya tum abhi danger se door aur kisi safe person ke saath ho?"
        else:
            opening = "I'm with you right now. Your immediate safety comes first."
            question = "Are you away from the danger and with a safe person right now?"

        if level == SafetyLevel.HARM_TO_OTHERS:
            if language in (Language.HINDI, Language.HINGLISH):
                question = "Kya tum abhi us person se door aur safe jagah par ho?"
            else:
                question = "Are you away from that person and in a safe place right now?"
        elif level == SafetyLevel.ABUSE_OR_DANGER:
            if language in (Language.HINDI, Language.HINGLISH):
                question = "Kya tum abhi us person se door kisi safe jagah par ho?"
            else:
                question = "Are you somewhere safe and away from that person right now?"

        return " ".join([opening, *steps, question]).strip()

    def _fallback(self, language: Language) -> str:
        return self.respond(language)
