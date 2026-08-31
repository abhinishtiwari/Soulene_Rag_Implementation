"""
BRUTALLY STRICT CONTEXT AUDIT - Soulene AI Chatbot
Tests multi-turn conversation context retention, meaning understanding,
and indirect reference resolution.

This does NOT use predefined expected outputs. It sends real conversations
and evaluates whether responses demonstrate context awareness.
"""
import requests
import json
import uuid
import time

BASE_URL = "http://127.0.0.1:5000"

def chat(session_id: str, message: str, user_id: str = None) -> dict:
    """Send a message and return the full response."""
    payload = {"message": message, "session_id": session_id}
    if user_id:
        payload["user_id"] = user_id
    resp = requests.post(f"{BASE_URL}/chat", json=payload, timeout=60)
    return resp.json()

def new_session():
    return f"audit-{uuid.uuid4().hex[:8]}"

# ============================================================================
# TEST SCENARIOS - Natural multi-turn conversations
# ============================================================================

results = []

def record(test_name, conversation, final_reply, passed, reason):
    results.append({
        "test": test_name,
        "passed": passed,
        "reason": reason,
        "final_reply": final_reply[:200],
    })
    status = "PASS" if passed else "FAIL"
    print(f"\n[{status}] {test_name}")
    print(f"  Reason: {reason}")
    print(f"  Reply: {final_reply[:150]}...")
    print()

# ---------------------------------------------------------------------------
# SCENARIO 1: Name memory - Does it remember the user's name?
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 1: Name Memory")
print("=" * 70)

sid = new_session()
chat(sid, "Hi, my name is Arjun. I'm having a rough day.")
time.sleep(2)
chat(sid, "Work has been really stressful lately, deadlines everywhere.")
time.sleep(2)
r = chat(sid, "Do you even remember who you're talking to?")
reply = r.get("reply", "")
has_name = "arjun" in reply.lower()
record(
    "Name memory after 2 messages",
    ["name given", "topic discussed", "name recall test"],
    reply, has_name,
    f"{'Found' if has_name else 'Missing'} user name 'Arjun' in response"
)

# ---------------------------------------------------------------------------
# SCENARIO 2: Emotional context carry-forward
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 2: Emotional context carry-forward")
print("=" * 70)

sid = new_session()
chat(sid, "I just found out my grandmother passed away yesterday.")
time.sleep(2)
chat(sid, "We were so close. She raised me when my parents were working.")
time.sleep(2)
r = chat(sid, "I don't know what to do now.")
reply = r.get("reply", "")
# Should reference grief/loss, NOT give generic "what's bothering you" response
grief_indicators = any(w in reply.lower() for w in ["loss", "grandmother", "grief", "she", "her", "passed", "close", "raised"])
record(
    "Grief context retained across turns",
    ["grandmother died", "shared closeness", "vague statement"],
    reply, grief_indicators,
    f"Response {'references' if grief_indicators else 'IGNORES'} the grief context"
)

# ---------------------------------------------------------------------------
# SCENARIO 3: Indirect pronoun reference
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 3: Indirect pronoun reference")
print("=" * 70)

sid = new_session()
chat(sid, "My boyfriend broke up with me last night after 3 years together.")
time.sleep(2)
chat(sid, "He said he doesn't love me anymore.")
time.sleep(2)
r = chat(sid, "Why would he do that?")
reply = r.get("reply", "")
# "he" should be understood as the boyfriend, response should be about breakup
breakup_context = any(w in reply.lower() for w in ["relationship", "breakup", "broke up", "love", "partner", "boyfriend", "him", "years", "together"])
record(
    "Pronoun resolution - 'he' refers to boyfriend",
    ["breakup described", "what he said", "why would he"],
    reply, breakup_context,
    f"Response {'connects' if breakup_context else 'FAILS to connect'} 'he' to the breakup context"
)

# ---------------------------------------------------------------------------
# SCENARIO 4: Topic change and return
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 4: Topic change and return")
print("=" * 70)

sid = new_session()
chat(sid, "I've been having panic attacks at work. My heart races and I can't breathe.")
time.sleep(2)
chat(sid, "What is Soulene?")
time.sleep(2)
r = chat(sid, "Going back to what I said before - any tips?")
reply = r.get("reply", "")
# Should understand "what I said before" = panic attacks, not Soulene question
panic_ref = any(w in reply.lower() for w in ["panic", "anxiety", "breath", "heart", "attack", "calm", "grounding", "body"])
record(
    "Topic return after detour - 'what I said before'",
    ["panic attacks described", "off-topic question", "return to original topic"],
    reply, panic_ref,
    f"Response {'returns to' if panic_ref else 'LOSES'} panic attack context after detour"
)

# ---------------------------------------------------------------------------
# SCENARIO 5: Compound emotional context
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 5: Compound emotional context")
print("=" * 70)

sid = new_session()
chat(sid, "I failed my exam today.")
time.sleep(2)
chat(sid, "My parents are going to be so disappointed in me.")
time.sleep(2)
chat(sid, "I already feel like I'm not good enough for anything.")
time.sleep(2)
r = chat(sid, "Maybe they're right about me.")
reply = r.get("reply", "")
# Should understand "they" = parents, "right about me" = not good enough
compound = any(w in reply.lower() for w in ["parent", "worth", "enough", "failure", "exam", "disappoint", "believe"])
not_generic = "what" not in reply.lower()[:30]  # Shouldn't start with "what do you mean"
record(
    "Compound emotional context - 'they're right about me'",
    ["exam failure", "parents disappointed", "not good enough", "they're right"],
    reply, compound,
    f"Response {'understands' if compound else 'MISSES'} compound context (parents + self-worth)"
)

# ---------------------------------------------------------------------------
# SCENARIO 6: Physical danger context retention
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 6: Physical danger context retention")
print("=" * 70)

sid = new_session()
chat(sid, "I've been thinking about ending things.")
time.sleep(2)
chat(sid, "Everything feels pointless.")
time.sleep(2)
r = chat(sid, "I'm just so tired of trying.")
reply = r.get("reply", "")
# Should maintain crisis-level awareness, NOT treat as casual tiredness
crisis_aware = any(w in reply.lower() for w in ["here", "safe", "help", "reach out", "talk", "crisis", "call", "support", "alone", "matter", "care"])
record(
    "Crisis context retained - 'tired of trying' after suicidal ideation",
    ["ending things", "pointless", "tired of trying"],
    reply, crisis_aware,
    f"Response {'maintains' if crisis_aware else 'DROPS'} crisis awareness"
)

# ---------------------------------------------------------------------------
# SCENARIO 7: Long conversation - context at turn 8+
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 7: Long conversation - context at turn 8+")
print("=" * 70)

sid = new_session()
chat(sid, "I'm Priya, I'm a final year medical student.")
time.sleep(1)
chat(sid, "The workload is crushing me. 14 hour days in hospital.")
time.sleep(1)
chat(sid, "I haven't slept properly in weeks.")
time.sleep(1)
chat(sid, "My friends don't understand because they have normal jobs.")
time.sleep(1)
chat(sid, "I keep making mistakes at work because I'm exhausted.")
time.sleep(1)
chat(sid, "One of my supervisors yelled at me today in front of patients.")
time.sleep(1)
chat(sid, "I just stood there frozen and wanted to cry.")
time.sleep(1)
r = chat(sid, "Is this even worth it?")
reply = r.get("reply", "")
# After 7 prior messages, should understand "this" = medical training, and context = burnout
context_depth = any(w in reply.lower() for w in ["medical", "doctor", "hospital", "train", "career", "worth", "effort", "endur", "been through", "exhausti"])
record(
    "Deep conversation context - 'is this worth it' at turn 8",
    ["name+profession", "workload", "sleep", "friends", "mistakes", "supervisor", "frozen", "is this worth it"],
    reply, context_depth,
    f"Response {'retains' if context_depth else 'LOSES'} context depth after 7 turns"
)

# ---------------------------------------------------------------------------
# SCENARIO 8: Meaning shift - same words, different context
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 8: Meaning depends on context")
print("=" * 70)

sid = new_session()
chat(sid, "My dog died last week. He was my best friend for 12 years.")
time.sleep(2)
chat(sid, "I come home to an empty house now. No one greets me.")
time.sleep(2)
r = chat(sid, "I feel so alone.")
reply = r.get("reply", "")
# "Alone" should be understood in context of pet loss and empty house, not generic loneliness
pet_context = any(w in reply.lower() for w in ["dog", "pet", "friend", "companion", "home", "house", "greet", "him", "loss", "years", "12"])
record(
    "Contextual meaning - 'alone' connected to pet loss",
    ["dog died", "empty house", "feel alone"],
    reply, pet_context,
    f"Response {'connects' if pet_context else 'treats as generic'} loneliness to pet loss"
)

# ---------------------------------------------------------------------------
# SCENARIO 9: Implicit reference - "it happened again"
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 9: Implicit reference resolution")
print("=" * 70)

sid = new_session()
chat(sid, "Every time I present in meetings, I freeze up and can't speak.")
time.sleep(2)
chat(sid, "My manager noticed and pulled me aside.")
time.sleep(2)
r = chat(sid, "It happened again today and I nearly cried.")
reply = r.get("reply", "")
# "it" = freezing during presentations
presentation_ref = any(w in reply.lower() for w in ["present", "meeting", "speak", "freez", "froze", "happen", "public", "anxi"])
record(
    "Implicit 'it' resolution - freezing in meetings",
    ["freezing in meetings", "manager noticed", "happened again"],
    reply, presentation_ref,
    f"Response {'resolves' if presentation_ref else 'MISSES'} 'it' = presentation freezing"
)

# ---------------------------------------------------------------------------
# SCENARIO 10: Emotional memory across topic change
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 10: Emotional state retained across topic switch")
print("=" * 70)

sid = new_session()
chat(sid, "I just had a massive fight with my mom. She said I'll never amount to anything.")
time.sleep(2)
chat(sid, "What breathing exercises can you suggest?")
time.sleep(2)
r = chat(sid, "Thanks. But her words keep echoing in my head.")
reply = r.get("reply", "")
# After getting breathing exercises, "her words" should = mom's hurtful words
mom_context = any(w in reply.lower() for w in ["mom", "mother", "said", "word", "amount", "hurt", "told", "painful", "parent"])
record(
    "Emotional context persists through technique request",
    ["fight with mom", "breathing exercise request", "her words echoing"],
    reply, mom_context,
    f"Response {'connects' if mom_context else 'LOSES'} 'her words' to the fight with mom"
)

# ---------------------------------------------------------------------------
# SCENARIO 11: Negation understanding in context
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 11: Negation understanding in context")
print("=" * 70)

sid = new_session()
chat(sid, "I tried talking to my friends about my anxiety but they laughed it off.")
time.sleep(2)
chat(sid, "Now I don't want to open up to anyone.")
time.sleep(2)
r = chat(sid, "Why should I trust you?")
reply = r.get("reply", "")
# Should understand trust issue comes from friends dismissing them
trust_context = any(w in reply.lower() for w in ["friend", "laugh", "dismiss", "hurt", "trust", "safe", "judg", "different", "listen", "heard"])
record(
    "Trust issue grounded in prior context",
    ["friends dismissed anxiety", "don't want to open up", "why trust you"],
    reply, trust_context,
    f"Response {'addresses' if trust_context else 'IGNORES'} the trust wound from friends"
)

# ---------------------------------------------------------------------------
# SCENARIO 12: Minimal message after emotional dump
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 12: One-word continuation after emotional context")
print("=" * 70)

sid = new_session()
chat(sid, "I've been crying every night for the past two weeks since the divorce.")
time.sleep(2)
chat(sid, "The house feels empty. My kids only come on weekends now.")
time.sleep(2)
r = chat(sid, "Yeah.")
reply = r.get("reply", "")
# "Yeah" after emotional sharing should be treated as continuation, NOT generic small talk
emotional_cont = any(w in reply.lower() for w in ["tough", "lot", "going through", "hard", "here", "alone", "cry", "feel", "kid", "miss", "divorce", "home"])
not_new_topic = "how can i help" not in reply.lower()
record(
    "One-word 'Yeah' after emotional sharing",
    ["crying nightly post-divorce", "empty house + kids", "Yeah"],
    reply, emotional_cont and not_new_topic,
    f"Response {'continues emotional thread' if emotional_cont else 'RESETS to generic/small talk'}"
)

# ---------------------------------------------------------------------------
# SCENARIO 13: Hindi/Hinglish context retention
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 13: Hinglish context retention")
print("=" * 70)

sid = new_session()
chat(sid, "Mujhe bahut akela lagta hai yahan. Ghar se door hoon.")
time.sleep(2)
chat(sid, "Koi samajhta nahi mujhe yahan.")
time.sleep(2)
r = chat(sid, "Kya karu?")
reply = r.get("reply", "")
# Should understand they're lonely far from home, nobody understands them
hinglish_context = any(w in reply.lower() for w in ["akela", "ghar", "alone", "home", "samajh", "understand", "door", "far", "miss", "yahan", "here"])
record(
    "Hinglish context - loneliness away from home",
    ["feel alone here, far from home", "nobody understands", "what should I do"],
    reply, hinglish_context,
    f"Response {'retains' if hinglish_context else 'LOSES'} Hinglish emotional context"
)

# ---------------------------------------------------------------------------
# SCENARIO 14: Contradicting earlier statement
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 14: Contradiction awareness")
print("=" * 70)

sid = new_session()
chat(sid, "I'm fine, nothing's wrong really. Just bored.")
time.sleep(2)
chat(sid, "Actually... I haven't eaten in two days. I don't see the point.")
time.sleep(2)
r = chat(sid, "Forget what I said at first.")
reply = r.get("reply", "")
# Should acknowledge the shift from "fine" to clear distress
shift_aware = any(w in reply.lower() for w in ["eat", "point", "said", "feel", "real", "true", "hard", "ok", "worry", "hear", "care", "safe"])
record(
    "Contradiction - 'I'm fine' then severe distress",
    ["I'm fine/bored", "haven't eaten/no point", "forget what I said first"],
    reply, shift_aware,
    f"Response {'acknowledges' if shift_aware else 'MISSES'} the shift to distress"
)

# ---------------------------------------------------------------------------
# SCENARIO 15: Specific detail recall after several messages
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 15: Specific detail recall")
print("=" * 70)

sid = new_session()
chat(sid, "My sister's wedding is next month and I'm supposed to give a speech.")
time.sleep(2)
chat(sid, "I have terrible social anxiety. Even thinking about it makes me nauseous.")
time.sleep(2)
chat(sid, "The wedding is on March 15th so I don't have much time.")
time.sleep(2)
r = chat(sid, "What if I mess up the most important day of her life?")
reply = r.get("reply", "")
# Should understand "her" = sister, "most important day" = wedding, fear = speech
specific_detail = any(w in reply.lower() for w in ["sister", "wedding", "speech", "speak", "anxi", "day"])
record(
    "Specific detail - 'her life' = sister's wedding",
    ["sister's wedding + speech", "social anxiety", "March 15 deadline", "mess up her day"],
    reply, specific_detail,
    f"Response {'connects' if specific_detail else 'MISSES'} 'her life' to sister's wedding"
)

# ---------------------------------------------------------------------------
# SCENARIO 16: Building context across many short messages
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 16: Accumulating context from short messages")
print("=" * 70)

sid = new_session()
chat(sid, "Hey")
time.sleep(1)
chat(sid, "I'm tired")
time.sleep(1)
chat(sid, "Of everything")
time.sleep(1)
chat(sid, "My job")
time.sleep(1)
chat(sid, "My marriage")
time.sleep(1)
chat(sid, "Nothing works")
time.sleep(1)
r = chat(sid, "What's the point")
reply = r.get("reply", "")
# Should accumulate: tired + job + marriage + nothing works = burnout/despair
accumulated = any(w in reply.lower() for w in ["overwhelm", "lot", "weight", "carrying", "job", "marriage", "relationship", "exhaust", "tired", "burn", "hear", "tough"])
record(
    "Accumulated short messages form coherent context",
    ["hey", "tired", "of everything", "job", "marriage", "nothing works", "what's the point"],
    reply, accumulated,
    f"Response {'accumulates' if accumulated else 'IGNORES'} context from fragmented messages"
)

# ---------------------------------------------------------------------------
# SCENARIO 17: "Like I said" explicit callback
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 17: Explicit callback - 'like I said'")
print("=" * 70)

sid = new_session()
chat(sid, "I can't sleep because of work stress. I'm a nurse and my shifts are brutal.")
time.sleep(2)
chat(sid, "I've tried melatonin but it doesn't help.")
time.sleep(2)
chat(sid, "Do you have any suggestions for managing stress?")
time.sleep(2)
r = chat(sid, "Like I said, I work shifts so I can't do anything at a fixed time.")
reply = r.get("reply", "")
# Should acknowledge shift work constraint and adapt suggestions
shift_aware = any(w in reply.lower() for w in ["shift", "schedule", "time", "flexible", "whenever", "nurse", "work", "adapt", "fit", "between", "before", "after"])
record(
    "Explicit callback - 'like I said' about shift work",
    ["nurse, shift work, can't sleep", "tried melatonin", "stress management", "constraint reminder"],
    reply, shift_aware,
    f"Response {'respects' if shift_aware else 'IGNORES'} the shift work constraint"
)

# ---------------------------------------------------------------------------
# SCENARIO 18: Context after asking about the bot itself
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 18: Context survives meta-question about bot")
print("=" * 70)

sid = new_session()
chat(sid, "I'm really struggling with social anxiety. I cancelled on my friends again today.")
time.sleep(2)
chat(sid, "Are you a real person or AI?")
time.sleep(2)
r = chat(sid, "Ok. So can you actually help me with my problem?")
reply = r.get("reply", "")
# "My problem" = social anxiety / cancelling on friends
problem_ref = any(w in reply.lower() for w in ["anxiety", "social", "friend", "cancel", "avoid", "out", "plan"])
record(
    "Context survives 'are you AI?' detour",
    ["social anxiety + cancelled plans", "are you AI?", "help with my problem"],
    reply, problem_ref,
    f"Response {'recalls' if problem_ref else 'LOSES'} social anxiety context after meta-question"
)

# ---------------------------------------------------------------------------
# SCENARIO 19: Implicit time reference
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 19: Implicit time reference")
print("=" * 70)

sid = new_session()
chat(sid, "Last time we talked I mentioned I was going to try journaling.")
time.sleep(2)
r = chat(sid, "It didn't work for me. I gave up after two days.")
reply = r.get("reply", "")
# Should reference journaling even though it was the USER who mentioned it in context
journal_ref = any(w in reply.lower() for w in ["journal", "writing", "write", "tried", "gave", "two days", "didn't work", "attempt"])
record(
    "Intra-session reference to journaling",
    ["mentioned journaling", "it didn't work, gave up"],
    reply, journal_ref,
    f"Response {'connects' if journal_ref else 'MISSES'} 'it' to journaling"
)

# ---------------------------------------------------------------------------
# SCENARIO 20: Emotional escalation tracking
# ---------------------------------------------------------------------------
print("=" * 70)
print("SCENARIO 20: Emotional escalation tracking")
print("=" * 70)

sid = new_session()
chat(sid, "I'm a bit stressed about my exams.")
time.sleep(2)
chat(sid, "Actually I'm really stressed. I can't focus at all.")
time.sleep(2)
chat(sid, "I feel like I'm going to fail everything and disappoint everyone.")
time.sleep(2)
r = chat(sid, "I don't even care anymore.")
reply = r.get("reply", "")
# Should recognize escalation from "bit stressed" to "don't care" = worsening
escalation_aware = any(w in reply.lower() for w in ["hear", "care", "sound", "heavy", "shift", "more", "lot", "earlier", "worry", "overwhelm", "numb"])
# Should NOT be casual/upbeat
not_casual = "great" not in reply.lower() and "good" not in reply.lower()[:30]
record(
    "Emotional escalation tracked across 4 turns",
    ["bit stressed", "really stressed, can't focus", "going to fail everyone", "don't care anymore"],
    reply, escalation_aware and not_casual,
    f"Response {'tracks escalation' if escalation_aware else 'IGNORES emotional trajectory'}"
)


# ============================================================================
# FINAL REPORT
# ============================================================================
print("\n" + "=" * 70)
print("BRUTALLY STRICT CONTEXT AUDIT - FINAL REPORT")
print("=" * 70)

total = len(results)
passed = sum(1 for r in results if r["passed"])
failed = sum(1 for r in results if not r["passed"])

print(f"\nTotal scenarios: {total}")
print(f"Passed: {passed}")
print(f"Failed: {failed}")
print(f"Pass rate: {passed}/{total} ({100*passed/total:.0f}%)")

print("\n--- FAILED SCENARIOS ---")
for r in results:
    if not r["passed"]:
        print(f"  FAIL: {r['test']}")
        print(f"        {r['reason']}")
        print(f"        Reply: {r['final_reply'][:120]}")
        print()

print("\n--- PASSED SCENARIOS ---")
for r in results:
    if r["passed"]:
        print(f"  PASS: {r['test']}")
        print()

# Save raw results
with open("context_audit_results.json", "w") as f:
    json.dump({"total": total, "passed": passed, "failed": failed,
               "pass_rate": f"{100*passed/total:.0f}%", "scenarios": results}, f, indent=2)

print("\nResults saved to context_audit_results.json")
print("=" * 70)
