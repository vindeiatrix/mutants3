# room_headers.py
"""
Static room headers + a symbolic store placeholder.
The store header uses the "{PRICE}" token; at render time, substitute the
century-based price (no comma separators) when the tile is a for-sale store.
"""

STORE_FOR_SALE_TEMPLATE = "A sign reads: FOR SALE $ {PRICE}"

ROOM_HEADERS = [
    STORE_FOR_SALE_TEMPLATE,
    "You see rubble everywhere.",
    "You feel a cold breeze.",
    "The street is cracked here.",
    "Broken lamp posts line the streets.",
    "The wind is whistling through open windows.",
    "You're in an abandoned building.",
    "An eerie calm settles in the distance.",
    "You're in a maintenance shop.",
    "You're in a wrecked building.",
    "Crumbling buildings surround you.",
    "Relics of the war line the streets.",
    "The two moons are rising above.",
    "An old hydro line has fallen here.",
    "You hear volcanoes erupt in the distance.",
    "Graffiti lines the city walls.",
    "Broken glass covers the road.",
    "City Trading Centre.",
]

# Optional convenience: fixed index for tools/world-builder
STORE_FOR_SALE_IDX = 0
