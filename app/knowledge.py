"""Static knowledge base: waters, regs, stocking, targeting, gear.

Every fact in this file is traceable to the research-scout dossiers
(compiled 2026-11-23, kanban task t_b068203a attachments) — see DOSSIERS.
No invented facts: each entry carries its source. Regs are from the
official CDFW 2026 Freshwater Sport Fishing Regulations booklet
(updated 2026-07-10) as summarized in dossier §4 sections.
"""

DOSSIERS = {
    "collins-lake": "collins-lake-dossier.md (research-scout, 2026-11-23)",
    "new-bullards-bar": "new-bullards-bar-dossier.md (research-scout, 2026-11-23)",
    "loon-lake": "loon-lake-dossier.md (research-scout, 2026-11-23)",
    "sacramento-river-westport": "sacramento-river-dossier.md (research-scout, 2026-11-23)",
}

REGS_BOOKLET = (
    "CDFW 2026 Freshwater Sport Fishing Regulations booklet "
    "(nrm.dfg.ca.gov DocID 209090, updated 2026-07-10)"
)

# Machine-readable as-of date for the REGS seeds: the CDFW 2026–2027
# booklets' update date (see REGS_BOOKLET). Bump this (and REGS) when the
# annual CDFW update lands — the annual refresh cron fires 2027-06-15.
# Drives the "Regs as of <date>" stamp and the >12-month staleness banner
# (app/services/regs_meta.py); refreshing the seeds clears the banner
# automatically because it is tied to this date, never a hardcoded flag.
REGS_AS_OF = "2026-07-10"
REGS_STALE_AFTER_YEARS = 1
REGS_STALE_WARNING = (
    "Regulations may be outdated — CDFW releases annual updates in July."
)

# ---------------------------------------------------------------------------
# USGS station registry.
# Official names + coordinates verified 2026-11-23 against
# waterdata.usgs.gov (WDFN) monitoring-location pages and the
# api.waterdata.usgs.gov OGC API (monitoring-locations collection).
# Live-data status as of 2026-11-23 (OGC API latest-continuous/latest-daily):
#   11377100  ACTIVE   (5,790 cfs + 1.39 ft @ 19:45Z)
#   11453000  ACTIVE   (10.01 ft @ 19:30Z)
#   11413515  no recent data (latest daily: storage 648,500 af @ 2025-09-30)
#   11413520  no recent data (latest daily: discharge 6.4 cfs @ 2004-09-30)
#   11453120  DORMANT  (no continuous/daily data types; last field work 1997)
# ---------------------------------------------------------------------------
USGS_STATIONS = {
    "11413515": {
        "name": "New Bullards Bar Reservoir (stage)",
        "official_name": "NEW BULLARDS BAR RES NR NORTH SAN JUAN CA",
        "lat": 39.3927,
        "lon": -121.1413,
    },
    "11413520": {
        "name": "North Yuba River below New Bullards Bar Dam (outflow)",
        "official_name": "N YUBA R BL NEW BULLARDS BAR DAM NR N SAN JUAN CA",
        "lat": 39.3904,
        "lon": -121.1444,
    },
    "11377100": {
        "name": "Sacramento River above Bend Bridge, nr Red Bluff (Tehama Co.)",
        "official_name": "SACRAMENTO R AB BEND BRIDGE NR RED BLUFF CA",
        "lat": 40.288459595017024,
        "lon": -122.1866311823976,
    },
    "11453000": {
        "name": "Yolo Bypass nr Woodland",
        "official_name": "YOLO BYPASS NR WOODLAND CA",
        "lat": 38.67765721007921,
        "lon": -121.64409242511478,
    },
    "11453120": {
        "name": "Yolo Bypass at I-80, nr West Sacramento",
        "official_name": "YOLO BYPASS a I-80 NR W SACRAMENTO CA",
        "lat": 38.5668502922904,
        "lon": -121.615236066253,
    },
}

# Gauge assignments per water (task spec + dossiers):
#   NBB: stage 11413515, outflow 11413520
#   Sacramento River: Red Bluff 11377100 (primary), Yolo Bypass 11453000/11453120
#   Collins: NO gauge on the lake (verified) — 11413520 as labelled regional
#            indicator only
#   Loon: no public gauge (verified) — none
WATER_GAUGES = {
    "collins-lake": [
        {
            "site": "11413520",
            "role": "indicator",
            "label": "Regional indicator ONLY — North Yuba River below New Bullards Bar Dam (NOT the lake; no USGS gauge exists on Collins Lake)",
            "note": "Verified 2026-11-23: no station on the lake (USGS OGC API sweep of Browns Valley area + waterdata.usgs.gov). The howsyourriver.com 'Collins Lake' page is a different 52-acre lake in Sacramento County.",
        },
    ],
    "new-bullards-bar": [
        {"site": "11413515", "role": "stage", "label": "NBB reservoir stage"},
        {"site": "11413520", "role": "outflow", "label": "North Yuba River below NBB Dam (outflow)"},
    ],
    "loon-lake": [],
    "sacramento-river-westport": [
        {
            "site": "11377100",
            "role": "primary",
            "label": "Sacramento River above Bend Bridge, nr Red Bluff (Tehama Co.) — primary river gauge",
        },
        {"site": "11453000", "role": "secondary", "label": "Yolo Bypass nr Woodland"},
        {
            "site": "11453120",
            "role": "secondary",
            "label": "Yolo Bypass at I-80, nr West Sacramento",
            "note": "Station dormant: no continuous/daily data types (last field work 1997) — verified 2026-11-23 via USGS WDFN + OGC API.",
        },
    ],
}

WATER_SEEDS = [
    {
        "slug": "collins-lake",
        "name": "Collins Lake (Merle Collins / Virginia Ranch Reservoir)",
        "location": "Browns Valley, Yuba County, CA",
        "lat": 39.341,
        "lon": -121.312,
        "kind": "lake",
        "usgs_site": None,
        # Map footprint (task t_3e3437bb): ~975-ac lake → ~0.7 km radius circle.
        "radius_km": 0.7,
        "extent": None,
        "notes": (
            "Impounded by Virginia Ranch Dam on French Dry Creek; owned/operated for "
            "irrigation by Browns Valley Irrigation District (57,000 AF, 975 ac at full); "
            "recreation side run by the Collins family (collinslake.com). "
            "NO USGS gauge on the lake (verified 2026-11-23) — nearest public gauge "
            "11413520 shown as regional indicator only. Marker re-seeded on the "
            "reservoir (Yuba Co.; the old seed sat ~25 km NW in Sierra Co.) — "
            "verified against satellite 2026-11-27. Source: collins-lake-dossier.md §1."
        ),
    },
    {
        "slug": "new-bullards-bar",
        "name": "New Bullards Bar Reservoir",
        "location": "Yuba County, CA (North Yuba River, ~12 mi S of Marysville)",
        "lat": 39.46,
        "lon": -121.16,
        "kind": "lake",
        "usgs_site": "11413515",
        # Large highway reservoir (~10 mi long, dam at the SE end) — a 1 km
        # circle would read as a pond; 3 km covers the main central basin.
        "radius_km": 3.0,
        "extent": None,
        "notes": (
            "Highway-access reservoir on the North Yuba; open year-round, no seasonal "
            "closures. Emerald Cove Marina (south end): launch, fuel, tackle, rentals. "
            "Kokanee is the flagship fishery (naturally reproducing). "
            "Gauges: 11413515 (stage) + 11413520 (outflow). "
            "Source: new-bullards-bar-dossier.md §1–§2."
        ),
    },
    {
        "slug": "loon-lake",
        "name": "Loon Lake",
        "location": "Crystal Basin, Eldorado NF (El Dorado County), CA",
        "lat": 38.9998,
        "lon": -120.3062,
        "kind": "lake",
        "usgs_site": None,
        # Small alpine reservoir (988 ac) → tight 0.5 km footprint.
        "radius_km": 0.5,
        "extent": None,
        "notes": (
            "SMUD-managed reservoir in the Crystal Basin watershed; 988 acres, elevation "
            "6,378 ft; one of three Crystal Basin lakes (with Union Valley and Ice House); "
            "deep, clear and cold. No public USGS gauge (verified 2026-11-23). "
            "NO CDFW stocking in the past 13 months (Oct 2025–Nov 2026) — the 'biweekly "
            "May–August' claim (davessierrafishing.com) is unverified/stale and is NOT "
            "seeded. Access via Ice House Rd (NF Rd 3): SMUD plowing may not begin until "
            "after 8:00 AM the morning after a fresh snow; wait 24 h after large storms "
            "(ebsp.org). Marker re-seeded on Loon Lake itself (OSM way/36939697; "
            "the old seed sat on Union Valley Reservoir, ~13 km SW) — verified "
            "against satellite 2026-11-27. Source: loon-lake-dossier.md §1–§3."
        ),
    },
    {
        "slug": "sacramento-river-westport",
        "name": "Sacramento River — Red Bluff→Colusa Reach",
        "location": "Red Bluff → Colusa, Tehama/Colusa Co., CA — Sec. 7.40(80) legal zone: Deschutes Rd Br (Anderson) → Woodson Br (Corning)",
        # Marker sits ON the channel at the arc midpoint of the full
        # Red Bluff→Colusa reach. Prior seeds: (39.23, -121.85) was ~13 km
        # EAST of the river; (40.177, -122.2294) sat just above Red Bluff.
        "lat": 39.6805,
        "lon": -121.96315,
        "kind": "river",
        "usgs_site": "11377100",
        # River REACH, not a point: the NAMED reach runs Red Bluff → Colusa
        # (~105 km straight-line; ~154.1 km of meandering channel). The
        # 2026 LEGAL fishable zone (Sec. 7.40(80) Deschutes Rd Br → Woodson Br)
        # is only the northern portion, ending ~39.910 — the footprint shows
        # the full named reach; the legal sub-zone is its northern segment.
        # extent.path is the OSM "Sacramento River" channel re-traced for the
        # full reach (verified 2026-11-27: endpoints snap to the channel at
        # Red Bluff and Colusa; ribbon hugs the water on satellite). Same line
        # the OSM basemap draws, so the ribbon matches the map; vs satellite
        # it can sit on a bank (<= half channel width, ~200 m). Frontend
        # renders it as a translucent ribbon; without path it falls back to a
        # chord ellipse between a/b (~1.5 km wide channel).
        "radius_km": None,
        "extent": {
            "a": [40.15414, -122.20576],  # river at Red Bluff (NW end)
            "b": [39.21641, -122.01031],  # river at Colusa (SE end)
            "width_km": 1.5,
            "path": [
                [40.15414, -122.20576], [40.15287, -122.19586], [40.15389, -122.18926], [40.15467, -122.18311], [40.15334, -122.17868], [40.14635, -122.17024],
                [40.14516, -122.16217], [40.1467, -122.15563], [40.14248, -122.1464], [40.13729, -122.14287], [40.13349, -122.14071], [40.12356, -122.1388],
                [40.11332, -122.1344], [40.10856, -122.13773], [40.10534, -122.13967], [40.10245, -122.13838], [40.09989, -122.13156], [40.09639, -122.12968],
                [40.09079, -122.12804], [40.08689, -122.12461], [40.0835, -122.11705], [40.08057, -122.11574], [40.07643, -122.12161], [40.07361, -122.12519],
                [40.07011, -122.12544], [40.06711, -122.12244], [40.0657, -122.11415], [40.06128, -122.11171], [40.05699, -122.11003], [40.0525, -122.11097],
                [40.04908, -122.11316], [40.04245, -122.11482], [40.03698, -122.11767], [40.02431, -122.1193], [40.01568, -122.11606], [40.00776, -122.10653],
                [39.99973, -122.10897], [39.99617, -122.11056], [39.99322, -122.11042], [39.99138, -122.10448], [39.99177, -122.0973], [39.98824, -122.09452],
                [39.98014, -122.09348], [39.96885, -122.09362], [39.96126, -122.09054], [39.95685, -122.0799], [39.95099, -122.07669], [39.94562, -122.07709],
                [39.94249, -122.08035], [39.94015, -122.08711], [39.93569, -122.0912], [39.93035, -122.0953], [39.92685, -122.09349], [39.92277, -122.08531],
                [39.91827, -122.08667], [39.91539, -122.08886], [39.9116, -122.09251], [39.90591, -122.08692], [39.90218, -122.07651], [39.89978, -122.07111],
                [39.89428, -122.06521], [39.89011, -122.06286], [39.88669, -122.06293], [39.88344, -122.06418], [39.87815, -122.06774], [39.87536, -122.06737],
                [39.87459, -122.06027], [39.87528, -122.04969], [39.87447, -122.04595], [39.87172, -122.04494], [39.86822, -122.04724], [39.86299, -122.05668],
                [39.85849, -122.06017], [39.8541, -122.06211], [39.85087, -122.0615], [39.84807, -122.05943], [39.84438, -122.06152], [39.8422, -122.06507],
                [39.8398, -122.06781], [39.83638, -122.06871], [39.83355, -122.06737], [39.8308, -122.06458], [39.82807, -122.06165], [39.82704, -122.05546],
                [39.82579, -122.05331], [39.82237, -122.05346], [39.81911, -122.05642], [39.81824, -122.05985], [39.81698, -122.06183], [39.81465, -122.06446],
                [39.81265, -122.06571], [39.80331, -122.05308], [39.79536, -122.04534], [39.79193, -122.03821], [39.78635, -122.02954], [39.7784, -122.02839],
                [39.77109, -122.02894], [39.76509, -122.02748], [39.76291, -122.02151], [39.76142, -122.01686], [39.75883, -122.0088], [39.75481, -122.00143],
                [39.74932, -121.99408], [39.74531, -121.98834], [39.7378, -121.98519], [39.73305, -121.98115], [39.73165, -121.97656], [39.73213, -121.97054],
                [39.7347, -121.96357], [39.73621, -121.95973], [39.73248, -121.95664], [39.73111, -121.95398], [39.72875, -121.95168], [39.72631, -121.95265],
                [39.72285, -121.95486], [39.71945, -121.95386], [39.717, -121.952], [39.71513, -121.94864], [39.71126, -121.94516], [39.70732, -121.94438],
                [39.70245, -121.94353], [39.69903, -121.94353], [39.69658, -121.94254], [39.69212, -121.94221], [39.68816, -121.94367], [39.68585, -121.94741],
                [39.68628, -121.95248], [39.68747, -121.95696], [39.68601, -121.96108], [39.68361, -121.96333], [39.68066, -121.96322], [39.67631, -121.96196],
                [39.67374, -121.96316], [39.674, -121.9681], [39.67583, -121.97346], [39.6751, -121.98116], [39.66972, -121.98783], [39.66985, -121.99636],
                [39.66476, -121.99909], [39.66085, -121.99594], [39.65961, -121.98711], [39.65888, -121.98117], [39.66351, -121.97329], [39.66253, -121.96888],
                [39.65737, -121.96823], [39.65151, -121.96934], [39.64689, -121.97199], [39.6485, -121.97858], [39.6483, -121.988], [39.64418, -121.99012],
                [39.6398, -121.98698], [39.63697, -121.98492], [39.63495, -121.9895], [39.63276, -121.99285], [39.62966, -121.99341], [39.62656, -121.99061],
                [39.62209, -121.9879], [39.61769, -121.97999], [39.61498, -121.97579], [39.61031, -121.97732], [39.60775, -121.98334], [39.60842, -121.9914],
                [39.60071, -121.99724], [39.59539, -121.99755], [39.59204, -121.99835], [39.58748, -121.99589], [39.58299, -121.99673], [39.57845, -121.9987],
                [39.57427, -121.999], [39.56875, -122.00271], [39.56505, -122.00049], [39.56321, -121.99224], [39.56027, -121.98899], [39.55712, -121.9933],
                [39.55747, -121.99988], [39.5534, -122.00186], [39.54265, -121.99775], [39.53457, -121.99447], [39.52882, -121.99242], [39.52078, -122.00594],
                [39.51628, -122.00847], [39.50994, -122.00231], [39.50798, -121.99765], [39.50861, -121.99135], [39.50742, -121.98555], [39.5044, -121.98577],
                [39.49878, -121.98817], [39.49645, -121.99127], [39.49741, -121.99984], [39.49523, -122.00494], [39.49088, -122.00513], [39.48497, -121.9962],
                [39.48118, -121.99443], [39.47377, -121.99721], [39.46735, -121.9959], [39.46291, -121.99368], [39.4519, -121.9951], [39.44116, -121.9958],
                [39.4354, -122.00347], [39.42844, -122.00445], [39.42661, -121.9985], [39.42196, -121.99714], [39.42004, -122.00275], [39.41942, -122.00852],
                [39.41107, -122.00846], [39.40131, -122.00545], [39.39641, -122.00292], [39.3914, -122.00481], [39.38727, -122.01044], [39.38235, -122.01127],
                [39.379, -122.00813], [39.37485, -122.00871], [39.36962, -122.01108], [39.36495, -122.01307], [39.358, -122.01339], [39.35133, -122.01533],
                [39.34911, -122.02072], [39.34883, -122.02779], [39.34393, -122.03085], [39.33776, -122.03079], [39.33181, -122.02915], [39.32365, -122.0277],
                [39.31655, -122.02708], [39.31178, -122.02332], [39.30617, -122.03025], [39.29972, -122.02917], [39.29872, -122.021], [39.29785, -122.01567],
                [39.2924, -122.01441], [39.28443, -122.01595], [39.27008, -122.02212], [39.26566, -122.01765], [39.26816, -122.01206], [39.27197, -122.00483],
                [39.26711, -122.00057], [39.26249, -122.00065], [39.25656, -122.00816], [39.2515, -122.00626], [39.24618, -122.00061], [39.24277, -121.99742],
                [39.2378, -121.99983], [39.23519, -122.00174], [39.23186, -121.9981], [39.22935, -122.00174], [39.22832, -122.00648], [39.22422, -122.00708],
                [39.21965, -122.01045], [39.21641, -122.01031],
            ]
        },
        "notes": (
            "Named reach: Red Bluff → Colusa (~105 km straight-line; ~154 km of "
            "channel). Fishable zone per 2026 regs: Sec. 7.40(80) Deschutes Rd Br → "
            "Woodson Br — the northern portion of the reach (ending ~39.910) — the "
            "ONLY legal mid-December salmon harvest of the four waters (chinook, "
            "Nov 1–Dec 31). Gauges: 11377100 (primary, Red Bluff area), 11453000 + "
            "11453120 (Yolo Bypass). Keswick→650 ft is CLOSED all year. Footprint "
            "shows the full named reach; the legal sub-zone is its northern segment. "
            "Channel re-traced from OSM Red Bluff→Colusa and verified against "
            "satellite 2026-11-27 (the prior extent stopped ~75 km short of Colusa). "
            "Source: sacramento-river-dossier.md §4–§5."
        ),
    },
]

# ---------------------------------------------------------------------------
# Regulations — per water, from dossier §4 (2026 CDFW booklet, updated 2026-07-10).
# daily_bag/possession are ints (0 = closed); None = not specified in dossier.
# ---------------------------------------------------------------------------
REGS = {
    "collins-lake": {
        "zone": None,
        "species": [
            {
                "species": "inland trout (rainbow/brown)",
                "season": "all year",
                "daily_bag": 5,
                "possession": 10,
                "size_limit": "none",
                "authority": "T14 CCR §5.85(a)(1)",
            },
            {
                "species": "black bass (largemouth/spotted)",
                "season": "all year",
                "daily_bag": 5,
                "possession": None,
                "size_limit": "12 in min total length",
                "authority": "T14 CCR §5.00(a)(1)",
            },
        ],
        "special_regs": "None for Collins Lake — only booklet mention is an OEHHA health-advisory reference (p. 5952).",
        "license": "Standard CA freshwater license (16+); trout license not required for inland trout in CA.",
        "health_advisory": "OEHHA advisory exists — check oehha.ca.gov/advisories/collins-lake for consumption guidance.",
    },
    "loon-lake": {
        "zone": None,
        "species": [
            {
                "species": "inland trout (rainbow/brown)",
                "season": "all year",
                "daily_bag": 5,
                "possession": 10,
                "size_limit": "none",
                "authority": "T14 CCR §5.85(a)(1)",
            },
            {
                "species": "kokanee (if present)",
                "season": "all year",
                "daily_bag": 5,
                "possession": 10,
                "size_limit": "none",
                "authority": "T14 CCR §5.41 statewide landlocked-salmon rule — Loon Lake is NOT on the 10/20 exception list",
            },
            {
                "species": "black bass (largemouth/spotted)",
                "season": "all year",
                "daily_bag": 5,
                "possession": None,
                "size_limit": "12 in min total length",
                "authority": "T14 CCR §5.00(a)(1) — statewide black bass rule (per task regs table, Collins/Loon alike)",
            },
        ],
        "special_regs": "None for Loon Lake (verified by full-text search of the 2026 booklet).",
        "license": "Standard CA freshwater license (16+).",
        "health_advisory": None,
    },
    "new-bullards-bar": {
        "zone": None,
        "species": [
            {
                "species": "kokanee (landlocked salmon)",
                "season": "all year",
                "daily_bag": 10,
                "possession": 20,
                "size_limit": "none",
                "authority": "T14 CCR §5.41 — NBB EXCEPTION (statewide default 5/day, 10 possession; shared with Bucks, Pardee, Trinity lakes)",
            },
            {
                "species": "black bass (incl. spotted)",
                "season": "all year",
                "daily_bag": 5,
                "possession": None,
                "size_limit": "12 in min total length",
                "authority": "T14 CCR §5.00(a)(1); NBB is not a specially-listed bass water (verified: no other NBB entries in booklet special regs)",
            },
            {
                "species": "inland trout",
                "season": "all year",
                "daily_bag": 5,
                "possession": 10,
                "size_limit": "none",
                "authority": "T14 CCR §5.85(a)(1)",
            },
        ],
        "special_regs": "Kokanee 10/20 exception only. Note: outboundcalifornia.com's 'kokanee counted under the trout/salmon limit' is INCORRECT per the official booklet — the NBB exception governs.",
        "license": "Standard CA freshwater license (16+).",
        "health_advisory": "OEHHA advisory exists — check oehha.ca.gov/advisories/new-bullards-bar-reservoir (booklet p. 5955).",
    },
    "sacramento-river-westport": {
        "zone": "Sec. 7.40(80): Deschutes Rd Bridge → Woodson Bridge (Red Bluff → Colusa)",
        "species": [
            {
                "species": "chinook salmon",
                "season": "Nov 1 – Dec 31",
                "daily_bag": 2,
                "possession": 4,
                "size_limit": None,
                "authority": "Sec. 7.40(80)",
            },
            {
                "species": "hatchery steelhead",
                "season": "all year",
                "daily_bag": 2,
                "possession": 4,
                "size_limit": None,
                "conditions": "CLIPPED-FINNED fish only (wild steelhead = release); FG 682 Steelhead Fishing Report & Restoration Card required",
                "authority": "Sec. 7.40(80) zone C + §5.88, per sacramento-river-dossier.md §4",
            },
            {
                "species": "brown trout",
                "season": "all year",
                "daily_bag": 5,
                "possession": 10,
                "size_limit": None,
                "authority": "Sec. 7.40(80) zone C, per sacramento-river-dossier.md §4",
            },
            {
                "species": "all fishing (Keswick Dam → 650 ft below dam)",
                "season": "CLOSED all year",
                "daily_bag": 0,
                "possession": 0,
                "size_limit": None,
                "conditions": "CLOSED TO ALL FISHING ALL YEAR — the immediate Oroville reach is off-limits",
                "authority": "Sec. 7.40(80)(A), per sacramento-river-dossier.md §4",
            },
            {
                "species": "sturgeon",
                "season": "all year",
                "daily_bag": 0,
                "possession": 0,
                "size_limit": None,
                "conditions": "Catch & release only; report card required",
                "authority": "2026 booklet, per sacramento-river-dossier.md §4",
            },
        ],
        "special_regs": "River-zone rules (Sec. 7.40(80)). The Red Bluff→Colusa stretch is the ONLY legal mid-December salmon harvest of the four waters.",
        "license": None,
        "health_advisory": None,
    },
}

# ---------------------------------------------------------------------------
# Stocking knowledge (dossier §3 sections).
# ---------------------------------------------------------------------------
STOCKING = {
    "collins-lake": {
        "programs": [
            {
                "program": "Private — Collins Lake operator (dominant winter program)",
                "detail": (
                    "Weekly trout plants Oct–winter at 1,000–2,000 lb/week; 7,000 lb "
                    "stocked since Oct 2026; '50,000+ trout stocked every spring'. "
                    "Recent plants: Nov 2 (2,000 lb), Nov 9 (2,000 lb), Nov 16 (1,000 lb), "
                    "Nov 23 (2,000 lb incl. 'Lightning trout' and trophy rainbows). "
                    "Expect continued weekly plants through December (upcoming dates not yet posted)."
                ),
                "source": "collinslake.com (retrieved 2026-11-23)",
            },
            {
                "program": "CDFW public planting",
                "detail": (
                    "Winter/spring cycle (≈Nov–Mar). 2025-26: 6 plants — Nov 2025 (×1), "
                    "Feb 2026 (×3), Mar 2026 (×2); most recent week of Feb 22, 2026. "
                    "A December CDFW plant is plausible but unverified."
                ),
                "source": "nrm.dfg.ca.gov/fishplants/publicplantsearch + stockedwaters.app mirror (CDFW-sourced)",
            },
        ],
        "advice": (
            "Assume fresh private-stock trout every week in winter; treat any CDFW plant "
            "as bonus. PLAN ARRIVAL NEAR A STOCKING WEEKEND — schedule is posted on "
            "collinslake.com. Freshly stocked fish are easiest in the first 1–2 weeks after each plant."
        ),
    },
    "loon-lake": {
        "programs": [],
        "advice": (
            "NO CDFW stocking of Loon Lake in the past 13 months (Oct 2025–Nov 2026) — "
            "Loon Lake is absent from the 13 El Dorado County waters on the CDFW-sourced "
            "mirror. The 'biweekly May–August' claim (davessierrafishing.com) is "
            "UNVERIFIED/likely stale and is deliberately NOT seeded. Any December trout "
            "are residual (survivors from earlier plants) or resident — plan expectations accordingly."
        ),
        "source": "troutstockingreport.com El Dorado County page (updated 2026-11-23, CDFW-sourced); conflict vs davessierrafishing.com noted in dossier §3",
    },
    "new-bullards-bar": {
        "programs": [
            {
                "program": "Kokanee",
                "detail": "Naturally reproducing population — no planting required (the reservoir's flagship fishery).",
                "source": "new-bullards-bar-dossier.md §3",
            },
            {
                "program": "Rainbow trout (CDFW)",
                "detail": (
                    "Planted annually per secondary source ('Eagle Lake Rainbow trout are "
                    "planted in the lake every year'); exact 2026-27 dates not captured — "
                    "check nrm.dfg.ca.gov/fishplants/publicplantsearch."
                ),
                "source": "californiasgreatestlakes.com (medium confidence)",
            },
        ],
        "advice": "Fall kokanee run winds down through December; season is all-year, so silvering adults remain catchable in coves/inlets — fewer fish than Sept–Nov but still legal and present.",
    },
    "sacramento-river-westport": {
        "programs": [],
        "advice": "River fishery — no stocking program. Seasons/limits governed by Sec. 7.40(80) (see regs).",
    },
}

# ---------------------------------------------------------------------------
# Mid-December / winter targeting logic (dossier §5 sections), Nov–Feb.
# ---------------------------------------------------------------------------
WINTER_MONTHS = {11, 12, 1, 2}

WINTER_TARGETING = {
    "sacramento-river-westport": {
        "focus": "chinook salmon",
        "why": (
            "The ONLY legal mid-December salmon harvest of the four waters — Sec. 7.40(80) "
            "Red Bluff→Colusa stretch, open Nov 1–Dec 31 (2/day, 4 possession). A December "
            "trip here should target chinook."
        ),
    },
    "new-bullards-bar": {
        "focus": "spotted bass",
        "why": (
            "Winter trophy spotted-bass water — both IGFA all-tackle world records were "
            "caught here in winter: 10 lb 6 oz (January 2015) and 11 lb 4 oz (February 12, 2017). "
            "Cold, clear water pushes big spotted into deep structure and creek mouths; slow presentations."
        ),
        "source": "bullardsbar.com/bullards-bar-spotted-bass (operator-affiliated; medium confidence)",
    },
    "collins-lake": {
        "focus": "rainbow trout",
        "why": (
            "Guaranteed weekly fresh private stocking all winter (1,000–2,000 lb/week) — "
            "the only water of the four with a guaranteed weekly winter stocking program. "
            "61 °F water (Nov 16 reading) is cool but not shutdown-cold; clear water favors presentation."
        ),
    },
    "loon-lake": {
        "focus": "CONDITIONAL — residual trout / kokanee",
        "why": (
            "Access is the binding constraint, not fish: 6,378 ft elevation, 3–8 ft winter "
            "snow at lower elevations, SMUD plowing lag. If the road is open after a quiet "
            "spell: residual stocked trout in deeper, cooler water; winter kokanee school up. "
            "Rank behind Collins (guaranteed fresh trout) and NBB (trophy bass) unless the "
            "road is confirmed open and you want a wilderness-style day."
        ),
    },
}

# ---------------------------------------------------------------------------
# Standing reminders — always shown for the water (every trip, any month).
# ---------------------------------------------------------------------------
REMINDERS = {
    "loon-lake": [
        (
            "ROAD STATUS — CHECK BEFORE DRIVING: Ice House Rd (NF Rd 3) at "
            "fs.usda.gov/r05/eldorado/alerts (and /conditions/road-and-trail-status). "
            "SMUD may not begin plowing until after 8:00 AM the morning after a fresh "
            "snow, and conditions permit; wait 24 h after any large storm (downed trees); "
            "no 'through' section of Ice House Road in winter (ebsp.org). Status was "
            "UNVERIFIED at dossier compile time (fs.usda.gov bot-blocked) — re-check."
        ),
        "Winter logistics: carry shovel, extra fuel/food/water, layers; no cell coverage deep in the basin (ebsp.org).",
    ],
    "collins-lake": [
        "Winter gate & store hours (mid-Aug → Memorial Day): Sun–Thu 6:30 AM–6:00 PM, Fri–Sat 6:30 AM–8:00 PM (collinslake.com). Dawn-to-dusk hours compress the day.",
        "Invasive-mussel prevention: dry, inspect, clean when moving between waterways (collinslake.com).",
    ],
    "new-bullards-bar": [],
    "sacramento-river-westport": [
        "Stay inside the Sec. 7.40(80) zone: Deschutes Rd Bridge → Woodson Bridge (Red Bluff → Colusa). Chinook season is Nov 1–Dec 31 only — after Dec 31 the stretch is closed for salmon.",
    ],
}

# ---------------------------------------------------------------------------
# Static water-context facts (operator status boards / agency pages) —
# point-in-time, with as_of + source. Shown in the plan panel.
# ---------------------------------------------------------------------------
WATER_CONTEXT = {
    "collins-lake": [
        {"fact": "Lake level 36 ft below full pond", "as_of": "2026-11-16", "source": "collinslake.com status board"},
        {"fact": "Water temp 61.3 °F, clarity clear", "as_of": "2026-11-16", "source": "collinslake.com status board"},
        {"fact": "Declining/low trend: 36 ft below full in mid-Nov is a low-to-moderate winter pool; expect stable or slowly falling levels in December absent rainfall (interpretation)", "as_of": "2026-11-23", "source": "collins-lake-dossier.md §1"},
    ],
    "new-bullards-bar": [
        {"fact": "USACE-reported pool elevation 1,874.95 ft, −0.23 ft over prior 24 h (late-autumn drawdown; expect low, stable winter levels)", "as_of": "~2026-11-23 (snippet date unverified)", "source": "water.usace.army.mil NBB location page (via search snippet)"},
        {"fact": "CA DWR CDEC project BUL (cdec.water.ca.gov/river/res_BUL.html) has stage plots + scheduled release (graphics-only page)", "as_of": "2026-11-23", "source": "new-bullards-bar-dossier.md §1"},
    ],
    "loon-lake": [
        {"fact": "Unmonitored by public gauges — ask SMUD or check on arrival", "as_of": "2026-11-23", "source": "loon-lake-dossier.md §1"},
        {"fact": "Crystal Basin receives 3–8 ft of snow at lower elevations — mid-December driving is snow-contingent", "as_of": "2026-11-23", "source": "ebsp.org (via loon-lake-dossier.md §2)"},
    ],
    "sacramento-river-westport": [
        {"fact": "Live reading: gage 11377100 Red Bluff = 5,820 cfs — moderate winter baseflow, fishable, not flooded; expect pulses after storms (higher flow = more steelhead movement, harder fishing)", "as_of": "2026-11-23 10:45 AM PST", "source": "sacramento-river-dossier.md §1 (retrieved via USGS OGC API)"},
    ],
}

# ---------------------------------------------------------------------------
# Machine-readable stocking dates — a strict SUBSET of the STOCKING narratives
# above (drives the "Stocking day tomorrow" condition alert). Dates are taken
# verbatim from the seeded narratives; no invented dates. Waters without
# dated programs get an empty list (the alert simply never fires for them).
# ---------------------------------------------------------------------------
STOCKING_DATES = {
    # Private-operator weekly plants, documented in STOCKING (dossier §3):
    # "Recent plants: Nov 2 (2,000 lb), Nov 9 (1,500 lb), Nov 16 (1,000 lb),
    #  Nov 23 (2,000 lb)". Future Dec dates are "not yet announced" — not seeded.
    "collins-lake": ["2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23"],
    # Annual rainbow program (Oct–Mar) — no fixed calendar dates published.
    "new-bullards-bar": [],
    # No CDFW stocking in the past 13 months (verified) — nothing to match.
    "loon-lake": [],
    # Wild fishery — no stocking program.
    "sacramento-river-westport": [],
}

# ---------------------------------------------------------------------------
# Species activity heuristics (0–3) per water per calendar month (Jan–Dec).
# Sacramento chinook curve corrected 2026-11-23: season is Nov 1–Dec 31 in
# the Sec. 7.40(80) zone (verified regs), so Nov/Dec are prime; October is
# closed in this stretch (season opens Nov 1).
# ---------------------------------------------------------------------------
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

SPECIES_BY_WATER_MONTH = {
    "collins-lake": {
        "rainbow trout": [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3],
        "brown trout": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        "largemouth bass": [1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 1, 1],
        "spotted bass": [1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 1, 1],
    },
    "new-bullards-bar": {
        "kokanee": [1, 1, 1, 1, 1, 1, 1, 2, 3, 3, 2, 2],
        "rainbow trout": [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2],
        "spotted bass": [2, 3, 3, 2, 1, 0, 0, 0, 1, 2, 3, 3],
        "bluegill": [1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 1, 1],
    },
    "loon-lake": {
        "rainbow trout": [1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 1, 1],
        "kokanee": [1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2],
        "brown trout": [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0],
    },
    "sacramento-river-westport": {
        "chinook salmon": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 3],
        "steelhead": [3, 3, 3, 2, 0, 0, 0, 0, 0, 1, 3, 3],
        "smallmouth bass": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    },
}

# ---------------------------------------------------------------------------
# Kayak safety gate rules (Angler owns a kayak and has never used it).
# Loon is HARD-flagged NO KAYAK (first-time user + 6,378 ft cold water +
# snow-contingent Ice House Rd access — see REMINDERS for the road check).
# ---------------------------------------------------------------------------
KAYAK_RULES = {
    "always_no": ["loon-lake"],  # high-elevation, cold, wind-prone: hard block
    "wind_caution_mph": 10.0,    # sustained wind at/above -> caution
    "gust_caution_mph": 15.0,    # gusts at/above -> caution
}

# ---------------------------------------------------------------------------
# Species-level tactics mapped to owned tackle (original v1 knowledge).
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
    "kokanee": {
        "rod": "Dobyns CL693SF + Shimano Sahara 2500J (light spinning)",
        "lures": ["triple teaser", "wedding ring", "needlefish", "small spoon"],
        "lines": "10-15 lb braid + 20 lb fluoro leader",
        "tips": [
            "Troll slow in coves and inlets; follow baitfish schools.",
            "Silvering autumn adults hang near structure at dawn/dusk.",
        ],
    },
    "spotted bass": {
        "rod": "Abu Garcia Vendetta (med/fast)",
        "lures": ["spinnerbait", "green weenie / plastic worm", "crankbait", "spoon"],
        "lines": "12-20 lb braid + 15 lb fluoro leader",
        "tips": [
            "Cold water: drop-shot and slow presentations around creek mouths and rocky points.",
            "Winter trophy fish hold deep structure — give lures time.",
        ],
    },
    "smallmouth bass": {
        "rod": "Abu Garcia Vendetta (med/fast)",
        "lures": ["small spoon", "Panther Martin #2", "jerkbait"],
        "lines": "10-15 lb braid + 15 lb fluoro leader",
        "tips": ["Rocky points, current seams, and gravel bars."],
    },
}

# ---------------------------------------------------------------------------
# Water-specific tactic notes (dossier §6 sections) — appended to the
# species-level TACTICS tips in the plan output.
# ---------------------------------------------------------------------------
WATER_TACTICS = {
    "collins-lake": {
        "rainbow trout": [
            "PowerBait, small spinners, spoon + egg, tiny jigs, small crankbaits; drift and slow-troll near shore and coves",
            "Known spots: shoreline below the store (easy shoreline trout action — Apr 2025 staff report), Elmer's Cove",
            "Docks, piers, and cove edges are typical winter trout ambush points",
            "Freshly stocked fish are easiest in the first 1–2 weeks after each plant",
        ],
        "brown trout": ["Winter: deeper, warmer water near structure and creek mouths; slower presentations"],
        "largemouth bass": [
            "Winter bass concentrate in deeper, warmer water near structure and creek mouths",
            "Slow jigging, drop-shot, plastic worms around wood/rocks/creek mouths",
        ],
        "spotted bass": [
            "Winter bass concentrate in deeper, warmer water near structure and creek mouths",
            "Slow jigging, drop-shot, plastic worms around wood/rocks/creek mouths",
        ],
    },
    "new-bullards-bar": {
        "kokanee": [
            "Triple teasers, wedding rings, needlefish, PowerBait, nightcrawlers; trolling with downriggers in deeper water",
            "Spots: Mill Creek Cove, Frenchy Point, Willow Creek inlet, near the dam, Dark Day Canyon inlet, west shore across from Garden Point",
        ],
        "rainbow trout": ["Cold-water structure; stocked fish (if planted) hold near inflows"],
        "spotted bass": [
            "THE winter target — trophy-class odds peak in the cold months (world records caught Jan/Feb)",
            "Spinnerbaits, plastic worms, green weenies, crankbaits, spoons, Rebel Pop-Rs; drop-shotting with Robo Worms in cold water",
            "Spots: Little Oregon Creek, Burnt Bridge Creek inlet, Tractor Cove, north arm — creek mouths and rocky points",
        ],
        "bluegill": ["Heads of coves, dock areas — worms, chicken livers, crayfish"],
    },
    "loon-lake": {
        "rainbow trout": [
            "Residual/resident fish in December — target structure and inflows in deeper, cooler water",
            "PowerBait, spinners, small spoons, tiny jigs/crankbaits; slow retrieves in cold, clear water",
            "Spots: near the dam, intake tunnel from Buck Island Lake, granite point east of the spillway, north of the boat ramp (PowerBait zone), cove edges",
        ],
        "kokanee": ["Flashers + spoons, small inline spinners, slow troll along thermocline/depths"],
        "brown trout": ["Soft plastics and jigs near rock (if present)"],
    },
    "sacramento-river-westport": {
        "chinook salmon": [
            "Dec trip = target chinook: the only legal mid-Dec salmon harvest of the four waters",
            "Season Nov 1–Dec 31 in the Sec. 7.40(80) zone (Red Bluff→Colusa); 2/day, 4 possession",
            "Watch gage 11377100 — rising water changes where fish hold",
        ],
        "steelhead": [
            "Harvest CLIPPED-FINNED hatchery fish only; FG 682 card required",
            "Keswick Dam → 650 ft downstream is CLOSED all year (wild steelhead)",
        ],
        "smallmouth bass": ["Rocky points and current seams"],
    },
}

GEAR = {
    "rods": [
        {"name": "Penn Dobyns CL693SF", "use": "general purpose — trout, kokanee, light river"},
        {"name": "Penn Abalone AL6100-2", "use": "heavier river work"},
    ],
    "reels": [
        {"name": "Penn Sahara 2500J", "pairing": "Dobyns CL693SF", "line": "10 lb mono"},
        {"name": "Abu Garcia Vendetta (med/fast)", "pairing": "Abalone AL6100-2", "line": "14 lb braid + 20 lb fluoro leader"},
    ],
    "lures": [
        "Kastmaster #1 and #3 spoons",
        "Panther Martin (red/white, chartreuse)",
        "Trout bugs (assorted colors)",
        "Assorted spoons (CD, willow leaf)",
        "Carolina-rig weights (1/4–1 oz)",
        "Wacky worms (chartreuse, watermelon)",
    ],
    "extras": ["Spare 10 lb mono spools", "Pliers", "Net"],
}

SEED_USER = {"name": "Angler", "email": None}
