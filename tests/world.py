"""A live world for ReplyGuard tests: the guardrail world (approved brief, UAE company, verified
contact, active account, thread) with jab 1 SENT, plus helpers to receive a reply and run the agent's job."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from paralax.agents.replyguard import agent as cm_agent  # noqa: F401  (registers the agent + hook)
from paralax.agents.knowledge import KnowledgeBase, register_version
from paralax.agents.registry import agent_job_handler
from paralax.core.config import Settings
from paralax.db.models import EvalRun, Job, Message
from paralax.llm import FakeLLM
from paralax.orchestrator.handlers import JobContext
from paralax.orchestrator.inbound import process_inbound
from tests import canned
from tests.guardrails.builders import World, build_world

AGENT = "replyguard"


def make_world(session: Any, clock: Any, channel: str = "whatsapp") -> World:
    w = build_world(session, clock, channel=channel)
    w.message.status = "sent"
    w.message.sent_at = clock.now() - timedelta(hours=1)
    w.lead.state = "contacted"
    session.flush()
    return w


def receive(
    w: World,
    text: str,
    *,
    seconds_after: float | None = None,
    headers: Mapping[str, str] | None = None,
    auto_submitted: bool = False,
    media: str | None = None,
) -> tuple[Message, dict[str, Any]]:
    """An inbound reply on our thread, processed at intake (``process_inbound``) like the pollers do."""
    s, now = w.session, w.clock.now()
    if seconds_after is not None:
        w.message.sent_at = now - timedelta(seconds=seconds_after)
    msg = Message(
        lead_id=w.lead.id,
        channel=w.channel,
        direction="in",
        sending_account_id=w.account.id,
        contact_point_id=w.cp.id,
        thread_id=w.thread.id,
        subject=str((headers or {}).get("Subject") or ""),
        body=text,
        status="delivered",
        received_at=now,
    )
    if headers or media:
        msg.gate_results = {"inbound": {"headers": dict(headers or {}), "media": media}}
    s.add(msg)
    s.flush()
    res = process_inbound(s, lead=w.lead, message=msg, clock=w.clock, auto_submitted=auto_submitted)
    s.flush()
    return msg, res


def qualify(session: Any, clock: Any, llm: Any) -> None:
    """A passing, full EvalRun for this model config on the active playbook version (Gate 1 'qualified')."""
    pv = register_version(session, KnowledgeBase.load(AGENT), clock)
    session.add(
        EvalRun(
            agent=AGENT,
            playbook_version_id=pv.id,
            model_config_hash=llm.model_config_hash(),
            score=5.0,
            passed=True,
            results={"partial": False, "summary": {"cases": 53}},
            run_at=clock.now(),
        )
    )
    session.flush()


def llm_with(extra: Mapping[str, dict[str, Any]] | None = None) -> FakeLLM:
    """The eval FakeLLM, plus test-only classifications keyed by reply text."""
    base = canned.eval_llm()
    if extra:
        orig = base.responses["replyguard.classify"]

        def classify(*, system: str, user: str, schema: Any) -> Any:
            import json

            text = json.loads(user)["reply"]["text"]
            return extra[text] if text in extra else orig(system=system, user=user, schema=schema)

        base.responses["replyguard.classify"] = classify
    return base


def cm_jobs(session: Any, message_id: str | None = None) -> list[Job]:
    q = select(Job).where(Job.kind == f"agent.{AGENT}")
    if message_id:
        q = q.where(Job.idempotency_key == f"agent.{AGENT}:{message_id}")
    return list(session.scalars(q))


def run_job(session: Any, clock: Any, job: Job, llm: Any, factory: Any = None) -> dict[str, Any]:
    handler = agent_job_handler(AGENT, llm_factory=lambda jctx, j: llm)
    try:
        jctx = JobContext(
            session=session,
            clock=clock,
            settings=Settings(_env_file=None, paralax_env="test"),
            worker_id="w-test",
            factory=factory,
        )
        out = handler(jctx, job)
        session.flush()
        return out
    finally:
        agent_job_handler(AGENT)


def reply_messages(session: Any, lead_id: str) -> list[Message]:
    rows = session.scalars(
        select(Message).where(Message.lead_id == lead_id, Message.direction == "out")
    ).all()
    return [m for m in rows if (m.gate_results or {}).get(AGENT)]
