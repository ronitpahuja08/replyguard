"""Load the case-shaped record for a live job from the database (read only).

``load_record(ctx, {"message_id": ...})`` for an inbound reply; ``{"lead_id": ..., "event": ...}`` for a
follow-up event. The record has the same shape as a test case's ``input`` so the same code decides both.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from paralax.agents.base import AgentContext

CM_META = "replyguard"  # Message.gate_results key for messages this agent drafted
DEAD_OUT = ("draft", "blocked", "failed", "checked", "in_sample")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(dt: datetime | None) -> str | None:
    a = _aware(dt)
    return a.isoformat() if a else None


def message_time(m: Any) -> datetime | None:
    return _aware(m.received_at if m.direction == "in" else (m.sent_at or m.created_at))


def thread_items(session: Any, lead_id: str, *, until: datetime | None = None) -> list[dict[str, Any]]:
    from paralax.db.models import Message

    rows = session.scalars(select(Message).where(Message.lead_id == lead_id)).all()
    items = []
    for m in rows:
        if m.direction == "out" and m.status in DEAD_OUT:
            continue
        at = message_time(m)
        if at is None or (until is not None and at > until):
            continue
        gr = m.gate_results or {}
        meta = gr.get(CM_META) or {}
        cw = gr.get("copywriter") or {}
        items.append(
            {
                "id": m.id,
                "dir": m.direction,
                "at": at.isoformat(),
                "channel": m.channel,
                "text": m.body,
                "kind": meta.get("kind") or cw.get("step") or None,
                "by": CM_META if meta else ("copywriter" if cw else None),
                "progress": bool(meta.get("progress")),
                "status": m.status,
            }
        )
    items.sort(key=lambda t: (t["at"], t["id"]))
    return items


def automated_without_progress(items: list[Mapping[str, Any]]) -> int:
    """CM-040: automated replies in a row (since the last progress) on this lead's threads."""
    n = 0
    for t in items:
        if t.get("dir") != "out" or t.get("by") != CM_META:
            continue
        n = 0 if t.get("progress") else n + 1
    return n


def thread_account(session: Any, msg: Any) -> Any:
    """The account that holds this thread (CM-045): the message's own, else the thread's, else the account of
    our latest outbound message to the lead on that channel."""
    from paralax.db.models import Message, SendingAccount, Thread

    if msg is None:
        return None
    if msg.sending_account_id:
        return session.get(SendingAccount, msg.sending_account_id)
    if msg.thread_id:
        t = session.get(Thread, msg.thread_id)
        if t is not None and t.sending_account_id:
            return session.get(SendingAccount, t.sending_account_id)
    last = session.scalars(
        select(Message)
        .where(
            Message.lead_id == msg.lead_id,
            Message.direction == "out",
            Message.channel == msg.channel,
            Message.sending_account_id.is_not(None),
        )
        .order_by(Message.created_at.desc())
    ).first()
    return session.get(SendingAccount, last.sending_account_id) if last is not None else None


def _sender(brief: Any, account: Any) -> dict[str, Any]:
    name = (getattr(brief, "sender_name", "") or "").strip() if brief is not None else ""
    if not name and account is not None:
        name = (account.display_name or "").split(" ")[0]
    company = (getattr(brief, "sender_company", "") or "").strip() if brief is not None else ""
    return {
        "name": name or "the team",
        "company": company or "Paralax",
        "account": account.address if account is not None else None,
        "account_id": account.id if account is not None else None,
    }


def load_record(ctx: AgentContext, inp: Mapping[str, Any]) -> dict[str, Any]:
    from paralax.agents.defaults import EffectiveDefaults  # noqa: F401  (typing aid)
    from paralax.db.models import (
        Brief,
        Campaign,
        CampaignCompany,
        Company,
        ContactPoint,
        Finding,
        Lead,
        Message,
        NumberAllowlist,
        Person,
        Report,
        SendingAccount,
    )
    from paralax.services.campaign_options import campaign_options

    s = ctx.session
    assert s is not None
    msg = s.get(Message, str(inp["message_id"])) if inp.get("message_id") else None
    if inp.get("message_id") and (msg is None or msg.direction != "in"):
        raise ValueError(f"replyguard: {inp['message_id']} is not an inbound message")
    lead_id = msg.lead_id if msg is not None else str(inp.get("lead_id") or ctx.lead_id or "")
    lead = s.get(Lead, lead_id)
    if lead is None:
        raise ValueError(f"replyguard: unknown lead {lead_id}")
    person = s.get(Person, lead.person_id)
    cc = s.get(CampaignCompany, lead.campaign_company_id)
    company = s.get(Company, cc.company_id) if cc is not None else None
    campaign = s.get(Campaign, lead.campaign_id)
    brief = (
        s.get(Brief, campaign.approved_brief_id)
        if campaign is not None and campaign.approved_brief_id
        else None
    )
    account = thread_account(s, msg)
    if account is None and msg is None:  # a follow-up event: the account that holds the lead's latest thread
        last = s.scalars(
            select(Message)
            .where(Message.lead_id == lead.id, Message.sending_account_id.is_not(None))
            .order_by(Message.created_at.desc())
        ).first()
        account = s.get(SendingAccount, last.sending_account_id) if last is not None else None

    arrived = message_time(msg) if msg is not None else None
    items = thread_items(s, lead.id, until=arrived)
    thread = [t for t in items if not (msg is not None and t["id"] == msg.id)]
    secs = None
    if msg is not None and arrived is not None:
        outs = [t for t in thread if t["dir"] == "out" and t["channel"] == msg.channel]
        if outs:
            secs = (arrived - datetime.fromisoformat(outs[-1]["at"])).total_seconds()
    intake = ((msg.gate_results or {}).get("inbound") or {}) if msg is not None else {}

    cp = None
    if msg is not None and msg.contact_point_id:
        cp = s.get(ContactPoint, msg.contact_point_id)
    if cp is None and person is not None:
        channel = msg.channel if msg is not None else None
        q = select(ContactPoint).where(ContactPoint.person_id == person.id)
        if channel:
            q = q.where(ContactPoint.channel == channel)
        cp = s.scalars(q.order_by(ContactPoint.created_at)).first()
    verified = sorted(
        {
            c.channel
            for c in s.scalars(select(ContactPoint).where(ContactPoint.person_id == lead.person_id))
            if c.verification == "verified" and c.erased_at is None
        }
    )

    findings = []
    if company is not None:
        for f in s.scalars(select(Finding).where(Finding.company_id == company.id)):
            if f.person_id and f.person_id != lead.person_id:
                continue
            findings.append(
                {
                    "id": f.id,
                    "kind": f.kind,
                    "text": f.text,
                    "value_num": f.value_num,
                    "unit": f.unit,
                    "observed_at": _iso(f.observed_at),
                }
            )
    report = None
    if cc is not None:
        r = s.scalars(
            select(Report).where(Report.campaign_company_id == cc.id).order_by(Report.version.desc())
        ).first()
        if r is not None:
            url = r.blob_key if str(r.blob_key or "").startswith(("http://", "https://")) else ""
            report = {"id": r.id, "headline": r.headline, "url": url}
    allow = []
    if brief is not None and campaign is not None:
        allow = [
            {"id": a.id, "value": a.value, "unit": a.unit, "text": a.text}
            for a in s.scalars(
                select(NumberAllowlist).where(
                    NumberAllowlist.campaign_id == campaign.id, NumberAllowlist.brief_id == brief.id
                )
            )
        ]
    others = []
    if cc is not None:
        for other in s.scalars(select(Lead).where(Lead.campaign_company_id == cc.id, Lead.id != lead.id)):
            others.append({"id": other.id, "state": other.state})

    opts = campaign_options(campaign) if campaign is not None else {}
    booking = (campaign.options or {}).get("booking_link") if campaign is not None else None
    if not booking and campaign is not None:
        # Day 5: the bound ``booking`` adapter's link, tagged for this lead; none bound → a human (CM-027)
        from paralax.services.booking import booking_link_for

        booking = booking_link_for(
            s,
            campaign.id,
            lead_id=lead.id,
            fallback=ctx.defaults.get("meetings.booking_link") if ctx.defaults is not None else None,
            clock=ctx.clock,
        )
    sender = _sender(brief, account)
    headers = dict(intake.get("headers") or {})
    if msg is not None and msg.subject and "Subject" not in headers:
        headers["Subject"] = msg.subject
    return {
        "message_id": msg.id if msg is not None else None,
        "lead_id": lead.id,
        "person_id": lead.person_id,
        "company_id": company.id if company is not None else None,
        "campaign_company_id": cc.id if cc is not None else None,
        "campaign_id": lead.campaign_id,
        "now": (arrived or ctx.clock.now()).isoformat() if msg is not None else ctx.clock.now().isoformat(),
        "channel": msg.channel if msg is not None else (thread[-1]["channel"] if thread else "email"),
        "country": company.country if company is not None else None,
        "campaign": {"options": opts, "booking_link": booking},
        "sender": sender,
        "lead": {
            "state": lead.state,
            "wave": lead.wave,
            "is_company_contact": bool(person and person.is_company_contact),
        },
        "person": {"first_name": ((person.full_name if person else "") or "").split(" ")[0]},
        "company": {"name": company.name if company else "", "other_leads": others},
        "thread": thread,
        "reply": (
            {
                "at": arrived.isoformat() if arrived else None,
                "text": msg.body,
                "headers": headers,
                "seconds_after_our_last": secs,
                "media": intake.get("media"),
            }
            if msg is not None
            else {}
        ),
        "subject": msg.subject if msg is not None else "",
        "detector_opt_out": intake.get("detector_opt_out") if "detector_opt_out" in intake else None,
        "auto_reply_at_intake": bool(intake.get("auto_reply")),
        "account_status": {sender["account"]: account.status} if account is not None else {},
        "contact_point": (
            {"id": cp.id, "source": cp.source, "collected_at": _iso(cp.collected_at)}
            if cp is not None
            else {}
        ),
        "verified_channels": verified,
        "findings": findings,
        "report": report or {},
        "offer": brief.offer if brief is not None else "",
        "allowlist": allow,
        "automated_replies_without_progress": automated_without_progress(items),
        "company_page": f"/companies/{company.id}" if company is not None else None,
        "person_card": f"/people/{lead.person_id}",
        "event": inp.get("event"),
        "event_data": {k: v for k, v in inp.items() if k not in ("message_id", "lead_id", "event")},
    }
