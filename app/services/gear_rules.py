"""Conditional gear rules: conditions snapshot -> suggested items.

Part of the per-trip briefing (GET /api/trips/<id>/briefing). Given the
water slug and the briefing's ``conditions`` block (as shaped by
app/services/briefing.py), emit a list of ``{"item": ..., "reason": ...}``
entries — every suggestion carries a human-readable reason, per spec.

Design: a small, documented, deterministic rule set. Each rule inspects
ONE condition dimension and fires independently; order of evaluation is
fixed (rain, cold, wind, low reservoir, high flow) so output is stable
for identical input — the smoke test pins the firing behaviour. Adding a
rule = appending one function to RULES.

PURE + stdlib-only (imports knowledge for the kayak thresholds, which is
a data module) — importable from scripts/smoke_test.py without fastapi,
httpx, or a running server.
"""
from ..knowledge import KAYAK_RULES

# --- thresholds (heuristics, documented per task spec) --------------------
#: Fire "rain jacket / dry bags" when the max precip probability in the
#: window reaches this percent (mirrors the alerts module's 50% convention).
RAIN_PROB_PCT = 50
#: Fire "warm layers" when the forecast low is at/below this °F.
COLD_TEMP_F = 45.0
#: Fire the kayak-safety item when peak wind reaches the shared kayak
#: caution threshold (KAYAK_RULES.wind_caution_mph = 10 mph).
WIND_CAUTION_MPH = KAYAK_RULES["wind_caution_mph"]

#: Waters where a LOW RESERVOIR LEVEL triggers "waders / access caution":
#: slug -> normal (full) pool elevation in feet. New Bullards Bar's full
#: pool is 1,900 ft (USACE); late-autumn drawdown puts the lake ~25 ft
#: below, exposing low shorelines (wading access, mudflats, boat-launch
#: changes). Extend by adding a water + its normal pool here.
LOW_RESERVOIR_WATERS = {
    "new-bullards-bar": {"normal_pool_ft": 1900.0},
}

#: Waters where HIGH RIVER FLOW triggers "safety: strong current":
#: slug -> threshold in cfs. Heuristic: the dossier measured 5,820 cfs at
#: Red Bluff as "moderate winter baseflow, fishable, not flooded"; 8,000+
#: cfs is a strong-current regime (harder access, reduced visibility).
HIGH_FLOW_WATERS = {
    "sacramento-river-westport": {"threshold_cfs": 8000.0},
}


def _num(x):
    """Coerce to float; None/junk -> None (rules skip on missing data)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def _view_value(view):
    """Numeric value of a briefing water_level/flow view (or None)."""
    if not isinstance(view, dict):
        return None
    return _num(view.get("value"))


def _rain_item(slug, conds):
    wx = (conds or {}).get("weather") or {}
    prob = _num(wx.get("precip_prob_max_pct"))
    if prob is None or prob < RAIN_PROB_PCT:
        return None
    return {
        "item": "rain jacket / dry bags",
        "reason": f"rain forecast: up to {prob:g}% chance of precipitation in the window",
    }


def _cold_item(slug, conds):
    wx = (conds or {}).get("weather") or {}
    tmin = _num(wx.get("temp_min_f"))
    if tmin is None or tmin > COLD_TEMP_F:
        return None
    return {
        "item": "warm layers",
        "reason": f"cold: low of {tmin:g}°F (at/below the {COLD_TEMP_F:g}°F threshold)",
    }


def _wind_item(slug, conds):
    wx = (conds or {}).get("weather") or {}
    wind = _num(wx.get("wind_peak_mph"))
    if wind is None or wind < WIND_CAUTION_MPH:
        return None
    if slug in KAYAK_RULES["always_no"]:
        # Hard no-kayak water: wind this strong means stand down entirely.
        return {
            "item": "strong wind — consider no-go",
            "reason": (f"{wind:g} mph peak wind at/above the {WIND_CAUTION_MPH:g} mph "
                       f"caution threshold on a no-kayak water — paddling not advised"),
        }
    return {
        "item": "kayak safety (PFD, bilge pump)",
        "reason": f"{wind:g} mph peak wind at/above the {WIND_CAUTION_MPH:g} mph kayak-caution threshold",
    }


def _low_reservoir_item(slug, conds):
    spec = LOW_RESERVOIR_WATERS.get(slug)
    if not spec:
        return None
    stage = _view_value((conds or {}).get("water_level"))
    if stage is None or stage >= spec["normal_pool_ft"]:
        return None
    return {
        "item": "waders / access caution",
        "reason": (f"reservoir at {stage:g} ft — below the "
                   f"{spec['normal_pool_ft']:,.0f} ft normal pool (low shoreline: "
                   f"wading access, exposed flats, shifted boat launches)"),
    }


def _high_flow_item(slug, conds):
    spec = HIGH_FLOW_WATERS.get(slug)
    if not spec:
        return None
    flow = _view_value((conds or {}).get("flow"))
    if flow is None or flow < spec["threshold_cfs"]:
        return None
    return {
        "item": "safety: strong current",
        "reason": (f"river flow {flow:,.0f} cfs at/above the "
                   f"{spec['threshold_cfs']:,.0f} cfs high-flow threshold — "
                   f"strong current, reduced visibility"),
    }


#: Evaluation order is part of the contract (stable output for tests/UI).
RULES = (_rain_item, _cold_item, _wind_item, _low_reservoir_item, _high_flow_item)


def derive_conditional_gear(water_slug: str, conditions: dict | None,
                            kayak: dict | None = None) -> list[dict]:
    """Apply the rule set; return [{"item", "reason"}, ...] (may be empty).

    ``kayak`` (the plan's kayak verdict) is accepted for forward
    compatibility; today's rules key off the water slug + conditions only.
    Never raises on missing/malformed input — a rule simply doesn't fire.
    """
    out = []
    for rule in RULES:
        item = rule(water_slug, conditions)
        if item and item.get("item") and item.get("reason"):
            out.append(item)
    return out
