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
import re
import xml.etree.ElementTree as ET
from typing import Any, Iterator

import pytest

from pandid.render.svg import _affine
from pandid.render.symbols import Symbol, default_registry

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _script(name: str) -> Any:
    """One of the dev-only generator scripts, imported by path.

    They are not part of the package and not importable as one. Same
    approach as ``tests/test_symbol_invariants._script``; kept local
    rather than imported across test modules, which would make one
    file's collection depend on another's.

    By path rather than by putting ``scripts/`` on ``sys.path`` and
    importing: a plain ``import`` of a directory added at run time is a
    name a type checker cannot resolve, and these tests are held to
    checking clean.
    """
    spec = importlib.util.spec_from_file_location(
        f"_pandid_script_{name}", ROOT / "scripts" / f"{name}.py"
    )
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


#: Attributes that name a drawing rather than draw it.
#:
#: Every symbol wraps its ink in ``<g id="sym_...">`` so the renderer has
#: a ``<defs>`` key to ``<use>``, and that id follows the *variant
#: spelling*. Hashing it would mean two identical drawings under two
#: device names hashed apart purely because they are under two device
#: names -- which is precisely the case this file exists to catch, so it
#: is precisely the attribute that must not be in the hash.
_NAMING_ONLY = re.compile(r'\s(?:id|class)="[^"]*"')


def _drawn(svg: str) -> "list[tuple[ET.Element, float]]":
    """Every painted element in *svg*, with the uniform scale over it.

    ``<g>`` is structure, not ink: the vendored symbols wrap their
    artwork in ``<g transform="scale(0.25)">`` and the reader sees
    through it. So the tree is flattened and each element carries the
    scale that reaches it, which is what lets a drawing be measured
    against its own box whether or not it was drawn at that box size.
    """
    out: "list[tuple[ET.Element, float]]" = []

    def walk(node: "ET.Element", scale: float) -> None:
        for child in node:
            if child.tag == "g":
                sx, sy, _tx, _ty = _affine(child.get("transform", ""))
                walk(child, scale * (abs(sx) + abs(sy)) / 2)
            else:
                out.append((child, scale))

    walk(ET.fromstring(svg), 1.0)
    return out


def _artwork(symbol: Symbol) -> str:
    """The ink, and the box it is drawn in -- and nothing that only names it.

    Not the whole ``Symbol``: two drawings that differ in a port name or
    an ``iso_reg`` are still the same ink on the page, which is exactly
    the confusion a placeholder causes. And not the raw markup either --
    see :data:`_NAMING_ONLY`.
    """
    return f"{symbol.width}x{symbol.height}|{_NAMING_ONLY.sub('', symbol.svg)}"


#: The one registered drawing that is legitimately nothing but its own box.
#:
#: A block flow diagram block **is** a rectangle: the stage is drawn as a
#: box and what identifies it is the lettering inside, which the renderer
#: puts there rather than the symbol. So it is the single exception
#: :func:`test_no_registered_drawing_is_a_bare_box` allows, and it is
#: named here rather than inferred, so that a second drawing arriving in
#: this state has to be argued for.
BARE_BOX_BY_DESIGN = {("block", "default")}


def _is_bare_box(symbol: Symbol) -> bool:
    """Is the whole of this drawing one rectangle, coincident with its box?

    That is what a placeholder converts to, and what it looks like at any
    size: the draw.io "Steam Trap" is a 50 x 50 ``<rect>`` with an empty
    foreground, which comes through this library's converter as a single
    rect filling the symbol's box -- 12.5 x 12.5 once ``piping.xml``'s
    own 0.25 is applied, and 60 x 60 for
    ``SymbolRegistry._generic_symbol``. Comparing against either one of
    those *artworks* catches only that one size, which is why this asks
    the question structurally instead.

    Deliberately narrow. Sixty-two shipped drawings are a single
    ``<path>`` and every one of them says something -- a vessel's shell,
    a valve's bowtie -- so "one element" is not the test. "One element,
    and it is the bounding box" is: a drawing that traces only the extent
    it was given has nothing in it a reader could read.
    """
    drawn = _drawn(symbol.svg)
    if len(drawn) != 1:
        return False
    element, scale = drawn[0]
    if element.tag != "rect":
        return False
    span = 0.01 * max(symbol.width, symbol.height)
    return (
        abs(float(element.get("x", 0)) * scale) <= span
        and abs(float(element.get("y", 0)) * scale) <= span
        and abs(float(element.get("width", 0)) * scale - symbol.width) <= span
        and abs(float(element.get("height", 0)) * scale - symbol.height) <= span
    )


def test_the_vendored_stencils_hold_exactly_the_duplicate_groups_recorded_here():
    """Upstream's duplicates are known, and a new one has to be noticed.

    A re-vendor is a bulk data change, and a shape that quietly became a
    copy of another between draw.io releases would otherwise arrive
    unremarked -- and then be available for someone to map in KIND_MAP,
    which is #367 happening a second time.
    """
    stencils = _script("vendor_symbols").STENCILS
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
    vendor = _script("vendor_symbols")
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
    drawing the other one's equipment -- unless the library *said* they
    were the same drawing. There are two ways of saying it, and both are
    a statement in the data rather than a coincidence in the output:

    1. **One ``Symbol`` object under two keys.** ``Centrifuge(...)`` and
       ``variant="decanter"`` are the one drawing, and so are
       ``instrument/sis`` and ``instrument/logic``; registering the same
       object twice is what stops them drifting apart.
    2. **One vendored stencil under two names.** A bare ``Valve`` is a
       gate valve, a bare ``Separator`` is the same drum a bare ``Vessel``
       is, and each pair maps to one shape in
       ``scripts/vendor_symbols.KIND_MAP``. The generator emits a
       ``Symbol`` per entry, so these are separate objects -- but they
       carry the same :attr:`~pandid.render.symbols.Symbol.drawio_shape`,
       and that key is derived from the stencil itself. Two drawings that
       name one stencil are one drawing by construction.

    Anything else is two drawings that merely *happen* to match, which is
    exactly what a placeholder is: draw.io's "Steam Trap" and its
    "Desuper Heater" are byte-identical and are two different shapes with
    two different keys, so vendoring both would fail here.

    No allow-list. Every collision in the shipped registry is declared by
    one of the two rules above, and a drawing that cannot say which is a
    drawing nobody has decided about.
    """
    symbols = default_registry._symbols
    by_artwork: "dict[str, list[tuple[str, str]]]" = collections.defaultdict(list)
    for key, symbol in symbols.items():
        by_artwork[_artwork(symbol)].append(key)

    offenders: "list[str]" = []
    for keys in by_artwork.values():
        if len(keys) == 1:
            continue
        drawings = [symbols[key] for key in keys]
        if all(drawing is drawings[0] for drawing in drawings):
            continue  # one object, two names
        stencils = {drawing.drawio_shape for drawing in drawings}
        if len(stencils) == 1 and drawings[0].drawio_shape:
            continue  # one vendored stencil, two names
        offenders.append(", ".join(f"{kind}/{variant}" for kind, variant in sorted(keys)))

    assert offenders == [], (
        "these registered drawings are byte-identical, and nothing in the "
        "library says they are meant to be the one drawing -- they are neither "
        "the same Symbol object nor the same vendored stencil. So the library "
        "ships one picture under two device names and a sheet asking for either "
        "gets the other one's equipment: "
        + "; ".join(sorted(offenders))
        + ". If they are meant to be one drawing, register the one object twice "
        "the way centrifuge/default does; if they are meant to be two, one of "
        "them has no artwork yet and must not be registered until it does "
        "(#367)."
    )


@pytest.mark.parametrize("kind,variant", sorted(default_registry._symbols))
def test_no_registered_drawing_is_a_bare_box(kind: str, variant: str):
    """A registered drawing always draws something.

    This is #367's defect reached from the direction that actually
    happens. The duplicate guards above need **two** drawings to compare;
    a placeholder mapped on its own has nothing to collide with, and that
    was the original defect -- the draw.io "Steam Trap" registered alone
    would have drawn an empty box under a device name and nothing would
    have said so.

    So this asks what the drawing *is* rather than what it equals. A kind
    with no artwork must stay unregistered, so that asking for it is
    refused (``SymbolRegistry.get`` raises) rather than answered with a
    blank -- which is the difference between a gap and a lie.
    """
    if (kind, variant) in BARE_BOX_BY_DESIGN:
        return
    assert not _is_bare_box(default_registry.get(kind, variant)), (
        f"{kind}/{variant} draws nothing but its own bounding box, which says "
        f"nothing about what the equipment is. That is what an unconverted "
        f"placeholder stencil looks like (#367). Either draw it, or leave it "
        f"unregistered so that asking for it is refused; if it really is a plain "
        f"box, name it in BARE_BOX_BY_DESIGN with the reason."
    )


def test_the_bare_box_guard_still_has_a_placeholder_to_catch():
    """The guard above is only worth having if it fires, and what it has
    to fire on is not hypothetical: it is a shape sitting in the vendored
    data today.

    So the placeholder is put through the real converter and asked. This
    is the non-vacuity proof kept in the suite rather than done once by
    hand -- if the converter ever started producing something with ink in
    it, or ``_is_bare_box`` stopped recognising a blank, this says so.
    """
    vendor = _script("vendor_symbols")
    index = dict(_shapes(pathlib.Path(vendor.STENCILS) / "piping.xml"))
    body, width, height, *_rest = _script("mxgraph_to_svg").convert_shape(index["Steam Trap"])
    placeholder = Symbol(svg=f"<g>{body}</g>", width=width, height=height)
    assert _is_bare_box(placeholder), (
        "the draw.io Steam Trap no longer converts to a bare box, so the guard "
        "that catches a placeholder registered on its own is no longer known "
        "to catch anything. Check what it draws now."
    )
    # And the drawing pandid ships instead is not one.
    assert not _is_bare_box(default_registry.get("fitting", "steam_trap"))
