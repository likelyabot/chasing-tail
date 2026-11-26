"""Rule-based recommendation engine.

Inputs: water slug, date (month), optional target species, optional live
weather snapshot (Open-Meteo hourly, °F/mph units — converted at the source),
USGS gauge bundle.
Outputs: ranked species suggestions with tactics mapped to owned tackle,
weather modifiers, the kayak safety gate, and the dossier-sourced context
blocks (regs, stocking, winter targeting, standing reminders, static water
context).

Deterministic and seeded — no ML, no external calls here. All knowledge is
static and sourced (app/knowledge.py — every entry traces to the
research-scout dossiers, 2026-11-23).
"""
import logging
from datetime import date, datetime

from ..knowledge import (
    KAYAK_RULES,
    MONTHS,
    REGS,
    REGS_BOOKLET,
    REMINDERS,
    SPECIES_BY_WATER_MONTH,
    STOCKING,
    TACTICS,
    WATER_CONTEXT,
    WATER_TACTICS,
    WINTER_MONTHS,
    WINTER_TARGETING,
)

log = logging.getLogger(__name__)

SCORE_LABELS = {3: "prime", 2: "good", 1: "fair", 0: "poor"}

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _month(date_str: str | None) -> int:
    """Month (1-12) from an ISO date. Router rejects bad dates with 422;
    this is a safe fallback (falls back to today's month, never raises)."""
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").month
        except ValueError:
            pass
    return date.today().month


def _weekday(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        return WEEKDAY_NAMES[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    except ValueError:
        return None


def _finite(seq: list) -> list[float]:
    """Numeric, non-null entries only (Open-Meteo emits nulls for missing hours)."""
    out = []
    for v in seq or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == f:  # not NaN
            out.append(f)
    return out


def _avg(vals: list[float]) -> float | None:
    """Mean of ACTUAL samples (divides by real count, not a fixed window)."""
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _wind_band(mph: float | None) -> str:
    if mph is None:
        return "unknown"
    if mph < 8:
        return "calm"
    if mph < 12:
        return "moderate"
    if mph < 18:
        return "rough"
    return "severe"


def _gauge_delta(usgs: dict | None) -> float | None:
    """Stage delta (ft) from the primary/stage gauge of a gauge bundle, if
    a trend series was available. Old single-gauge payloads (stage_delta_ft)
    are honoured too."""
    if not usgs:
        return None
    if isinstance(usgs.get("stage_delta_ft"), (int, float)):
        return usgs["stage_delta_ft"]
    for g in usgs.get("gauges", []):
        if g.get("role") in ("primary", "stage") and g.get("delta_ft_7d") is not None:
            return g["delta_ft_7d"]
    return None


def weather_modifiers(wx: dict | None, usgs: dict | None,
                      usgs_live: dict | None = None) -> list[str]:
    """Translate numeric weather into fishing advice. wx = open_meteo payload
    (hourly, °F/mph). Defensive: nulls are filtered, averages divide by the
    actual sample count, missing sources simply contribute no notes.

    usgs_live = the NEW USGS IV headline block (services.usgs.water_usgs) —
    feeds SOFT notes only (see the soft-modifier block below)."""
    mods: list[str] = []
    if not wx or "hourly" not in wx:
        mods.append("No live weather — using seasonal patterns only.")
        return mods

    h = wx["hourly"]
    temps = _finite(h.get("temperature_2m") or [])
    winds = _finite(h.get("wind_speed_10m") or [])
    gusts = _finite(h.get("wind_gusts_10m") or [])
    precip = _finite(h.get("precipitation_probability") or [])

    # 24h temperature trend (compare next 24h avg vs previous 24h avg)
    if len(temps) >= 48:
        prev_avg = _avg(temps[0:24])
        next_avg = _avg(temps[24:48])
        if prev_avg is not None and next_avg is not None:
            delta = next_avg - prev_avg
            if delta <= -5:
                mods.append(
                    f"Cold front expected (≈{delta:+.0f}°F/24h): pre-front bite surge, "
                    "then a lull — fish slower, smaller lures, and go a bit deeper."
                )
            elif delta >= 5:
                mods.append(
                    f"Warming trend (≈{delta:+.0f}°F/24h): fish shallower and more aggressively."
                )

    # Wind band (peak over next 24h)
    next_winds = winds[0:24]
    peak_wind = max(next_winds) if next_winds else None
    peak_gust = max(gusts[0:24]) if gusts else None
    band = _wind_band(peak_wind)
    if band == "rough":
        mods.append(
            f"Wind picking up (peaks ≈{peak_wind:.0f} mph): cast into the wind, "
            "favor sheltered coves and downwind shores; topwater less effective."
        )
    elif band == "severe":
        mods.append(
            f"Strong wind (peaks ≈{peak_wind:.0f} mph): rough water — focus on "
            "protected bays and structure; consider postponing if boating."
        )
    elif band == "calm":
        mods.append("Calm water — topwater and subtle presentations will work.")

    # Rain
    peak_precip = max(precip[0:24]) if precip else None
    if peak_precip is not None and peak_precip >= 60:
        mods.append(
            f"Rain likely (up to {peak_precip}%): stained water favors darker lures; "
            "the post-rain rise is a bonus window."
        )

    # Reservoir/river level movement (USGS gauge delta)
    d = _gauge_delta(usgs)
    if d is not None:
        if d >= 1.5:
            mods.append(
                f"Water rising (≈{d:+.1f} ft): fish the newly flooded edges — "
                "food is moving with the shoreline."
            )
        elif d <= -1.5:
            mods.append(
                f"Water dropping (≈{d:+.1f} ft): fish deeper structure; "
                "holding fish concentrate near the dam/outlet."
            )

    # ---- SOFT live-condition modifiers (notes only; no gating, no wx_fit) ----
    # Heuristics, deliberately conservative, tuned for the four CA waters:
    #  * Falling barometer: classic pre-frontal feeding cue — informational
    #    only (task: display/light-weight, do NOT weight in wx_fit).
    #  * Sacramento River flow (USGS IV @ Colusa): >=10,000 cfs is flood-
    #    scale (limited access, deep seams only); 5,000–10,000 cfs is
    #    elevated (strike zones shift to edges/hole heads). Winter baseflow
    #    is far below that — no note (avoids noise on 40–600 cfs readings).
    #  * NBB pool stage: baseline 1,875 ft = USACE-reported pool 1,874.95 ft
    #    (2026-11-23, knowledge.WATER_FACTS). Low pool exposes shoreline;
    #    high pool submerges banks.
    pr = (wx or {}).get("pressure") or {}
    if pr.get("trend") == "falling":
        mods.append(
            f"Barometer falling ({pr.get('delta_hpa', 0):+.1f} hPa over "
            f"{pr.get('window_hours', '?')} h) — often coincides with active feeding."
        )
    if usgs_live:
        flow = usgs_live.get("flow_cfs")
        label = usgs_live.get("label") or "River"
        if flow is not None:
            if flow >= 10000:
                mods.append(
                    f"{label} flow high ({flow:,.0f} cfs) — fish deeper seams, "
                    "slower presentations; bank access may be limited."
                )
            elif flow >= 5000:
                mods.append(
                    f"{label} flow elevated ({flow:,.0f} cfs) — strike zones shift; "
                    "focus edges and hole heads."
                )
        stage = usgs_live.get("stage_ft")
        if stage is not None:
            if stage < 1870:
                mods.append(
                    f"NBB pool low ({stage:,.1f} ft, below the ~1,875 ft "
                    "late-autumn baseline) — shoreline access extends; fish "
                    "concentrate in deeper coves."
                )
            elif stage >= 1880:
                mods.append(
                    f"NBB pool high ({stage:,.1f} ft) — banks submerged; shorelines "
                    "less effective, favor boats and deep structure."
                )
    return mods


def kayak_gate(slug: str, wx: dict | None) -> dict:
    """Kayak safety gate. Angler owns a kayak and has never used it.
    Loon Lake is a hard block (NO KAYAK) and carries the road-status check."""
    if slug in KAYAK_RULES["always_no"]:
        return {
            "allowed": False,
            "level": "no",
            "flag": "NO KAYAK",
            "reason": (
                "Loon Lake is a hard block for the kayak: first-time paddler, "
                "6,378 ft elevation, cold clear water, no cell coverage, and "
                "snow-contingent access via Ice House Rd (NF Rd 3). Paddle from "
                "shore or use a motorized boat until you've gained experience "
                "elsewhere. CHECK ROAD STATUS BEFORE DRIVING: "
                "fs.usda.gov/r05/eldorado/alerts — SMUD may not begin plowing "
                "until after 8:00 AM the morning after a fresh snow; wait 24 h "
                "after any large storm (downed trees)."
            ),
        }
    wind = gust = None
    if wx and "hourly" in wx:
        # Source is already mph (wind_speed_unit=mph) — NO km/h->mph factor
        # here: multiplying would loosen the kayak gate by 1.6x.
        winds = _finite(wx["hourly"].get("wind_speed_10m") or [])
        gusts = _finite(wx["hourly"].get("wind_gusts_10m") or [])
        if winds:
            wind = max(winds[0:24])
        if gusts:
            gust = max(gusts[0:24])

    caution = (
        (wind is not None and wind >= KAYAK_RULES["wind_caution_mph"])
        or (gust is not None and gust >= KAYAK_RULES["gust_caution_mph"])
    )
    if caution:
        return {
            "allowed": True,
            "level": "caution",
            "flag": "KAYAK CAUTION",
            "reason": (
                f"Sustained wind ≈{wind if wind is not None else '?'} mph / gusts "
                f"≈{gust if gust is not None else '?'} mph exceeds conservative "
                "limits for a first-time paddler. Stay ashore or use a motorized "
                "boat today."
            ),
        }
    return {
        "allowed": True,
        "level": "ok",
        "flag": "KAYAK OK*",
        "reason": (
            "Conditions are calm enough, but this is a first outing: wear a PFD, "
            "carry a bilge pump, stay close to shore, and don't go solo. "
            "*asterisk = never used before; respect the water."
        ),
    }


def _match_reg_entry(species: str, reg_entries: list[dict]) -> dict | None:
    """Find the regs entry governing a suggested species (token overlap;
    ties go to the earlier entry, which is ordered most-operative-first)."""
    sp_tokens = {t for t in species.lower().replace("/", " ").split() if len(t) > 3}
    best, best_overlap = None, 0
    for r in reg_entries:
        r_tokens = {t for t in r["species"].lower().replace("/", " ").split() if len(t) > 3}
        overlap = len(sp_tokens & r_tokens)
        if overlap > best_overlap:
            best, best_overlap = r, overlap
    return best


def _limits_line(reg_entry: dict | None) -> str | None:
    """Human-readable limits string from a regs entry (None if nothing stated)."""
    if not reg_entry:
        return None
    parts = []
    if reg_entry.get("daily_bag") is not None:
        parts.append(f"{reg_entry['daily_bag']}/day")
    if reg_entry.get("possession") is not None:
        parts.append(f"{reg_entry['possession']} possession")
    if reg_entry.get("size_limit"):
        parts.append(reg_entry["size_limit"])
    if reg_entry.get("conditions"):
        parts.append(reg_entry["conditions"])
    if reg_entry.get("season") and reg_entry["season"] != "all year":
        parts.append(f"season {reg_entry['season']}")
    return "; ".join(parts) if parts else None


def _is_winter_focus(winter: dict | None, species: str) -> bool:
    if not winter:
        return False
    return species.lower().startswith(winter["focus"].lower()[:12])


def recommend(slug: str, date_str: str | None, target_species: str | None,
              wx: dict | None = None, usgs: dict | None = None, *, gear: dict,
              usgs_live: dict | None = None) -> dict:
    """Rank species for a water/month and assemble the full plan.

    `date_str` should be validated by the router (422 on bad input); `_month`
    is a safe fallback regardless. `usgs` is the gauge bundle from
    weather.usgs_gauges() (or an old single-gauge dict). `gear` is the
    user's current tackle list (loaded via db.get_gear by the router) —
    echoed into the plan; tactic strings still cite the original item names
    (v1 behavior), and no lookup into gear is performed, so renamed/removed
    items can never break the engine.
    """
    month = _month(date_str)
    species_map = SPECIES_BY_WATER_MONTH.get(slug, {})
    regs = REGS.get(slug)
    winter = WINTER_TARGETING.get(slug) if month in WINTER_MONTHS else None

    scored = []
    for species, curve in species_map.items():
        season = curve[month - 1]
        # Weather fit: modest bonus when live data is calm/cool and favorable.
        wx_fit = 0
        if wx and "hourly" in wx:
            temps = _finite(wx["hourly"].get("temperature_2m") or [])
            winds = _finite(wx["hourly"].get("wind_speed_10m") or [])
            avg_t = _avg(temps[0:24])
            # Species-vs-weather fit nudges. Thresholds are the original metric
            # criteria expressed in the units the source now provides (°F/mph):
            # 12°C = 53.6°F, 24°C = 75.2°F, 15 km/h = 9.32 mph — behavior unchanged.
            if "trout" in species and avg_t is not None and avg_t <= 53.6:
                wx_fit += 1
            if "bass" in species and avg_t is not None and 53.6 <= avg_t <= 75.2:
                wx_fit += 1
            if winds and max(winds[0:24]) < 9.32 and "trout" in species:
                wx_fit += 1
        score = season * 2 + min(wx_fit, 2)
        # Winter-targeting boost: the dossier's designated focus species for
        # Nov–Feb jumps ahead of curve ties (e.g. Dec chinook on the river,
        # winter trophy spotted bass at NBB, guaranteed fresh trout at Collins).
        if _is_winter_focus(winter, species):
            score += 2
        if target_species and species.lower() == target_species.lower():
            score += 2  # pinned target floats to the top
        scored.append((score, species, season))

    scored.sort(key=lambda t: (-t[0], t[1]))
    top = scored[:3]

    suggestions = []
    for score, species, season in top:
        tac = TACTICS.get(species, {})
        reg_entry = _match_reg_entry(species, regs["species"]) if regs else None
        sugg = {
            "species": species,
            "activity": SCORE_LABELS.get(season, "unknown"),
            "season_score": season,
            "score": score,
            "rod": tac.get("rod"),
            "lures": tac.get("lures", []),
            "lines": tac.get("lines"),
            "tips": list(tac.get("tips", [])),
        }
        # Water-specific dossier notes (spots/techniques) lead the tip list.
        water_tips = WATER_TACTICS.get(slug, {}).get(species, [])
        if water_tips:
            sugg["tips"] = water_tips + sugg["tips"]
        limits = _limits_line(reg_entry)
        if limits:
            sugg["limits"] = limits
            if reg_entry:
                sugg["limits_authority"] = reg_entry.get("authority")
        if _is_winter_focus(winter, species):
            sugg["winter_focus"] = True
        suggestions.append(sugg)

    # If the user pinned a species not in the top 3, guarantee it appears.
    if target_species:
        tl = target_species.lower()
        if not any(s["species"].lower() == tl for s in suggestions):
            match = [s for s in scored if s[1].lower() == tl]
            if match:
                score, species, season = match[0]
                tac = TACTICS.get(species, {})
                reg_entry = _match_reg_entry(species, regs["species"]) if regs else None
                inserted = {
                    "species": species,
                    "activity": SCORE_LABELS.get(season, "absent here"),
                    "season_score": season,
                    "score": score,
                    "rod": tac.get("rod"),
                    "lures": tac.get("lures", []),
                    "lines": tac.get("lines"),
                    "tips": list(tac.get("tips", [])),
                }
                water_tips = WATER_TACTICS.get(slug, {}).get(species, [])
                if water_tips:
                    inserted["tips"] = water_tips + inserted["tips"]
                limits = _limits_line(reg_entry)
                if limits:
                    inserted["limits"] = limits
                    if reg_entry:
                        inserted["limits_authority"] = reg_entry.get("authority")
                if _is_winter_focus(winter, species):
                    inserted["winter_focus"] = True
                suggestions.insert(0, inserted)

    return {
        "water_slug": slug,
        "date": date_str,
        "month": month,
        "month_name": MONTHS[month - 1],
        "weekday": _weekday(date_str),
        "target_species": target_species,
        "suggestions": suggestions,
        "weather_notes": weather_modifiers(wx, usgs, usgs_live),
        "kayak": kayak_gate(slug, wx),
        "gear": gear,
        # Dossier-sourced context blocks (all traceable — see knowledge.py).
        "regs": {**(regs or {}), "booklet": REGS_BOOKLET} if regs else None,
        "stocking": STOCKING.get(slug),
        "winter_targeting": winter,
        "reminders": REMINDERS.get(slug, []),
        "water_context": WATER_CONTEXT.get(slug, []),
        "engine": "rules-v2 (seeded species/activity + weather modifiers + kayak gate + dossier regs/stocking/targeting)",
    }
