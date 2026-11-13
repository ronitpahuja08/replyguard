"""Deterministic signals read from a reply before (and alongside) the classifier. Pure functions, no I/O.

- the opt-out detector (``domain/optout.detect_inbound_opt_out``, CM-004): the floor the classifier can only
  add to;
- auto-replies (CM-007, CM-009): email headers first; on WhatsApp two signals (timing + boilerplate);
- language (CM-032): Arabic letters vs Latin words, majority of words for mixed text;
- keyword hints that ADD handover reasons and safety intents (pricing, legal, personal data, bot question,
  company-wide opt-out, deletion request, a stated block or report). Hints never remove anything the
  classifier found; a hint that fires on an ordinary message only sends it to a human (the safe side).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from paralax.domain.optout import detect_inbound_opt_out, normalize_arabic

_AR_LETTER = re.compile(r"[؀-ۿ]")
_AR_WORD = re.compile(r"[؀-ۿ]+")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def detector_opt_out(text: str) -> bool:
    return bool(detect_inbound_opt_out(text or ""))


# --------------------------------------------------------------------------------------------- language

# Arabizi: Gulf/Levantine words written in Latin letters (ours; the classifier is the main judge).
_ARABIZI = frozenset(
    "mashkoor mashkour shukran shokran mob mub mb mohtam muhtam mehtam abi abgha ab6a inshallah insha "
    "yalla habibi khalas 5alas wallah walla ahlan marhaba la ana mo mesh msh 3ndi 3andi 7ayak ma3 3la "
    "bas ba3den ba3dain baden".split()
)


def language_of(text: str, *, classifier_language: str | None = None) -> str:
    """en | ar | arabizi | other. Mixed Arabic/Latin text takes the language of most of the words (CM-032)."""
    t = text or ""
    ar_words = len(_AR_WORD.findall(t))
    latin = [w.lower() for w in _LATIN_WORD.findall(t)]
    if ar_words and ar_words >= len(latin):
        return "ar"
    if not latin:
        return "ar" if ar_words else "en"
    cl = (classifier_language or "").strip().lower()
    if cl in ("ar", "arabic"):
        cl = "arabizi"  # Latin-script Arabic
    if cl and cl not in ("en", "english", "mixed"):
        return cl if cl in ("arabizi",) else "other"
    arabizi = sum(1 for w in latin if w in _ARABIZI)
    if arabizi and arabizi * 2 >= len(latin):
        return "arabizi"
    return "en"


def reply_language(lang: str, thread_language: str | None = None) -> str | None:
    """The language we answer in: Arabic for Arabic, English for English and Arabizi (unless the thread was in
    Arabic), None for anything else (hand over, ``unsupported_language``)."""
    if lang == "ar":
        return "ar"
    if lang == "en":
        return "en"
    if lang == "arabizi":
        return "ar" if thread_language == "ar" else "en"
    return None


def thread_language(thread: list[Mapping[str, Any]]) -> str:
    for item in reversed(thread or []):
        if str(item.get("dir")) == "out" and item.get("text"):
            return "ar" if len(_AR_LETTER.findall(str(item["text"]))) >= 8 else "en"
    return "en"


# --------------------------------------------------------------------------------------------- auto-replies

_AUTO_PRECEDENCE = {"auto_reply", "bulk", "junk", "list"}
_SUBJECT_HINTS = re.compile(
    r"^\s*(?:automatic\s+reply|auto(?:matic)?\s*:|autoreply|auto-reply|out\s+of\s+(?:the\s+)?office|"
    r"رد\s+تلقائي|خارج\s+المكتب)",
    re.IGNORECASE,
)
_OOO_TEXT = re.compile(
    r"\b(?:out\s+of\s+(?:the\s+)?office|on\s+(?:annual\s+|sick\s+|parental\s+)?leave|on\s+vacation|on\s+holiday|"
    r"away\s+from\s+(?:the\s+)?office|limited\s+access\s+to\s+(?:e-?mail|my\s+e-?mail)|will\s+be\s+back|"
    r"return(?:ing)?\s+on|back\s+in\s+the\s+office|automatic\s+reply)\b"
    r"|خارج\s+المكتب|في\s+اجازة|في\s+إجازة",
    re.IGNORECASE,
)
_BOILERPLATE = re.compile(
    r"\b(?:thank(?:s|\s+you)\s+for\s+(?:contacting|reaching\s+out|your\s+message|messaging|getting\s+in\s+touch)|"
    r"(?:we|our\s+team)\s+will\s+(?:get\s+back|reply|respond|be\s+in\s+touch)|"
    r"(?:opening|business|showroom|working|office)\s+hours|"
    r"(?:reply|press|type|send)\s+\d+\s+(?:for|to)|"
    r"we\s+are\s+(?:currently\s+)?(?:closed|unavailable|away))\b"
    r"|شكرا\s*(?:ل|على)\s*(?:تواصلك|تواصلكم|رسالتك)|سنقوم\s+بالرد|سيتم\s+الرد|اوقات\s+العمل|ساعات\s+العمل",
    re.IGNORECASE,
)


def header(headers: Mapping[str, Any] | None, name: str) -> str:
    for k, v in (headers or {}).items():
        if str(k).strip().lower() == name.lower():
            return str(v or "").strip()
    return ""


def email_auto_reply(headers: Mapping[str, Any] | None, text: str) -> tuple[bool, list[str]]:
    """CM-007: definitive headers first; a subject hint counts only with text support."""
    reasons: list[str] = []
    auto = header(headers, "Auto-Submitted").lower()
    if auto and auto != "no":
        reasons.append(f"Auto-Submitted: {auto}")
    for h in ("X-Autoreply", "X-Autorespond"):
        if header(headers, h):
            reasons.append(f"{h} present")
    prec = header(headers, "Precedence").lower()
    if prec in _AUTO_PRECEDENCE:
        reasons.append(f"Precedence: {prec}")
    if reasons:
        return True, reasons
    subject = header(headers, "Subject")
    if subject and _SUBJECT_HINTS.search(subject) and _OOO_TEXT.search(text or ""):
        return True, [f"subject hint {subject[:40]!r} + out-of-office text"]
    return False, []


def is_boilerplate(text: str) -> bool:
    return bool(_BOILERPLATE.search(normalize_arabic(text or "")) or _OOO_TEXT.search(text or ""))


def whatsapp_auto_reply(
    text: str, seconds_after_our_last: float | None, *, max_seconds: float, classifier_says_auto: bool = False
) -> tuple[bool, list[str]]:
    """CM-009: auto only when BOTH signals hold: it came within ``max_seconds`` of our message AND it is
    generic boilerplate (pattern, or the classifier's reading). A short human "ok" is human."""
    fast = seconds_after_our_last is not None and 0 <= float(seconds_after_our_last) <= float(max_seconds)
    boiler = is_boilerplate(text) or classifier_says_auto
    if fast and boiler:
        return True, [f"arrived {seconds_after_our_last:g}s after our message", "generic boilerplate"]
    return False, []


# --------------------------------------------------------------------------------------------- hints

_HINTS: dict[str, re.Pattern[str]] = {
    "pricing": re.compile(
        r"\b(?:how\s+much|what(?:'s|\s+is|\s+does|\s+would)\s+(?:the\s+|it\s+|this\s+)?(?:price|cost)|price\s*\?|"
        r"pricing|prices|costs?\s+(?:us|me)|quote|quotation|discount|invoice|payment|per\s+month|monthly\s+fee|"
        r"subscription\s+fee)\b|كم\s+السعر|كم\s+سعر|بكم|الاسعار|التكلفة|كم\s+يكلف|كم\s+تكلف|خصم",
        re.IGNORECASE,
    ),
    "negotiation": re.compile(
        r"\b(?:contract|terms|free\s+trial|trial\s+period|sla|scope\s+of\s+work|deadline|exclusiv\w*)\b|عقد|تجربة\s+مجانية",
        re.IGNORECASE,
    ),
    "legal_or_regulator": re.compile(
        r"\b(?:tdra|pdpl|lawyer|legal\s+action|sue|police|regulator|authorit(?:y|ies)|court|gdpr|complain\s+to)\b"
        r"|محامي|الشرطة|هيئة\s+تنظيم|قضية|بلاغ",
        re.IGNORECASE,
    ),
    "personal_data_request": re.compile(
        r"\b(?:who\s+gave\s+you\s+my|where\s+did\s+you\s+get\s+my|how\s+did\s+you\s+get\s+my|what\s+data\s+do\s+you|"
        r"what\s+information\s+do\s+you\s+have|my\s+personal\s+data)\b"
        r"|من\s+(?:اين|وين)\s+(?:جبت|حصلت)|منو\s+عطاك|من\s+اعطاك",
        re.IGNORECASE,
    ),
    "visit_request": re.compile(
        r"\b(?:stop\s+by|come\s+(?:by|over|to\s+(?:our|the))|visit\s+(?:us|our)|drop\s+by|pop\s+in)\b"
        r"|تفضل\s+(?:عندنا|زورنا)|زورونا|مر\s+علينا",
        re.IGNORECASE,
    ),
}
_BOT_Q = re.compile(
    r"\b(?:are\s+you\s+(?:a\s+)?(?:bot|robot|real|human|ai|automated|a\s+real\s+person)|is\s+(?:this|it)\s+(?:an?\s+)?(?:bot|"
    r"robot|automated|automatic|ai|real|machine)|(?:automated|automatic|auto[\s-]?generated)\s+(?:message|reply|text|"
    r"system)s?\b(?=[^.!]*\?)|sent\s+by\s+(?:a\s+)?(?:bot|machine|computer)|am\s+i\s+(?:talking|speaking|chatting)\s+(?:to|with)\s+a\s+(?:bot|robot|machine|human|"
    r"real\s+person)|real\s+person\s+or|automated\?|chatgpt)\b|(?:هل\s+)?(?:هذا|انت|إنت|انتا)\s+(?:بوت|روبوت|آلي|الي)"
    r"|رد\s+آلي|ذكاء\s+اصطناعي",
    re.IGNORECASE,
)
_COMPANY_SCOPE = re.compile(
    r"\b(?:contact|message|email|text|call|spam)\s+us\b|\bremove\s+(?:us|our\s+company|our\s+details)\b|"
    r"\b(?:anyone|anybody|everyone|nobody)\s+(?:here|at\s+(?:our|this)\s+company)\b|\bour\s+company\b.*\b(?:stop|remove)\b"
    r"|لا\s+تراسلونا|لا\s+تتواصلوا\s+معنا|لا\s+ترسلون\s+لنا|احذفوا\s+رقمنا|شركتنا",
    re.IGNORECASE,
)
_DELETE_DATA = re.compile(
    r"\b(?:delete|erase)\s+(?:my|our|all\s+my)\s+(?:phone\s+)?(?:number|data|details|information|info|contact)\b"
    r"|(?:احذف|احذفوا|امسح|امسحوا)\s+(?:رقمي|بياناتي|معلوماتي)",
    re.IGNORECASE,
)
# Only what they say they DID (past tense): "Reported." / "I blocked you". A threat ("I will report this to
# TDRA") is a complaint, not a report (CM-010: add report/block only when stated).
_STATED_SIGNAL = {
    "report": re.compile(
        r"\breported\b|\bflagged\b|\bmarked\s+(?:it|this|you)\s+as\s+spam\b|بلغت|بلّغت", re.I
    ),
    "block": re.compile(r"\bblocked\b|حظرت|سويت\s+بلوك|سويتلك\s+بلوك", re.I),
}
_WA_CALL = re.compile(
    r"\b(?:whatsapp|wa)\s+(?:voice\s+|video\s+)?call\b|اتصال\s+واتساب|مكالمة\s+واتساب", re.I
)


def hint_reasons(text: str) -> list[str]:
    t = normalize_arabic(text or "")
    return [name for name, rx in _HINTS.items() if rx.search(t) or rx.search(text or "")]


def is_bot_question(text: str) -> bool:
    return bool(_BOT_Q.search(text or "") or _BOT_Q.search(normalize_arabic(text or "")))


def speaks_for_company(text: str) -> bool:
    return bool(_COMPANY_SCOPE.search(text or "") or _COMPANY_SCOPE.search(normalize_arabic(text or "")))


def deletion_request(text: str) -> bool:
    return bool(_DELETE_DATA.search(text or "") or _DELETE_DATA.search(normalize_arabic(text or "")))


def stated_signals(text: str) -> list[str]:
    return [k for k, rx in _STATED_SIGNAL.items() if rx.search(text or "")]


def asks_whatsapp_call(text: str) -> bool:
    return bool(_WA_CALL.search(text or ""))


# --------------------------------------------------------------------------------------------- referrals

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def emails_in(*texts: str) -> list[str]:
    out: list[str] = []
    for t in texts:
        for e in _EMAIL.findall(t or ""):
            if e.lower() not in out:
                out.append(e.lower())
    return out


def count_questions(text: str) -> int:
    # a "?" inside a link (the booking link's ?ref= tag, Day 5) is not a question
    return len(re.findall(r"[?؟]", re.sub(r"https?://\S+|www\.\S+", " ", text or "")))
