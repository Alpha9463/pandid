"""Reusable flowsheets for layout regression tests."""

from pandid import (
    DistillationColumn,
    Feed,
    Flowsheet,
    GravitySeparator,
    Product,
    Reactor,
)


PINS = {
    "water": {"x": 1125, "y": 200},
    "dc101": {"y": 450},
    "dc102": {"y": 0},
    "r102": {"y": 600},
    "s102": {"y": 250},
    "s103": {"y": 275},
    "r101": {"y": 0},
    "s101": {"y": 100},
    "r103": {"y": 800},
    "dirty_water": {"y": 450},
    "acid": {"x": 500},
    "waste": {"y": 1000},
}

ORDER = """r101 r102 s101 s102 s103 canola methanol sodium_hydroxide
biodiesel glycerol water dirty_water dirty_water_2 acid c102 dc101 dc102
waste methanol_recovery methanol_recovery_2 r103""".split()

EDGES = [
    ("canola", "outlet", "r101", "feed_1"),
    ("sodium_hydroxide", "outlet", "r101", "feed_3"),
    ("methanol", "outlet", "r101", "feed_2"),
    ("r101", "outlet", "s101", "feed"),
    ("s101", "overflow", "dc102", "feed"),
    ("dc102", "overhead", "methanol_recovery", "inlet"),
    ("dc102", "bottoms", "s102", "feed_2"),
    ("s101", "underflow", "dc101", "feed"),
    ("dc101", "overhead", "methanol_recovery_2", "inlet"),
    ("dc101", "bottoms", "r102", "feed_1"),
    ("acid", "outlet", "r102", "feed_2"),
    ("r102", "outlet", "c102", "feed"),
    ("water", "outlet", "s102", "feed_1"),
    ("water", "outlet", "s103", "feed_1"),
    ("s102", "overflow", "s103", "feed_2"),
    ("s102", "underflow", "dirty_water", "inlet"),
    ("s103", "overflow", "biodiesel", "inlet"),
    ("s103", "underflow", "dirty_water_2", "inlet"),
    ("c102", "overflow", "r103", "feed_1"),
    ("c102", "underflow", "waste", "inlet"),
    ("sodium_hydroxide", "outlet", "r103", "feed_2"),
    ("r103", "outlet", "glycerol", "inlet"),
]


def units():
    """Return fresh units for the Oaks biodiesel flowsheet."""
    result = {
        "r101": Reactor("R-101", n_feeds=3, agitator="turbine"),
        "r102": Reactor("R-102", n_feeds=2, agitator="turbine"),
        "r103": Reactor("R-103", n_feeds=2, agitator="turbine"),
        "s101": GravitySeparator("S-101"),
        "s102": GravitySeparator("S-102", n_feeds=2),
        "s103": GravitySeparator("S-103", n_feeds=2),
        "c102": GravitySeparator("C-102"),
        "dc101": DistillationColumn("DC-101", internals="tray", trays=10),
        "dc102": DistillationColumn("DC-102", internals="tray", trays=10),
    }
    for key, name in (
        ("canola", "Canola Oil"),
        ("sodium_hydroxide", "Sodium Hydroxide"),
        ("methanol", "Methanol"),
        ("water", "Water"),
        ("acid", "Acid"),
    ):
        result[key] = Feed(name)
    for key, name in (
        ("biodiesel", "Biodiesel"),
        ("glycerol", "Glycerol"),
        ("dirty_water", "Dirty Water"),
        ("dirty_water_2", "Dirty Water 2"),
        ("waste", "Waste"),
        ("methanol_recovery", "Methanol Recovery"),
        ("methanol_recovery_2", "Methanol Recovery 2"),
    ):
        result[key] = Product(name)
    return result


def build(pinned=True, skip=None):
    """Build a fresh Oaks biodiesel flowsheet and its unit lookup."""
    fs = Flowsheet("Oaks Biodiesel BFD")
    items = units()
    for key in ORDER:
        fs.add(items[key])
    if pinned:
        for key, pin in PINS.items():
            if key != skip:
                items[key].pin(**pin)
    for source, source_port, dest, dest_port in EDGES:
        fs.connect(getattr(items[source], source_port), getattr(items[dest], dest_port))
    return fs, items
