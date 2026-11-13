"""Follow-up events (CM-022, CM-036, CM-038, CM-039): what happens when a replier goes quiet.

- ``no_reply_after_jab_2``: the nudge plan (days 2, 5, 10; WhatsApp at most ``whatsapp.max_unanswered``
  unanswered, then another verified channel, else none) and then Warm with a check-in. Live: the nudges are
  scheduled as ``nudge_due`` events and the Warm move as ``nudges_done``.
- ``nudge_due`` / ``not_now_due`` / ``warm_checkin_due``: if they wrote to us since, nothing (the reply was
  handled); otherwise one nudge drafted from the record (LLM + self-check) on a channel the WhatsApp cap
  allows.
- ``nudges_done``: still nothing from them → Warm, check-in scheduled.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from paralax.agents.base import AgentContext, AgentResult, LoggedDecision
from paralax.agents.replyguard import replies as rp
from paralax.agents.replyguard import signals as sig
from paralax.agents.replyguard import timing as tm
from paralax.agents.replyguard.decide import followup_plan, send_times


def recipient_first_name(record: Mapping[str, Any]) -> str | None:
    if (record.get("lead") or {}).get("is_company_contact"):
        return None
    return str((record.get("person") or {}).get("first_name") or "").strip() or None


LIVE_STATES = ("replied", "engaged", "warm")


def _at(day: str, hhmm: str, pack: Any) -> str:
    d = date.fromisoformat(day)
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=tm.tz_of(pack)).isoformat()


def _inbound_since(record: Mapping[str, Any], since: datetime | None) -> bool:
    for t in record.get("thread") or []:
        at = tm.as_dt(t.get("at"))
        if t.get("dir") == "in" and at is not None and (since is None or at > since):
            return True
    return False


def unanswered_on(record: Mapping[str, Any], channel: str) -> int:
    """Outbound messages on ``channel`` since their last inbound message (CM-036)."""
    n = 0
    for t in record.get("thread") or []:
        if t.get("dir") == "in":
            n = 0
        elif t.get("channel", record.get("channel")) == channel:
            n += 1
    return n


def run_event(ctx: AgentContext, record: dict[str, Any]) -> AgentResult:
    event = str(record.get("event"))
    data = record.get("event_data") or {}
    pack = tm.pack_for(record.get("country"))
    out: dict[str, Any] = {
        "agent": "replyguard",
        "event": event,
        "label": None,
        "lead_id": record.get("lead_id"),
    }
    rules = ["CM-038", "CM-036"]

    if event == "no_reply_after_jab_2":
        plan = followup_plan(record, ctx.defaults)
        out.update(plan)
        channel = str(record.get("channel") or "email")
        hhmm = tm.window_start(channel, pack)
        anchor = (record.get("thread") or [{}])[-1].get("at")
        schedule = [
            {
                "event": "nudge_due",
                "run_after": _at(p["on"], tm.window_start(p["channel"], pack), pack),
                "channel": p["channel"],
                "index": i + 1,
                "anchor_at": anchor,
            }
            for i, p in enumerate(plan["followup_plan"])
        ]
        last = plan["followup_plan"][-1]["on"] if plan["followup_plan"] else None
        if last:
            schedule.append(
                {
                    "event": "nudges_done",
                    "run_after": _at(
                        tm.next_working_day(date.fromisoformat(last), pack).isoformat(), hhmm, pack
                    ),
                    "anchor_at": anchor,
                    "checkin_on": plan["then"]["checkin_on"],
                }
            )
        out["schedule"] = schedule
        out["decision"] = "plan"
        return _result(out, rules, f"nudge plan {[p['on'] for p in plan['followup_plan']]}")

    state = str((record.get("lead") or {}).get("state") or "")
    anchor_at = tm.as_dt(data.get("anchor_at"))
    if state not in LIVE_STATES:
        out["decision"] = "skip"
        out["reason"] = f"lead is {state}"
        return _result(out, rules, out["reason"])
    if _inbound_since(record, anchor_at):
        out["decision"] = "skip"
        out["reason"] = "they wrote to us since; that reply was handled"
        return _result(out, rules, out["reason"])

    if event == "nudges_done":
        out["decision"] = "warm"
        out["lead_state_after"] = "warm"
        checkin = str(data.get("checkin_on") or "")
        if checkin:
            out["schedule"] = [
                {
                    "event": "warm_checkin_due",
                    "run_after": _at(
                        checkin, tm.window_start(str(record.get("channel") or "email"), pack), pack
                    ),
                    "anchor_at": data.get("anchor_at"),
                }
            ]
        return _result(out, ["CM-038", "CM-039"], "no reply after the nudges: warm")

    # nudge_due | not_now_due | warm_checkin_due: one nudge, on a channel the WhatsApp cap allows
    channel = str(data.get("channel") or record.get("channel") or "email")
    cap = int(ctx.defaults.get("whatsapp.max_unanswered", 2) or 2)
    if channel == "whatsapp" and unanswered_on(record, "whatsapp") >= cap:
        alt = next((c for c in record.get("verified_channels") or [] if c != "whatsapp"), None)
        if alt is None:
            out["decision"] = "skip"
            out["reason"] = f"WhatsApp cap: {cap} unanswered and no other verified channel"
            return _result(out, rules, out["reason"])
        channel = alt
    sender = record.get("sender") or {}
    last_in = [t for t in record.get("thread") or [] if t.get("dir") == "in"]
    lang = "en"
    if last_in and sig.reply_language(sig.language_of(str(last_in[-1].get("text") or ""))) == "ar":
        lang = "ar"  # their language (CM-032)
    if lang == "ar" and not ((record.get("campaign") or {}).get("options") or {}).get(
        "arabic_auto_send", True
    ):
        out["decision"] = "handover"
        out["handover"] = {"reasons": ["unsupported_language"]}
        return _result(out, rules, "Arabic auto-send is off", handover=True, record=record)
    kb_ctx = ctx.knowledge.prompt_context(max_rules=48) if ctx.knowledge is not None else ""
    feedback: list[str] = []
    body = None
    claims: list[dict[str, Any]] = []
    for _ in (1, 2):
        try:
            draft = rp.draft_with_llm(
                ctx.llm,
                kind="nudge",
                language=lang,
                channel=channel,
                sender=sender,
                reply_text="",
                thread=list(record.get("thread") or []),
                record=record,
                kb_context=kb_ctx,
                feedback=feedback,
            )
        except Exception as exc:  # noqa: BLE001
            feedback = [f"draft unavailable: {type(exc).__name__}"]
            break
        body = rp.finish(draft.body, sender, lang, first_name=recipient_first_name(record))
        claims = [c.model_dump() for c in draft.claims]
        chk = rp.check_draft(
            body,
            kind="nudge",
            channel=channel,
            language=lang,
            sender=sender,
            defaults=ctx.defaults,
            claims=claims,
            record=record,
        )
        if chk.ok:
            break
        feedback, body = chk.reasons, None
    if body is None:
        out["decision"] = "handover"
        out["handover"] = {"reasons": ["low_confidence"], "why": feedback}
        return _result(out, rules, f"nudge draft failed: {feedback}", handover=True, record=record)
    rec = {
        **record,
        "reply": {"at": datetime.now(UTC).isoformat() if not record.get("now") else record["now"]},
    }
    not_before, send_at, delay = send_times(
        rec, channel, ctx.defaults, seed=f"{record.get('lead_id')}:{event}"
    )
    reply = {
        "kind": "nudge",
        "language": lang,
        "body": body,
        "claims": claims,
        "channel": channel,
        "account": sender.get("account") if channel == record.get("channel") else None,
        "send_not_before": not_before.isoformat() if not_before else None,
        "send_at": send_at.isoformat() if send_at else None,
        "delay_seconds": delay,
        "through_gates": True,
    }
    out.update(
        decision="reply",
        reply=reply,
        message={"body": body, "channel": channel, "language": lang, "step": "nudge"},
    )
    return _result(out, rules, f"{event}: nudge on {channel}")


def _result(
    out: dict[str, Any],
    rules: list[str],
    why: str,
    *,
    handover: bool = False,
    record: Mapping[str, Any] | None = None,
) -> AgentResult:
    out["rules"] = rules
    out.setdefault("version", {"agent": "1.0"})
    tasks = []
    if handover and record is not None:
        tasks.append(
            {
                "kind": "escalation_reply",
                "reason": f"ReplyGuard follow-up needs a human: {why}",
                "status": "open",
            }
        )
    return AgentResult(
        output=out,
        logged_decisions=[
            LoggedDecision(
                choice=f"{out['event']} -> {out.get('decision')}",
                reasoning=why,
                rule_ids=rules,
                lead_id=out.get("lead_id"),
            )
        ],
        human_tasks=tasks,
    )
