"""Test that no two shipped drawings are the same and none is a bare placeholder box."""

import collections
import hashlib
import pathlib
import re
import xml.etree.ElementTree as ET
from typing import Iterator

import pytest

from pandid.render.svg import _affine
from pandid.render.symbols import Symbol, default_registry
from test_symbol_invariants import _script

#: Every group of byte-identical shapes in the vendored draw.io stencil files, by file.
UPSTREAM_DUPLICATE_GROUPS: "dict[str, tuple[tuple[str, ...], ...]]" = {
    "filters": (
        # Pairs of filters drawn as the same box; none is registered.
        ("Gas Filter", "Gas Filter (HEPA)"),
        ("Liquid Filter (Biological)", "Liquid Filter (Ion Exchanger)"),
    ),
    "piping": (
        # The steam trap placeholder and its copy; neither is registered.
        ("Desuper Heater", "Steam Trap"),
        # One body-with-mesh drawing under three names; none is registered.
        ("Detonation Arrestor", "Flame Arrestor", "In-Line Silencer"),
    ),
    "valves": (
        # Both registered; STENCIL_PATCHES fills the globe valve's seat.
        ("Ball Valve", "Globe Valve"),
    ),
}


def _digest(shape: ET.Element) -> str:
    """Return the SHA-256 of one ``<shape>``'s canonical XML with its name removed."""
    clone = ET.fromstring(ET.tostring(shape, encoding="unicode"))
    clone.attrib.pop("name", None)
    return hashlib.sha256(ET.tostring(clone, encoding="utf-8")).hexdigest()


def _shapes(path: pathlib.Path) -> "Iterator[tuple[str, ET.Element]]":
    """Yield ``(name, element)`` for every shape in one stencil file."""
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    for shape in root.findall("shape"):
        yield shape.get("name", "?"), shape


#: Attributes that name a drawing rather than draw it.
_NAMING_ONLY = re.compile(r'\s(?:id|class)="[^"]*"')


def _drawn(svg: str) -> "list[tuple[ET.Element, float]]":
    """Return every painted element in *svg* with the uniform scale over it."""
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
    """Return a symbol's box and ink, without the attributes that only name it."""
    return f"{symbol.width}x{symbol.height}|{_NAMING_ONLY.sub('', symbol.svg)}"


#: The registered drawings that are only their own box.
BARE_BOX_BY_DESIGN = {
    ("block", "default"),
    # ISO 10628-2 item 1.1, 301, is a rectangle.
    ("tank", "flat_roof"),
}


def _is_bare_box(symbol: Symbol) -> bool:
    """Return whether the whole drawing is one rectangle coincident with its box."""
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
    """Check that the vendored stencils hold exactly the recorded duplicate groups."""
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
    assert found == want, "the vendored stencils no longer match UPSTREAM_DUPLICATE_GROUPS"


def test_no_duplicate_group_reaches_the_registry_undistinguished():
    """Check that registered members of a duplicate group differ after ``patch_shape``."""
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
                f"{stencil}.xml {sorted(live)} are registered and identical after patching"
            )


def test_no_two_registered_drawings_are_byte_identical():
    """Check that identical registered artwork is one Symbol object or one vendored stencil."""
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

    assert offenders == [], "byte-identical registered drawings: " + "; ".join(sorted(offenders))


@pytest.mark.parametrize("kind,variant", sorted(default_registry._symbols))
def test_no_registered_drawing_is_a_bare_box(kind: str, variant: str):
    """Check that no registered drawing outside BARE_BOX_BY_DESIGN is a bare box."""
    if (kind, variant) in BARE_BOX_BY_DESIGN:
        return
    assert not _is_bare_box(default_registry.get(kind, variant)), (
        f"{kind}/{variant} draws only its bounding box"
    )


def test_the_bare_box_guard_still_has_a_placeholder_to_catch():
    """Check that the converted draw.io Steam Trap is a bare box and the shipped one is not."""
    vendor = _script("vendor_symbols")
    index = dict(_shapes(pathlib.Path(vendor.STENCILS) / "piping.xml"))
    body, width, height, *_rest = _script("mxgraph_to_svg").convert_shape(index["Steam Trap"])
    placeholder = Symbol(svg=f"<g>{body}</g>", width=width, height=height)
    assert _is_bare_box(placeholder), "the draw.io Steam Trap no longer converts to a bare box"
    assert not _is_bare_box(default_registry.get("fitting", "steam_trap"))
