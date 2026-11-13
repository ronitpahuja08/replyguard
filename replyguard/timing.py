"""Dates and hours for replies and follow-ups: allowed hours (the country's compliance pack, CM-035), working
days, follow-up dates (CM-008, CM-022, CM-038) and response time in working minutes (CM-033). Pure."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from paralax.compliance.base import get_pack

# Fixed-date public holidays treated as non-working for follow-up DATES (not for allowed hours, which belong
# to
# the compliance pack). Only Gregorian New Year: lunar holidays (Eid) need the holiday calendar that does not
# exist yet (CHANGELOG open point 7), so "after Eid" is asked, not computed.
FIXED_HOLIDAYS = frozenset({(1, 1)})

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAY_WORDS = {
    **{d: i for i, d in enumerate(WEEKDAYS)},
    **{d[:3]: i for i, d in enumerate(WEEKDAYS)},
    "الاثنين": 0,
    "الإثنين": 0,
    "الثلاثاء": 1,
    "الاربعاء": 2,
    "الأربعاء": 2,
    "الخميس": 3,
    "الجمعة": 4,
    "السبت": 5,
    "الاحد": 6,
    "الأحد": 6,
}
MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_WORDS = {**{m: i + 1 for i, m in enumerate(MONTHS)}, **{m[:3]: i + 1 for i, m in enumerate(MONTHS)}}
_MONTH_WORDS["sept"] = 9


def pack_for(country: str | None) -> Any:
    pack = get_pack(country or "AE")
    if pack is None:
        from paralax.compliance.uae import UAEPack

        pack = UAEPack()  # the conservative default (Mon-Fri 09:00-18:00 Dubai)
    return pack


def tz_of(pack: Any) -> ZoneInfo:
    return ZoneInfo(str(getattr(pack, "rules", {}).get("timezone") or "Asia/Dubai"))


def _hours(pack: Any, *, is_reply: bool = False) -> tuple[list[int], time, time]:
    rules = getattr(pack, "rules", {}) or {}
    ah = (rules.get("reply_hours") if is_reply else None) or rules.get("allowed_hours") or {}
    days = list(ah.get("weekdays") or [0, 1, 2, 3, 4])
    h1, m1 = (int(x) for x in str(ah.get("start") or "09:00").split(":"))
    h2, m2 = (int(x) for x in str(ah.get("end") or "18:00").split(":"))
    return days, time(h1, m1), time(h2, m2)


def as_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=UTC)
    if isinstance(v, str) and v.strip():
        try:
            d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    return None


def is_working_day(d: date, pack: Any) -> bool:
    days, _, _ = _hours(pack)
    return d.weekday() in days and (d.month, d.day) not in FIXED_HOLIDAYS


def next_working_day(d: date, pack: Any, *, inclusive: bool = False) -> date:
    cur = d if inclusive else d + timedelta(days=1)
    for _ in range(30):
        if is_working_day(cur, pack):
            return cur
        cur += timedelta(days=1)
    return cur


def nearest_working_day(d: date, pack: Any, *, not_before: date | None = None) -> date:
    """The working day closest to ``d`` (ties go earlier), never before ``not_before`` (keeps a nudge cadence
    from drifting: day 5 on a Saturday is the Friday, not the Monday; CM-038 example)."""
    if is_working_day(d, pack):
        return d
    for k in range(1, 8):
        back, fwd = d - timedelta(days=k), d + timedelta(days=k)
        if is_working_day(back, pack) and (not_before is None or back > not_before):
            return back
        if is_working_day(fwd, pack):
            return fwd
    return d


def next_allowed(dt: datetime, pack: Any, *, is_reply: bool = False) -> datetime:
    """The earliest moment >= ``dt`` inside the pack's allowed hours (CM-035); replies to someone who wrote
    first use the pack's reply window (owner decisions G8 + L3: Mon-Fri 09:00-21:00 in the UAE)."""
    tz = tz_of(pack)
    days, start, end = _hours(pack, is_reply=is_reply)
    local = dt.astimezone(tz)
    for k in range(0, 15):
        day = (local + timedelta(days=k)).date()
        if day.weekday() not in days:
            continue
        open_at = datetime.combine(day, start, tzinfo=tz)
        close_at = datetime.combine(day, end, tzinfo=tz)
        if k == 0 and local >= close_at:
            continue
        return max(open_at, local) if k == 0 else open_at
    return local


def working_minutes(start: datetime, end: datetime, pack: Any) -> float:
    """Minutes between two instants that fall inside allowed hours (CM-033: night time counts as zero)."""
    if end <= start:
        return 0.0
    tz = tz_of(pack)
    days, s_t, e_t = _hours(pack)
    total = 0.0
    a, b = start.astimezone(tz), end.astimezone(tz)
    day = a.date()
    while day <= b.date():
        if day.weekday() in days:
            lo = max(a, datetime.combine(day, s_t, tzinfo=tz))
            hi = min(b, datetime.combine(day, e_t, tzinfo=tz))
            if hi > lo:
                total += (hi - lo).total_seconds() / 60.0
        day += timedelta(days=1)
    return round(total, 1)


def window_start(channel: str, pack: Any) -> str:
    """HH:MM a follow-up is aimed at: the Channel Operator's first send window for the channel (CO-006), else
    the opening of allowed hours."""
    try:
        from paralax.orchestrator.send_planner import windows_for

        wins, _ = windows_for(None, channel)
        if wins:
            start = str(wins[0].get("from") or wins[0].get("start") or "")[:5]
            if start:
                return start
    except Exception:  # noqa: BLE001, S110 - planner not configured: fall back to the pack
        pass
    return _hours(pack)[1].strftime("%H:%M")


# --------------------------------------------------------------------------------------------- parsing


def _year_for(month: int, day: int, now: date) -> date:
    try:
        d = date(now.year, month, day)
    except ValueError:
        return now
    return d if d >= now else date(now.year + 1, month, day)


_DATE_DM = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})\b")
_DATE_MD = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b")
_DATE_NUM = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b")
_UNTIL = re.compile(
    r"\b(?:until|till|til|through|back\s+on|returning\s+on|return\s+on|back\s+in\s+the\s+office\s+on|from)\b"
    r"|حتى|لغاية|الى\s+غاية",
    re.IGNORECASE,
)


def find_dates(text: str, now: date) -> list[date]:
    out: list[date] = []
    for m in _DATE_DM.finditer(text or ""):
        mon = _MONTH_WORDS.get(m.group(2).lower())
        if mon:
            out.append(_year_for(mon, int(m.group(1)), now))
    for m in _DATE_MD.finditer(text or ""):
        mon = _MONTH_WORDS.get(m.group(1).lower())
        if mon:
            out.append(_year_for(mon, int(m.group(2)), now))
    for m in _DATE_NUM.finditer(text or ""):
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            out.append(_year_for(mo, d, now))
    return out


def return_date(text: str, now: date) -> date | None:
    """The return date an out-of-office states ("until 24 Nov", "on annual leave until 1 December")."""
    t = text or ""
    m = _UNTIL.search(t)
    tail = t[m.end() :] if m else t
    found = find_dates(tail, now) or find_dates(t, now)
    if found:
        return found[0]
    for word, idx in _WEEKDAY_WORDS.items():
        if re.search(rf"\b(?:until|back\s+on|returning)\s+{re.escape(word)}\b", t, re.IGNORECASE):
            ahead = (idx - now.weekday()) % 7 or 7
            return now + timedelta(days=ahead)
    return None


def resume_after_ooo(
    text: str, now: datetime, pack: Any, *, business_days_after: int, default_days: int
) -> date:
    """CM-008: the first allowed working day after the stated return date, else ``default_days`` later."""
    today = now.astimezone(tz_of(pack)).date()
    back = return_date(text, today)
    if back is None:
        return next_working_day(today + timedelta(days=default_days - 1), pack)
    d = back
    for _ in range(max(1, business_days_after)):
        d = next_working_day(d, pack)
    return d


def quarter_start(q: int, now: date) -> date:
    month = 3 * (q - 1) + 1
    d = date(now.year, month, 1)
    return d if d > now else date(now.year + 1, month, 1)


def weekday_in_text(text: str) -> int | None:
    low = (text or "").lower()
    for word in sorted(_WEEKDAY_WORDS, key=len, reverse=True):
        if re.search(rf"(?<![\w؀-ۿ]){re.escape(word)}(?![\w؀-ۿ])", low):
            return _WEEKDAY_WORDS[word]
    return None


_QUARTER = re.compile(r"\bq([1-4])\b|\b(first|second|third|fourth)\s+quarter\b", re.IGNORECASE)
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_RELATIVE = re.compile(r"\b(?:in|after)\s+(\d{1,2}|a|one|two|three)\s+(day|week|month)s?\b", re.IGNORECASE)
_NEXT = re.compile(r"\bnext\s+(week|month|year)\b", re.IGNORECASE)
_NUMWORD = {"a": 1, "one": 1, "two": 2, "three": 3}


def requested_date(text: str, now: date, timing: Any = None) -> tuple[date | None, str | None, int | None]:
    """(date asked for, anchor we cannot compute, weekday they named) from their words, then the classifier's
    ``timing``. A quarter means its first working day (applied by the caller); an anchor ("after Eid") has no
    date until the holiday calendar exists (CHANGELOG open point 7)."""
    kind = str(getattr(timing, "kind", "") or "")
    value = str(getattr(timing, "value", "") or "")
    if kind == "anchor" and value:
        return None, value, None
    m = _QUARTER.search(text or "")
    if m or (kind == "quarter" and value[-1:].isdigit()):
        q = (
            int(m.group(1))
            if m and m.group(1)
            else (_ORD.get((m.group(2) or "").lower()) if m else int(value[-1]))
        )
        return quarter_start(int(q or 1), now), None, None
    wd = weekday_in_text(text)
    if wd is None and kind == "weekday" and value.lower() in WEEKDAYS:
        wd = WEEKDAYS.index(value.lower())
    if wd is not None:
        ahead = (wd - now.weekday()) % 7 or 7
        return now + timedelta(days=ahead), None, wd
    dates = find_dates(text, now)
    if dates:
        return dates[0], None, None
    if kind == "date":
        d = as_dt(value)
        if d is not None:
            return d.date(), None, None
    m2 = _RELATIVE.search(text or "")
    if m2:
        n = int(m2.group(1)) if m2.group(1).isdigit() else _NUMWORD.get(m2.group(1).lower(), 1)
        unit = m2.group(2).lower()
        days = n * (1 if unit == "day" else 7 if unit == "week" else 30)
        return now + timedelta(days=days), None, None
    m3 = _NEXT.search(text or "")
    if m3:
        unit = m3.group(1).lower()
        if unit == "week":
            return now + timedelta(days=(7 - now.weekday()) % 7 or 7), None, None
        if unit == "month":
            first = date(now.year + (now.month // 12), now.month % 12 + 1, 1)
            return first, None, None
        return date(now.year + 1, 1, 1), None, None
    if kind == "relative_days" and value.isdigit():
        return now + timedelta(days=int(value)), None, None
    return None, None, None
