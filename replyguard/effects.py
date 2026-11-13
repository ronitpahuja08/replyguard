"""The ReplyGuard's after-run hook: the single place its decisions are written (live jobs only).

Runs in the job's transaction, after ``apply_result`` stored the decision log and the handover tasks:

- opt-out / complaint: suppress the person on every channel (and the company for "us"), Do-not-contact, cancel
  the person's jobs, erase on a deletion request (CM-004, CM-010 to CM-012, CM-043). The detector already did
  the first part at intake; doing it again is idempotent, and it is how a classifier-only opt-out is honoured;
- complaint: ``account_health.record_account_signal(kind="complaint")`` (+ report / block when stated) on the
  thread's account. Written WhatsApp complaints are recorded as ``complaint`` here; whether they count toward
  the WhatsApp health triggers is ``account_health``'s call (CHANGELOG open point 4);
- the reply: a ``Message`` (status approved, ``is_reply``, the thread's own account and contact point) and a
  ``message.send`` job at the allowed time. Nothing is sent from here: every gate and the outbox run at send
  time (CM-035). A confirmation after an opt-out is never queued (Gate 2 blocks it; no exemption, CM-013);
- auto-replies: the company lock released with a logged reason, the person's pending touches moved to the
  resume date (CM-008); referrals and alternate contacts go to the Contact Finder unverified (CM-019); people
  who left are flagged (CM-020, CM-048); follow-ups are scheduled as ``agent.replyguard`` events
  (CM-022, CM-038);
- every handover raises an alert next to its task (critical for complaints, legal and possible false
  opt-outs).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from paralax.core.clock import Clock
from paralax.db.events import record_event, transition_lead
from paralax.domain.lead_states import LeadState, can_transition
from paralax.orchestrator.handlers import JobContext, handler
from paralax.orchestrator.queue import cancel_jobs, enqueue

AGENT = "replyguard"
FINAL_STATUSES = ("sent", "delivered", "blocked", "failed", "bounced")
URGENT_REASONS = frozenset({"complaint", "legal_or_regulator", "possible_false_opt_out"})


def _dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    return None


def _utc(dt: datetime | None) -> datetime | None:
    return dt.astimezone(UTC) if dt is not None else None


def _move(session: Any, lead: Any, to: str, reason: str, clock: Clock, job_id: str | None) -> bool:
    if lead.state == to or not can_transition(lead.state, to):
        return False
    transition_lead(
        session, lead, to, actor_type="agent", actor_id=AGENT, reason=reason[:200], job_id=job_id, clock=clock
    )
    return True


def _event(
    session: Any, *, lead: Any, type_: str, payload: dict[str, Any], clock: Clock, job_id: str | None
) -> None:
    record_event(
        session,
        entity_type="lead",
        entity_id=lead.id,
        type=type_,
        actor_type="agent",
        actor_id=AGENT,
        campaign_id=lead.campaign_id,
        payload=payload,
        job_id=job_id,
        clock=clock,
    )


def schedule_event(
    session: Any, *, lead: Any, company_id: str | None, item: dict[str, Any], clock: Clock, parent: str | None
) -> Any:
    run_after = _dt(item.get("run_after")) or clock.now()
    data = {k: v for k, v in item.items() if k != "run_after"}
    key = f"agent.{AGENT}:{lead.id}:{data.get('event')}:{data.get('index') or ''}:{run_after.isoformat()}"
    return enqueue(
        session,
        kind=f"agent.{AGENT}",
        payload={"input": {"lead_id": lead.id, **data}},
        idempotency_key=key,
        run_after=run_after,
        campaign_id=lead.campaign_id,
        lead_id=lead.id,
        company_id=company_id,
        parent_job_id=parent,
        clock=clock,
    )


# --------------------------------------------------------------------------------------------- the hook


def apply(jctx: Any, job: Any, result: Any, applied: dict[str, Any]) -> dict[str, Any]:
    from paralax.db.models import CampaignCompany, Company, Lead, Message

    s, clock = jctx.session, jctx.clock
    out = dict(result.output or {})
    lead = s.get(Lead, out.get("lead_id") or job.lead_id)
    if lead is None:
        return {"skipped": "no lead"}
    cc = s.get(CampaignCompany, lead.campaign_company_id)
    company = s.get(Company, cc.company_id) if cc is not None else None
    done: dict[str, Any] = {"actions": []}

    if out.get("event"):
        return _apply_event(jctx, job, out, lead, company, done)

    inbound = s.get(Message, out.get("message_id")) if out.get("message_id") else None
    if inbound is None:
        return {"skipped": "no inbound message"}
    marker = (inbound.gate_results or {}).get(AGENT) or {}
    if marker.get("applied"):
        return {"skipped": "already applied", "job_id": marker.get("job_id")}
    from paralax.agents.replyguard.record import thread_account

    account = thread_account(s, inbound)
    actions = out.get("actions") or {}
    state_before = lead.state

    # 1. suppression, Do-not-contact, cancelled jobs (at once, any hour)
    if actions.get("suppress") in ("person", "company"):
        from paralax.domain.suppression import suppress, suppress_person_everywhere

        reason = "complaint" if out.get("label") == "complaint" else "opt_out"
        suppress_person_everywhere(
            s,
            lead.person_id,
            reason,
            source=f"inbound:{inbound.id}",
            created_by=f"agent:{AGENT}",
            clock=clock,
            campaign_id=lead.campaign_id,
        )
        cancel_jobs(s, lead_id=lead.id)
        done["actions"].append(f"suppressed:{actions['suppress']}")
        if actions["suppress"] == "company" and company is not None:
            suppress(
                s,
                type="company",
                value=company.id,
                reason=reason,
                source=f"inbound:{inbound.id}",
                created_by=f"agent:{AGENT}",
                clock=clock,
                campaign_id=lead.campaign_id,
            )
            cancel_jobs(s, company_id=company.id, kinds=["message.send", "sequence.next"])
            for other in s.scalars(select(Lead).where(Lead.campaign_company_id == lead.campaign_company_id)):
                if other.id != lead.id:
                    cancel_jobs(s, lead_id=other.id)
        _move(s, lead, LeadState.DO_NOT_CONTACT, "asked to stop (conversation manager)", clock, job.id)

    # 2. account-health signals on the thread's account (CM-010, CM-044)
    for kind in actions.get("account_signals") or []:
        if account is None:
            done["actions"].append(f"signal_skipped_no_account:{kind}")
            continue
        from paralax.orchestrator.account_health import record_account_signal

        record_account_signal(
            s,
            account,
            kind,
            clock=clock,
            payload={"lead_id": lead.id, "message_id": inbound.id},
            campaign_id=lead.campaign_id,
            actor_id=AGENT,
        )
        done["actions"].append(f"signal:{kind}")

    # 3. company lock: an auto-reply releases it, with a reason (CM-008)
    if (
        actions.get("company_lock") == "released_auto_reply"
        and cc is not None
        and cc.company_lock_at is not None
    ):
        human_since = [
            m
            for m in s.scalars(
                select(Message)
                .join(Lead, Lead.id == Message.lead_id)
                .where(Lead.campaign_company_id == cc.id, Message.direction == "in", Message.id != inbound.id)
            )
            if not ((m.gate_results or {}).get("inbound") or {}).get("auto_reply")
            and not ((m.gate_results or {}).get(AGENT) or {}).get("label") == "auto_reply"
        ]
        if not human_since:
            cc.company_lock_at = None
            record_event(
                s,
                entity_type="campaign_company",
                entity_id=cc.id,
                type="company.lock_released",
                actor_type="agent",
                actor_id=AGENT,
                campaign_id=lead.campaign_id,
                payload={"reason": "auto_reply", "message_id": inbound.id},
                job_id=job.id,
                clock=clock,
            )
            done["actions"].append("company_lock_released")

    # 4. people: referral / alternate contact, left the company, a correction about someone else
    if actions.get("new_person") and "contact_finder" in (actions.get("route_to") or []) and cc is not None:
        done["referral"] = _referral(s, lead, cc, inbound, actions["new_person"], clock, job.id)
    if actions.get("person_flag") == "left_company":
        from paralax.db.models import Person

        p = s.get(Person, lead.person_id)
        if p is not None:
            p.card = {
                **(p.card or {}),
                "left_company": {"at": clock.now().isoformat(), "source": f"inbound:{inbound.id}"},
            }
        cancel_jobs(s, lead_id=lead.id, kinds=["message.send", "sequence.next"])
        _event(
            s,
            lead=lead,
            type_="person.left_company",
            payload={"route_to": actions.get("route_to")},
            clock=clock,
            job_id=job.id,
        )
        done["actions"].append("left_company_flagged")
    if actions.get("other_person") and cc is not None:
        done["other_person"] = _other_person(s, lead, cc, inbound, actions["other_person"], clock, job.id)

    # 5. the reply: a Message through the normal send path, never a direct send
    reply = out.get("reply") or {}
    message_id = None
    if (
        reply.get("body")
        and reply.get("kind") not in ("none", "confirmation_only")
        and lead.state
        not in (
            "do_not_contact",
            "lost",
            "won",
        )
    ):
        progress = (
            state_before != "replied"
            or out.get("label") in ("referral", "meeting_request")
            or out.get("lead_state_after") in ("warm", "lost", "meeting_booked")
        )
        message_id = queue_reply(
            s,
            lead=lead,
            inbound=inbound,
            account=account,
            reply=reply,
            out=out,
            progress=bool(progress),
            clock=clock,
            job=job,
            company_id=company.id if company else None,
        )
        done["reply_message_id"] = message_id
        if reply.get("kind") == "jab_2":
            send_at = _dt(reply.get("send_at")) or clock.now()
            schedule_event(
                s,
                lead=lead,
                company_id=company.id if company else None,
                item={
                    "event": "no_reply_after_jab_2",
                    "run_after": (send_at + timedelta(hours=1)).isoformat(),
                    "jab2_message_id": message_id,
                },
                clock=clock,
                parent=job.id,
            )
    elif reply.get("kind") == "confirmation_only":
        _event(
            s,
            lead=lead,
            type_="conversation.confirmation_not_sent",
            payload={"reason": "gate_dnc_blocks_suppressed_person", "rule": "CM-013"},
            clock=clock,
            job_id=job.id,
        )

    # 6. lead state (CM-021, CM-022, CM-039); Lost waits until the thanks has left (Gate 2 blocks Lost leads)
    to = out.get("lead_state_after")
    if to in ("replied", "warm"):
        if lead.state not in ("replied", "warm") and to == "warm":
            _move(s, lead, LeadState.REPLIED, "reply received", clock, job.id)
        _move(s, lead, to, f"{out.get('label')}", clock, job.id)
    elif to == "lost":
        if message_id:
            enqueue(
                s,
                kind="conversation.finalize_state",
                payload={
                    "lead_id": lead.id,
                    "to_state": "lost",
                    "reason": out.get("lost_reason") or "",
                    "message_id": message_id,
                    "deadline": (clock.now() + timedelta(days=3)).isoformat(),
                },
                idempotency_key=f"conversation.finalize_state:{lead.id}:{message_id}",
                run_after=(_dt(reply.get("send_at")) or clock.now()) + timedelta(minutes=5),
                campaign_id=lead.campaign_id,
                lead_id=lead.id,
                clock=clock,
            )
        else:
            _move(s, lead, LeadState.LOST, out.get("lost_reason") or "said no", clock, job.id)
        cancel_jobs(s, lead_id=lead.id, kinds=["sequence.next"])

    # 7. follow-ups (CM-008, CM-022)
    fu = out.get("followup") or {}
    if fu.get("kind") == "resume_after_ooo" and fu.get("on"):
        done["postponed_jobs"] = _postpone(s, lead, fu["on"], clock, company.country if company else None)
    elif fu.get("kind") == "not_now" and fu.get("on"):
        hh = str(fu.get("window_start") or "09:00")
        from paralax.agents.replyguard import timing as tm

        pack = tm.pack_for(company.country if company else None)
        on = datetime.fromisoformat(fu["on"])
        at = on.replace(hour=int(hh[:2]), minute=int(hh[3:5]), tzinfo=tm.tz_of(pack))
        lead.next_action_at = _utc(at)
        schedule_event(
            s,
            lead=lead,
            company_id=company.id if company else None,
            item={
                "event": "not_now_due",
                "run_after": at.isoformat(),
                "anchor_at": inbound_time(inbound),
                "channel": inbound.channel,
            },
            clock=clock,
            parent=job.id,
        )

    # 8. erasure last (it scrubs the stored texts, including the inbound message)
    if actions.get("erase"):
        from paralax.services.erasure import erase

        erase(s, person_id=lead.person_id, requested_by=f"agent:{AGENT}", clock=clock)
        done["actions"].append("erased")

    # 9. handover alert next to the task(s)
    reasons = (
        list(((actions.get("handover") or {}) or {}).get("reasons") or []) if actions.get("handover") else []
    )
    if reasons:
        from paralax.alerts.service import raise_alert

        urgent = bool(set(reasons) & URGENT_REASONS)
        raise_alert(
            s,
            severity="critical" if urgent else "warning",
            kind="conversation_handover",
            dedupe_key=f"conversation_handover:{inbound.id}",
            subject=f"Reply needs a human: {', '.join(reasons)}",
            message=f"Lead {lead.id}, {inbound.channel}. "
            f"Task(s): {', '.join(applied.get('human_task_ids') or [])}",
            clock=clock,
        )
        done["actions"].append("alert")

    # 10. the handover check (SOP acceptance rule), the decision on the inbound message, the KPI event
    from paralax.agents.handover import check_handover

    check_handover(
        s,
        from_agent="channel_operator",
        to_agent=AGENT,
        subject_type="message",
        subject_id=inbound.id,
        check_fn=lambda: list(out.get("acceptance") or []),
        clock=clock,
    )
    if actions.get("erase"):
        s.refresh(inbound)
    inbound.gate_results = {
        **(inbound.gate_results or {}),
        AGENT: {
            "applied": True,
            "job_id": job.id,
            "label": out.get("label"),
            "also": out.get("also"),
            "confidence": out.get("confidence"),
            "decision": out.get("decision"),
            "counts_as_reply": out.get("counts_as_reply"),
            "reply_message_id": message_id,
        },
    }
    _event(
        s,
        lead=lead,
        type_="conversation.classified",
        payload={
            **(out.get("kpi") or {}),
            "message_id": inbound.id,
            "reply_message_id": message_id,
            "rules": out.get("rules"),
        },
        clock=clock,
        job_id=job.id,
    )
    s.flush()
    return done


def inbound_time(m: Any) -> str | None:
    t = m.received_at or m.created_at
    if t is None:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).isoformat()


def queue_reply(
    s: Any,
    *,
    lead: Any,
    inbound: Any,
    account: Any,
    reply: dict[str, Any],
    out: dict[str, Any],
    progress: bool,
    clock: Clock,
    job: Any,
    company_id: str | None,
) -> str:
    """The draft as an approved ``Message`` on the thread's own account + a ``message.send`` job at
    ``send_at``. Idempotent per inbound message (one reply per reply)."""
    from paralax.db.models import Finding, Message, MessageClaim

    in_reply_to = inbound.id if inbound is not None else None
    for m in s.scalars(select(Message).where(Message.lead_id == lead.id, Message.direction == "out")):
        meta = (m.gate_results or {}).get(AGENT) or {}
        if in_reply_to and meta.get("in_reply_to") == in_reply_to:
            return m.id
    channel = str(reply.get("channel") or (inbound.channel if inbound is not None else "email"))
    same_thread = inbound is not None and channel == inbound.channel
    msg = Message(
        lead_id=lead.id,
        channel=channel,
        direction="out",
        sending_account_id=account.id if (account is not None and same_thread) else None,
        contact_point_id=inbound.contact_point_id if same_thread else None,
        thread_id=inbound.thread_id if same_thread else None,
        subject=str(reply.get("subject") or "")[:300],
        body=str(reply["body"]),
        language=str(reply.get("language") or "en")[:8],
        status="approved",
        is_first_touch=False,
        linkedin_kind="message" if channel == "linkedin" else "",
        playbook_version_id=None,
    )
    msg.gate_results = {
        "is_reply": True,
        AGENT: {
            "kind": reply.get("kind"),
            "label": out.get("label"),
            "in_reply_to": in_reply_to,
            "progress": progress,
            "rules": out.get("rules"),
            "job_id": job.id,
        },
    }
    s.add(msg)
    s.flush()
    for c in reply.get("claims") or []:
        src, ref = str(c.get("source") or ""), str(c.get("ref") or "")
        if src == "findings" and ref and s.get(Finding, ref) is not None:
            s.add(
                MessageClaim(
                    message_id=msg.id, claim_text=str(c.get("text") or ""), about="prospect", finding_id=ref
                )
            )
        elif src in ("brief_offer", "offer_allow_list"):
            s.add(MessageClaim(message_id=msg.id, claim_text=str(c.get("text") or ""), about="offer"))
    send_at = _dt(reply.get("send_at")) or clock.now()
    enqueue(
        s,
        kind="message.send",
        payload={"message_id": msg.id},
        idempotency_key=f"message.send:{msg.id}",
        run_after=send_at,
        campaign_id=lead.campaign_id,
        lead_id=lead.id,
        company_id=company_id,
        clock=clock,
    )
    _event(
        s,
        lead=lead,
        type_="conversation.reply_queued",
        payload={
            "message_id": msg.id,
            "kind": reply.get("kind"),
            "send_at": send_at.isoformat(),
            "in_reply_to": in_reply_to,
        },
        clock=clock,
        job_id=job.id,
    )
    s.flush()
    return msg.id


def _referral(
    s: Any, lead: Any, cc: Any, inbound: Any, person: dict[str, Any], clock: Clock, job_id: str
) -> dict[str, Any]:
    """CM-019: the colleague as a person + lead at the company (unverified), then the Contact Finder. No
    message goes to them until a contact detail is verified."""
    from paralax.db.models import ContactPoint, Lead, Person

    name = str(person.get("name") or person.get("name_original") or "").strip()
    existing = None
    if name:
        for p in s.scalars(select(Person).where(Person.company_id == cc.company_id)):
            if (p.full_name or "").casefold().split(" ")[:1] == name.casefold().split(" ")[:1]:
                existing = p
                break
    p = existing or Person(
        company_id=cc.company_id,
        full_name=name,
        title=str(person.get("role_hint") or "")[:200],
        card={
            "referred": {
                "by_lead_id": lead.id,
                "source": f"inbound:{inbound.id}",
                "role_hint": person.get("role_hint"),
            }
        },
    )
    if existing is None:
        s.add(p)
        s.flush()
    new_lead = s.scalars(
        select(Lead).where(Lead.person_id == p.id, Lead.campaign_id == lead.campaign_id)
    ).first()
    if new_lead is None:
        new_lead = Lead(
            campaign_id=lead.campaign_id,
            person_id=p.id,
            campaign_company_id=cc.id,
            state="new",
            wave=lead.wave,
            referred_by_lead_id=lead.id,
        )
        s.add(new_lead)
        s.flush()
    email = str(person.get("candidate_email") or "").strip().lower()
    if (
        email
        and not s.scalars(
            select(ContactPoint).where(ContactPoint.person_id == p.id, ContactPoint.value_normalized == email)
        ).first()
    ):
        s.add(
            ContactPoint(
                person_id=p.id,
                company_id=cc.company_id,
                channel="email",
                value_normalized=email,
                source=f"referral:inbound:{inbound.id}",
                collected_at=_utc(clock.now()),
                verification="unverified",
            )
        )
    enqueue(
        s,
        kind="agent.contact_finder",
        payload={"input": {"campaign_company_id": cc.id}},
        idempotency_key=f"agent.contact_finder:{cc.id}:referral:{inbound.id}",
        campaign_id=lead.campaign_id,
        company_id=cc.company_id,
        clock=clock,
    )
    _event(
        s,
        lead=lead,
        type_="conversation.referral_routed",
        payload={"new_lead_id": new_lead.id, "person_id": p.id, "route_to": "contact_finder"},
        clock=clock,
        job_id=job_id,
    )
    return {"person_id": p.id, "lead_id": new_lead.id}


def _other_person(
    s: Any, lead: Any, cc: Any, inbound: Any, other: dict[str, Any], clock: Clock, job_id: str
) -> dict[str, Any]:
    """CM-048: a correction about someone else: their touches stop, their contact points are marked stale and
    re-verified. The replier is not suppressed."""
    from paralax.db.models import ContactPoint, Lead, Person

    first = str(other.get("name") or "").casefold().split(" ")[0]
    hits = []
    for p in s.scalars(select(Person).where(Person.company_id == cc.company_id, Person.id != lead.person_id)):
        if first and (p.full_name or "").casefold().split(" ")[:1] == [first]:
            hits.append(p)
    for p in hits:
        for cp in s.scalars(select(ContactPoint).where(ContactPoint.person_id == p.id)):
            cp.verification = "unverified"
            cp.details = {
                **(cp.details or {}),
                "stale": {"reason": other.get("issue"), "source": f"inbound:{inbound.id}"},
            }
        for ol in s.scalars(select(Lead).where(Lead.person_id == p.id)):
            cancel_jobs(s, lead_id=ol.id)
    if hits:
        enqueue(
            s,
            kind="agent.contact_finder",
            payload={"input": {"campaign_company_id": cc.id}},
            idempotency_key=f"agent.contact_finder:{cc.id}:stale:{inbound.id}",
            campaign_id=lead.campaign_id,
            company_id=cc.company_id,
            clock=clock,
        )
    _event(
        s,
        lead=lead,
        type_="conversation.other_person_corrected",
        payload={"matched_people": [p.id for p in hits], "issue": other.get("issue")},
        clock=clock,
        job_id=job_id,
    )
    return {"matched_people": [p.id for p in hits]}


def _postpone(s: Any, lead: Any, on: str, clock: Clock, country: str | None = None) -> int:
    """CM-008: the person's pending touches wait until the resume date (first allowed working day after
    return), from the opening of allowed hours there."""
    from paralax.agents.replyguard import timing as tm
    from paralax.db.models import Job

    pack = tm.pack_for(country)
    day = datetime.fromisoformat(on)
    at = tm.next_allowed(day.replace(hour=0, minute=0, tzinfo=tm.tz_of(pack)), pack).astimezone(UTC)
    lead.next_action_at = at
    n = 0
    for j in s.scalars(
        select(Job).where(
            Job.lead_id == lead.id,
            Job.status.in_(("queued", "waiting")),
            Job.kind.in_(("message.send", "sequence.next")),
        )
    ):
        ra = _dt(j.run_after)
        if ra is None or ra < at:
            j.run_after = at
            n += 1
    s.flush()
    return n


def _apply_event(
    jctx: Any, job: Any, out: dict[str, Any], lead: Any, company: Any, done: dict[str, Any]
) -> dict[str, Any]:
    s, clock = jctx.session, jctx.clock
    for item in out.get("schedule") or []:
        schedule_event(
            s, lead=lead, company_id=company.id if company else None, item=item, clock=clock, parent=job.id
        )
    reply = out.get("reply") or {}
    if out.get("decision") == "reply" and reply.get("body") and lead.state in ("replied", "engaged", "warm"):
        from paralax.db.models import Message, SendingAccount

        last_in = s.scalars(
            select(Message)
            .where(Message.lead_id == lead.id, Message.direction == "in")
            .order_by(Message.received_at.desc())
        ).first()
        account = None
        if reply.get("account") and last_in is not None and last_in.sending_account_id:
            account = s.get(SendingAccount, last_in.sending_account_id)
        mid = queue_reply(
            s,
            lead=lead,
            inbound=last_in if (last_in is not None and reply.get("channel") == last_in.channel) else None,
            account=account,
            reply=reply,
            out=out,
            progress=False,
            clock=clock,
            job=job,
            company_id=company.id if company else None,
        )
        done["reply_message_id"] = mid
    if out.get("lead_state_after") == "warm":
        _move(s, lead, LeadState.WARM, "no reply after the nudges", clock, job.id)
    s.flush()
    return done


@handler("conversation.finalize_state")
def finalize_state(ctx: JobContext, job: Any) -> dict[str, Any]:
    """Move a lead to its final state once the last automated message has left (or could not)."""
    from paralax.db.models import Lead, Message

    s, clock = ctx.session, ctx.clock
    p = job.payload or {}
    lead = s.get(Lead, p.get("lead_id"))
    if lead is None:
        return {"skipped": "no lead"}
    msg = s.get(Message, p.get("message_id")) if p.get("message_id") else None
    deadline = _dt(p.get("deadline"))
    if msg is not None and msg.status not in FINAL_STATUSES and (deadline is None or clock.now() < deadline):
        nxt = clock.now() + timedelta(minutes=10)
        enqueue(
            s,
            kind="conversation.finalize_state",
            payload=p,
            idempotency_key=f"conversation.finalize_state:{lead.id}:{p.get('message_id')}:{nxt.isoformat()}",
            run_after=nxt,
            campaign_id=lead.campaign_id,
            lead_id=lead.id,
            clock=clock,
        )
        return {"waiting_for_message": msg.status}
    moved = _move(s, lead, str(p.get("to_state")), str(p.get("reason") or ""), clock, job.id)
    return {"moved": moved, "state": lead.state}
