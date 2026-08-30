import re
from datetime import UTC, datetime, timedelta


def parse_natural_date(text: str | None, base_time: datetime | None = None) -> datetime | None:
    """Parses natural language date/time expressions into UTC datetime.

    Supports:
    - Relative shortcuts: 'today', 'eod', 'tonight', 'tomorrow', 'tomorrow 9am', 'tomorrow 5pm'
    - Relative offsets: 'in 2 hours', 'in 30 mins', 'in 2 days', 'in 3d', 'in 1 week', 'in 2w', 'in 1 month'
    - Days of week: 'monday', 'next tuesday', 'this friday', 'friday 5pm', 'sat 12:00'
    - Month day dates: 'apr 15', '15 april', 'dec 31 18:00', 'may 1 2026'
    - Standard ISO: '2026-04-15', '2026-04-15 18:00', '2026-04-15T18:00:00Z'
    - Returns None if empty or if clear keywords ('clear', 'none', 'remove', 'null') are used.
    """
    if not text:
        return None

    raw = text.strip().lower()
    if raw in ("clear", "none", "remove", "null", "unset", "off", "cancel"):
        return None

    now = base_time or datetime.now(UTC)
    now_utc = now.astimezone(UTC)

    # 1. Check standard ISO and explicit formats
    explicit_formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ]
    for fmt in explicit_formats:
        try:
            dt = datetime.strptime(text.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            # If no time component was provided (hour=0, min=0), default to 17:00 UTC
            if fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
                dt = dt.replace(hour=17, minute=0, second=0)
            return dt.astimezone(UTC)
        except ValueError:
            pass

    # 2. Time extract helper (e.g. '5pm', '18:00', '9:30am', '9am')
    time_colon = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?\b", raw)
    time_ampm = re.search(r"\b(\d{1,2})\s*(am|pm)\b", raw)
    hour = 17
    minute = 0
    time_found = False

    if time_colon:
        h_str, m_str, _, am_pm = time_colon.groups()
        h = int(h_str)
        m = int(m_str) if m_str else 0
        if am_pm:
            if am_pm == "pm" and h < 12:
                h += 12
            elif am_pm == "am" and h == 12:
                h = 0
        if 0 <= h <= 23 and 0 <= m <= 59:
            hour = h
            minute = m
            time_found = True
    elif time_ampm:
        h_str, am_pm = time_ampm.groups()
        h = int(h_str)
        if am_pm == "pm" and h < 12:
            h += 12
        elif am_pm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23:
            hour = h
            minute = 0
            time_found = True

    # 3. Simple keywords
    if raw in ("today", "eod", "tonight", "end of day"):
        target_h = 21 if raw == "tonight" else 17
        return now_utc.replace(hour=target_h, minute=0, second=0, microsecond=0)

    if raw.startswith("tomorrow"):
        target = now_utc + timedelta(days=1)
        h = hour if time_found else 17
        m = minute if time_found else 0
        return target.replace(hour=h, minute=m, second=0, microsecond=0)

    # 4. Relative offsets: 'in X hours / mins / days / weeks / months' or 'Xd', 'Xw', 'Xh'
    offset_match = re.match(
        r"^(?:in\s+)?(\d+)\s*(mins?|minutes?|hours?|hrs?|h|days?|d|weeks?|w|months?|m)(?:\s+from\s+now)?$",
        raw,
    )
    if offset_match:
        qty = int(offset_match.group(1))
        unit = offset_match.group(2)
        if unit in ("mins", "min", "minutes", "minute"):
            return now_utc + timedelta(minutes=qty)
        elif unit in ("hours", "hour", "hrs", "hr", "h"):
            return now_utc + timedelta(hours=qty)
        elif unit in ("days", "day", "d"):
            target = now_utc + timedelta(days=qty)
            return target.replace(hour=17, minute=0, second=0, microsecond=0)
        elif unit in ("weeks", "week", "w"):
            target = now_utc + timedelta(weeks=qty)
            return target.replace(hour=17, minute=0, second=0, microsecond=0)
        elif unit in ("months", "month", "m"):
            target = now_utc + timedelta(days=qty * 30)
            return target.replace(hour=17, minute=0, second=0, microsecond=0)

    # 5. Days of week: 'monday', 'next monday', 'this friday', etc.
    weekdays = {
        "monday": 0,
        "mon": 0,
        "tuesday": 1,
        "tue": 1,
        "wednesday": 2,
        "wed": 2,
        "thursday": 3,
        "thu": 3,
        "friday": 4,
        "fri": 4,
        "saturday": 5,
        "sat": 5,
        "sunday": 6,
        "sun": 6,
    }
    for name, day_num in weekdays.items():
        if re.search(rf"\b{name}\b", raw):
            current_day = now_utc.weekday()
            days_ahead = (day_num - current_day) % 7
            if days_ahead == 0 or "next" in raw:
                days_ahead += 7
            target = now_utc + timedelta(days=days_ahead)
            h = hour if time_found else 17
            m = minute if time_found else 0
            return target.replace(hour=h, minute=m, second=0, microsecond=0)

    # 6. Month Day: 'apr 15', '15 apr', 'december 31', 'may 5th'
    months = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    # Pattern: (Month) (Day) or (Day) (Month)
    m_match = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?",
        raw,
    )
    if not m_match:
        m_match = re.search(
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+(\d{4}))?",
            raw,
        )
        if m_match:
            d_str, m_name, y_str = m_match.groups()
        else:
            m_name, d_str, y_str = None, None, None
    else:
        m_name, d_str, y_str = m_match.groups()

    if m_name and d_str:
        month = months[m_name]
        day = int(d_str)
        year = int(y_str) if y_str else now_utc.year
        try:
            dt = datetime(year, month, day, hour if time_found else 17, minute if time_found else 0, tzinfo=UTC)
            if not y_str and dt < now_utc:
                dt = dt.replace(year=year + 1)
            return dt
        except ValueError:
            pass

    return None


def get_due_date_from_preset(preset_key: str, base_time: datetime | None = None) -> tuple[datetime | None, bool]:
    """Returns (calculated_datetime, is_clear) for a given preset key."""
    now = (base_time or datetime.now(UTC)).astimezone(UTC)
    eod = now.replace(hour=17, minute=0, second=0, microsecond=0)

    if preset_key == "clear":
        return None, True
    elif preset_key == "today":
        return eod, False
    elif preset_key == "tomorrow":
        return eod + timedelta(days=1), False
    elif preset_key == "2days":
        return eod + timedelta(days=2), False
    elif preset_key == "3days":
        return eod + timedelta(days=3), False
    elif preset_key == "1week":
        return eod + timedelta(weeks=1), False
    elif preset_key == "2weeks":
        return eod + timedelta(weeks=2), False
    elif preset_key == "1month":
        return eod + timedelta(days=30), False

    # Fallback to natural parsing
    parsed = parse_natural_date(preset_key, base_time=now)
    return parsed, parsed is None
