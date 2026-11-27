"""Regulations staleness: pure date math over the static REGS seeds.

The regs in app/knowledge.py are a frozen snapshot of the CDFW 2026–2027
booklets (see knowledge.REGS_BOOKLET). CDFW releases annual updates in
July; the annual refresh cron (fires 2027-06-15) bumps REGS_AS_OF + REGS
when the new booklets land. Plans whose seeds are strictly older than
REGS_STALE_AFTER_YEARS carry a warning banner (REGS_STALE_WARNING).

Everything here is driven by the STORED as-of date — there is no flag to
flip — so refreshing the seeds clears the banner automatically.

Pure and stdlib-only: `regs_stamp(today=...)` accepts an injectable date
so the smoke test can exercise the thresholds (including a backdated
fixture) without touching the clock or the network.
"""
from datetime import date

from .. import knowledge


def _add_years(d: date, years: int) -> date:
    """Calendar-year addition (Feb 29 clamps to Feb 28 in non-leap years)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def regs_stamp(today: date | None = None) -> dict:
    """Staleness stamp for the regs seeds (pure; never raises).

    Reads knowledge.REGS_AS_OF at CALL time (not import time) so fixtures
    can backdate the seed by reassigning the module attribute. A corrupt
    or missing as-of date degrades to "not stale, raw value surfaced" —
    a typo must never crash a plan or false-alarm a banner.
    """
    as_of_iso = str(getattr(knowledge, "REGS_AS_OF", "") or "")
    try:
        as_of = date.fromisoformat(as_of_iso)
    except ValueError:
        return {
            "regs_as_of": as_of_iso,
            "regs_booklet": knowledge.REGS_BOOKLET,
            "regs_stale_after": None,
            "regs_age_days": None,
            "regs_stale": False,
            "regs_warning": None,
        }
    today = today or date.today()
    years = int(getattr(knowledge, "REGS_STALE_AFTER_YEARS", 1) or 1)
    stale_after = _add_years(as_of, years)
    stale = today > stale_after  # strictly older than N calendar years
    return {
        "regs_as_of": as_of_iso,
        "regs_booklet": knowledge.REGS_BOOKLET,
        "regs_stale_after": stale_after.isoformat(),
        "regs_age_days": (today - as_of).days,
        "regs_stale": stale,
        "regs_warning": knowledge.REGS_STALE_WARNING if stale else None,
    }
