"""From one reply to one decision: deterministic signals + the classifier → label, actions, reply kind, state.

``decide(record, classification, defaults)`` is pure: it takes the case-shaped record (``agent.load_input``)
and the classifier's reading and returns the decision the agent logs and the after-hook applies. The locked
rules are written here as code, not left to the model:

- opt-out = detector OR classifier; the classifier never clears a detector hit (CM-004, CM-006);
- safety labels win (CM-003); complaints add account signals and a human (CM-010);
- auto-replies need headers (email) or two signals (WhatsApp) and are never answered (CM-007, CM-009);
- the escalation list is applied from the classifier, the keyword hints and the context (CM-028), and the
  no-message reasons always silence the reply (CM-029);
- never negotiate, pay, book or visit: meetings get the configured booking link or a human (CM-018, CM-027);
- the stop rule (CM-040), banned-account threads (CM-045) and the language switch (CM-032).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from paralax.agents.replyguard import signals as sig
from paralax.agents.replyguard import timing as tm
from paralax.agents.replyguard.schemas import LABELS, Classification

SAFETY = ("complaint", "opt_out", "bot_question")
DEFAULT_PRECEDENCE = (
    "complaint",
    "opt_out",
    "bot_question",
    "meeting_request",
    "positive",
    "question",
    "objection",
    "referral",
    "not_now",
    "not_interested",
    "wrong_person",
    "auto_reply",
    "unclear",
)
# reasons after which the agent itself sends nothing (CM-029 locked list + the "would have to guess" ones)
SILENT_REASONS = frozenset(
    {
        "complaint",
        "legal_or_regulator",
        "possible_false_opt_out",
        "sarcasm_suspected",
        "banned_account_thread",
        "personal_data_request",
        "finding_disputed",
        "outside_evidence",
        "low_confidence",
        "unsupported_language",
        "unsupported_media",
        "stop_rule",
    }
)
SEQUENCE_KINDS = ("message.send", "sequence.next")


@dataclass
class Decision:
    label: str | None
    also: list[str] = field(default_factory=list)
    confidence: float = 0.0
    spans: list[str] = field(default_factory=list)
    language: str = "en"
    reply_language: str | None = "en"
    detector_opt_out: bool = False
    opt_out: bool = False
    suppress: str = "none"  # none | person | company
    erase: bool = False
    account_signals: list[str] = field(default_factory=list)
    company_lock: str = "kept"  # kept | released_auto_reply
    route_to: list[str] = field(default_factory=list)
    new_person: dict[str, Any] | None = None
    other_person: dict[str, Any] | None = None
    person_flag: str | None = None
    handover_reasons: list[str] = field(default_factory=list)
    handover_attach: dict[str, Any] = field(default_factory=dict)
    reply_kind: str = "none"
    reply_allowed: Any = False  # True | False | "confirmation_only" | "holding_line"
    state_after: str = "unchanged"
    lost_reason: str | None = None
    counts_as_reply: bool = True
    followup: dict[str, Any] | None = None
    auto_reply_reasons: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    timing_date: date | None = None
    timing_said_weekday: int | None = None
    timing_stated: bool = False

    def rule(self, *ids: str) -> None:
        for i in ids:
            if i not in self.rules:
                self.rules.append(i)

    def add_reason(self, reason: str) -> None:
        if reason and reason not in self.handover_reasons:
            self.handover_reasons.append(reason)


def _defaults_list(defaults: Any, key: str, fallback: list[str]) -> list[str]:
    v = defaults.get(key)
    return [str(x) for x in v] if isinstance(v, list) and v else list(fallback)


def precedence(defaults: Any) -> list[str]:
    order = _defaults_list(defaults, "precedence", list(DEFAULT_PRECEDENCE))
    # the safety labels always come first, whatever a policy says (CM-003 locked)
    return [*SAFETY, *[x for x in order if x not in SAFETY]]


def fallback_classification(text: str, *, reason: str) -> Classification:
    """No classifier answer (provider down, or nothing to read): deterministic safety intents only, confidence
    0, so the reply goes to a human (CM-031)."""
    label = (
        "opt_out"
        if sig.detector_opt_out(text)
        else ("bot_question" if sig.is_bot_question(text) else "unclear")
    )
    return Classification(label=label, confidence=0.0, reasoning=reason, spans=[])


# --------------------------------------------------------------------------------------------- the decision


def decide(record: Mapping[str, Any], c: Classification, defaults: Any) -> Decision:
    reply = record.get("reply") or {}
    text = str(reply.get("text") or "")
    channel = str(record.get("channel") or "email")
    campaign = record.get("campaign") or {}
    options = campaign.get("options") or {}
    booking_link = campaign.get("booking_link") or defaults.get("meetings.booking_link")
    sender = record.get("sender") or {}
    allowed_reasons = set(_defaults_list(defaults, "handover.reasons", []))
    min_conf = float(defaults.get("classification.min_confidence", 0.8) or 0.8)

    d = Decision(label=c.label if c.label in LABELS else "unclear")
    d.rule("CM-001", "CM-002")
    d.confidence = float(c.confidence)
    d.spans = [s for s in c.spans if s]
    d.also = [a for a in dict.fromkeys(c.also) if a in LABELS and a != d.label]

    # ---- the opt-out floor (CM-004): the intake verdict when the pipeline recorded one, else the detector
    # now
    intake = record.get("detector_opt_out")
    d.detector_opt_out = bool(intake) if isinstance(intake, bool) else sig.detector_opt_out(text)

    # ---- unreadable media (CM-028 unsupported_media): nothing to classify
    media = reply.get("media")
    if media and not text.strip():
        d.label, d.also, d.confidence = "unclear", [], 0.0
        d.add_reason("unsupported_media")
        d.rule("CM-028")

    # ---- auto-replies (CM-007, CM-009)
    headers = reply.get("headers") or {}
    auto, why = False, []
    if channel == "email":
        auto, why = sig.email_auto_reply(headers, text)
        if not auto and d.label == "auto_reply" and sig.is_boilerplate(text):
            auto, why = True, ["out-of-office text, no headers (classifier + text)"]
    elif channel in ("whatsapp", "linkedin"):
        secs = reply.get("seconds_after_our_last")
        auto, why = sig.whatsapp_auto_reply(
            text,
            secs,
            max_seconds=float(defaults.get("auto_reply.whatsapp_max_seconds_after_our_message", 10) or 10),
            classifier_says_auto=d.label == "auto_reply" or "auto_reply" in d.also,
        )
    if record.get("auto_reply_at_intake"):
        auto, why = True, why or ["marked automatic at intake (headers)"]
    if auto:
        if d.label != "auto_reply":
            d.also = [x for x in [d.label, *d.also] if x not in ("auto_reply", "unclear")]
        d.label = "auto_reply"
        d.also = [a for a in d.also if a in ("referral",) or a in SAFETY]
        d.auto_reply_reasons = why
        d.counts_as_reply = False
        d.company_lock = "released_auto_reply"
        d.rule("CM-007", "CM-008" if channel == "email" else "CM-009")
    elif d.label == "auto_reply":
        # the classifier alone cannot make a human message automatic (CM-009: two signals; DubiCars lesson)
        nxt = [a for a in d.also if a != "auto_reply"]
        d.label = nxt[0] if nxt else "unclear"
        d.also = nxt[1:]
        d.confidence = min(d.confidence, 0.5) if not nxt else d.confidence
        d.notes.append("classifier said auto_reply without the timing/header signal: treated as human")
        d.rule("CM-009")

    # ---- safety intents the classifier may have missed (they can only be ADDED)
    if not auto and sig.is_bot_question(text) and "bot_question" not in (d.label, *d.also):
        d.also.append("bot_question")
    classifier_opt = d.label in ("opt_out", "complaint") or any(a in ("opt_out", "complaint") for a in d.also)
    if d.detector_opt_out and not classifier_opt:
        if d.confidence >= min_conf and d.label not in ("unclear",):
            # CM-006: stays suppressed; a human reads it; nothing is reversed by the agent
            d.add_reason("possible_false_opt_out")
            d.rule("CM-006")
        else:
            d.also = [x for x in [d.label, *d.also] if x not in ("opt_out", "unclear")]
            d.label = "opt_out"
    d.opt_out = d.detector_opt_out or classifier_opt or d.label in ("opt_out", "complaint")

    # ---- primary label by precedence (safety first, CM-003); an auto-reply stays an auto-reply
    if not auto:
        present = [d.label, *d.also]
        order = precedence(defaults)
        if "possible_false_opt_out" in d.handover_reasons:
            pass  # the classifier's own label stands (CM-006); the opt-out floor acts below
        else:
            best = min(present, key=lambda x: order.index(x) if x in order else len(order))
            if best != d.label and best in SAFETY:
                d.also = [x for x in present if x != best]
                d.label = best
    d.also = [a for a in dict.fromkeys(d.also) if a != d.label]
    if d.label in SAFETY or any(a in SAFETY for a in d.also):
        d.rule("CM-003")

    # ---- language (CM-032)
    thread = list(record.get("thread") or [])
    d.language = sig.language_of(text, classifier_language=c.language if c.language != "mixed" else None)
    d.reply_language = sig.reply_language(d.language, sig.thread_language(thread))

    # ---- suppression, erasure, account signals (CM-010, CM-011, CM-012, CM-043)
    if d.opt_out:
        d.rule("CM-004", "CM-011")
        company = c.speaks_for_company or sig.speaks_for_company(text)
        d.suppress = "company" if company else "person"
        if company:
            d.rule("CM-012")
        d.erase = bool(c.deletion_request or sig.deletion_request(text))
        if d.erase:
            d.rule("CM-043")
    if d.label == "complaint" or "complaint" in d.also:
        d.rule("CM-010")
        d.account_signals.append(str(defaults.get("complaint.account_signal_kind") or "complaint"))
        if defaults.get("complaint.add_report_or_block_if_stated", True):
            stated = [s for s in [*sig.stated_signals(text), *c.stated_signals] if s in ("report", "block")]
            d.account_signals += [s for s in dict.fromkeys(stated) if s not in d.account_signals]
        d.add_reason("complaint")
        d.rule("CM-044")

    # ---- handover reasons (CM-028): classifier + hints + context; unknown reasons are dropped (logged)
    hints = sig.hint_reasons(text) if not auto else []
    if d.opt_out and d.label != "complaint" and "possible_false_opt_out" not in d.handover_reasons:
        hints = [h for h in hints if h == "legal_or_regulator"]  # a plain opt-out needs no human
    for r in [*c.handover_reasons, *hints]:
        if r in allowed_reasons:
            d.add_reason(r)
        elif r:
            d.notes.append(f"classifier reason {r!r} is not on the handover list (ignored)")
    if "legal_or_regulator" in d.handover_reasons and d.label != "complaint" and d.opt_out:
        d.add_reason("complaint")
    if c.sarcasm_suspected:
        d.add_reason("sarcasm_suspected")
        d.rule("CM-031")
    if "bot_question" in (d.label, *d.also):
        d.add_reason("bot_question")
        d.rule("CM-016", "CM-017")
    if not auto and not d.opt_out and d.label not in SAFETY and "unsupported_media" not in d.handover_reasons:
        if d.confidence < min_conf:
            d.add_reason("low_confidence")
            d.rule("CM-031")
        if d.label == "unclear" and "unsupported_media" not in d.handover_reasons:
            d.add_reason("low_confidence")
    if "personal_data_request" in d.handover_reasons:
        cp = record.get("contact_point") or {}
        d.handover_attach = {
            "contact_point.source": cp.get("source"),
            "contact_point.collected_at": cp.get("collected_at"),
        }
        d.rule("CM-043")
    meeting = d.label == "meeting_request" or "meeting_request" in d.also
    if meeting or "visit_request" in d.handover_reasons:
        d.rule("CM-027", "CM-018")
        if not booking_link:
            d.add_reason("meeting_request_no_link")
    if not d.opt_out and d.reply_language is None:
        d.add_reason("unsupported_language")
    if d.reply_language == "ar" and not options.get("arabic_auto_send", True):
        d.add_reason("unsupported_language")
        d.notes.append("Arabic auto-send is off (owner switch): the Arabic draft goes to a human")
    status = (record.get("account_status") or {}).get(str(sender.get("account") or ""))
    if status and str(status).lower() not in ("active", "warming"):  # banned, suspended, paused, resting ...
        d.add_reason("banned_account_thread")
        d.rule("CM-045")
    if d.handover_reasons:
        d.rule("CM-028")

    # ---- referrals, wrong person, corrections about someone else (CM-019, CM-020, CM-048)
    if (d.label == "referral" or "referral" in d.also) and not d.opt_out:
        d.route_to.append("contact_finder")
        ref = c.referral
        cc_emails = sig.emails_in(sig.header(headers, "Cc"), sig.header(headers, "To") if auto else "", text)
        if ref is not None and (ref.name or ref.email):
            d.new_person = {"name": ref.name or ref.name_original, "name_original": ref.name_original}
            if ref.role_hint:
                d.new_person["role_hint"] = ref.role_hint
            email = ref.email or next((e for e in cc_emails), "")
            if email:
                d.new_person["candidate_email"] = email
        d.rule("CM-019")
    if d.label == "wrong_person":
        d.rule("CM-020")
        if c.left_company:
            d.person_flag = "left_company"
            d.route_to += ["buyer_mapper", "contact_finder"]
    if c.other_person is not None and c.other_person.name and not d.opt_out:
        d.other_person = {
            "name": c.other_person.name,
            "issue": c.other_person.issue,
            "contact_point": "stale",
            "touches_cancelled": True,
            "suppressed": False,
        }
        if "contact_finder" not in d.route_to:
            d.route_to.append("contact_finder")
        d.rule("CM-048")
    d.route_to = list(dict.fromkeys(d.route_to))

    # ---- the stop rule (CM-040)
    max_auto = int(defaults.get("stop_rule.max_automated_replies_without_progress", 3) or 3)
    if int(record.get("automated_replies_without_progress") or 0) >= max_auto and not d.opt_out and not auto:
        d.add_reason("stop_rule")
        d.rule("CM-040")

    # ---- state after (CM-011, CM-021, CM-022, CM-039)
    lead_state = str((record.get("lead") or {}).get("state") or "contacted")
    if d.opt_out:
        d.state_after = "do_not_contact"
    elif auto:
        d.state_after = "unchanged"
    elif d.label == "not_interested" and "unsupported_language" not in d.handover_reasons:
        d.state_after = "lost"
        d.lost_reason = text.strip()
        d.rule("CM-021")
    elif d.label == "not_now":
        d.state_after = "warm"
        d.rule("CM-022")
    elif d.person_flag == "left_company":
        d.state_after = "lost"
        d.lost_reason = text.strip()
    else:
        d.state_after = "replied" if lead_state not in ("replied",) else "replied"

    # ---- follow-ups (CM-008, CM-022)
    pack = tm.pack_for(record.get("country"))
    now = tm.as_dt(record.get("now")) or tm.as_dt(reply.get("at"))
    if now is not None:
        today = now.astimezone(tm.tz_of(pack)).date()
        if auto:
            on = tm.resume_after_ooo(
                text,
                now,
                pack,
                business_days_after=int(defaults.get("auto_reply.resume_business_days_after_return", 1) or 1),
                default_days=int(defaults.get("auto_reply.default_resume_days", 7) or 7),
            )
            d.followup = {"kind": "resume_after_ooo", "on": on.isoformat()}
        elif d.label == "not_now" and not d.opt_out:
            asked, anchor, wd = tm.requested_date(text, today, c.timing)
            d.timing_stated = asked is not None
            if asked is None and anchor is None:
                asked = today + timedelta(days=int(defaults.get("followup.not_now_default_days", 30) or 30))
            if asked is not None:
                on = tm.next_working_day(asked, pack, inclusive=True)
                d.timing_date, d.timing_said_weekday = on, wd
                d.followup = {
                    "kind": "not_now",
                    "on": on.isoformat(),
                    "window_start": tm.window_start(channel, pack),
                }
            else:
                d.followup = {"kind": "not_now", "at": None, "anchor": anchor}
                d.notes.append(f"'{anchor}' needs the holiday calendar (CHANGELOG open point 7): asked when")

    # ---- the reply (CM-013, CM-016, CM-021 ... CM-029)
    d.reply_kind, d.reply_allowed = _reply_kind(d, defaults, booking_link=booking_link, c=c)
    if d.reply_kind == "none":
        d.reply_allowed = False
    return d


def _reply_kind(d: Decision, defaults: Any, *, booking_link: Any, c: Classification) -> tuple[str, Any]:
    reasons = set(d.handover_reasons)
    holding_ok = set(_defaults_list(defaults, "handover.holding_line_allowed_for", []))
    if d.label == "auto_reply":
        return "none", False
    if d.label == "complaint" or "possible_false_opt_out" in reasons:
        return "none", False
    if d.opt_out:
        d.rule("CM-013")
        return (
            "confirmation_only",
            "confirmation_only",
        )  # sent only if the gates accept it (they do not today)
    if "banned_account_thread" in reasons or "stop_rule" in reasons:
        return "none", False
    if "bot_question" in (d.label, *d.also):
        if reasons & {"legal_or_regulator", "sarcasm_suspected", "personal_data_request"}:
            return "none", False
        return "bot_disclosure", True  # truthful, then a human (CM-016)
    if reasons & SILENT_REASONS:
        return "none", False
    if reasons - {"visit_request"}:
        if reasons - {"visit_request"} <= holding_ok:
            d.rule("CM-029")
            return "holding_line", "holding_line"
        return "none", False
    if "visit_request" in reasons:  # a visit with a booking link configured: the link, a human for the visit
        return "booking_link", True
    label = d.label
    if label == "meeting_request":
        return ("booking_link", True) if booking_link else ("holding_line", "holding_line")
    if label == "positive":
        d.rule("CM-023")
        return "jab_2", True
    if label == "question":
        d.rule("CM-024")
        return "two_line_answer_then_jab_2", True
    if label == "objection":
        d.rule("CM-025", "CM-026")
        return "label_then_calibrated_question", True
    if label == "referral":
        return "thanks", True
    if label == "wrong_person":
        return ("thanks", True) if c.left_company else ("ask_who", True)
    if label == "not_now":
        return ("confirm_date", True) if d.timing_stated else ("when_suits_you", True)
    if label == "not_interested":
        return "thanks_optional_why", True
    return "none", False


# --------------------------------------------------------------------------------------------- timing of a
# send


def send_times(
    record: Mapping[str, Any], channel: str, defaults: Any, *, seed: str
) -> tuple[datetime | None, datetime | None, int]:
    """(send_not_before, send_at, delay seconds): the next allowed moment from the reply's arrival (CM-035),
    plus a random human-pace delay on chat channels (CM-034; >= the 20 s floor)."""
    pack = tm.pack_for(record.get("country"))
    arrived = tm.as_dt((record.get("reply") or {}).get("at")) or tm.as_dt(record.get("now"))
    if arrived is None:
        return None, None, 0
    not_before = tm.next_allowed(arrived, pack, is_reply=True)  # G8 + L3: replies Mon-Fri 09:00-21:00
    delay = 0
    if channel in ("whatsapp", "linkedin"):
        lo, hi = defaults.get("response.chat_delay_seconds") or [60, 240]
        floor = int(defaults.get("response.min_gap_between_messages_seconds", 20) or 20)
        rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))  # noqa: S311 - pacing
        delay = max(floor, rng.randint(int(lo), int(hi)))
    send_at = not_before + timedelta(seconds=delay)
    return not_before, send_at, delay


# --------------------------------------------------------------------------------------------- follow-up plan


def followup_plan(record: Mapping[str, Any], defaults: Any) -> dict[str, Any]:
    """CM-038 + CM-036: nudges on days 2, 5, 10 after our last message (nearest working day, never drifting
    before the previous one); WhatsApp never more than ``whatsapp.max_unanswered`` unanswered nudges, then the
    next verified channel, else none; then warm with a check-in ``followup.warm_checkin_days`` later."""
    pack = tm.pack_for(record.get("country"))
    thread = list(record.get("thread") or [])
    outs = [t for t in thread if str(t.get("dir")) == "out" and t.get("at")]
    last = tm.as_dt(outs[-1]["at"]) if outs else tm.as_dt(record.get("now"))
    assert last is not None
    base = last.astimezone(tm.tz_of(pack)).date()
    channel = str(record.get("channel") or "email")
    verified = [str(x) for x in record.get("verified_channels") or [channel]]
    cap = int(defaults.get("whatsapp.max_unanswered", 2) or 2)
    plan: list[dict[str, Any]] = []
    prev = base
    wa_used = 0
    for n in defaults.get("followup.nudge_days") or [2, 5, 10]:
        day = tm.nearest_working_day(base + timedelta(days=int(n)), pack, not_before=prev)
        ch = channel
        if ch == "whatsapp" and wa_used >= cap:
            ch = next((v for v in verified if v != "whatsapp"), "")
        if not ch:
            continue
        if ch == "whatsapp":
            wa_used += 1
        plan.append({"on": day.isoformat(), "channel": ch, "kind": "nudge"})
        prev = day
    last_day = date.fromisoformat(plan[-1]["on"]) if plan else base
    checkin = last_day + timedelta(days=int(defaults.get("followup.warm_checkin_days", 30) or 30))
    return {
        "followup_plan": plan,
        "then": {"state": "warm", "checkin_on": checkin.isoformat()},
        "whatsapp_unanswered_max": wa_used,
    }
