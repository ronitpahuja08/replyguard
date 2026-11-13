"""The ReplyGuard's acceptance rule ([S1] ReplyGuard): every reply arrives with the person, the
company, the message it answered and the full thread. A reply that fails it is still acted on for safety
(opt-out, complaint) but gets no automated answer: a human reads it.

``check_inbound_handover`` records the check as a ``HandoverCheck`` (from the Channel Operator, which
delivered the reply, to this agent), the SOP's handover quality score.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def acceptance_problems(record: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    reply = record.get("reply")
    if not isinstance(reply, Mapping) or not (str(reply.get("text") or "").strip() or reply.get("media")):
        problems.append("no reply text or media")
    if not record.get("_case_mode"):
        if not record.get("lead_id"):
            problems.append("no lead")
        if not record.get("person_id"):
            problems.append("no person")
        if not record.get("company_id"):
            problems.append("no company")
    thread = record.get("thread")
    if not isinstance(thread, list):
        problems.append("no thread")
    elif not any(isinstance(t, Mapping) and str(t.get("dir")) == "out" for t in thread):
        problems.append("the message it answered is missing (no outbound message in the thread)")
    if not (record.get("sender") or {}).get("account"):
        problems.append("no sending account on the thread")
    return problems


def check_inbound_handover(session: Any, record: Mapping[str, Any], *, clock: Any) -> bool:
    from paralax.agents.handover import check_handover

    return check_handover(
        session,
        from_agent="channel_operator",
        to_agent="replyguard",
        subject_type="message",
        subject_id=str(record.get("message_id") or ""),
        check_fn=lambda: acceptance_problems(record),
        clock=clock,
    )
