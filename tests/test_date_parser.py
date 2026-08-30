from datetime import UTC, datetime

from src.utils.date_parser import get_due_date_from_preset, parse_natural_date


def test_parse_natural_date_iso_and_explicit():
    # ISO date
    dt = parse_natural_date("2026-04-15")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 15
    assert dt.hour == 17  # Default workday EOD

    # Date with time
    dt2 = parse_natural_date("2026-04-15 14:30")
    assert dt2 is not None
    assert dt2.hour == 14
    assert dt2.minute == 30


def test_parse_natural_date_relative_offsets():
    base = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    # Today
    today_dt = parse_natural_date("today", base_time=base)
    assert today_dt is not None
    assert today_dt.day == 1
    assert today_dt.hour == 17

    # Tomorrow
    tom_dt = parse_natural_date("tomorrow", base_time=base)
    assert tom_dt is not None
    assert tom_dt.day == 2
    assert tom_dt.hour == 17

    # Tomorrow with time
    tom_time_dt = parse_natural_date("tomorrow 9am", base_time=base)
    assert tom_time_dt is not None
    assert tom_time_dt.day == 2
    assert tom_time_dt.hour == 9

    # In 3 days
    in_3d = parse_natural_date("in 3 days", base_time=base)
    assert in_3d is not None
    assert in_3d.day == 4
    assert in_3d.hour == 17

    # In 2 weeks
    in_2w = parse_natural_date("in 2 weeks", base_time=base)
    assert in_2w is not None
    assert in_2w.day == 15

    # In 2 hours
    in_2h = parse_natural_date("in 2 hours", base_time=base)
    assert in_2h is not None
    assert in_2h.hour == 12


def test_parse_natural_date_month_day():
    base = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    # Apr 15
    apr15 = parse_natural_date("apr 15", base_time=base)
    assert apr15 is not None
    assert apr15.month == 4
    assert apr15.day == 15
    assert apr15.year == 2026

    # Dec 31
    dec31 = parse_natural_date("december 31", base_time=base)
    assert dec31 is not None
    assert dec31.month == 12
    assert dec31.day == 31


def test_parse_natural_date_clear_keywords():
    for kw in ("clear", "none", "remove", "null", "unset"):
        assert parse_natural_date(kw) is None

    assert parse_natural_date("") is None
    assert parse_natural_date(None) is None


def test_get_due_date_from_preset():
    base = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    # Presets
    dt, is_clear = get_due_date_from_preset("today", base_time=base)
    assert not is_clear
    assert dt is not None
    assert dt.day == 1

    dt, is_clear = get_due_date_from_preset("tomorrow", base_time=base)
    assert not is_clear
    assert dt.day == 2

    dt, is_clear = get_due_date_from_preset("3days", base_time=base)
    assert not is_clear
    assert dt.day == 4

    dt, is_clear = get_due_date_from_preset("1week", base_time=base)
    assert not is_clear
    assert dt.day == 8

    dt, is_clear = get_due_date_from_preset("clear", base_time=base)
    assert is_clear
    assert dt is None
