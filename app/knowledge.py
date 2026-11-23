"""Seeded domain knowledge: waters, species-by-month activity, tactics, gear.

This is the "seeded species-per-water knowledge" the recommendation engine
reads from. Activity scale per month (1..12): 0 = absent/poor, 1 = fair,
2 = good, 3 = prime. Months are 1-indexed (Jan=1).

Sources: CDFW stocking schedules, collinslake.com, USFS/USGS water-year
summaries, and standard NorCal foothill patterns. Tune freely — it's data.
"""

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
SEED_USER = {"name": "Angler", "email": None}

# ---------------------------------------------------------------------------
# Water bodies (static seed — mirrors the waters table)
# ---------------------------------------------------------------------------
WATER_SEEDS = [
    {
        "slug": "collins-lake",
        "name": "Collins Lake",
        "location": "Browns Valley, CA (Yuba Co.; 7530 Collins Lake Rd)",
        "lat": 39.3376,
        "lon": -121.3271,
        "kind": "reservoir",
        "usgs_site": None,
        "notes": "Private 1,600-acre reservoir (Virginia Ranch Dam). Largest "
                 "private trout plant north of Sacramento: 50k+ rainbow in "
                 "spring, incl. 3-8 lb trophy and lightning trout. Day-use fee.",
    },
    {
        "slug": "new-bullards-bar",
        "name": "New Bullards Bar Reservoir",
        "location": "North Yuba River, Yuba/Plumas Co., CA",
        "lat": 39.4599,
        "lon": -121.1553,
        "kind": "reservoir",
        "usgs_site": "11413515",
        "notes": "USFS reservoir on the North Yuba River. Cold-water fishery: "
                 "rainbow + brown trout, bass, white bass, catfish, carp. "
                 "Level tracked via USGS gage 11413515.",
    },
    {
        "slug": "loon-lake",
        "name": "Loon Lake",
        "location": "Crystal Basin, Eldorado NF, El Dorado Co., CA (~6,400 ft)",
        "lat": 38.99,
        "lon": -120.31,
        "kind": "reservoir",
        "usgs_site": None,
        "notes": "High-elevation alpine reservoir (Buck-Loon Tunnel). Rainbow "
                 "trout planted every other week; ice fishing Jan-Mar most "
                 "years. Cold, clear, wind-prone.",
    },
    {
        "slug": "sacramento-river-westport",
        "name": "Sacramento River — Westport Reach",
        "location": "Colusa Co., CA (near Westport)",
        "lat": 39.24,
        "lon": -122.03,
        "kind": "river",
        "usgs_site": None,
        "notes": "Representative nearby stretch of the lower Sacramento "
                 "River. Winter steelhead, summer/fall Chinook, resident "
                 "rainbow, occasional striped bass, catfish.",
    },
]

# ---------------------------------------------------------------------------
# Species activity by month, per water. 0=present-but-poor, 1=fair, 2=good,
# 3=prime. Missing species = not pursued there.
# ---------------------------------------------------------------------------
SPECIES_BY_WATER_MONTH = {
    "collins-lake": {
        "rainbow trout":  [3, 3, 3, 3, 2, 1, 1, 1, 2, 3, 3, 3],
        "largemouth bass": [1, 1, 2, 3, 3, 2, 1, 1, 2, 3, 2, 1],
        "crappie":        [2, 2, 3, 2, 1, 1, 1, 1, 2, 3, 3, 2],
        "bluegill":       [1, 1, 2, 2, 2, 1, 1, 1, 2, 2, 2, 1],
        "channel catfish": [1, 1, 1, 1, 2, 3, 3, 3, 2, 1, 1, 1],
    },
    "new-bullards-bar": {
        "rainbow trout":  [3, 3, 3, 2, 2, 1, 0, 0, 1, 2, 3, 3],
        "brown trout":    [2, 2, 2, 2, 1, 1, 1, 1, 2, 2, 2, 2],
        "largemouth bass": [1, 1, 2, 3, 3, 2, 1, 1, 2, 2, 1, 1],
        "white bass":     [2, 2, 1, 1, 0, 0, 0, 0, 1, 1, 2, 2],
        "channel catfish": [1, 1, 1, 1, 2, 3, 3, 3, 2, 1, 1, 1],
        "carp":           [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    },
    "loon-lake": {
        "rainbow trout":  [3, 3, 3, 2, 2, 2, 1, 1, 2, 3, 3, 3],
        "brown trout":    [1, 1, 1, 1, 2, 2, 2, 2, 2, 1, 1, 1],
        "bluegill":       [0, 0, 0, 1, 1, 2, 2, 2, 1, 1, 0, 0],
        "channel catfish": [0, 0, 0, 0, 1, 2, 2, 2, 1, 0, 0, 0],
    },
    "sacramento-river-westport": {
        "steelhead":      [3, 3, 3, 2, 0, 0, 0, 0, 0, 1, 3, 3],
        "chinook salmon": [0, 0, 0, 0, 0, 1, 3, 3, 3, 2, 0, 0],
        "rainbow trout":  [2, 2, 2, 2, 1, 1, 1, 1, 2, 2, 2, 2],
        "striped bass":   [0, 1, 2, 2, 1, 0, 0, 0, 0, 0, 0, 0],
        "channel catfish": [1, 1, 1, 1, 2, 3, 3, 3, 2, 1, 1, 1],
    },
}

# ---------------------------------------------------------------------------
# Tactics per species, mapped to Angler's actual tackle.
# rod: which of the two rods fits; lures: owned lure families.
# ---------------------------------------------------------------------------
TACTICS = {
    "rainbow trout": {
        "rod": "Dobyns CL693SF + Shimano Sahara 2500J (light spinning)",
        "lures": ["Panther Martin spinner #2-3", "small spoon (silver/gold)",
                   "trout bug / jig", "wacky worm (chartreuse/pink)"],
        "lines": "4-8 lb mono or fluoro; 10-15 lb braid + fluoro leader in rivers",
        "tips": [
            "Winter: fish shallow bays and inflows at dawn/dusk, slow retrieves.",
            "Summer: drop deep — thermocline and structure hold the fish.",
            "Spinners and spoons along ledges; wacky worms fished slow and deep.",
        ],
    },
    "brown trout": {
        "rod": "Dobyns CL693SF + Shimano Sahara 2500J (light spinning)",
        "lures": ["small spoon", "Panther Martin #2", "trout bug / jig"],
        "lines": "4-8 lb fluoro",
        "tips": [
            "Hold near structure and deeper water; spooky — give them space.",
            "Low light and cold fronts trigger strikes.",
        ],
    },
    "largemouth bass": {
        "rod": "Abu Garcia Vendetta (med/fast)",
        "lures": ["Kastmasters crankbait", "wacky worm", "Panther Martin spinnerbait"],
        "lines": "12-20 lb braid + 15 lb fluoro leader",
        "tips": [
            "Spring: crash shallow grass and wood with crankbaits.",
            "Clear water: wacky worms dragged slow along flats.",
            "Bluff banks and brush piles in the evening.",
        ],
    },
    "crappie": {
        "rod": "Dobyns CL693SF + Shimano Sahara 2500J (light spinning)",
        "lures": ["trout bug / small jig tipped with minnow", "tiny spoon"],
        "lines": "4-6 lb mono/fluoro",
        "tips": [
            "Vertical presentations under docks, brush piles, and hula hops.",
            "Early morning and evening in winter; daytime in summer.",
        ],
    },
    "bluegill": {
        "rod": "Dobyns CL693SF + Shimano Sahara 2500J (light spinning)",
        "lures": ["trout bug / small jig", "tiny spoon"],
        "lines": "4-6 lb mono",
        "tips": ["Shallow grass lines and points; spring spawn is the window."],
    },
    "channel catfish": {
        "rod": "Abu Garcia Vendetta (med/fast)",
        "lures": ["Carolina-rig weight (3/8-1/2 oz) + stink bait", "bottom-bounced jig"],
        "lines": "20-30 lb braided or heavy mono",
        "tips": [
            "Warm nights June-August: fish deep points and current seams at night.",
            "Patience — cats move slowly and strike hard.",
        ],
    },
    "white bass": {
        "rod": "Dobyns CL693SF + Shimano Sahara 2500J (light spinning)",
        "lures": ["small spoon", "Panther Martin #2"],
        "lines": "6-10 lb fluoro",
        "tips": ["Schools in cold water — locate them, then work the edge."],
    },
    "carp": {
        "rod": "Abu Garcia Vendetta (med/fast)",
        "lures": ["Carolina-rig weight + dough/bread", "bottom rig"],
        "lines": "15-20 lb mono",
        "tips": ["Shallow edges and weed lines; watch for surface swirls."],
    },
    "steelhead": {
        "rod": "Abu Garcia Vendetta (med/fast)",
        "lures": ["spoon (Cleveland/Willow)", "bottom-bounce / spud rig"],
        "lines": "15-25 lb braid + 25 lb fluoro leader",
        "tips": [
            "Swing spoons across the main channel; pause on the drop-off.",
            "Big water, big swings — read the current seams, not the bank.",
            "December-February is peak; cloudy days and rain help.",
        ],
    },
    "chinook salmon": {
        "rod": "Abu Garcia Vendetta (med/fast)",
        "lures": ["spoon + diver", "fly line / dipsey"],
        "lines": "20-30 lb braid + 30 lb fluoro leader",
        "tips": [
            "Summer/fall run: fish early morning and low light.",
            "Track baitfish; divers and flies at 15-30 ft.",
        ],
    },
    "striped bass": {
        "rod": "Abu Garcia Vendetta (med/fast)",
        "lures": ["spoon", "swim jig"],
        "lines": "20-30 lb braid + 30 lb fluoro leader",
        "tips": ["Follow bait balls and current breaks; February-May window."],
    },
}

# ---------------------------------------------------------------------------
# Owned gear (served by /api/gear; referenced by the recommendation engine).
# ---------------------------------------------------------------------------
GEAR = {
    "rods": [
        {"name": "Dobyns CL693SF", "pairing": "Shimano Sahara 2500J",
         "role": "Light spinning — trout, panfish, finesse"},
        {"name": "Abu Garcia Vendetta", "pairing": "med power / fast action reel",
         "role": "Medium — bass, catfish, river work"},
    ],
    "lures": [
        "Kastmasters crankbaits",
        "Panther Martin spinners",
        "Trout bugs / jigs",
        "Spoons",
        "Carolina-rig weights",
        "Wacky worms",
    ],
      "boats": [],
}

# ---------------------------------------------------------------------------
# Kayak safety gate.
# Angler owns a kayak and has NEVER used it. Conservative thresholds.
# ---------------------------------------------------------------------------
KAYAK_RULES = {
    "always_no": ["loon-lake"],  # high-elevation, cold, wind-prone: hard block
    "wind_caution_mph": 10.0,    # sustained wind at/above -> caution
    "gust_caution_mph": 15.0,    # gusts at/above -> caution
}
