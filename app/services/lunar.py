"""Lunar phase calculation — pure, offline, zero dependencies.

Mean-lunation model: a fixed, almanac-verified new-moon epoch (UTC) plus
the mean synodic month. Accurate enough for angling decisions (phase name,
rough illumination, countdown to the next new/full moon — typically within
a day of the true event); not for astronomy.

Validated against published almanac dates (UTC; timeanddate.com,
nightskytoday.com, earthsky.org, 13cal.net all agree):
  * new moon  2026-11-09 07:02 UTC   <- NEW_MOON_EPOCH
  * full moon 2026-11-24 14:53 UTC   (Beaver Moon)
  * new moon  2026-12-09 00:52 UTC
This model predicts:
  * full moon 2026-11-24 01:24 UTC   (delta 13h29m vs almanac)
  * new moon  2026-12-08 19:46 UTC   (delta 5h06m vs almanac)
Both within the +/-1 day tolerance; the vectors are hardcoded in
scripts/smoke_test.py so a regression in the constants fails the suite.
"""
from datetime import date, datetime, timezone
import math

#: Mean synodic month (new moon -> new moon), in days.
SYNODIC_MONTH_DAYS = 29.53058867

#: Fixed new-moon epoch, UTC — a published almanac instant (see docstring).
NEW_MOON_EPOCH = datetime(2026, 11, 9, 7, 2, tzinfo=timezone.utc)

#: Eight phase names, indexed by eighth of the cycle (0 = new, 4 = full).
PHASE_NAMES = (
    "new moon",
    "waxing crescent",
    "first quarter",
    "waxing gibbous",
    "full moon",
    "waning gibbous",
    "last quarter",
    "waning crescent",
)


def moon_phase(day: date) -> dict:
    """Lunar info for a calendar date, evaluated at 12:00 UTC of that date.

    Pure function (no I/O, no network) — importable and unit-testable
    without the app. Returns::

        {
            "phase": "waxing gibbous",         # one of PHASE_NAMES
            "illumination_pct": 78,            # int, 0-100
            "next_new_moon_in_days": 9,        # int, rounded (0 = that day)
            "next_full_moon_in_days": 2,       # int, rounded (0 = that day)
        }
    """
    t = datetime(day.year, day.month, day.day, 12, 0, tzinfo=timezone.utc)
    age = (t - NEW_MOON_EPOCH).total_seconds() / 86400.0
    age %= SYNODIC_MONTH_DAYS               # days since the last (mean) new moon
    frac = age / SYNODIC_MONTH_DAYS         # 0..1 through the cycle

    # Phase name: eighth of the cycle, buckets centred on the principal
    # phases (new/full at the centres, quarters at the boundaries +/-1/16).
    idx = int(round(frac * 8)) % 8

    # Illumination: cosine law — 0 at new moon, 100 at full moon.
    illum = (1.0 - math.cos(2.0 * math.pi * frac)) / 2.0 * 100.0
    illum = int(max(0, min(100, round(illum))))

    # Countdowns to the next events, rounded to whole days (0 = that day).
    next_new = SYNODIC_MONTH_DAYS - age
    half = SYNODIC_MONTH_DAYS / 2.0
    next_full = half - age if age < half else half + (SYNODIC_MONTH_DAYS - age)

    return {
        "phase": PHASE_NAMES[idx],
        "illumination_pct": illum,
        "next_new_moon_in_days": max(0, int(round(next_new))),
        "next_full_moon_in_days": max(0, int(round(next_full))),
    }
