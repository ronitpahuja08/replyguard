"""A deterministic stand-in for the ReplyGuard's model, for the demo database and end-to-end tests
only.

``install_fake(label)`` binds a ``FakeLLM`` (same label as the demo's other fakes, so the demo's TEST
QUALIFICATION covers it) to the ``agent.replyguard`` job handler; ``qualify_fake`` seeds the
matching test EvalRun. The fake reads a reply with the deterministic signals only (detector, bot question, a
few "yes" phrases); anything else is ``unclear`` at confidence 0.5, which the agent hands to a human. It is
not an eval.
"""

from __future__ import annotations

import json
import re
from typing import Any

from paralax.agents.replyguard import signals as sig
from paralax.llm import FakeLLM

AGENT = "replyguard"
_PRICE = re.compile(r"\b(?:how\s+much|price|pricing|cost|fee|quote)\b|كم\s+السعر|بكم", re.IGNORECASE)
_MEET = re.compile(r"\b(?:call\s+me|meet(?:ing)?|book\s+a|appointment|tomorrow\s+morning)\b", re.IGNORECASE)
_YES = re.compile(r"\b(?:yes|sure|send (?:it|me|the)|go ahead|sounds (?:good|interesting))\b", re.IGNORECASE)


def _classify(*, system: str, user: str, schema: Any) -> dict[str, Any]:
    text = str(json.loads(user)["reply"]["text"] or "")
    if sig.detector_opt_out(text):
        return {"label": "opt_out", "confidence": 0.95, "spans": [text[:60]]}
    if sig.is_bot_question(text):
        return {"label": "bot_question", "confidence": 0.95}
    if _PRICE.search(text):
        return {"label": "question", "confidence": 0.9, "spans": [text[:60]], "flags": ["pricing"]}
    if _MEET.search(text):
        return {"label": "meeting_request", "confidence": 0.9, "spans": [text[:60]]}
    if _YES.search(text):
        return {"label": "positive", "confidence": 0.9, "spans": [text[:60]]}
    return {"label": "unclear", "confidence": 0.5, "reasoning": "demo fake: not a reading"}


def _draft(*, system: str, user: str, schema: Any) -> dict[str, Any]:
    data = json.loads(user)
    link = ((data.get("record") or {}).get("report") or {}).get("url") or ""
    return {"body": f"Here it is: {link}\nAnything in it you'd like me to explain?", "claims": []}


def fake_llm(label: str) -> FakeLLM:
    return FakeLLM(
        {
            "replyguard.classify": _classify,
            **{
                f"replyguard.draft.{k}": _draft
                for k in ("jab_2", "two_line_answer_then_jab_2", "label_then_calibrated_question", "nudge")
            },
        },
        label=label,
    )


def install_fake(label: str) -> None:
    from paralax.agents.replyguard import agent as _agent  # noqa: F401  (registers the agent)
    from paralax.agents.registry import agent_job_handler

    agent_job_handler(AGENT, llm_factory=lambda jctx, job: fake_llm(label))


def restore() -> None:
    from paralax.agents.registry import agent_job_handler

    agent_job_handler(AGENT)


def qualify_fake(session: Any, clock: Any, label: str) -> None:
    """TEST QUALIFICATION (demo database / tests only): a passing EvalRun for the fake's model config."""
    from paralax.agents.knowledge import KnowledgeBase, register_version
    from paralax.db.models import EvalRun

    pv = register_version(session, KnowledgeBase.load(AGENT), clock)
    session.add(
        EvalRun(
            agent=AGENT,
            playbook_version_id=pv.id,
            model_config_hash=fake_llm(label).model_config_hash(),
            score=1.0,
            passed=True,
            results={"test_qualification": True, "note": "fakes only; not a real eval"},
            run_at=clock.now(),
        )
    )
    session.flush()
