"""Reply drafts: fixed-form replies from templates, free-form ones (jab 2, a two-line answer, an objection
question, a nudge) from the LLM, every draft through the self-check before it may become a message.

Every draft ends with the sender line and the opt-out line in the reply's language (CM-032, CM-037), carries
no digits of its own (dates are written as words, so the evidence gate has nothing to trace), and is checked
against the locked lists: never claim to be human (CM-017), never price, terms, times or visits (CM-018,
CM-027), no outside statistics (CM-030).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from paralax.agents.replyguard.schemas import Draft
from paralax.agents.replyguard.signals import count_questions
from paralax.domain.evidence import extract_numbers, number_matches
from paralax.domain.optout import OPT_OUT_LINE_AR, OPT_OUT_LINE_EN, strip_opt_out

# reply kinds (the test set's names, R21)
LLM_KINDS = frozenset({"jab_2", "two_line_answer_then_jab_2", "label_then_calibrated_question", "nudge"})
TEMPLATE_KINDS = frozenset(
    {
        "bot_disclosure",
        "holding_line",
        "thanks",
        "ask_who",
        "thanks_optional_why",
        "when_suits_you",
        "confirm_date",
        "booking_link",
        "confirmation_only",
    }
)
NO_SEND_KINDS = frozenset({"none", "confirmation_only"})

AR_WEEKDAYS = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")
EN_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
EN_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
AR_MONTHS = (
    "يناير",
    "فبراير",
    "مارس",
    "أبريل",
    "مايو",
    "يونيو",
    "يوليو",
    "أغسطس",
    "سبتمبر",
    "أكتوبر",
    "نوفمبر",
    "ديسمبر",
)

TEMPLATES: dict[str, dict[str, str]] = {
    "thanks_referral": {
        "en": "Thanks a lot, much appreciated. I'll get in touch with {name}.",
        "ar": "شكراً جزيلاً على المساعدة، نقدّر لك ذلك.",
    },
    "thanks_left": {
        "en": "Thanks for letting me know, and all the best.",
        "ar": "شكراً على إبلاغي، وكل التوفيق.",
    },
    "ask_who": {
        "en": "Thanks for letting me know. Who would be the right person to speak to about this?",
        "ar": "شكراً على إبلاغي. مين الشخص المناسب للتواصل معه بخصوص هذا الموضوع؟",
    },
    "thanks_optional_why": {
        "en": "Thanks for letting me know. Out of interest, is it timing or just not a fit?",
        "ar": "مشكور على ردك. للعلم فقط، هل السبب التوقيت أم أنه غير مناسب لكم؟",
    },
    "when_suits_you": {
        "en": "No problem at all. When would suit you better?",
        "ar": "ولا يهمك. متى يناسبك أكثر؟",
    },
    "confirm_date": {
        "en": "No problem, I'll message you {when}.",
        "ar": "ولا يهمك، بتواصل معك {when}.",
    },
    "confirm_date_moved": {
        "en": "No problem. {asked} is outside our messaging days, so I'll message you {when}.",
        "ar": "ولا يهمك. يوم {asked} خارج أيام التواصل عندنا، فبتواصل معك {when}.",
    },
    "booking_link": {
        "en": "Here's the link to pick a short slot that suits you: {link}",
        "ar": "هذا الرابط لاختيار الموعد اللي يناسبك: {link}",
    },
    "holding_meeting": {
        "en": "Great, thanks. {sender_name} will get back to you personally during working hours.",
        "ar": "ممتاز، شكراً. {sender_name} بيتواصل معك بنفسه خلال ساعات العمل.",
    },
    "confirmation_only": {
        "en": "Done, you won't hear from us again.",
        "ar": "تم، لن نراسلك مرة أخرى.",
    },
}

# CM-018 / CM-027 / CM-030: phrases that may never appear in an automated draft
NEVER_IN_DRAFT = re.compile(
    r"\b(?:aed|dhs?|usd|sar)\b|\$|€|£|\bdiscount\b|\bper\s+month\b|\bfree\s+trial\b|\binvoice\b|"
    r"\bsee\s+you\b|\bi'?ll\s+come\b|\bcalling\s+you\s+now\b|\bconfirmed\b|"
    r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\s+at\b|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|"
    r"\bstudies\s+show\b|\bresearch\s+(?:shows|says|finds)\b|\bharvard\b|\bhbr\b|\bindustry\s+(?:data|average)\b|"
    r"\bshort\s+life\s+of\s+online\s+sales\s+leads\b|\bfeatures?\b|"
    # CM-049 (owner, 10 Nov): no time promises in an automated draft; only a human commits to a time
    r"\b(?:will|'ll|shall|going\s+to|get(?:ting)?\s+back|come\s+back|reply|respond|call|contact)\b"
    r"[^.?!\n]{0,60}\b(?:today|tonight|this\s+(?:morning|afternoon|evening)|within\s+(?:the|an|\d+)\s+hours?)\b|"
    r"(?:بيرد|بيتواصل|نرد|بنرد|نتواصل|بنتواصل|يرد|يتواصل)[^.؟!\n]{0,40}(?:اليوم|الليلة)",
    re.IGNORECASE,
)
QUESTION_MARK = re.compile(r"[?؟]")


def opt_out_line(language: str) -> str:
    return OPT_OUT_LINE_AR if (language or "").startswith("ar") else OPT_OUT_LINE_EN


def signature(sender: Mapping[str, Any], language: str) -> str:
    name = str(sender.get("name") or "").strip()
    company = str(sender.get("company") or "").strip()
    sep = "، " if language == "ar" else ", "
    return sep.join(x for x in (name, company) if x)


GREETING_RE = re.compile(r"^(?:Hi|هلا)\s+[^\n,،]{1,40}[,،]\n")


def greeting(first_name: str | None, language: str) -> str:
    name = (first_name or "").strip()
    if not name:
        return ""
    return f"هلا {name}،" if language == "ar" else f"Hi {name},"


def finish(body: str, sender: Mapping[str, Any], language: str, *, first_name: str | None = None) -> str:
    """Greeting with their first name (the content gate's locked name rule) + the body + the sender line
    (sender identification, unless the body already names the company) + the opt-out line in the reply's
    language (every message, CM-037)."""
    text = body.strip()
    if first_name and not re.search(rf"(?<![\w]){re.escape(first_name.strip())}(?![\w])", text):
        text = greeting(first_name, language) + "\n" + text
    company = str(sender.get("company") or "").strip()
    parts = [text]
    words = re.sub(r"https?://\S+|www\.\S+", " ", text).casefold()  # a link is not a sender line
    if not company or company.casefold() not in words:
        sig = signature(sender, language)
        if sig:
            parts.append(sig)
    parts.append(opt_out_line(language))
    return "\n\n".join(parts[:-1]) + "\n" + parts[-1]


def core(body: str, sender: Mapping[str, Any], language: str) -> str:
    """The body without the greeting, the sender line and the opt-out line (what the limits count)."""
    text = strip_opt_out(body or "")
    text = GREETING_RE.sub("", text)
    sig = signature(sender, language)
    if sig and text.rstrip().endswith(sig):
        text = text.rstrip()[: -len(sig)]
    return text.strip()


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def when_words(d: date, today: date, language: str, *, morning: bool = True) -> str:
    """A date in words, no digits: "on Monday morning" within a week, else "in early January"."""
    if 0 < (d - today).days <= 7:
        if language == "ar":
            return f"يوم {AR_WEEKDAYS[d.weekday()]}" + (" الصبح" if morning else "")
        return f"on {EN_WEEKDAYS[d.weekday()]}" + (" morning" if morning else "")
    part = "early" if d.day <= 10 else ("mid" if d.day <= 20 else "late")
    if language == "ar":
        ar_part = {"early": "بداية", "mid": "منتصف", "late": "نهاية"}[part]
        return f"{ar_part} {AR_MONTHS[d.month - 1]}"
    return f"in {part} {EN_MONTHS[d.month - 1]}"


def template(kind: str, language: str, **values: Any) -> str:
    lang = "ar" if language == "ar" else "en"
    return TEMPLATES[kind][lang].format(**values)


# --------------------------------------------------------------------------------------------- self-check


@dataclass
class DraftCheck:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    evidence_problem: bool = False


def check_draft(
    body: str,
    *,
    kind: str,
    channel: str,
    language: str,
    sender: Mapping[str, Any],
    defaults: Any,
    claims: list[Mapping[str, Any]] | None = None,
    record: Mapping[str, Any] | None = None,
) -> DraftCheck:
    """The CM's own checks on a finished draft (the send gates still run on the message)."""
    reasons: list[str] = []
    evidence = False
    text = core(body, sender, language)
    limit = int(
        defaults.get(
            f"reply_form.max_words_{'chat' if channel != 'email' else 'email'}",
            60 if channel != "email" else 80,
        )
    )
    if word_count(text) >= limit:
        reasons.append(f"too long: {word_count(text)} words (limit < {limit})")
    q = count_questions(text)
    max_q = 0 if kind in ("bot_disclosure", "holding_line", "confirmation_only", "booking_link") else 1
    if q > max_q:
        reasons.append(f"{q} questions (max {max_q})")
    if q == 1 and not text.rstrip().endswith(("?", "؟")):
        reasons.append("the question is not last")
    for phrase in defaults.get("truthfulness.forbidden_claims") or []:
        if str(phrase).casefold() in body.casefold():
            reasons.append(f"claims to be human: {phrase!r}")
    for fig in defaults.get("answers.banned_figures") or []:
        if str(fig).casefold() in body.casefold():
            reasons.append(f"banned figure: {fig!r}")
    m = NEVER_IN_DRAFT.search(text)
    if m and kind not in ("bot_disclosure",):
        reasons.append(f"never-say phrase: {m.group(0)!r}")
    if opt_out_line(language) not in body:
        reasons.append("opt-out line missing")
    arabic = bool(re.search(r"[؀-ۿ]", text))
    if language == "ar" and not arabic:
        reasons.append("Arabic reply has no Arabic text")
    if language == "en" and arabic:
        reasons.append("English reply contains Arabic text")
    # evidence only (CM-024, CM-030): claims cite an allowed source; every number traces to the record
    allowed = set(defaults.get("answers.allowed_sources") or []) | {"thread"}
    for c in claims or []:
        src = str(c.get("source") or "")
        if src not in allowed:
            reasons.append(f"claim from a source that is not allowed: {src or 'none'}")
            evidence = True
        if str(c.get("text") or "").strip() and _norm(str(c["text"])) not in _norm(body):
            reasons.append("claim text not in the message")
            evidence = True
    sources = [
        (f.get("value_num"), str(f.get("unit") or ""))
        for f in (record or {}).get("findings") or []
        if isinstance(f, Mapping) and f.get("value_num") is not None
    ]
    sources += [
        (a.get("value"), str(a.get("unit") or ""))
        for a in (record or {}).get("allowlist") or []
        if isinstance(a, Mapping) and a.get("value") is not None
    ]
    for n in extract_numbers(text):
        if not any(number_matches(n, v, u) for v, u in sources if v is not None):
            reasons.append(f"number {n.raw!r} not traced to a finding or the allow-list")
            evidence = True
    return DraftCheck(ok=not reasons, reasons=reasons, evidence_problem=evidence)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().casefold().rstrip(".!?")


# --------------------------------------------------------------------------------------------- the LLM


def _one_line(text: str) -> str:
    return " ".join(text.split())


_KIND_BRIEF = {
    "jab_2": _one_line(
        """They said yes. Write jab 2: hand over their one-page report (the report link from the record)
        with its headline in one line, then ONE easy question at the end (CM-023, CM-037)."""
    ),
    "two_line_answer_then_jab_2": _one_line(
        """They asked a question. Answer it in at most two short lines using ONLY the record (findings,
        report, the brief's offer, the allow-list, the approved FAQ, or what our earlier message in the thread
        already said), then offer jab 2 with ONE easy question at the end (CM-024)."""
    ),
    "label_then_calibrated_question": _one_line(
        """They raised an objection. Name what you heard tentatively (a label, e.g. 'Sounds like ...'), then
        ask ONE calibrated 'what' or 'how' question. No rebuttal, no feature list, no numbers, shorter than
        their message (CM-025, CM-026)."""
    ),
    "nudge": _one_line(
        """They replied before and went quiet. Write one short nudge that adds something NEW from the record
        (a finding not yet shared, or a short answer to their last point) and ends with one easy, no-pressure
        question (CM-038). Never 'just checking in', never pressure."""
    ),
}
DRAFT_RULES = _one_line(
    """Write in {language}; under {words} words; at most one question and it comes last; no digits unless
    the record has that exact number; no price, discount, terms, dates, times, visits or calls; no outside
    statistics or studies; never claim or imply a human is typing. Do NOT add a greeting, a signature or an
    opt-out line (code adds them). List every factual claim you make in `claims` with its source (findings |
    company_report | brief_offer | offer_allow_list | approved_faq | thread) and ref."""
)


def draft_with_llm(
    llm: Any,
    *,
    kind: str,
    language: str,
    channel: str,
    sender: Mapping[str, Any],
    reply_text: str,
    thread: list[Mapping[str, Any]],
    record: Mapping[str, Any],
    kb_context: str,
    feedback: list[str] | None = None,
) -> Draft:
    words = 60 if channel != "email" else 80
    lang_name = "Arabic (Gulf, polite)" if language == "ar" else "English"
    system = (
        "You are the ReplyGuard, writing ONE reply on behalf of "
        f"{sender.get('name') or 'the sender'} at {sender.get('company') or 'our company'}. "
        f"{_KIND_BRIEF[kind]}\n" + DRAFT_RULES.format(language=lang_name, words=words) + "\n\n" + kb_context
    )
    user = json.dumps(
        {
            "their_reply": reply_text,
            "thread": [
                {"dir": t.get("dir"), "kind": t.get("kind"), "text": t.get("text")} for t in thread[-6:]
            ],
            "record": {
                k: v for k, v in record.items() if k in ("findings", "report", "offer", "allowlist", "faq")
            },
            "fix_these_problems": feedback or [],
        },
        ensure_ascii=False,
        default=str,
    )
    return llm.complete_json(
        f"replyguard.draft.{kind}",
        system=system,
        user=user,
        schema=Draft,
        model_tier="strong",
        timeout_s=60,
    )
