"""Deterministic deadline resolution (RO/RU/EN). 7B LLMs get calendar maths wrong,
so the model only quotes the spoken expression and this module turns it into a date."""
import calendar
import datetime as dt
import re

WEEKDAY_STEMS = [
    # (regex stem, weekday) - Romanian without diacritics, Russian stems, English
    (r"\bluni\b", 0), (r"\bmarti\b", 1), (r"\bmiercuri\b", 2), (r"\bjoi[a]?\b", 3),
    (r"\bvineri[a]?\b", 4), (r"\bsambat", 5), (r"\bduminic", 6),
    (r"понедельник", 0), (r"вторник", 1), (r"сред[аыу]", 2), (r"четверг", 3),
    (r"пятниц", 4), (r"суббот", 5), (r"воскресен", 6),
    (r"\bmonday", 0), (r"\btuesday", 1), (r"\bwednesday", 2), (r"\bthursday", 3),
    (r"\bfriday", 4), (r"\bsaturday", 5), (r"\bsunday", 6),
]
MONTHS = [
    (r"ianuarie|январ|january", 1), (r"februarie|феврал|february", 2), (r"martie|март|march", 3),
    (r"aprilie|апрел|april", 4), (r"\bmai\b|ма[яй]\b|\bmay\b", 5), (r"iunie|июн|june", 6),
    (r"iulie|июл|july", 7), (r"august|август", 8), (r"septembrie|сентябр|september", 9),
    (r"octombrie|октябр|october", 10), (r"noiembrie|ноябр|november", 11),
    (r"decembrie|декабр|december", 12),
]
# "două luni" = two MONTHS in Romanian, not Monday
MONTHS_NOT_MONDAY = re.compile(r"(\d+|doua|trei|patru|cinci|cateva|cat\w*)\s+luni\b")


RO_PLAIN = str.maketrans("ăâîșşțţ", "aaisstt")


def normalize(text: str) -> str:
    # Romanian diacritics -> plain letters; Cyrillic untouched (й must stay й)
    return text.lower().replace("ё", "е").translate(RO_PLAIN)


def _future(d: dt.date, ref: dt.date) -> dt.date:
    return d if d >= ref else d.replace(year=d.year + 1)


def resolve(text: str, meeting: dt.date) -> str | None:
    """Spoken deadline -> ISO date, or None if the expression isn't recognised."""
    if not text:
        return None
    t = normalize(text)

    # explicit dates: 15.10 / 15.10.2026 / 15/10
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", t)
    if m:
        day, month, year = int(m[1]), int(m[2]), m[3]
        y = int(year) + (2000 if year and len(year) == 2 else 0) if year else meeting.year
        try:
            d = dt.date(y, month, day)
            return (d if year else _future(d, meeting)).isoformat()
        except ValueError:
            pass
    # "15 octombrie" / "15 октября" / "october 15"
    for pattern, month in MONTHS:
        m = re.search(rf"(\d{{1,2}})\s*(?:{pattern})", t) or re.search(rf"(?:{pattern})\w*\s+(\d{{1,2}})\b", t)
        if m:
            try:
                return _future(dt.date(meeting.year, month, int(m[1])), meeting).isoformat()
            except ValueError:
                pass

    relative = [
        (r"poimaine|послезавтра|day after tomorrow", 2),
        (r"\bmaine\b|завтра|tomorrow", 1),
        (r"\bazi\b|\bastazi\b|сегодня|today", 0),
    ]
    for pattern, days in relative:
        if re.search(pattern, t):
            return (meeting + dt.timedelta(days=days)).isoformat()

    m = re.search(r"(\d+)\s*(zile|days?|дн|день)", t)
    if m:
        return (meeting + dt.timedelta(days=int(m[1]))).isoformat()
    m = re.search(r"(\d+)\s*(saptaman|weeks?|недел)", t)
    if m:
        return (meeting + dt.timedelta(weeks=int(m[1]))).isoformat()

    if re.search(r"(sfarsit|final)\w*\s+(lunii|luna)|end of (the )?month|конц\w*\s+месяц", t):
        last = calendar.monthrange(meeting.year, meeting.month)[1]
        return meeting.replace(day=last).isoformat()
    if re.search(r"(sfarsit|final)\w*\s+saptaman|end of (the )?week|конц\w*\s+недел", t):
        return (meeting + dt.timedelta(days=(4 - meeting.weekday()) % 7 or 7)).isoformat()
    if re.search(r"saptamana viitoare|next week|следующ\w*\s+недел", t):
        return (meeting + dt.timedelta(days=7 - meeting.weekday())).isoformat()   # next Monday

    t_days = MONTHS_NOT_MONDAY.sub(" ", t)
    for pattern, weekday in WEEKDAY_STEMS:
        if re.search(pattern, t_days):
            ahead = (weekday - meeting.weekday()) % 7 or 7   # first one AFTER the meeting
            return (meeting + dt.timedelta(days=ahead)).isoformat()
    return None
