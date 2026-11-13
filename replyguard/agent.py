"""ReplyGuard, the ReplyGuard: classify every reply on our threads and take the right next step.

Input:
- live: ``{"message_id": <inbound Message id>}`` (one job per inbound message, enqueued by
  ``orchestrator/inbound.process_inbound``), or a follow-up event ``{"event": "nudge_due" | "not_now_due" |
  "nudges_done" | "warm_checkin_due", "lead_id": ...}`` scheduled by ``effects.py``;
- eval: the case-shaped record itself (``now, channel, campaign, sender, lead, thread, reply, ...``), or
  ``event: no_reply_after_jab_2``.

Flow for a reply: acceptance check (the reply arrives with person, company, the message it answered and the
thread) → deterministic signals (detector, auto-reply headers / timing, hints) → the classifier (LLM; when it
is unavailable the reply goes to a human with the deterministic safety intents still applied) → ``decide``
(locked rules in code) → the reply draft (template or LLM + self-check, one rewrite) → the result. The agent
never writes: ``effects.apply`` (the after-run hook) suppresses, signals, queues the draft as a Message
through the normal send path (all gates, outbox) and schedules follow-ups.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from paralax.agents.base import AgentContext, AgentResult, LoggedDecision
from paralax.agents.replyguard import checks as _checks  # noqa: F401  (registers the hard checks)
from paralax.agents.replyguard import replies as rp
from paralax.agents.replyguard import signals as sig
from paralax.agents.replyguard import timing as tm
from paralax.agents.replyguard.acceptance import acceptance_problems
from paralax.agents.replyguard.decide import (
    Decision,
    decide,
    fallback_classification,
    followup_plan,
    send_times,
)
from paralax.agents.replyguard.schemas import LABELS, Classification
from paralax.agents.registry import register_agent

AGENT_NAME = "replyguard"
VERSION = "1.0"
EVENTS = frozenset({"no_reply_after_jab_2", "nudge_due", "not_now_due", "nudges_done", "warm_checkin_due"})


# --------------------------------------------------------------------------------------------- loading


def _is_case_shaped(inp: Mapping[str, Any]) -> bool:
    return isinstance(inp.get("reply"), Mapping) or (inp.get("event") in EVENTS and "thread" in inp)


def load_input(ctx: AgentContext, inp: Mapping[str, Any]) -> dict[str, Any]:
    if _is_case_shaped(inp):
        rec = dict(inp)
        if ctx.session is None:
            rec["_case_mode"] = True
            company = str((rec.get("company") or {}).get("name") or "your company")
            rec.setdefault(
                "report", {"url": "https://reports.paralax.test/" + _slug(company), "headline": ""}
            )
        return rec
    if ctx.session is None:
        raise ValueError("replyguard: a message_id / lead_id job needs a database session")
    from paralax.agents.replyguard.record import load_record

    return load_record(ctx, inp)


def _slug(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", s.casefold()).strip("-") or "company"


# --------------------------------------------------------------------------------------------- the classifier


CLASSIFY_PROMPT = " ".join(
    """
You classify ONE inbound reply on a B2B outreach thread for the ReplyGuard. Read the meaning of
the whole message and the thread, not keywords ('stop by our showroom' is not an opt-out; 'remove the
price column' is not an opt-out). Gulf Arabic, English, mixed and Arabizi are common.
Labels: {labels}. Pick the primary `label`; put every other intent present in `also`. Safety intents
(complaint, opt_out, bot_question) must never be missed. `confidence` is 0-1 for the primary label; say
`sarcasm_suspected` when irony may flip the meaning. Set `speaks_for_company` when they ask us to stop
contacting their company ('us', 'anyone here'), `deletion_request` when they ask to delete their number or
data, `stated_signals` only for what they say they DID (reported, blocked), `handover_reasons` from:
{reasons}. For a referral give `referral` (name in Latin letters, name_original as written, role_hint,
email). For a correction about someone else give `other_person`. For a wrong person who left,
`left_company`. For timing give `timing` (kind: date|weekday|quarter|relative_days|anchor, value).
`language`: en | ar | mixed | arabizi | other (+ language_name). Cite rule ids.
""".split()
)


def classify(ctx: AgentContext, record: Mapping[str, Any]) -> tuple[Classification, bool]:
    """(classification, from_llm). No LLM answer → a deterministic fallback with confidence 0: a human reads
    it."""
    reply = record.get("reply") or {}
    text = str(reply.get("text") or "")
    if not text.strip():
        return Classification(label="unclear", confidence=0.0, reasoning="no text to read"), False
    kb = ctx.knowledge
    labels = ", ".join(LABELS)
    system = (
        CLASSIFY_PROMPT.format(labels=labels, reasons=", ".join(ctx.defaults.get("handover.reasons") or []))
        + "\n\n"
        + (kb.prompt_context(max_rules=48) if kb is not None else "")
    )
    user = json.dumps(
        {
            "channel": record.get("channel"),
            "reply": {
                "text": text,
                "headers": reply.get("headers") or {},
                "seconds_after_our_last": reply.get("seconds_after_our_last"),
            },
            "thread": [
                {"dir": t.get("dir"), "kind": t.get("kind"), "at": t.get("at"), "text": t.get("text")}
                for t in list(record.get("thread") or [])[-8:]
            ],
        },
        ensure_ascii=False,
        default=str,
    )
    try:
        c = ctx.llm.complete_json(
            "replyguard.classify",
            system=system,
            user=user,
            schema=Classification,
            model_tier="strong",
            timeout_s=60,
        )
    except Exception as exc:  # noqa: BLE001 - provider down / invalid output: a human reads it (CM-031)
        return fallback_classification(text, reason=f"classifier unavailable: {type(exc).__name__}"), False
    return c, True


# --------------------------------------------------------------------------------------------- drafting


def build_reply(ctx: AgentContext, record: Mapping[str, Any], d: Decision) -> dict[str, Any]:
    """The reply for ``d.reply_kind``: body (with sender + opt-out lines), claims, self-check result. A
    free-form draft that fails the self-check twice is not sent: the reply becomes a handover."""
    kind = d.reply_kind
    lang = d.reply_language or "en"
    channel = str(record.get("channel") or "email")
    sender = record.get("sender") or {}
    out: dict[str, Any] = {"kind": kind, "language": lang if kind != "none" else None, "body": None}
    if kind == "none":
        return out
    text = str((record.get("reply") or {}).get("text") or "")
    now = tm.as_dt(record.get("now")) or datetime.now(UTC)
    pack = tm.pack_for(record.get("country"))
    today = now.astimezone(tm.tz_of(pack)).date()
    claims: list[dict[str, Any]] = []
    body: str | None = None
    first = recipient_first_name(record)

    if kind == "confirmation_only":
        out["text_if_allowed"] = rp.finish(
            rp.template("confirmation_only", lang), sender, lang, first_name=first
        )
        out["status"] = "not_sent:gate_dnc_blocks_suppressed_person"
        return out
    if kind == "bot_disclosure":
        tpl = ctx.defaults.get(f"bot_question.template_{'ar' if lang == 'ar' else 'en'}") or ""
        body = str(tpl).format(
            sender_name=sender.get("name") or "", sender_company=sender.get("company") or ""
        )
        # owner, 10 Nov: also say truthfully where the number came from (the stored, real source)
        where = source_in_words((record.get("contact_point") or {}).get("source"), lang)
        if where:
            body = f"{body} {where}"
    elif kind == "holding_line":
        reasons = set(d.handover_reasons)
        if reasons & {"meeting_request_no_link", "visit_request"} and not reasons & {
            "pricing",
            "negotiation",
        }:
            body = rp.template("holding_meeting", lang, sender_name=sender.get("name") or "")
        else:
            tpl = ctx.defaults.get(f"handover.holding_line_{'ar' if lang == 'ar' else 'en'}") or ""
            body = str(tpl).format(sender_name=sender.get("name") or "")
    elif kind == "thanks":
        if d.person_flag == "left_company":
            body = rp.template("thanks_left", lang)
        else:
            name = str((d.new_person or {}).get("name") or "them")
            body = rp.template("thanks_referral", lang, name=name)
    elif kind == "ask_who":
        body = rp.template("ask_who", lang)
    elif kind == "thanks_optional_why":
        body = rp.template("thanks_optional_why", lang)
    elif kind == "when_suits_you":
        body = rp.template("when_suits_you", lang)
    elif kind == "confirm_date":
        on = d.timing_date or today
        when = rp.when_words(on, today, lang)
        wd = d.timing_said_weekday
        if wd is not None and wd != on.weekday():
            asked = (rp.AR_WEEKDAYS if lang == "ar" else rp.EN_WEEKDAYS)[wd]
            body = rp.template("confirm_date_moved", lang, asked=asked, when=when)
        else:
            body = rp.template("confirm_date", lang, when=when)
    elif kind == "booking_link":
        link = (record.get("campaign") or {}).get("booking_link") or ctx.defaults.get("meetings.booking_link")
        body = rp.template("booking_link", lang, link=link)
    elif kind in rp.LLM_KINDS:
        rec = dict(record)
        if kind in ("jab_2",) and not ((rec.get("report") or {}).get("url")):
            out.update(kind="none", language=None, failed="no report link to send")
            d.add_reason("outside_evidence")
            d.reply_kind, d.reply_allowed = "none", False
            return out
        kb_ctx = ctx.knowledge.prompt_context(max_rules=48) if ctx.knowledge is not None else ""
        feedback: list[str] = []
        for attempt in (1, 2):
            try:
                draft = rp.draft_with_llm(
                    ctx.llm,
                    kind=kind,
                    language=lang,
                    channel=channel,
                    sender=sender,
                    reply_text=text,
                    thread=list(record.get("thread") or []),
                    record=rec,
                    kb_context=kb_ctx,
                    feedback=feedback,
                )
            except Exception as exc:  # noqa: BLE001 - no draft: a human answers
                out.update(kind="none", language=None, failed=f"draft unavailable: {type(exc).__name__}")
                d.add_reason("low_confidence")
                d.reply_kind, d.reply_allowed = "none", False
                return out
            body = rp.finish(draft.body, sender, lang, first_name=first)
            claims = [c.model_dump() for c in draft.claims]
            chk = rp.check_draft(
                body,
                kind=kind,
                channel=channel,
                language=lang,
                sender=sender,
                defaults=ctx.defaults,
                claims=claims,
                record=rec,
            )
            out["self_check"] = {"attempt": attempt, "ok": chk.ok, "reasons": chk.reasons}
            if chk.ok:
                break
            feedback = chk.reasons
        else:
            out.update(kind="none", language=None, body=None, failed="; ".join(feedback)[:500])
            d.add_reason("outside_evidence" if chk.evidence_problem else "low_confidence")
            d.reply_kind, d.reply_allowed = "none", False
            d.notes.append(f"draft failed the self-check twice: {feedback}")
            return out
        out.update(body=body, claims=claims, subject=_subject(record))
        _times(out, record, channel, ctx, d)
        return out
    else:
        return out

    assert body is not None
    full = rp.finish(body, sender, lang, first_name=first)
    chk = rp.check_draft(
        full, kind=kind, channel=channel, language=lang, sender=sender, defaults=ctx.defaults
    )
    out["self_check"] = {"attempt": 1, "ok": chk.ok, "reasons": chk.reasons}
    if not chk.ok:  # a template that fails is a bug: never send it, hand over
        out.update(kind="none", language=None, failed="; ".join(chk.reasons))
        d.add_reason("low_confidence")
        d.reply_kind, d.reply_allowed = "none", False
        return out
    out.update(body=full, claims=[], subject=_subject(record))
    _times(out, record, channel, ctx, d)
    return out


def recipient_first_name(record: Mapping[str, Any]) -> str | None:
    """The person's first name (company mailboxes have none), as the content gate checks it."""
    if (record.get("lead") or {}).get("is_company_contact"):
        return None
    return str((record.get("person") or {}).get("first_name") or "").strip() or None


def _subject(record: Mapping[str, Any]) -> str:
    if str(record.get("channel")) != "email":
        return ""
    subj = sig.header((record.get("reply") or {}).get("headers"), "Subject") or str(
        record.get("subject") or ""
    )
    if not subj:
        return ""
    return subj if subj.lower().startswith("re:") else f"Re: {subj}"


def _times(
    out: dict[str, Any], record: Mapping[str, Any], channel: str, ctx: AgentContext, d: Decision
) -> None:
    seed = f"{record.get('message_id') or ''}:{(record.get('reply') or {}).get('text') or ''}"
    not_before, send_at, delay = send_times(record, channel, ctx.defaults, seed=seed)
    out["send_not_before"] = not_before.isoformat() if not_before else None
    out["send_at"] = send_at.isoformat() if send_at else None
    out["delay_seconds"] = delay
    out["through_gates"] = True  # queued as a Message for message.send: all gates + outbox (CM-035)
    out["channel"] = channel
    out["account"] = (record.get("sender") or {}).get("account")  # the thread's own account only (CM-045)
    out["questions"] = sig.count_questions(
        rp.core(out.get("body") or "", record.get("sender") or {}, out["language"] or "en")
    )
    d.rule("CM-034", "CM-035", "CM-037")


# --------------------------------------------------------------------------------------------- the agent


def _handover_task(
    record: Mapping[str, Any], d: Decision, reply: Mapping[str, Any], cls: Classification
) -> dict[str, Any]:
    """CM-029: everything the human needs in one step (reasons, classification, thread, links, account,
    suggested draft)."""
    sender = record.get("sender") or {}
    reply_in = record.get("reply") or {}
    thread = list(record.get("thread") or [])
    suggested = reply.get("body") or reply.get("text_if_allowed") or ""
    lines = [
        f"ReplyGuard handover: {', '.join(d.handover_reasons)}",
        f"Classification: {d.label} (also: {', '.join(d.also) or '-'}; confidence {d.confidence:.2f}); "
        f"detector opt-out: {d.detector_opt_out}",
        f"Channel: {record.get('channel')} · account: {sender.get('account')} · sender: {sender.get('name')}",
        f"Company page: {record.get('company_page') or '-'} · "
        f"person card: {record.get('person_card') or '-'}",
        f"Their message ({reply_in.get('at')}): {reply_in.get('text') or reply_in.get('media') or ''}",
        "Thread:",
        *[f"  [{t.get('dir')}] {t.get('at')}: {str(t.get('text') or '')[:400]}" for t in thread[-10:]],
    ]
    if d.handover_attach:
        lines.append("Attached: " + json.dumps(d.handover_attach, default=str, ensure_ascii=False))
    if reply.get("kind") not in (None, "none"):
        lines.append(f"Sent automatically ({reply.get('kind')}): {suggested}")
    else:
        lines.append(f"Suggested reply (not sent): {suggested or '(write one)'}")
    if cls.reasoning:
        lines.append(f"Classifier reasoning: {cls.reasoning[:500]}")
    urgent = bool(set(d.handover_reasons) & {"complaint", "legal_or_regulator", "possible_false_opt_out"})
    now = tm.as_dt(record.get("now")) or datetime.now(UTC)
    return {
        "kind": "escalation_reply",
        "reason": "\n".join(lines)[:8000],
        "due_at": (now if urgent else now + timedelta(hours=4)).astimezone(UTC),
        "status": "open",
    }


@register_agent(AGENT_NAME)
class ConversationManager:
    name = AGENT_NAME
    version = VERSION

    def run(self, ctx: AgentContext, inp: dict[str, Any]) -> AgentResult:
        record = load_input(ctx, inp)
        if record.get("event"):
            from paralax.agents.replyguard.followups import run_event

            return run_event(ctx, record)
        return self.reply(ctx, record)

    def reply(self, ctx: AgentContext, record: dict[str, Any]) -> AgentResult:
        problems = acceptance_problems(record)
        reply_in = record.get("reply") or {}
        text = str(reply_in.get("text") or "")
        if reply_in.get("media") and not text.strip():
            cls, from_llm = (
                Classification(label="unclear", confidence=0.0, reasoning="media we can't read"),
                False,
            )
        else:
            cls, from_llm = classify(ctx, record)
        d = decide(record, cls, ctx.defaults)
        if problems:
            d.add_reason("low_confidence")
            d.notes.append(f"acceptance: {problems}")
            if d.reply_kind not in ("none", "confirmation_only"):
                d.reply_kind, d.reply_allowed = "none", False
        reply = build_reply(ctx, record, d)
        if d.reply_kind == "none":
            reply.setdefault("kind", "none")

        handover: Any = False
        tasks: list[dict[str, Any]] = []
        if d.handover_reasons:
            handover = {"reasons": list(d.handover_reasons)}
            if d.handover_attach:
                handover["attach"] = list(d.handover_attach)
                handover["attached"] = d.handover_attach
            tasks.append(_handover_task(record, d, reply, cls))

        now = tm.as_dt(record.get("now")) or datetime.now(UTC)
        pack = tm.pack_for(record.get("country"))
        arrived = tm.as_dt(reply_in.get("at")) or now
        sent_at = tm.as_dt(reply.get("send_at")) if reply.get("body") else None
        first_response = sent_at or (now if tasks else None)
        response_minutes = tm.working_minutes(arrived, first_response, pack) if first_response else None

        cancelled = []
        others = ((record.get("company") or {}).get("other_leads") or []) if d.counts_as_reply else []
        for other in others:  # the company lock (set at intake, CM-014) cancelled their next touches
            nj = other.get("next_job") or {}
            if nj:
                cancelled.append(
                    {"lead": other.get("id"), "channel": nj.get("channel"), "kind": "sequence.next"}
                )

        output: dict[str, Any] = {
            "agent": AGENT_NAME,
            "acceptance": list(problems),  # the SOP acceptance rule; recorded as a HandoverCheck when applied
            "message_id": record.get("message_id"),
            "lead_id": record.get("lead_id"),
            "channel": record.get("channel"),
            "language": d.language,
            "label": d.label,
            "also": list(d.also),
            "confidence": round(d.confidence, 3),
            "classified_by": "llm+rules" if from_llm else "rules_only",
            "detector_opt_out": d.detector_opt_out,
            "spans": d.spans,
            "actions": {
                "suppress": d.suppress,
                "suppressed_at": arrived.isoformat() if d.suppress != "none" else None,
                "suppression_lifted": False,  # never by the agent (CM-006)
                "erase": d.erase,
                "account_signals": list(d.account_signals),
                "company_lock": d.company_lock,
                "cancel_jobs": bool(d.opt_out),
                "cancelled_jobs": cancelled,
                "other_people_jobs_cancelled": d.suppress == "company",
                "route_to": list(d.route_to),
                "new_person": d.new_person,
                "messages_to_new_person_before_verified": 0,  # CM-019: the Contact Finder verifies first
                "other_person": d.other_person,
                "person_flag": d.person_flag,
                "further_touches_to_person": 0 if d.person_flag == "left_company" else None,
                "handover": handover,
                "calendar_events_created": 0,  # CM-018 / CM-027: never
                "whatsapp_call_placed": False,
                "messages_from_other_accounts": 0,  # CM-045
            },
            "reply": reply,
            "lead_state_after": d.state_after,
            "lost_reason": d.lost_reason,
            "counts_as_reply": d.counts_as_reply,
            "followup": d.followup,
            "auto_reply_reasons": d.auto_reply_reasons,
            "rules": list(d.rules),
            "notes": list(d.notes),
            "version": {"playbook": ctx.knowledge.version if ctx.knowledge else VERSION, "agent": VERSION},
            "kpi": {
                "arrived_at": arrived.isoformat(),
                "label": d.label,
                "confidence": round(d.confidence, 3),
                "action": "reply" if reply.get("body") else ("handover" if tasks else "no_reply"),
                "response_working_minutes": response_minutes,
                "handover_reasons": list(d.handover_reasons),
                "state_after": d.state_after,
                "counts_as_reply": d.counts_as_reply,
            },
            "decision": "reply" if reply.get("body") else ("handover" if tasks else "no_reply"),
        }
        if reply.get("body"):
            output["message"] = {
                "body": reply["body"],
                "subject": reply.get("subject") or "",
                "channel": record.get("channel"),
                "language": reply.get("language"),
                "is_reply": True,
                "step": "reply",
                "claims": reply.get("claims") or [],
            }
        logged = LoggedDecision(
            choice=f"{d.label} -> {output['decision']} ({reply.get('kind')})",
            options_considered=[d.label, *d.also],
            reasoning=(cls.reasoning or "")[:800]
            + (f" | handover: {d.handover_reasons}" if d.handover_reasons else ""),
            confidence=float(d.confidence),
            inputs_summary=f"{record.get('channel')} reply {text[:160]!r}",
            lead_id=record.get("lead_id"),
            rule_ids=list(d.rules),
        )
        return AgentResult(output=output, logged_decisions=[logged], human_tasks=tasks)


def plan_followups(record: Mapping[str, Any], defaults: Any) -> dict[str, Any]:
    """The nudge plan after jab 2 went unanswered (eval event ``no_reply_after_jab_2``)."""
    return followup_plan(record, defaults)


def _install_hook() -> None:
    from paralax.agents.replyguard import effects
    from paralax.agents.registry import register_after_hook

    register_after_hook(AGENT_NAME, effects.apply)


_install_hook()


def source_in_words(source: Any, lang: str = "en") -> str:
    """The contact's real stored source as one plain sentence (never invented). Empty if none is stored."""
    from urllib.parse import urlparse

    s = str(source or "").strip()
    if not s:
        return ""
    low = s.lower()
    host = urlparse(s if "://" in s else f"https://{s}").netloc.lower().removeprefix("www.")
    if any(k in low for k in ("google", "maps.app.goo.gl", "goo.gl/maps", "g.page")):
        en, ar = "your Google Business profile", "ملفكم على Google"
    elif host and "." in host and " " not in host:
        en, ar = f"{host}", f"{host}"
    else:
        en, ar = s[:80], s[:80]
    if lang == "ar":
        return f"وحصلنا على الرقم من {ar} حيث هو منشور للعموم."
    return f"We found your number on {en}, where it is publicly listed."
