"""A FakeLLM for the ReplyGuard's 53 cases: the classifier's reading of each reply (what a good
model returns; the cases define the expected label, the rest is crafted to the playbook) and three free-form
drafts.

Keyed by the reply text, so the same canned reading serves the eval and the integration tests."""

from __future__ import annotations

import json
from typing import Any

from paralax.llm import FakeLLM


def _c(label: str, conf: float, **kw: Any) -> dict[str, Any]:
    return {"label": label, "confidence": conf, "spans": kw.pop("spans", []), "rule_ids": ["CM-002"], **kw}


AWAY = (
    "Thank you for contacting Al Noor Motors! Our team will get back to you shortly. Showroom hours: 9am-9pm."
)
CLASSIFY: dict[str, dict[str, Any]] = {
    "STOP": _c("opt_out", 0.99, spans=["STOP"]),
    "stop sending me these": _c("opt_out", 0.98),
    "Please stop by our showroom on Sheikh Zayed Road, we can talk there": _c(
        "meeting_request",
        0.9,
        handover_reasons=["visit_request"],
        reasoning="'stop by' is an invitation (CM-005)",
    ),
    "Can you remove the price column from the report before you send it?": _c(
        "positive", 0.86, also=["question"], handover_reasons=["report_change_request"]
    ),
    "Please remove my number from your list": _c("opt_out", 0.95),
    "احذف رقمي لو سمحت": _c("opt_out", 0.95, deletion_request=True, language="ar"),
    "شيلوا رقمي من عندكم": _c("opt_out", 0.93, language="ar"),
    "لا ترسل لي رسائل مرة ثانية": _c("opt_out", 0.97, language="ar"),
    "This is spam. Reported.": _c("complaint", 0.95, stated_signals=["report"]),
    "Great, another 'personal' message from a robot. Just what I needed.": _c(
        "complaint", 0.82, sarcasm_suspected=True
    ),
    "Is this a bot?": _c("bot_question", 0.97),
    "هل هذا بوت؟": _c("bot_question", 0.96, language="ar"),
    "Are you a real person or automated?": _c("bot_question", 0.96),
    "الشغل عندنا ما توقف طول رمضان، ارسل التقرير": _c(
        "positive",
        0.9,
        language="ar",
        reasoning="'never stopped' describes their work; they ask for the report",
    ),
    "Not interested, thanks": _c("not_interested", 0.95),
    "Not interested. Please stop.": _c("opt_out", 0.97, also=["not_interested"]),
    "مب مهتم، مشكور": _c("not_interested", 0.93, language="ar"),
    "بعدين، بعد العيد": _c(
        "not_now",
        0.9,
        language="ar",
        timing={"kind": "anchor", "value": "after_eid_al_fitr", "text": "بعد العيد"},
    ),
    "Thanks but we're not looking at this until Q1": _c(
        "not_now", 0.93, timing={"kind": "quarter", "value": "Q1"}
    ),
    "Busy now, msg me Sunday": _c("not_now", 0.92, timing={"kind": "weekday", "value": "sunday"}),
    "Talk to my colleague Priya, she handles marketing": _c(
        "referral", 0.94, referral={"name": "Priya", "role_hint": "marketing"}
    ),
    "Forwarding to Hana who runs our call centre. Hana, see below.": _c(
        "referral", 0.93, referral={"name": "Hana", "role_hint": "call centre"}
    ),
    "كلم أخوي سالم هو المسؤول عن المبيعات": _c(
        "referral",
        0.9,
        language="ar",
        referral={"name": "Salem", "name_original": "سالم", "role_hint": "sales"},
    ),
    "I left Al Noor Motors in August, I'm not the right person anymore.": _c(
        "wrong_person", 0.93, left_company=True
    ),
    "Yes send it": _c("positive", 0.97),
    "sounds interesting, what does it involve?": _c("question", 0.9),
    "We already use a CRM for this, why would we need you?": _c("objection", 0.9),
    "Hi, how much would this cost us per month?": _c("question", 0.93, handover_reasons=["pricing"]),
    "كم السعر؟": _c("question", 0.94, language="ar", handover_reasons=["pricing"]),
    "Let's talk next week, Tuesday works": _c("meeting_request", 0.93),
    "Happy to have a quick call about this.": _c("meeting_request", 0.92),
    "Can we jump on a WhatsApp call now?": _c("meeting_request", 0.9),
    "I'm out of the office until 24 Nov with limited access to email.": _c(
        "auto_reply", 0.97, timing={"kind": "date", "value": "2026-11-24"}
    ),
    "I am on annual leave until 1 December. For urgent matters please contact Sara Haddad at "
    "sara.haddad@pearlsmile.example.": _c(
        "auto_reply",
        0.96,
        also=["referral"],
        referral={"name": "Sara Haddad", "email": "sara.haddad@pearlsmile.example"},
    ),
    AWAY: _c("auto_reply", 0.95),
    "ok": _c("positive", 0.85, reasoning="'ok' 40 minutes after 'Shall I send you the one-pager?'"),
    "Who gave you my number?": _c("question", 0.9, handover_reasons=["personal_data_request"]),
    "I will report this number to TDRA": _c("complaint", 0.95, handover_reasons=["legal_or_regulator"]),
    "Lol nice try": _c("unclear", 0.55, sarcasm_suspected=True),
    "yes please send. also please remove my colleague ahmed from your emails, he left the company": _c(
        "positive", 0.93, other_person={"name": "Ahmed", "issue": "left_company"}
    ),
    "Stop. Who is this?": _c("opt_out", 0.9, also=["question"]),
    "I'll stop you right there - we handle every enquiry within 5 minutes.": _c(
        "objection", 0.88, handover_reasons=["finding_disputed"]
    ),
    "ممكن تشيل اسم الشركة من التقرير؟": _c(
        "question", 0.88, language="ar", handover_reasons=["report_change_request"]
    ),
    "Please don't contact us again.": _c("opt_out", 0.97, speaks_for_company=True),
    "Yes, send it": _c("positive", 0.97),
    "Interesting. Send me the summary.": _c("positive", 0.93),
    "Merci, pas intéressé.": _c("not_interested", 0.9, language="other", language_name="French"),
    "Hi, send the report please. شكراً": _c("positive", 0.93, language="mixed"),
    "mashkoor bas mob mohtam": _c("not_interested", 0.88, language="arabizi"),
    "Pls stop, ما ابي رسايل": _c("opt_out", 0.95, language="mixed"),
}

JAB2 = {
    "body": "Here it is: {link}\nThe weekend result is on the first page. Anything in it you'd like me to "
    "explain?",
    "claims": [],
    "rule_ids": ["CM-023"],
}
DRAFTS: dict[str, dict[str, Any]] = {
    "two_line_answer_then_jab_2": {
        "body": "It's a one-page summary of how Skyline Keys handles portal enquiries on weekends, from what "
        "we "
        "measured. Want me to send it over?",
        "claims": [
            {"text": "how Skyline Keys handles portal enquiries on weekends", "source": "thread", "ref": "0"}
        ],
        "rule_ids": ["CM-024"],
    },
    "label_then_calibrated_question": {
        "body": "Sounds like the CRM already holds every enquiry. How quickly does the first reply go out "
        "when one "
        "lands on a weekend?",
        "claims": [],
        "rule_ids": ["CM-025", "CM-026"],
    },
}


def classify(*, system: str, user: str, schema: Any) -> dict[str, Any]:
    text = json.loads(user)["reply"]["text"]
    if text not in CLASSIFY:
        raise KeyError(f"no canned classification for {text!r}")
    return CLASSIFY[text]


def _draft(kind: str):  # noqa: ANN202
    def fn(*, system: str, user: str, schema: Any) -> dict[str, Any]:
        if kind == "jab_2":
            data = json.loads(user)
            link = ((data.get("record") or {}).get("report") or {}).get("url") or ""
            return {**JAB2, "body": JAB2["body"].format(link=link)}
        if kind == "nudge":
            return {
                "body": "One more thing from the report: weekend enquiries waited longest. Worth a look?",
                "claims": [],
            }
        return DRAFTS[kind]

    return fn


def eval_llm() -> FakeLLM:
    return FakeLLM(
        {
            "replyguard.classify": classify,
            **{
                f"replyguard.draft.{k}": _draft(k)
                for k in ("jab_2", "two_line_answer_then_jab_2", "label_then_calibrated_question", "nudge")
            },
        },
        label="cm-eval",
    )


class FixedJudge:
    def __init__(self) -> None:
        self.calls = 0

    def score(self, *, agent, case, output, criteria, kb):  # noqa: ANN001, ANN201
        self.calls += 1
        return {c.id: (5, "fixed") for c in criteria}
