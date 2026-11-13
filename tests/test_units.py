"""Pure pieces of the ReplyGuard: auto-reply signals, language, dates and hours, the decision rules
that are code (opt-out floor, safety precedence, silent reasons), the follow-up plan and the reply form."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from paralax.agents.replyguard import replies as rp
from paralax.agents.replyguard import signals as sig
from paralax.agents.replyguard import timing as tm
from paralax.agents.replyguard.checks import DEFAULTS
from paralax.agents.replyguard.decide import decide, followup_plan
from paralax.agents.replyguard.schemas import Classification

UAE = tm.pack_for("AE")
SENDER = {"name": "Ali", "company": "Paralax", "account": "wa-ali"}


def _record(text: str, *, channel: str = "whatsapp", **kw):  # noqa: ANN202
    rec = {
        "now": "2026-11-10T10:12:00+04:00",
        "channel": channel,
        "campaign": {"options": {"arabic_auto_send": True}, "booking_link": None},
        "sender": SENDER,
        "lead": {"state": "contacted"},
        "thread": [
            {"dir": "out", "at": "2026-11-10T10:05:00+04:00", "text": "Hi Khalid ...", "kind": "jab_1"}
        ],
        "reply": {"at": "2026-11-10T10:12:00+04:00", "text": text},
    }
    rec.update(kw)
    return rec


# --------------------------------------------------------------------------------------------- signals


def test_email_auto_reply_needs_headers_or_a_supported_subject_hint() -> None:
    assert sig.email_auto_reply({"Auto-Submitted": "auto-replied"}, "anything")[0]
    assert not sig.email_auto_reply({"Auto-Submitted": "no"}, "hello")[0]
    assert sig.email_auto_reply({"Precedence": "bulk"}, "")[0]
    # a subject hint alone is not enough; with out-of-office text it is
    assert not sig.email_auto_reply({"Subject": "Auto: hello"}, "Thanks, interested")[0]
    assert sig.email_auto_reply({"Subject": "Out of Office"}, "I am on annual leave until Monday")[0]


def test_whatsapp_auto_reply_needs_both_signals() -> None:
    away = "Thank you for contacting Al Noor Motors! Our team will get back to you shortly."
    assert sig.whatsapp_auto_reply(away, 3, max_seconds=10)[0]
    assert not sig.whatsapp_auto_reply(away, 600, max_seconds=10)[0]  # slow: a person may have typed it
    assert not sig.whatsapp_auto_reply("ok", 2, max_seconds=10)[0]  # fast but human (DubiCars lesson)


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Yes send it", "en"),
        ("مب مهتم، مشكور", "ar"),
        ("Hi, send the report please. شكراً", "en"),
        ("mashkoor bas mob mohtam", "arabizi"),
    ],
)
def test_language_by_majority_of_words(text: str, lang: str) -> None:
    assert sig.language_of(text) == lang


def test_bot_questions_and_company_scope() -> None:
    assert sig.is_bot_question("Are you a bot?") and sig.is_bot_question("هل هذا بوت؟")
    assert not sig.is_bot_question("Great, another message from a robot.")
    assert sig.speaks_for_company("Please don't contact us again.")
    assert not sig.speaks_for_company("Please don't contact me again.")
    assert sig.stated_signals("This is spam. Reported.") == ["report"]
    assert sig.stated_signals("I will report this number to TDRA") == []  # a threat is not a report


# --------------------------------------------------------------------------------------------- timing


def test_allowed_hours_and_working_minutes() -> None:
    thu_night = datetime(2026, 11, 12, 18, 30, tzinfo=UTC)  # 22:30 Dubai
    assert tm.next_allowed(thu_night, UAE).isoformat() == "2026-11-13T09:00:00+04:00"
    # a reply at 22:30 Thursday answered at 09:00 Friday counts zero working minutes (CM-033)
    assert tm.working_minutes(thu_night, datetime(2026, 11, 13, 5, 0, tzinfo=UTC), UAE) == 0.0
    assert (
        tm.working_minutes(
            datetime(2026, 11, 10, 6, 2, tzinfo=UTC), datetime(2026, 11, 10, 6, 5, tzinfo=UTC), UAE
        )
        == 3.0
    )


def test_dates_from_their_words() -> None:
    today = date(2026, 11, 10)
    assert tm.return_date("I'm out of the office until 24 Nov", today) == date(2026, 11, 24)
    assert tm.requested_date("not until Q1", today)[0] == date(2027, 1, 1)
    assert tm.next_working_day(date(2027, 1, 1), UAE, inclusive=True) == date(2027, 1, 4)  # New Year, weekend
    d, anchor, wd = tm.requested_date("msg me Sunday", today)
    assert d == date(2026, 11, 15) and wd == 6 and anchor is None
    assert tm.next_working_day(d, UAE, inclusive=True) == date(2026, 11, 16)


# --------------------------------------------------------------------------------------------- decide


def test_detector_floor_is_never_cleared_and_goes_to_a_human() -> None:
    d = decide(_record("STOP"), Classification(label="positive", confidence=0.95), DEFAULTS)
    assert d.opt_out and d.suppress == "person" and d.state_after == "do_not_contact"
    assert "possible_false_opt_out" in d.handover_reasons and d.reply_kind == "none"


def test_classifier_adds_an_opt_out_the_detector_missed() -> None:
    rec = _record("I'd rather not get these anymore")
    d = decide(rec, Classification(label="opt_out", confidence=0.9), DEFAULTS)
    assert not d.detector_opt_out and d.opt_out and d.reply_kind == "confirmation_only"


def test_a_low_confidence_reading_of_a_detector_hit_is_an_opt_out() -> None:
    d = decide(_record("STOP"), Classification(label="unclear", confidence=0.4), DEFAULTS)
    assert d.label == "opt_out" and "possible_false_opt_out" not in d.handover_reasons


def test_safety_label_wins_over_the_classifier_primary() -> None:
    c = Classification(label="positive", also=["bot_question"], confidence=0.9)
    d = decide(_record("Is this a bot? Anyway send the report"), c, DEFAULTS)
    assert d.label == "bot_question" and "positive" in d.also and d.reply_kind == "bot_disclosure"


def test_classifier_cannot_make_a_human_reply_automatic() -> None:
    rec = _record(
        "ok", reply={"at": "2026-11-10T10:45:00+04:00", "text": "ok", "seconds_after_our_last": 2400}
    )
    d = decide(rec, Classification(label="auto_reply", also=["positive"], confidence=0.9), DEFAULTS)
    assert d.label == "positive" and d.counts_as_reply


def test_arabic_reply_with_the_switch_off_goes_to_a_human() -> None:
    rec = _record("مب مهتم، مشكور", campaign={"options": {"arabic_auto_send": False}, "booking_link": None})
    d = decide(rec, Classification(label="not_interested", confidence=0.93), DEFAULTS)
    assert "unsupported_language" in d.handover_reasons and d.reply_kind == "none"


def test_meeting_with_a_booking_link_sends_the_link_never_a_time() -> None:
    rec = _record("Let's talk Tuesday", campaign={"options": {}, "booking_link": "https://cal.example/x"})
    d = decide(rec, Classification(label="meeting_request", confidence=0.9), DEFAULTS)
    assert d.reply_kind == "booking_link" and not d.handover_reasons


def test_banned_account_thread_is_not_continued() -> None:
    rec = _record("Yes send it", account_status={"wa-ali": "banned"})
    d = decide(rec, Classification(label="positive", confidence=0.97), DEFAULTS)
    assert d.handover_reasons == ["banned_account_thread"] and d.reply_kind == "none"


def test_stop_rule() -> None:
    rec = _record("what else?", automated_replies_without_progress=3)
    d = decide(rec, Classification(label="question", confidence=0.9), DEFAULTS)
    assert "stop_rule" in d.handover_reasons and d.reply_kind == "none"


def test_followup_plan_respects_the_whatsapp_cap() -> None:
    rec = _record(
        "",
        now="2026-11-09T11:00:00+04:00",
        thread=[{"dir": "out", "at": "2026-11-09T10:10:00+04:00", "text": "jab 2", "kind": "jab_2"}],
        verified_channels=["whatsapp"],
    )
    plan = followup_plan(rec, DEFAULTS)
    assert [p["channel"] for p in plan["followup_plan"]] == [
        "whatsapp",
        "whatsapp",
    ]  # no third, no other channel
    assert plan["whatsapp_unanswered_max"] == 2


# --------------------------------------------------------------------------------------------- reply form


def test_finish_adds_greeting_sender_and_opt_out_and_check_passes() -> None:
    body = rp.finish(rp.template("thanks_optional_why", "en"), SENDER, "en", first_name="Feras")
    assert body.startswith("Hi Feras,\n") and body.endswith("Ali, Paralax\nReply STOP to opt out.")
    chk = rp.check_draft(
        body, kind="thanks_optional_why", channel="whatsapp", language="en", sender=SENDER, defaults=DEFAULTS
    )
    assert chk.ok, chk.reasons
    ar = rp.finish(rp.template("when_suits_you", "ar"), SENDER, "ar")
    assert ar.endswith("للإلغاء، أرسل STOP.")


def test_self_check_blocks_human_claims_prices_and_untraced_numbers() -> None:
    bad = rp.finish(
        "Sorry, I was in a meeting! It's only AED 500 per month. Studies show 78% buy first.", SENDER, "en"
    )
    reasons = rp.check_draft(
        bad, kind="jab_2", channel="whatsapp", language="en", sender=SENDER, defaults=DEFAULTS
    ).reasons
    assert any("human" in r for r in reasons)
    assert any("never-say" in r for r in reasons)
    assert any("not traced" in r for r in reasons)


def test_bot_disclosure_names_the_real_source_of_the_number() -> None:
    """Owner, 10 Nov: 'Is this automated? How did you get our number?' gets a truthful answer and the real,
    stored source of the number. Nothing is invented when no source is stored."""
    from paralax.agents.replyguard.agent import source_in_words

    assert source_in_words("https://www.google.com/maps/place/?q=place_id:abc") == (
        "We found your number on your Google Business profile, where it is publicly listed."
    )
    assert "acmemotors.ae" in source_in_words("https://acmemotors.ae/contact")
    assert source_in_words("") == "" and source_in_words(None) == ""
    assert "Google" in source_in_words("google_maps listing", "ar")


def test_no_time_promises_in_drafts() -> None:
    """CM-049 (owner, 10 Nov): automated drafts never promise 'today'; only 'shortly' or 'during working
    hours'."""
    from paralax.agents.replyguard import replies as rp
    from paralax.agents.knowledge import KnowledgeBase

    kb = KnowledgeBase.load("replyguard")
    assert "CM-049" in {r.id for r in kb.rules}
    for bad in (
        "Good question, Sam will come back to you on that today.",
        "Sam will get back to you personally today.",
        "We will reply within the hour.",
        "سؤال مهم، سام بيرد عليك بنفسه اليوم.",
    ):
        assert rp.NEVER_IN_DRAFT.search(bad), bad
    for ok in (
        "Good question, Sam will come back to you on that shortly.",
        "Sam will get back to you personally during working hours.",
    ):
        assert not rp.NEVER_IN_DRAFT.search(ok), ok
    assert "today" not in rp.template("holding_meeting", "en", sender_name="Sam")
