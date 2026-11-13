"""ReplyGuard end to end on the database: the qualification gate, referrals, a 'no' that waits for
its thanks before Lost, jab 2 with its follow-up plan, not-now dates, auto-reply lock release, nudges under
the WhatsApp cap, and the decision log / handover check."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from paralax.agents.replyguard.effects import finalize_state
from paralax.core.config import Settings
from paralax.db.models import (
    CampaignCompany,
    ContactPoint,
    DecisionLog,
    Event,
    HandoverCheck,
    Job,
    Lead,
    Message,
    Person,
    Report,
)
from paralax.orchestrator.errors import Permanent
from paralax.orchestrator.handlers import JobContext
from paralax.orchestrator.queue import enqueue
from tests.world import (
    cm_jobs,
    llm_with,
    make_world,
    qualify,
    receive,
    reply_messages,
    run_job,
)


def _jobs(session, kind: str) -> list[Job]:  # noqa: ANN001
    return list(session.scalars(select(Job).where(Job.kind == kind)))


def test_live_job_without_a_passing_eval_is_not_qualified(session, clock) -> None:
    w = make_world(session, clock)
    msg, _ = receive(w, "Yes send it")
    (job,) = cm_jobs(session, msg.id)
    with pytest.raises(Permanent, match="agent not qualified"):
        run_job(session, clock, job, llm_with())


def test_dry_run_applies_nothing(session, clock) -> None:
    w = make_world(session, clock)
    msg, _ = receive(w, "Talk to my colleague Priya, she handles marketing")
    job = enqueue(
        session,
        kind="agent.replyguard",
        payload={"mode": "dry_run", "input": {"message_id": msg.id}},
        idempotency_key="dry",
        lead_id=w.lead.id,
        clock=clock,
    )
    out = run_job(session, clock, job, llm_with())
    assert out["mode"] == "dry_run" and out["output"]["label"] == "referral"
    assert reply_messages(session, w.lead.id) == []


def test_referral_routes_the_colleague_to_the_contact_finder_unverified(session, clock) -> None:
    w = make_world(session, clock, channel="email")
    text = "Forwarding to Hana who runs our call centre. Hana, see below."
    msg, _ = receive(w, text, headers={"Cc": "hana@acmemotors.ae"})
    llm = llm_with()
    qualify(session, clock, llm)
    (job,) = cm_jobs(session, msg.id)
    out = run_job(session, clock, job, llm)
    assert out["output"]["actions"]["route_to"] == ["contact_finder"]
    hana = session.scalars(select(Person).where(Person.full_name == "Hana")).one()
    lead = session.scalars(select(Lead).where(Lead.person_id == hana.id)).one()
    assert lead.state == "new" and lead.referred_by_lead_id == w.lead.id
    cp = session.scalars(select(ContactPoint).where(ContactPoint.person_id == hana.id)).one()
    assert cp.verification == "unverified" and cp.value_normalized == "hana@acmemotors.ae"
    assert cp.source.startswith("referral:inbound:")
    assert [j.payload["input"] for j in _jobs(session, "agent.contact_finder")] == [
        {"campaign_company_id": w.cc.id}
    ]
    # thanks to the replier only; nothing to Hana until the Contact Finder verifies her (CM-019)
    assert session.scalars(select(Message).where(Message.lead_id == lead.id)).all() == []
    (thanks,) = reply_messages(session, w.lead.id)
    assert thanks.body.startswith("Hi Feras,") and "Hana" in thanks.body
    # the decision is logged with rule ids, and the reply's handover was checked (CM-001)
    log = session.scalars(select(DecisionLog).where(DecisionLog.agent == "replyguard")).one()
    assert "CM-019" in log.reasoning
    check = session.scalars(
        select(HandoverCheck).where(HandoverCheck.to_agent == "replyguard")
    ).one()
    assert check.passed is True and check.subject_id == msg.id


def test_not_interested_is_lost_only_after_the_thanks_left(session, clock) -> None:
    w = make_world(session, clock, channel="email")
    msg, _ = receive(w, "Not interested, thanks")
    llm = llm_with()
    qualify(session, clock, llm)
    run_job(session, clock, cm_jobs(session, msg.id)[0], llm)
    (thanks,) = reply_messages(session, w.lead.id)
    assert "timing or just not a fit?" in thanks.body
    assert session.get(Lead, w.lead.id).state == "replied"  # Gate 2 would block a Lost lead's thanks
    (fin,) = _jobs(session, "conversation.finalize_state")
    jctx = JobContext(
        session=session, clock=clock, settings=Settings(_env_file=None, paralax_env="test"), worker_id="w"
    )
    assert finalize_state(jctx, fin)["waiting_for_message"] == "approved"
    thanks.status = "sent"
    session.flush()
    assert finalize_state(jctx, fin)["moved"] is True
    assert session.get(Lead, w.lead.id).state == "lost"


def test_yes_send_it_queues_jab_2_with_the_report_and_plans_the_nudges(session, clock) -> None:
    w = make_world(session, clock)
    session.add(
        Report(
            campaign_company_id=w.cc.id,
            version=1,
            data_as_of=clock.now(),
            headline="Weekend enquiries waited",
            blob_key="https://reports.paralax.test/acme-motors",
        )
    )
    session.flush()
    msg, _ = receive(w, "Yes send it")
    llm = llm_with()
    qualify(session, clock, llm)
    run_job(session, clock, cm_jobs(session, msg.id)[0], llm)
    (jab2,) = reply_messages(session, w.lead.id)
    assert "https://reports.paralax.test/acme-motors" in jab2.body
    assert jab2.gate_results["replyguard"]["kind"] == "jab_2"
    send = [j for j in _jobs(session, "message.send") if j.payload.get("message_id") == jab2.id]
    assert len(send) == 1
    assert 60 <= (send[0].run_after - clock.now()).total_seconds() <= 240  # human pace on WhatsApp (CM-034)
    plan = [
        j for j in cm_jobs(session) if (j.payload.get("input") or {}).get("event") == "no_reply_after_jab_2"
    ]
    assert len(plan) == 1


def test_not_now_sunday_goes_warm_with_a_monday_follow_up(session, clock) -> None:
    w = make_world(session, clock)
    msg, _ = receive(w, "Busy now, msg me Sunday")
    llm = llm_with()
    qualify(session, clock, llm)
    run_job(session, clock, cm_jobs(session, msg.id)[0], llm)
    lead = session.get(Lead, w.lead.id)
    assert lead.state == "warm"
    due = [j for j in cm_jobs(session) if (j.payload.get("input") or {}).get("event") == "not_now_due"]
    assert len(due) == 1 and due[0].run_after.date().isoformat() == "2026-11-16"
    (reply,) = reply_messages(session, w.lead.id)
    assert "Monday" in reply.body


def test_classifier_only_away_message_releases_the_company_lock(session, clock) -> None:
    w = make_world(session, clock)
    text = "Hello! Al Noor Motors here. Please leave your name and car model."
    msg, res = receive(w, text, seconds_after=4)
    assert res["replied"] is True  # the boilerplate pattern missed it: locked at intake
    assert session.get(CampaignCompany, w.cc.id).company_lock_at is not None
    run = llm_with({text: {"label": "auto_reply", "confidence": 0.9}})
    qualify(session, clock, run)
    out = run_job(session, clock, cm_jobs(session, msg.id)[0], run)
    assert out["output"]["label"] == "auto_reply"
    assert session.get(CampaignCompany, w.cc.id).company_lock_at is None
    assert (
        session.scalars(select(Event).where(Event.type == "company.lock_released")).one().payload["reason"]
        == "auto_reply"
    )


def test_nudge_moves_off_whatsapp_at_the_unanswered_cap(session, clock) -> None:
    w = make_world(session, clock)
    w.lead.state = "replied"
    session.add(
        ContactPoint(
            person_id=w.person.id,
            company_id=w.company.id,
            channel="email",
            value_normalized="feras@acmemotors.ae",
            verification="verified",
        )
    )
    inbound = Message(
        lead_id=w.lead.id,
        channel="whatsapp",
        direction="in",
        sending_account_id=w.account.id,
        body="Yes send it",
        status="delivered",
        received_at=clock.now() - timedelta(days=6),
    )
    session.add(inbound)
    for d in (5, 3):
        session.add(
            Message(
                lead_id=w.lead.id,
                channel="whatsapp",
                direction="out",
                sending_account_id=w.account.id,
                body="earlier",
                status="sent",
                sent_at=clock.now() - timedelta(days=d),
            )
        )
    session.flush()
    llm = llm_with()
    qualify(session, clock, llm)
    job = enqueue(
        session,
        kind="agent.replyguard",
        payload={
            "input": {
                "lead_id": w.lead.id,
                "event": "nudge_due",
                "channel": "whatsapp",
                "anchor_at": (clock.now() - timedelta(days=5, hours=1)).isoformat(),
            }
        },
        idempotency_key="nudge-3",
        lead_id=w.lead.id,
        campaign_id=w.campaign.id,
        clock=clock,
    )
    out = run_job(session, clock, job, llm)
    assert out["output"]["decision"] == "reply" and out["output"]["reply"]["channel"] == "email"
    (nudge,) = [
        m
        for m in reply_messages(session, w.lead.id)
        if m.gate_results["replyguard"]["kind"] == "nudge"
    ]
    assert nudge.channel == "email" and nudge.sending_account_id is None  # the pool assigns an email account
