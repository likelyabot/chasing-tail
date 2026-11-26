"""Species-name -> pixel-art sprite mapping.

The Plan tab renders a pixel-art sprite next to each suggested species.
The UI resolves sprites CLIENT-SIDE from a byte-identical mirror of this
table (SPRITE_KEYWORDS in app/static/app.js) so rendering never depends on
a network round-trip; this module is the canonical copy and backs the
GET /api/species-icon/<name> endpoint. The smoke test asserts the two
tables stay in sync.

Pure stdlib, no I/O — importable from scripts/smoke_test.py without
fastapi installed.
"""

#: Subdirectory of /static holding the 184x104 sprites (4x of the 46x26 base).
SPRITE_DIR = "img/fish"

#: Returned for anything unrecognized — the UI must never show a broken image.
SPRITE_FALLBACK = "generic.png"

#: Ordered keyword table: normalize the name (lowercase + strip), then the
#: FIRST keyword contained in it wins. Keep in lockstep with SPRITE_KEYWORDS
#: in app/static/app.js (the smoke test enforces this).
SPRITE_KEYWORDS = [
    ("rainbow", "rainbow-trout.png"),
    ("steelhead", "steelhead.png"),
    ("coho", "steelhead.png"),
    ("chinook", "salmon.png"),
    ("king", "salmon.png"),
    ("salmon", "salmon.png"),
    ("brown trout", "brown-trout.png"),
    ("largemouth", "largemouth-bass.png"),
    ("smallmouth", "smallmouth-bass.png"),
    ("crappie", "crappie.png"),
    ("catfish", "catfish.png"),
    ("channel", "catfish.png"),
    ("blue cat", "catfish.png"),
    ("bluegill", "bluegill.png"),
    ("sunfish", "bluegill.png"),
    ("sturgeon", "sturgeon.png"),
    ("carp", "carp.png"),
]


def resolve_sprite(name: str | None) -> str:
    """Map a species name to a sprite filename (fallback: generic.png)."""
    n = (name or "").lower().strip()
    for kw, sprite in SPRITE_KEYWORDS:
        if kw in n:
            return sprite
    return SPRITE_FALLBACK
