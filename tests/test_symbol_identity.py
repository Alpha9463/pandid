"""No two drawings this library ships are secretly the same drawing.

The failure this guards against is #367's, and it is the quietest one the
project has: a stencil that is a *placeholder* rather than a drawing. The
draw.io P&ID set ships a shape called "Steam Trap" which is an empty
50 x 50 rectangle, byte-for-byte identical to the same file's "Desuper
Heater". Vendoring it would have registered one blank box under two
device names, and a sheet asking for a steam trap would have come out
showing a desuperheater -- with no warning, because nothing anywhere
compares two drawings to each other.

That is the general shape of it. A duplicate reaching the registry is not
a crash and not a wrong number; it is a sheet that *draws*, and draws
something else. So the check is on identity rather than on any one
symbol: hash every drawing, and refuse a collision.

Two levels, because the duplicate can enter at either:

1. **The vendored stencil files**, where upstream's own duplicates live.
   :data:`UPSTREAM_DUPLICATE_GROUPS` records every one of them, so a
   re-vendor that brings in a new pair has to say so here.
2. **The registry**, which is what actually ships, and where a hand-drawn
   drawing could collide with a vendored one just as easily.

Neither list is an allow-list of *defects*. Nothing pandid registers today
draws a lie: the one upstream duplicate group with two registered members
(Ball Valve / Globe Valve) is repaired on the way through by
``vendor_symbols.STENCIL_PATCHES``, and the only two collisions in the
registry are one Symbol object deliberately registered under two names.
Both tests assert that, rather than tolerating an exception to it.
"""

import collections
import hashlib
import importlib.util
import pathlib
import xml.etree.ElementTree as ET
from typing import Any, Iterator

import pytest

from pandid.render.symbols import Symbol, default_registry

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _vendor_symbols() -> Any:
    """``scripts/vendor_symbols.py``, imported by path.

    The generators are dev-only and not part of the package, so they are
    not importable as one. Same approach as
    ``tests/test_symbol_invariants._script``; kept local rather than
    imported across test modules, which would make one file's collection
    depend on another's.
    """
    path = ROOT / "scripts" / "vendor_symbols.py"
    spec = importlib.util.spec_from_file_location("_pandid_script_vendor", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: Every group of byte-identical shapes in the vendored draw.io stencil
#: files, as vendored, keyed by the file they are in.
#:
#: Recorded rather than derived, so that a re-vendor bringing in a *new*
#: duplicate pair fails here and gets looked at. Each of these is
#: upstream's, and none of them is pandid's to fix in the stencil data --
#: the vendored XML stays exactly as vendored, which is
#: ``scripts/vendor_symbols`` policy.
#:
#: What matters about each group is which of its members pandid
#: *registers*, and that is what
#: :func:`test_no_duplicate_group_reaches_the_registry_undistinguished`
#: asks. Four of the five are registered zero-or-once and so cannot
#: collide; the fifth is corrected by ``STENCIL_PATCHES``.
UPSTREAM_DUPLICATE_GROUPS: "dict[str, tuple[tuple[str, ...], ...]]" = {
    "filters": (
        # Two filters drawn as the same box. Neither is registered: pandid
        # draws a HEPA filter and a biological filter from other rows.
        ("Gas Filter", "Gas Filter (HEPA)"),
        ("Liquid Filter (Biological)", "Liquid Filter (Ion Exchanger)"),
    ),
    "piping": (
        # #367. The steam trap placeholder, and the shape it is a copy of.
        # Neither is registered, and the steam trap pandid draws is
        # hand-drawn from ISO 10628-2 item 24.15 instead.
        ("Desuper Heater", "Steam Trap"),
        # Three names, one drawing of a body with a mesh in it. pandid
        # registers ``fitting/silencer`` from a different shape and draws
        # its flame arrestors from the fittings file.
        ("Detonation Arrestor", "Flame Arrestor", "In-Line Silencer"),
    ),
    "valves": (
        # The one group with two registered members, and the reason
        # ``STENCIL_PATCHES`` exists: ISO 10628-2 draws the globe valve's
        # seat solid and the ball valve's open, and upstream ships both
        # open. The patch fills the globe valve's, quoting the stencil's
        # own arcs.
        ("Ball Valve", "Globe Valve"),
    ),
}


def _digest(shape: ET.Element) -> str:
    """SHA-256 of one ``<shape>``'s canonical XML, with its *name* removed.

    The name is what a duplicate differs in, and nothing else: strip it and
    two placeholder entries hash alike, which is the whole question.
    """
    clone = ET.fromstring(ET.tostring(shape, encoding="unicode"))
    clone.attrib.pop("name", None)
    return hashlib.sha256(ET.tostring(clone, encoding="utf-8")).hexdigest()


def _shapes(path: pathlib.Path) -> "Iterator[tuple[str, ET.Element]]":
    """``(name, element)`` for every shape in one stencil file."""
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    for shape in root.findall("shape"):
        yield shape.get("name", "?"), shape


def _artwork(symbol: Symbol) -> str:
    """The bytes that decide what a reader sees: the drawing and its box.

    Not the whole Symbol. Two drawings that differ only in a port name or
    an ``iso_reg`` are still the same ink on the page, which is exactly
    the confusion a placeholder causes.
    """
    return f"{symbol.width}x{symbol.height}|{symbol.svg}"


def test_the_vendored_stencils_hold_exactly_the_duplicate_groups_recorded_here():
    """Upstream's duplicates are known, and a new one has to be noticed.

    A re-vendor is a bulk data change, and a shape that quietly became a
    copy of another between draw.io releases would otherwise arrive
    unremarked -- and then be available for someone to map in KIND_MAP,
    which is #367 happening a second time.
    """
    stencils = _vendor_symbols().STENCILS
    found: "dict[str, tuple[tuple[str, ...], ...]]" = {}
    for path in sorted(pathlib.Path(stencils).glob("*.xml")):
        groups: "dict[str, list[str]]" = collections.defaultdict(list)
        for name, shape in _shapes(path):
            groups[_digest(shape)].append(name)
        duplicates = tuple(tuple(sorted(names)) for names in groups.values() if len(names) > 1)
        if duplicates:
            found[path.stem] = tuple(sorted(duplicates))

    want = {
        stencil: tuple(sorted(tuple(sorted(g)) for g in groups))
        for stencil, groups in UPSTREAM_DUPLICATE_GROUPS.items()
    }
    assert found == want, (
        "the vendored stencil files no longer hold exactly the duplicate groups "
        "tests/test_symbol_identity.UPSTREAM_DUPLICATE_GROUPS records. A group that "
        "appeared is a placeholder nobody has looked at yet -- check what it draws "
        "before mapping either member in KIND_MAP -- and one that vanished means the "
        "record is stale. Update the constant with the reason, either way."
    )


def test_no_duplicate_group_reaches_the_registry_undistinguished():
    """Two members of one duplicate group may both be registered only if
    something told them apart on the way through.

    This is the test that would have caught #367 had the steam trap been
    vendored: mapping both "Steam Trap" and "Desuper Heater" in KIND_MAP
    with nothing in ``STENCIL_PATCHES`` to separate them puts two device
    names on one blank box.

    Asked after ``patch_shape``, because that is the stencil the generator
    actually converts. The globe valve is the live case: identical to the
    ball valve as vendored, and a different drawing by the time it is
    registered.
    """
    vendor = _vendor_symbols()
    registered: "dict[tuple[str, str], list[str]]" = collections.defaultdict(list)
    for (kind, variant), entry in vendor.KIND_MAP.items():
        if isinstance(entry, tuple):
            registered[(entry[0], entry[1])].append(f"{kind}/{variant}")

    for stencil, groups in UPSTREAM_DUPLICATE_GROUPS.items():
        index = dict(_shapes(pathlib.Path(vendor.STENCILS) / f"{stencil}.xml"))
        for group in groups:
            live = [name for name in group if (stencil, name) in registered]
            digests = {
                name: _digest(vendor.patch_shape(stencil, name, index[name])) for name in live
            }
            assert len(set(digests.values())) == len(live), (
                f"{stencil}.xml's {sorted(live)} are byte-identical upstream and are "
                f"still identical after STENCIL_PATCHES, yet both are registered: "
                f"{sorted(n for name in live for n in registered[(stencil, name)])}. "
                f"That ships one drawing under two device names. Either patch the "
                f"one the standard draws differently, or draw it by hand and stop "
                f"vendoring it -- which is what fitting/steam_trap did for #367."
            )


def test_no_two_registered_drawings_are_byte_identical():
    """The invariant #367 asks for, on the thing that actually ships.

    Every registered ``(kind, variant)`` is a drawing a user can ask for by
    name, and two names resolving to the same ink means one of them is
    drawing the other one's equipment.

    The one legitimate exception is an **alias**: one ``Symbol`` object
    deliberately registered under two keys, so that ``Centrifuge(...)`` and
    ``variant="decanter"`` cannot drift apart, and ``instrument/sis`` and
    ``instrument/logic`` stay the one square-and-diamond. That is identity,
    not coincidence, so it is tested as identity -- ``is``, not ``==``. A
    second drawing that merely *happens* to match another still fails, and
    that is the case a placeholder is in.
    """
    symbols = default_registry._symbols
    by_artwork: "dict[str, list[tuple[str, str]]]" = collections.defaultdict(list)
    for key, symbol in symbols.items():
        by_artwork[_artwork(symbol)].append(key)

    offenders: "list[str]" = []
    for keys in by_artwork.values():
        if len(keys) == 1:
            continue
        first = symbols[keys[0]]
        if all(symbols[key] is first for key in keys):
            continue  # a deliberate alias: one object, two names
        offenders.append(", ".join(f"{kind}/{variant}" for kind, variant in sorted(keys)))

    assert offenders == [], (
        "these registered drawings are byte-identical without being the same Symbol "
        "object, so the library ships one drawing under two device names and a sheet "
        "asking for either gets the same picture: "
        + "; ".join(sorted(offenders))
        + ". If they are meant to be one drawing, register the one object twice the "
        "way centrifuge/default and instrument/logic do, so they cannot drift; if "
        "they are meant to be two, one of them has no artwork yet and must not be "
        "registered until it does (#367)."
    )


@pytest.mark.parametrize("kind,variant", sorted(default_registry._symbols))
def test_no_registered_drawing_is_the_generic_box(kind: str, variant: str):
    """A registered drawing is never the empty fallback.

    ``SymbolRegistry._generic_symbol`` is the plain square drawn for a unit
    kind from outside this package, and it is the *right* answer there. It
    is never the right answer for a kind pandid ships: registering it would
    be the same silent substitution #367 is about, reached from the other
    direction -- and it is what vendoring draw.io's "Steam Trap" would have
    produced, since that shape converts to exactly an empty box.
    """
    generic = _artwork(default_registry._generic_symbol())
    symbol = default_registry.get(kind, variant)
    assert _artwork(symbol) != generic, (
        f"{kind}/{variant} is registered as the generic empty box, which draws "
        f"nothing and says nothing. A kind with no artwork must stay unregistered, "
        f"so that asking for it is refused rather than answered with a blank."
    )
