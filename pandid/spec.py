"""Build a flowsheet from data: the declarative spec format.

The other door beside the topology API (``fs.add`` / ``fs.connect``): a
plain mapping describing the same flowsheet, plus the serializer that
writes one back out, so a diagram round-trips through data.

    fs = Flowsheet.from_dict(spec)   # plain dict, no dependencies
    fs = Flowsheet.from_json(path)   # stdlib only
    fs = Flowsheet.from_yaml(path)   # needs the PyYAML extra
    spec = fs.to_dict()              # feeds back into from_dict()

The spec is *validated*, not interpreted: an unknown key is an error
rather than a silent no-op, because a typo in a hand-written file must
not quietly drop a nozzle off the sheet. Every message names the entry
it came from (``units[3] 'P-101'``) and lists what would have been
accepted, in the style of :meth:`pandid.units.Unit.port`.

The format::

    name: Feed Metering Skid      # required; the rest is optional
    stream_naming_scheme: "S{n}"
    stream_number_start: 1        # the S1 a flag draws
    line_numbering_scheme: "{size}-{service}-{sequence}-{spec}"
    line_number_start: 1001       # the 1001 in 6"-P-1001-A1A
    loop_number_start: 101        # where an unnumbered loop starts
    auto_faces: true              # engine picks each movable face
    components: [{name: Water, formula: H2O}]

    units:
      - {kind: Feed, name: Raw Feed, reference: PFD-100,
         pin: {x: 60, y: 275}}
      - {kind: Feed, name: CWSH, header: true}    # tap it as often
      - {kind: Fitting, name: ST-101, variant: strainer,
         description: Strainer}
      - {kind: Valve, name: HV-101, variant: gate,
         normal_position: closed}
      - {kind: Mixer, name: M-100, n_inlets: 2}
      - {kind: Vessel, name: V-101, variant: horizontal,
         width: 130, height: 42, port_faces: {inlet: N},
         pin: {x: 680, y: 210, mirrored: y}}
      - {kind: Vessel, name: D-301, supports: skirt}   # what it stands on
      - {kind: Reactor, name: R-201, internals: packing, agitator: null}
      - {kind: Column, name: T-101, internals: valve_tray, trays: 30}

    loops:
      - {variable: L, number: 101}   # a loop draws nothing itself
      - {variable: F}                # no number: takes the next one

    instruments:
      - {type: LIC, number: 101, display: central,
         near: LT-101, at: S, offset: 115, port_faces: {sig_out: W}}
      - {balloon_of: FE-101, at: N, offset: 38}   # the element's own tag

    streams:
      - {from: [Raw Feed, outlet], to: [ST-101, inlet],
         size: '6"', service: P, spec: A1A}
      - {from: [LIC-101, sig_out], to: [FV-101, actuator],
         kind: electric}
      - {from: [FV-200, outlet], to: [M-100, in_2],
         draw_as_recycle: true, tabulate: true,
         properties: {"Temperature (C)": 25 C}}

    stream_table_sections: [[Benzene, Mass Fraction]]
    stream_table: {font_size: 8}
    title_block: {title: ..., revisions: [{rev: A, date: ..., by: AA}]}
    annotations: [{type: equipment_list, align: top-right}]

A unit is addressed by its name, so a symbol drawn more than once -- an
interlock square, a utility header flag -- is addressed by the name the
flowsheet gives each drawing: the first entry is ``I-1``, the second
``I-1 (2)``, in list order. Each entry carries the tag, so a header
tapped twice is written as two ``CWSH`` entries and read back as the
same two taps.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import fields as dataclass_fields
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Literal

from pandid import devices as device_types
from pandid import units as unit_types
from pandid.components import Component
from pandid.document import (
    Annotation,
    Revision,
    StreamTableOptions,
    TableBox,
    TitleBlock,
    equipment_list,
    legend,
    notes,
)
from pandid.flowsheet import (
    DEFAULT_LINE_NUMBER_START,
    DEFAULT_LINE_NUMBERING_SCHEME,
    DEFAULT_LOOP_NUMBER_START,
    DEFAULT_STREAM_NUMBER_START,
    Flowsheet,
)
from pandid.loops import Loop
from pandid.portgeom import pin_intent, unmeasured_port
from pandid.ports import Port
from pandid.streams import LINE_NUMBER_FIELDS, Stream
from pandid.units import Instrument, Unit, _Boundary


class SpecError(ValueError):
    """A flowsheet spec could not be understood.

    A :class:`ValueError`, so ``except ValueError`` handlers still catch
    it; a distinct class so a tool loading user files can tell "your
    spec is wrong" apart from "the engine is unhappy".
    """


# ----------------------------------------------------------------
# Primitive validation. Each helper takes the dotted path of the value
# it is checking, so the message points at the line to fix.
# ----------------------------------------------------------------


def _suggest(value: Any, candidates) -> str:
    """``" (did you mean 'variant'?)"`` for a near-miss typo."""
    close = get_close_matches(str(value), [str(c) for c in candidates], n=1, cutoff=0.6)
    return f" (did you mean {close[0]!r}?)" if close else ""


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SpecError(
            f"{where} must be a mapping of field -> value, "
            f"got {type(value).__name__}: {value!r}"
        )
    for key in value:
        if not isinstance(key, str):
            raise SpecError(f"{where}: field names must be text, got {key!r}")
    return value


def _sequence(value: Any, where: str) -> list:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SpecError(f"{where} must be a list, got {type(value).__name__}: {value!r}")
    return list(value)


def _check_keys(data: Mapping[str, Any], allowed, where: str) -> None:
    for key in data:
        if key not in allowed:
            raise SpecError(
                f"{where}: unknown key {key!r}{_suggest(key, allowed)}; "
                f"allowed keys: {sorted(allowed)}"
            )


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise SpecError(f"{where} must be text, got {value!r} (quote it if it is a number)")
    return value


def _number(value: Any, where: str) -> float:
    # Returned unchanged rather than coerced to float: a whole-number
    # coordinate is drawn as "120" and a float one as "120.0", so
    # widening here rewrites the SVG of every flowsheet built from a
    # spec.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"{where} must be a number, got {value!r}")
    return value


def _column_width(value: Any, where: str) -> float | Literal["auto"]:
    """A stream-table column-width floor: a number, or ``auto``.

    Both spellings are what the attribute takes, said in a file: YAML
    reads a bare ``auto`` as the string already, and JSON has no other
    way to write one.
    """
    if value == "auto":
        return "auto"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f'{where} must be a number or "auto", got {value!r}')
    return value


def _integer(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f"{where} must be a whole number, got {value!r}")
    return value


def _flag(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise SpecError(f"{where} must be true or false, got {value!r}")
    return value


def _faces(value: Any, where: str) -> int | list[str]:
    """A connection count, or one face per connection.

    Both spellings go straight to the class, which owns the vocabulary
    and the message for a face that is not one; this only settles that
    the spec said a whole number or a list of words. A bare string is
    refused here because YAML makes ``inputs: W`` easy to write, and a
    string is a sequence of one-character faces that reads as what was
    meant right up until somebody writes ``inputs: WN``.
    """
    if isinstance(value, bool) or isinstance(value, int):
        return _integer(value, where)
    return [_text(face, f"{where}[{i}]") for i, face in enumerate(_sequence(value, where))]


def _composed(value: Any, default: Any, where: str) -> Any:
    """One composition keyword's value: a part's name, or a count of them.

    Which of the two it is comes off the class's own default rather than
    a table here, so ``trays: 30`` is a whole number and
    ``agitator: turbine`` names a group-28 stirrer without this function
    knowing either keyword. The name itself goes straight to the class,
    which owns the vocabulary and the message for a name that is not in
    it.

    ``null`` is a **statement**, and the reason this is not just
    :func:`_text`. A column told ``internals: null`` is a bare shell
    somebody asked for on purpose, where one that says nothing at all is
    drawn with the trays its class draws; the two have to stay
    distinguishable or a shell comes back with eight decks in it.
    """
    if isinstance(default, int) and not isinstance(default, bool):
        return _integer(value, where)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SpecError(
            f"{where} must be the name of a part, or null for none at all, got {value!r}"
        )
    return value


def _stages(value: Any, where: str) -> list[int | None]:
    """``feed_stages:``/``draw_stages:``'s value: one stage number per
    feed or draw, or ``null`` for one that keeps the even spread.

    ``null`` is the same statement it is in :func:`_composed`: a feed or
    a draw naming no stage is not one the list said nothing about, and
    reading the two alike would pin every one of them to whichever
    stage the first one named.
    """
    return [None if item is None else _integer(item, f"{where}[{i}]")
            for i, item in enumerate(_sequence(value, where))]


def _component(value: Any, where: str) -> str | float:
    """A line-number component.

    Text such as ``6"``, or the number an unquoted metric size
    (``size: 150``) parses as.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise SpecError(
            f"{where} must be text or a number (an imperial size carries its own "
            f"inch mark, e.g. '6\"'), got {value!r}"
        )
    return value


def _fail_from(error: Exception, where: str) -> SpecError:
    """Re-raise a library error against the entry that provoked it."""
    message = error.args[0] if error.args else str(error)
    return SpecError(f"{where}: {message}")


# --------------------------------------------------------------
# The equipment registry
# --------------------------------------------------------------


def _snake(name: str) -> str:
    out = [name[0].lower()]
    for char in name[1:]:
        out.append(f"_{char.lower()}" if char.isupper() else char)
    return "".join(out)


# Every class a spec may name, and both layers are needed, in opposite
# directions: ``_resolve_kind`` reads a spec naming a device class such
# as ``Cyclone``, and ``_write_unit`` writes ``type(unit).__name__``.
_CLASSES: dict[str, type[Unit]] = {
    name: getattr(unit_types, name) for name in unit_types.__all__ if name != "Unit"
}
_CLASSES.update({name: getattr(device_types, name) for name in device_types.__all__})

# A spec is hand-written, so accept every name the reader might
# reasonably use: the class name from the README (``HeatExchanger``),
# and its snake_case spelling.
_ALIASES: dict[str, str] = {}
for _name, _cls in _CLASSES.items():
    for _alias in (_name, _snake(_name)):
        _ALIASES[_alias.lower()] = _name
# ...and the internal ``Unit.kind`` tag (``hex``), which names a kind
# rather than a class and must resolve to the class owning the whole
# kind. Built from ``units`` alone: fifteen device classes carry
# ``kind == "pump"``, so folding them in would make ``kind: pump`` mean
# whichever iterated last, and that answer moves as classes are added.
for _name in unit_types.__all__:
    if _name != "Unit":
        _ALIASES[_CLASSES[_name].kind.lower()] = _name


def _resolve_kind(value: Any, where: str) -> type[Unit]:
    name = _ALIASES.get(_text(value, f"{where}.kind").strip().lower())
    if name is None:
        raise SpecError(
            f"{where}: unknown equipment kind {value!r}{_suggest(value, _CLASSES)}; "
            f"available kinds: {sorted(_CLASSES)}"
        )
    if name == "Instrument":
        raise SpecError(
            f"{where}: instruments go in the top-level 'instruments:' section, not in "
            "'units:'; that is where their tag (type/number) and attachment "
            "(on/at/offset/angle) live"
        )
    return _CLASSES[name]


# --------------------------------------------------------------
# Reading: spec -> Flowsheet
# --------------------------------------------------------------

_TOP_KEYS = {
    "name", "stream_naming_scheme", "stream_number_start",
    "line_numbering_scheme", "line_number_start", "loop_number_start",
    "auto_faces", "components", "units", "loops",
    "instruments", "streams", "stream_table_sections", "stream_table", "title_block",
    "annotations",
}
# Keys the format no longer has. A file written against the old one
# names the sheet it wants, so say so rather than reporting an unknown
# key or honouring it silently.
_RETIRED_KEYS = {
    "direction": "the layout engine only draws left to right, so it never did anything",
}
_PIN_KEYS = {"x", "y", "col", "row", "orientation", "mirrored", "port"}
_UNIT_KEYS = {
    "kind", "name", "variant", "description", "reference", "width", "height",
    "label_pos", "new_line_number", "pin", "port_faces",
}
_INSTRUMENT_KEYS = {
    "type", "number", "variant", "display", "description", "reference", "width",
    "height", "label_pos", "new_line_number", "sensing", "acting_on", "near",
    "at", "offset", "angle", "pin", "port_faces", "quadrants",
}
#: The three ways an instrument entry names its anchor.
_ANCHOR_KEYS = ("sensing", "acting_on", "near")
#: What a primary element's balloon entry may set. Everything an
#: instrument entry may, less the tag and the anchor: the tag is the
#: element's, which is the whole of what a balloon is for, and the
#: anchor is that element too, named once by ``balloon_of``. Derived
#: rather than listed a second time, because listing it a second time
#: is what let the writer grow fields -- ``description``, ``width``,
#: ``quadrants`` -- that the balloon reader then refused to read back.
_BALLOON_KEYS = ({"balloon_of"} | _INSTRUMENT_KEYS) - {"type", "number", *_ANCHOR_KEYS}
#: The quadrant each ``quadrants:`` key writes into. The spec spells the
#: argument names :meth:`pandid.units.Instrument.annotate` takes, not
#: ISO's letters, so a spec and the call it round-trips read the same.
_QUADRANT_KEYS = {"safety": "a", "variable": "b", "high": "c", "low": "d"}
_LOOP_KEYS = {"variable", "number"}
_STREAM_KEYS = {
    "from", "to", "kind", "name", "draw_as_recycle", "properties", "tabulate", "via",
    "color", "dasharray", "ends",
    *LINE_NUMBER_FIELDS,
}
_COMPONENT_KEYS = {"name", "formula"}
# Port counts, keyed by the classes that take one. A count named on a
# class with no such family is rejected rather than ignored: the ports
# it asked for would not exist on the drawing.
_VARIABLE_PORTS = {
    "n_inlets": ("Mixer",),
    "n_outlets": ("Splitter",),
    "n_feeds": ("Column", "Reactor"),
    "n_draws": ("Column",),
}
# Sizes only some classes carry, policed the same way: a conveyor's belt
# run and its roller are dimensions of its own rather than the generic
# width and height, so naming either on anything else asks for a size
# nothing draws.
_KIND_SIZES = {
    "length": ("Conveyor",),
    "diameter": ("Conveyor",),
}
# Text fields only some classes carry. ``normal_position`` is where a
# valve or a blind sits with the plant running; a pump has no such
# position, so naming one on it is a statement nothing draws.
_KIND_TEXT = {
    "normal_position": ("Valve", "Fitting"),
    # Where an actuated valve goes on loss of motive power. Narrower
    # than ``normal_position``: a blind has a position but no actuator.
    "fail": ("Valve",),
    # Which way a tee's third connection runs; nothing else has one.
    "branch": ("Tee",),
    # Which nozzle a reducer's wide face is on, and so whether it
    # reduces the line or expands it.
    "large_end": ("Reducer",),
}
# Connection faces, keyed the same way. A block declares which side of
# its box each connection is on, as a count (all on the default face) or
# one face per connection; a tank or a vessel declares the same thing
# for its own two families, over vendored artwork instead of a grown
# box (see ``pandid.units._MultiPortVessel``). Every other symbol is
# artwork drawn in advance with nothing to count, so where its nozzles
# are is a fact about the drawing alone.
_KIND_FACES = {
    "inputs": ("Block", "Tank", "Vessel"),
    "outputs": ("Block", "Tank", "Vessel"),
}
# The order along a face. Separate from the two above because it is not
# a constructor argument: ``Block.order_on``/``_MultiPortVessel.order_on``
# take the ports, which do not exist until the unit does. Written only
# where a face's order is not the declared one; see ``_write_unit``.
_KIND_ORDER = {
    "port_order": ("Block", "Tank", "Vessel"),
}
# Flags only some classes carry. ``header`` says a boundary flag stands
# for a utility service tapped wherever it is wanted rather than for one
# line leaving the sheet, which is what lets it repeat.
_KIND_FLAGS = {
    "header": ("Feed", "Product"),
}
# One stage number per feed, or per draw, keyed the same way. Not a
# composition keyword: it names no part and has no per-variant default,
# it only says where an already-drawn feed or draw lands, so it is
# checked and read like the tables above rather than folded into
# ``_KIND_COMPOSITION`` below.
_KIND_STAGES = {
    "feed_stages": ("Column",),
    "draw_stages": ("Column",),
}
#: The composition keywords, keyed the same way and **derived rather
#: than listed**: every one of them is an entry in the
#: :attr:`~pandid.units.Unit.COMPOSITION` of the class that declares it,
#: so a keyword added to a class arrives in the spec format with it.
#:
#: Listing them here a second time is exactly how the format came to be
#: unable to express a composed unit at all. They landed on four classes
#: and none of the tables above heard about them, so ``to_dict`` wrote
#: ``{kind, name}`` for a skirted vessel and ``from_dict`` read it back
#: as a vessel standing on nothing -- a different drawing, and one no
#: comparison of the two specs could see, because the state was dropped
#: on the way *out* and both directions therefore agreed.
#: :data:`_BALLOON_KEYS`'s comment is the same lesson learned on the
#: instrument side.
#:
#: Only the class that *declares* the keyword is named, as the tables
#: above name theirs: ``_takes`` matches by inheritance, so every device
#: subclass takes what its base takes.
_KIND_COMPOSITION: dict[str, tuple[str, ...]] = {}
for _name, _cls in _CLASSES.items():
    for _key in _cls.__dict__.get("COMPOSITION", {}):
        _KIND_COMPOSITION[_key] = tuple(sorted((*_KIND_COMPOSITION.get(_key, ()), _name)))
#: Every table above whose keys are constructor arguments only some
#: classes take, in one mapping: what a unit entry may carry beyond
#: :data:`_UNIT_KEYS`, and which classes may carry it.
_KIND_KEYS = {**_VARIABLE_PORTS, **_KIND_SIZES, **_KIND_TEXT, **_KIND_FLAGS,
              **_KIND_FACES, **_KIND_ORDER, **_KIND_COMPOSITION, **_KIND_STAGES}


def from_dict(spec: Mapping[str, Any]) -> Flowsheet:
    """Build a :class:`~pandid.flowsheet.Flowsheet` from a mapping.

    Raises :class:`SpecError` (a :class:`ValueError`) naming the
    offending entry for anything it cannot honour.
    """
    where = "the flowsheet spec"
    data = _mapping(spec, where)
    for key, why in _RETIRED_KEYS.items():
        if key in data:
            raise SpecError(f"{where}: {key!r} is no longer part of the spec: {why}; remove it")
    _check_keys(data, _TOP_KEYS, where)
    if "name" not in data:
        raise SpecError(f"{where} needs a 'name' (the flowsheet's title)")

    scheme = data.get("stream_naming_scheme", "S{n}")
    stream_start = data.get("stream_number_start", DEFAULT_STREAM_NUMBER_START)
    line_scheme = data.get("line_numbering_scheme", DEFAULT_LINE_NUMBERING_SCHEME)
    start = data.get("line_number_start", DEFAULT_LINE_NUMBER_START)
    loop_start = data.get("loop_number_start", DEFAULT_LOOP_NUMBER_START)
    fs = Flowsheet(
        _text(data["name"], f"{where}: 'name'"),
        stream_naming_scheme=_text(scheme, f"{where}: 'stream_naming_scheme'"),
        stream_number_start=_integer(stream_start, f"{where}: 'stream_number_start'"),
        line_numbering_scheme=_text(line_scheme, f"{where}: 'line_numbering_scheme'"),
        line_number_start=_integer(start, f"{where}: 'line_number_start'"),
        loop_number_start=_integer(loop_start, f"{where}: 'loop_number_start'"),
        auto_faces=_flag(data.get("auto_faces", True), f"{where}: 'auto_faces'"),
    )

    for i, entry in enumerate(_sequence(data.get("components", []), "components")):
        fs.add_component(_read_component(entry, f"components[{i}]"))

    for i, entry in enumerate(_sequence(data.get("units", []), "units")):
        _read_unit(fs, entry, f"units[{i}]")

    for i, entry in enumerate(_sequence(data.get("loops", []), "loops")):
        _read_loop(fs, entry, f"loops[{i}]")
    # After the section, not during it: reading a hand-written spec is
    # the same declaration as typing the same calls, so a number left
    # out here takes the sheet's next one exactly as `add_loop()` would.
    # What is restored is the state AFTER those declarations -- how many
    # numbers the sheet has spent -- which the file records only as the
    # numbers themselves.
    fs._resume_loop_numbering()

    # Instruments are created before the streams so a controller output
    # can be connected, but attached afterwards because a balloon may
    # hang off a line that does not exist yet.
    pending = []
    for i, entry in enumerate(_sequence(data.get("instruments", []), "instruments")):
        where_i = f"instruments[{i}]"
        mapping = _mapping(entry, where_i)
        # A primary element's balloon is anchored to a unit that already
        # exists, so it needs none of the deferral below.
        if "balloon_of" in mapping:
            _read_balloon(fs, mapping, where_i)
            continue
        pending.append((_read_instrument(fs, entry, where_i), mapping, where_i))

    for i, entry in enumerate(_sequence(data.get("streams", []), "streams")):
        _read_stream(fs, entry, f"streams[{i}]")

    for inst, entry, where_i in pending:
        _attach_instrument(fs, inst, entry, where_i)

    fs.stream_table_sections = [
        _read_section(entry, f"stream_table_sections[{i}]")
        for i, entry in enumerate(_sequence(data.get("stream_table_sections", []),
                                            "stream_table_sections"))
    ]
    if "stream_table" in data:
        fs.stream_table = _read_stream_table(data["stream_table"], "stream_table")
    if "title_block" in data:
        fs.title_block = _read_title_block(data["title_block"], "title_block")
    for i, entry in enumerate(_sequence(data.get("annotations", []), "annotations")):
        fs.add_annotation(_read_annotation(fs, entry, f"annotations[{i}]"))
    return fs


def _read_component(entry: Any, where: str) -> Component:
    if isinstance(entry, str):
        return Component(entry)
    data = _mapping(entry, where)
    _check_keys(data, _COMPONENT_KEYS, where)
    if "name" not in data:
        raise SpecError(f"{where} needs a 'name'")
    formula = data.get("formula")
    return Component(
        _text(data["name"], f"{where}.name"),
        None if formula is None else _text(formula, f"{where}.formula"),
    )


def _takes(cls: type[Unit], owners: tuple[str, ...]) -> bool:
    """Whether ``cls`` is a class that carries a keyed argument.

    The tables above name the class the argument is declared on; a
    subclass inherits the constructor and so inherits the argument.
    """
    return any(issubclass(cls, _CLASSES[owner]) for owner in owners)


def _read_unit(fs: Flowsheet, entry: Any, where: str) -> Unit:
    data = _mapping(entry, where)
    if "kind" not in data:
        raise SpecError(
            f"{where} needs a 'kind' (the equipment type, e.g. 'Pump'); got {dict(data)!r}"
        )
    cls = _resolve_kind(data["kind"], where)
    if "name" not in data:
        raise SpecError(f"{where}: a {cls.__name__} needs a 'name' (its tag, e.g. 'P-101')")
    name = _text(data["name"], f"{where}.name")
    where = f"{where} {name!r}"

    allowed = set(_UNIT_KEYS)
    for key, owners in _KIND_KEYS.items():
        # By inheritance, not by name: the tables above name the class
        # that *declares* the argument, and a ControlValve is a Valve.
        # Matching on the name would refuse every device class an
        # argument its own constructor accepts.
        if _takes(cls, owners):
            allowed.add(key)
        elif key in data:
            takers = " or ".join(f"a {owner}" for owner in owners)
            raise SpecError(f"{where}: only {takers} takes {key!r}, not a {cls.__name__}")
    _check_keys(data, allowed, where)

    kwargs: dict[str, Any] = {}
    for key in ("variant", "description", "reference"):
        if key in data:
            kwargs[key] = _text(data[key], f"{where}.{key}")
    for key in ("width", "height"):
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    for key in _VARIABLE_PORTS:
        if key in data:
            kwargs[key] = _integer(data[key], f"{where}.{key}")
    for key in _KIND_SIZES:
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    for key in _KIND_TEXT:
        if key in data:
            kwargs[key] = _text(data[key], f"{where}.{key}")
    for key in _KIND_FLAGS:
        if key in data:
            kwargs[key] = _flag(data[key], f"{where}.{key}")
    for key in _KIND_FACES:
        if key in data:
            kwargs[key] = _faces(data[key], f"{where}.{key}")
    for key in _KIND_STAGES:
        if key in data:
            kwargs[key] = _stages(data[key], f"{where}.{key}")
    # The parts drawn *in* the body, where ``variant`` above chose the
    # body. The class's own default says which of the two shapes a value
    # takes, so nothing here has to know that ``trays`` counts and the
    # rest name.
    for key, default in cls.COMPOSITION.items():
        if key in data:
            kwargs[key] = _composed(data[key], default, f"{where}.{key}")
    try:
        unit = cls(name, **kwargs)
    except ValueError as e:
        raise _fail_from(e, where) from None

    _read_common(fs, unit, data, where)
    # After ``_read_common``, whose ``port_faces`` decides which face a
    # connection is on; this orders what is on one. The gate above
    # already refuses the key on anything but a Block, a Tank or a
    # Vessel, so the isinstance is for the type checker rather than a
    # second guard.
    if "port_order" in data and isinstance(unit, (unit_types.Block, unit_types.Tank,
                                                   unit_types.Vessel)):
        _read_port_order(unit, data["port_order"], f"{where}.port_order")
    return unit


def _read_loop(fs: Flowsheet, entry: Any, where: str) -> Loop:
    """Read one declared control loop.

    A loop's members carry their whole tag, so the section says only
    that the loop was declared. The rule a loop enforces, that a
    balloon's first letter is the loop's measured variable, is checked
    where the letters are typed, and in a spec they are typed once, on
    the instrument itself.

    ``number`` is optional and omitting it allocates, exactly as
    omitting the argument to
    :meth:`~pandid.flowsheet.Flowsheet.add_loop` does. The spec is the
    same declaration in another language and a hand-written one is
    drafted the same way, so ``loop_number_start`` would be unreachable
    from a file if the number stayed compulsory here. It does not cost
    the round trip anything: :func:`to_dict` writes every loop's number
    out as a literal, so a spec this module *wrote* never leaves one to
    be allocated and reads back frozen.
    """
    data = _mapping(entry, where)
    _check_keys(data, _LOOP_KEYS, where)
    if "variable" not in data:
        raise SpecError(
            f"{where} needs a 'variable': a loop is identified by what it measures "
            "and its number together, e.g. {variable: F, number: 303} for loop F-303. "
            "The number may be left out to take the sheet's next one; the variable "
            "may not, because nothing else on the sheet knows what this loop measures"
        )
    number = data.get("number")
    if number is not None and (not isinstance(number, (str, int)) or isinstance(number, bool)):
        raise SpecError(f"{where}.number must be a loop number or text, got {number!r}")
    try:
        return fs.add_loop(_text(data["variable"], f"{where}.variable"), number)
    except ValueError as e:
        raise _fail_from(e, where) from None


def _read_instrument(fs: Flowsheet, entry: Any, where: str) -> Instrument:
    data = _mapping(entry, where)
    _check_keys(data, _INSTRUMENT_KEYS, where)
    if "type" not in data:
        raise SpecError(
            f"{where} needs a 'type': the ISA functional letters, e.g. "
            "{type: FT, number: 101} for FT-101"
        )
    type_ = _text(data["type"], f"{where}.type")
    number = data.get("number", "")
    if not isinstance(number, (str, int)) or isinstance(number, bool):
        raise SpecError(f"{where}.number must be a loop number or text, got {number!r}")

    kwargs: dict[str, Any] = {}
    for key in ("variant", "display", "description", "reference"):
        if key in data:
            kwargs[key] = _text(data[key], f"{where}.{key}")
    for key in ("width", "height"):
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    try:
        inst = Instrument(type_, number, **kwargs)
    except ValueError as e:
        raise _fail_from(e, where) from None
    if "quadrants" in data:
        _annotate_instrument(inst, data["quadrants"], f"{where}.quadrants")
    _read_common(fs, inst, data, f"{where} {inst.name!r}")
    return inst


def _annotate_instrument(inst: Instrument, entry: Any, where: str) -> None:
    """Apply an instrument entry's ``quadrants:`` mapping."""
    data = _mapping(entry, where)
    _check_keys(data, set(_QUADRANT_KEYS), where)
    codes: dict[str, Any] = {}
    for key, value in data.items():
        codes[key] = ([_text(v, f"{where}.{key}[{i}]") for i, v in enumerate(value)]
                      if isinstance(value, (list, tuple))
                      else _text(value, f"{where}.{key}"))
    try:
        inst.annotate(**codes)
    except ValueError as e:
        raise _fail_from(e, where) from None


def _read_common(fs: Flowsheet, unit: Unit, data: Mapping[str, Any], where: str) -> None:
    """Apply the shared fields, then register the unit on the sheet."""
    if "label_pos" in data:
        unit.label_pos = _text(data["label_pos"], f"{where}.label_pos")
    if "new_line_number" in data:
        unit.new_line_number = _flag(data["new_line_number"], f"{where}.new_line_number")
    try:
        fs.add(unit)
    except ValueError as e:
        raise _fail_from(e, where) from None
    if "pin" in data:
        _read_pin(unit, data["pin"], f"{where}.pin")
    if "port_faces" in data:
        _read_port_faces(unit, data["port_faces"], f"{where}.port_faces")


def _read_balloon(fs: Flowsheet, entry: Mapping[str, Any], where: str) -> Instrument:
    """A primary element's balloon; see ``Flowsheet.add_balloon``.

    An instrument entry rather than a key on the element's, even though
    it carries the element's tag, because a spec is read back in the
    order it was written and this is the order the balloon was made in.
    """
    _check_keys(entry, _BALLOON_KEYS, where)
    name = _text(entry["balloon_of"], f"{where}.balloon_of")
    element = next((u for u in fs.units if u.name == name), None)
    if element is None:
        raise SpecError(
            f"{where}.balloon_of names {name!r}, which is not a unit on this sheet. "
            f"A balloon carries the tag of the element it is drawn for, so that "
            f"element has to be in the 'units:' section"
        )
    kwargs: dict[str, Any] = {}
    if "at" in entry:
        at = entry["at"]
        kwargs["at"] = at if isinstance(at, str) else _number(at, f"{where}.at")
    for key in ("offset", "angle", "width", "height"):
        if key in entry:
            kwargs[key] = _number(entry[key], f"{where}.{key}")
    for key in ("variant", "display", "description", "reference", "label_pos"):
        if key in entry:
            kwargs[key] = _text(entry[key], f"{where}.{key}")
    try:
        inst = fs.add_balloon(element, **kwargs)
    except (TypeError, ValueError) as e:
        raise _fail_from(e, where) from None
    # The rest afterwards rather than through the call: ``add_balloon``
    # is what makes the balloon and puts it on the sheet, so these are
    # set on the object it hands back. ``_read_common``, which does the
    # same for every other unit, is not usable here for that reason.
    if "new_line_number" in entry:
        inst.new_line_number = _flag(entry["new_line_number"], f"{where}.new_line_number")
    if "quadrants" in entry:
        _annotate_instrument(inst, entry["quadrants"], f"{where}.quadrants")
    if "pin" in entry:
        _read_pin(inst, entry["pin"], f"{where}.pin")
    if "port_faces" in entry:
        _read_port_faces(inst, entry["port_faces"], f"{where}.port_faces")
    return inst


def _read_pin(unit: Unit, entry: Any, where: str) -> None:
    data = _mapping(entry, where)
    _check_keys(data, _PIN_KEYS, where)
    kwargs: dict[str, Any] = {}
    for key in ("x", "y"):
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    for key in ("col", "row"):
        if key in data:
            kwargs[key] = _integer(data[key], f"{where}.{key}")
    if "orientation" in data:
        kwargs["orientation"] = data["orientation"]
    if "mirrored" in data:
        kwargs["mirrored"] = data["mirrored"]
    ports = _read_pin_ports(data.get("port"), {a for a in ("x", "y") if a in kwargs},
                            f"{where}.port")
    for axis, name in ports.items():
        # Through the same door ``port_faces`` uses, so a nozzle a
        # pooled connection mints is found and a misspelt one is named
        # against the key that misspelt it rather than raising a
        # ``KeyError`` out of ``pin()``.
        _find_port(unit, name, f"{where}.port.{axis}")
    try:
        # Split by what each coordinate was measured to, because that is
        # what ``pin()`` takes: one call per nozzle, and one for the
        # axes that are the corner itself.
        #
        # ``port=None`` on that first call and never the default: a
        # written coordinate carrying no ``port`` is a corner, including
        # a flag's, which :meth:`~pandid.units.Unit.pin` would otherwise
        # read back as its nozzle and move by an offset the write never
        # took out. The transform and the grid ride with it, so a pin
        # stating nothing but ``orientation`` still lands.
        unit.pin(port=None,
                 **{axis: value for axis, value in kwargs.items() if axis not in ports})
        for nozzle in dict.fromkeys(ports.values()):
            unit.pin(port=nozzle,
                     **{axis: kwargs[axis] for axis, p in ports.items() if p == nozzle})
    except ValueError as e:
        raise _fail_from(e, where) from None


def _read_pin_ports(entry: Any, stated: set[str], where: str) -> dict[str, str]:
    """``port:`` on a written pin, as ``{axis: nozzle}``.

    Two spellings, because the ordinary pin measures both coordinates to
    one nozzle and the exceptional one does not. ``port: inlet`` names
    it for every coordinate the pin states -- the shape
    :meth:`~pandid.units.Unit.pin` itself takes -- and
    ``port: {y: inlet}`` names it per axis, which is the only way to
    write a pin whose x is a corner and whose y is a nozzle. Naming a
    *different* nozzle per axis is not a contradiction and is written
    exactly that way: two calls measured two coordinates to two things.

    ``stated`` is the axes this pin actually gives a coordinate for, and
    every rule below is the same rule: **a port that measures nothing is
    refused rather than dropped.** A nozzle named for an axis the pin
    does not state is the author saying where something goes and the
    reader silently not putting it there, which is the defect this whole
    change is about -- so it raises here, against the key that says it.

    The sentence is :func:`~pandid.portgeom.unmeasured_port`'s, which is
    also what :meth:`pandid.units.Unit.pin` refuses the same shape with.
    Only the *path* is this module's: a key can say which axis it went
    wrong on and a keyword argument cannot, and that is the whole of the
    difference between the two doors.
    """
    key = where.rsplit(".", 1)[-1]
    if entry is None:
        return {}
    if not isinstance(entry, (str, Mapping)):
        raise SpecError(
            f"{where} names the nozzle a coordinate was measured to: either one "
            f"name for every coordinate this pin states (port: inlet) or one per "
            f"axis (port: {{y: inlet}}), got {type(entry).__name__}: {entry!r}"
        )
    if isinstance(entry, str):
        if not stated:
            raise SpecError(f"{where}: {unmeasured_port(entry, ('x', 'y'), key)}")
        return dict.fromkeys(sorted(stated), entry)
    axes = _mapping(entry, where)
    _check_keys(axes, {"x", "y"}, where)
    if not axes:
        raise SpecError(f"{where} names no axis; give port: {{x: ...}} or drop port")
    for axis, name in axes.items():
        if axis not in stated:
            raise SpecError(f"{where}.{axis}: "
                            + unmeasured_port(_text(name, f"{where}.{axis}"),
                                              (axis,), f"{key}.{axis}"))
    return {axis: _text(name, f"{where}.{axis}") for axis, name in axes.items()}


def _read_port_faces(unit: Unit, entry: Any, where: str) -> None:
    for port_name, face in _mapping(entry, where).items():
        _find_port(unit, port_name, where)
        try:
            unit.nozzle(port_name, _text(face, f"{where}.{port_name}"))
        except ValueError as e:
            raise _fail_from(e, f"{where}.{port_name}") from None


def _read_port_order(
    unit: "unit_types.Block | unit_types.Tank | unit_types.Vessel", entry: Any, where: str
) -> None:
    """``port_order: {S: [out_2, in_2]}``: one ``order_on`` per face."""
    for face, names in _mapping(entry, where).items():
        at = f"{where}.{face}"
        ports = [_find_port(unit, name, at)
                 for name in _sequence(names, at)]
        try:
            unit.order_on(_text(face, at), ports)
        except ValueError as e:
            raise _fail_from(e, at) from None


def _find_port(unit: Unit, name: Any, where: str) -> Port:
    # A pooled connection is minted per line rather than declared, so a
    # spec names exactly the members its sheet had grown -- a balloon's
    # ``sig_out_2`` on a split-range loop, a flag's ``outlet_2`` on a
    # header serving two users. Asking the *unit* for the name is what
    # makes ``from_dict(to_dict(fs))`` rebuild either.
    if isinstance(name, str) and name not in unit.ports:
        minted = unit._mint_port(name)
        if minted is not None:
            return minted
    # ``_canonical_port_name`` first: a live alias like ``Reactor.feed``/
    # ``Column.feed`` is a plain attribute rather than a second entry in
    # ``ports`` (see its own docstring), so a spec naming it would
    # otherwise read as a port that does not exist. It resolves to a name
    # ``ports`` really holds, which is what the checks below want.
    if isinstance(name, str):
        name = unit._canonical_port_name(name)
    # A retired nozzle -- one a class still answers for one release after it
    # stopped building it outright, e.g. a plain Column's ``reflux_in`` (see
    # Unit._RETIRED_PORTS/_RETIRED_PORT_ALIASES) -- is not in ``unit.ports``
    # until something reads it by name, which is exactly what an author's own
    # script did to connect a stream there in the first place. ``to_dict()``
    # writes that stream out under the retired name because that really is
    # the port it is on, so without this ``from_dict()`` could not read the
    # very sheet it just wrote -- the grace period breaking its own round
    # trip. ``getattr`` is what mints it, warning the same way the author's
    # script did.
    #
    # After the canonicalisation above, and not before: an alias names a
    # port that exists, a retired nozzle names one that has to be minted,
    # and only the second wants ``getattr``.
    if isinstance(name, str) and name not in unit.ports:
        try:
            retired = getattr(unit, name)
        except AttributeError:
            retired = None
        if isinstance(retired, Port):
            return retired
    if not isinstance(name, str) or name not in unit.ports:
        raise SpecError(
            f"{where}: {type(unit).__name__} {unit.name!r} has no port {name!r}"
            f"{_suggest(name, unit.ports)}; available ports: {sorted(unit.ports)}"
        )
    return unit.ports[name]


def _find_unit(fs: Flowsheet, name: str, where: str) -> Unit:
    for unit in fs.units:
        if unit.name == name:
            return unit
    names = [u.name for u in fs.units]
    raise SpecError(
        f"{where}: no unit named {name!r} on this flowsheet{_suggest(name, names)}; "
        f"declared units: {sorted(names)}"
    )


def _read_endpoint(fs: Flowsheet, entry: Any, where: str) -> Port:
    if isinstance(entry, Mapping):
        _check_keys(entry, {"unit", "port"}, where)
        missing = [key for key in ("unit", "port") if key not in entry]
        if missing:
            raise SpecError(f"{where}: an endpoint mapping needs {missing}; got {dict(entry)!r}")
        unit_name, port_name = entry["unit"], entry["port"]
    elif isinstance(entry, Sequence) and not isinstance(entry, (str, bytes)):
        if len(entry) != 2:
            raise SpecError(
                f"{where}: an endpoint is [unit, port] (exactly two items), got {list(entry)!r}"
            )
        unit_name, port_name = entry
    else:
        raise SpecError(
            f"{where}: an endpoint is [unit, port] (a two-item list) or "
            f"{{unit: ..., port: ...}}, got {entry!r}"
        )
    unit = _find_unit(fs, _text(unit_name, f"{where}: the unit name"), where)
    return _find_port(unit, port_name, where)


def _read_stream(fs: Flowsheet, entry: Any, where: str) -> Stream:
    data = _mapping(entry, where)
    _check_keys(data, _STREAM_KEYS, where)
    for key in ("from", "to"):
        if key not in data:
            raise SpecError(
                f"{where}: a connection needs both 'from' and 'to'; {key!r} is missing "
                f"from {dict(data)!r}"
            )
    src = _read_endpoint(fs, data["from"], f"{where}.from")
    dst = _read_endpoint(fs, data["to"], f"{where}.to")
    kwargs: dict[str, Any] = {}
    if "kind" in data:
        kwargs["kind"] = _text(data["kind"], f"{where}.kind")
    if "name" in data:
        kwargs["name"] = _text(data["name"], f"{where}.name")
    if "draw_as_recycle" in data:
        kwargs["draw_as_recycle"] = _flag(data["draw_as_recycle"], f"{where}.draw_as_recycle")
    if "ends" in data:
        kwargs["ends"] = _read_ends(data["ends"], f"{where}.ends")
    for key in LINE_NUMBER_FIELDS:
        if key in data:
            kwargs[key] = _component(data[key], f"{where}.{key}")
    try:
        stream = fs.connect(src, dst, **kwargs)
    except ValueError as e:
        raise _fail_from(e, where) from None

    for key in ("color", "dasharray"):
        if key in data:
            setattr(stream, key, _text(data[key], f"{where}.{key}"))
    if "properties" in data:
        stream.properties = _read_properties(data["properties"], f"{where}.properties")
    if "tabulate" in data:
        stream.tabulate = _flag(data["tabulate"], f"{where}.tabulate")
    if "via" in data:
        stream.via(_read_waypoints(data["via"], f"{where}.via"))
    return stream


def _read_ends(entry: Any, where: str) -> "str | tuple[str, str]":
    """How a line's two joints are made: a name, or ``[source, dest]``.

    The name itself is not checked here. ``connect()`` checks it against
    :data:`~pandid.render.svg.CONNECTIONS` and raises with the accepted
    spellings in the message, and one list of them beats two.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, (list, tuple)) and len(entry) == 2:
        return (_text(entry[0], f"{where}[0]"), _text(entry[1], f"{where}[1]"))
    raise SpecError(
        f"{where} must be a connection name for both ends or a two-item "
        f"[source, dest] list, got {entry!r}"
    )


def _read_properties(entry: Any, where: str) -> dict[str, str | float]:
    out: dict[str, str | float] = {}
    for key, value in _mapping(entry, where).items():
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise SpecError(
                f"{where}[{key!r}] must be text or a number (values carry their own "
                f"units, e.g. '25 C'), got {value!r}"
            )
        out[key] = value
    return out


def _read_waypoints(entry: Any, where: str) -> list[tuple[float, float]]:
    points = []
    for i, item in enumerate(_sequence(entry, where)):
        pair = _sequence(item, f"{where}[{i}]")
        if len(pair) != 2:
            raise SpecError(f"{where}[{i}]: a waypoint is [x, y], got {pair!r}")
        points.append((_number(pair[0], f"{where}[{i}].x"), _number(pair[1], f"{where}[{i}].y")))
    return points


def _read_host(fs: Flowsheet, entry: Any, where: str) -> Stream | Unit:
    """Resolve an instrument's anchor: a unit or stream, or a port."""
    if isinstance(entry, str):
        unit = next((u for u in fs.units if u.name == entry), None)
        stream = next((s for s in fs.streams if s.name == entry), None)
        if unit is not None and stream is not None:
            raise SpecError(
                f"{where}: {entry!r} names both a unit and a stream; identify the stream "
                "as [unit, port] (the port it leaves from) instead"
            )
        if unit is not None:
            return unit
        if stream is not None:
            return stream
        names = [u.name for u in fs.units] + [s.name for s in fs.streams if not s.auto_named]
        raise SpecError(
            f"{where}: nothing named {entry!r} to attach to{_suggest(entry, names)}; "
            f"hosts available: {sorted(names)}"
        )
    port = _read_endpoint(fs, entry, where)
    if port.stream is None:
        raise SpecError(
            f"{where}: {port.owner.name}.{port.name} carries no stream, so there is no "
            "line to tap; attach to a connected port or name the unit itself"
        )
    return port.stream


def _attach_instrument(fs: Flowsheet, inst: Instrument, data: Mapping[str, Any],
                       where: str) -> None:
    where = f"{where} {inst.name!r}"
    named = [key for key in _ANCHOR_KEYS if key in data]
    if len(named) > 1:
        raise SpecError(
            f"{where}: a balloon is anchored to one thing, and this entry named "
            f"{len(named)} ({', '.join(repr(k) for k in named)}). Which one decides "
            f"what is drawn between them: 'sensing' and 'acting_on' draw a "
            f"connection, 'near' draws nothing"
        )
    if not named:
        stray = [key for key in ("at", "offset", "angle") if key in data]
        if stray:
            raise SpecError(
                f"{where}: {stray} only mean something with one of "
                f"{', '.join(repr(k) for k in _ANCHOR_KEYS)}: the stream or unit the "
                f"balloon is placed against"
            )
        return
    relation = named[0]
    host = _read_host(fs, data[relation], f"{where}.{relation}")
    kwargs: dict[str, Any] = {"relation": relation}
    if "at" in data:
        at = data["at"]
        kwargs["at"] = at if isinstance(at, str) else _number(at, f"{where}.at")
    for key in ("offset", "angle"):
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    try:
        inst.attach(host, **kwargs)
    except (TypeError, ValueError) as e:
        raise _fail_from(e, where) from None


def _read_section(entry: Any, where: str) -> tuple[str, str]:
    pair = _sequence(entry, where)
    if len(pair) != 2:
        raise SpecError(
            f"{where}: a section is [before_key, heading] (the property row the heading "
            f"is injected above), got {pair!r}"
        )
    return _text(pair[0], f"{where}[0]"), _text(pair[1], f"{where}[1]")


def _read_stream_table(entry: Any, where: str) -> StreamTableOptions:
    """``stream_table:`` -- how the table is drawn, not what is in it.

    ``font_size`` takes ``null`` as itself, which is the field's own
    default and means *let the table pick one*. So the reader
    distinguishes an absent key from a stated null only in that both
    land on the same value, and a spec may state the default back
    explicitly without being told it is wrong.

    The two widths have no such spelling -- their default is a number,
    not *unset* -- so ``null`` is refused there rather than read as
    "leave it alone". Whether a stated floor is a *usable* one is the
    layout's question, exactly as it is for ``font_size``: this reader
    settles the kind of the value and the sheet settles its sense.
    """
    data = _mapping(entry, where)
    _check_keys(data, {f.name for f in dataclass_fields(StreamTableOptions)}, where)
    options = StreamTableOptions()
    if data.get("font_size") is not None:
        options.font_size = _number(data["font_size"], f"{where}.font_size")
    if "label_width" in data:
        options.label_width = _column_width(data["label_width"], f"{where}.label_width")
    if "column_width" in data:
        options.column_width = _column_width(data["column_width"], f"{where}.column_width")
    return options


def _read_title_block(entry: Any, where: str) -> TitleBlock:
    data = _mapping(entry, where)
    allowed = {f.name for f in dataclass_fields(TitleBlock)}
    _check_keys(data, allowed, where)
    kwargs: dict[str, Any] = {
        key: _text(value, f"{where}.{key}") for key, value in data.items() if key != "revisions"
    }
    revisions = []
    for i, item in enumerate(_sequence(data.get("revisions", []), f"{where}.revisions")):
        rev_where = f"{where}.revisions[{i}]"
        rev = _mapping(item, rev_where)
        _check_keys(rev, {f.name for f in dataclass_fields(Revision)}, rev_where)
        revisions.append(
            Revision(**{key: _text(value, f"{rev_where}.{key}") for key, value in rev.items()})
        )
    return TitleBlock(revisions=revisions, **kwargs)


_ANNOTATION_KEYS = {
    "annotation": {"type", "title", "rows", "align", "position", "margin", "width", "font_size"},
    "table": {"type", "title", "headers", "rows", "align", "position", "margin", "font_size",
              "col_align"},
    "equipment_list": {"type", "title", "align", "position", "margin", "width", "include"},
    "notes": {"type", "title", "items", "align", "position", "margin", "width", "numbered"},
    "legend": {"type", "title", "entries", "align", "position", "margin", "width"},
}


def _read_placement(data: Mapping[str, Any], where: str) -> dict[str, Any]:
    """The ``align``/``position``/``margin`` trio every box shares."""
    out: dict[str, Any] = {}
    if "align" in data:
        out["align"] = _text(data["align"], f"{where}.align")
    if "position" in data:
        pair = _sequence(data["position"], f"{where}.position")
        if len(pair) != 2:
            raise SpecError(
                f"{where}.position: an absolute placement is [x, y] (the box's top-left "
                f"corner), got {pair!r}"
            )
        out["position"] = (_number(pair[0], f"{where}.position[0]"),
                           _number(pair[1], f"{where}.position[1]"))
    for key in ("margin", "width", "font_size"):
        if key in data:
            out[key] = _number(data[key], f"{where}.{key}")
    return out


def _read_rows(entry: Any, where: str) -> list:
    """Annotation rows: a plain line, or cells aligned in columns."""
    rows: list = []
    for i, row in enumerate(_sequence(entry, where)):
        if isinstance(row, str):
            rows.append(row)
        else:
            cells = _sequence(row, f"{where}[{i}]")
            rows.append(tuple(_text(c, f"{where}[{i}][{j}]") for j, c in enumerate(cells)))
    return rows


def _read_annotation(fs: Flowsheet, entry: Any, where: str) -> Annotation | TableBox:
    data = _mapping(entry, where)
    kind = data.get("type", "annotation")
    if kind not in _ANNOTATION_KEYS:
        raise SpecError(
            f"{where}: unknown box type {kind!r}{_suggest(kind, _ANNOTATION_KEYS)}; "
            f"available types: {sorted(_ANNOTATION_KEYS)}"
        )
    _check_keys(data, _ANNOTATION_KEYS[kind], where)
    kwargs = _read_placement(data, where)
    if "title" in data:
        kwargs["title"] = _text(data["title"], f"{where}.title")

    try:
        if kind == "equipment_list":
            include = data.get("include")
            if include is not None:
                include = [_text(t, f"{where}.include") for t in _sequence(include,
                                                                          f"{where}.include")]
            return equipment_list(fs, include=include, **kwargs)
        if kind == "notes":
            if "items" not in data:
                raise SpecError(f"{where}: a notes box needs 'items' (the list of note texts)")
            items = [_text(t, f"{where}.items") for t in _sequence(data["items"], f"{where}.items")]
            if "numbered" in data:
                kwargs["numbered"] = _flag(data["numbered"], f"{where}.numbered")
            return notes(items, **kwargs)
        if kind == "legend":
            if "entries" not in data:
                raise SpecError(f"{where}: a legend box needs 'entries' (abbreviation -> meaning)")
            entries = data["entries"]
            pairs = (list(entries.items()) if isinstance(entries, Mapping)
                     else [tuple(_sequence(e, f"{where}.entries")) for e in
                           _sequence(entries, f"{where}.entries")])
            return legend(pairs, **kwargs)
        if kind == "table":
            if "headers" in data:
                kwargs["headers"] = [_text(h, f"{where}.headers")
                                     for h in _sequence(data["headers"], f"{where}.headers")]
            if "col_align" in data:
                kwargs["col_align"] = [_text(a, f"{where}.col_align")
                                       for a in _sequence(data["col_align"], f"{where}.col_align")]
            kwargs["rows"] = [_sequence(row, f"{where}.rows[{i}]")
                              for i, row in enumerate(_sequence(data.get("rows", []),
                                                                f"{where}.rows"))]
            return TableBox(**kwargs)
        kwargs["rows"] = _read_rows(data.get("rows", []), f"{where}.rows")
        return Annotation(**kwargs)
    except SpecError:
        raise  # already carries its own path
    except ValueError as e:
        raise _fail_from(e, where) from None  # e.g. a bad align=


# --------------------------------------------------------------
# Writing: Flowsheet -> spec
# --------------------------------------------------------------

_MIRROR_NAMES = {(True, False): "x", (False, True): "y", (True, True): "xy"}


def to_dict(fs: Flowsheet) -> dict:
    """Serialize a flowsheet to a spec :func:`from_dict` reads back.

    Only what differs from a default is written, so the output stays a
    file a human can read and edit. Placement *results* (``Frame``,
    routed paths, computed stream numbers) are left out: they are the
    engine's output, not the author's intent, and re-deriving them is
    the whole point of the engine.
    """
    if not isinstance(fs.stream_naming_scheme, str):
        raise SpecError(
            "a callable stream_naming_scheme cannot be written to a spec; use a format "
            "string such as 'S{n}'"
        )
    if not isinstance(fs.line_numbering_scheme, str):
        raise SpecError(
            "a callable line_numbering_scheme cannot be written to a spec; use a format "
            f"string such as {DEFAULT_LINE_NUMBERING_SCHEME!r}"
        )
    spec: dict[str, Any] = {"name": fs.name}
    if fs.stream_naming_scheme != "S{n}":
        spec["stream_naming_scheme"] = fs.stream_naming_scheme
    if fs.stream_number_start != DEFAULT_STREAM_NUMBER_START:
        spec["stream_number_start"] = fs.stream_number_start
    if fs.line_numbering_scheme != DEFAULT_LINE_NUMBERING_SCHEME:
        spec["line_numbering_scheme"] = fs.line_numbering_scheme
    if fs.line_number_start != DEFAULT_LINE_NUMBER_START:
        spec["line_number_start"] = fs.line_number_start
    # Written even though every loop below carries a literal number, so
    # nothing in the file needs it to read the sheet back. It is here
    # for the edit after: a loop added by hand tomorrow should land in
    # this sheet's series rather than at 1.
    if fs.loop_number_start != DEFAULT_LOOP_NUMBER_START:
        spec["loop_number_start"] = fs.loop_number_start
    if not fs.auto_faces:
        spec["auto_faces"] = False
    if fs.components:
        spec["components"] = [
            c.name if c.formula is None else {"name": c.name, "formula": c.formula}
            for c in fs.components
        ]

    equipment = [u for u in fs.units if not isinstance(u, Instrument)]
    instruments = [u for u in fs.units if isinstance(u, Instrument)]
    if equipment:
        spec["units"] = [_write_unit(u) for u in equipment]
    # A sheet that declared no loop writes no section, so a spec written
    # before loops existed and one written after are the same file.
    if fs.loops:
        spec["loops"] = [{"variable": loop.variable, "number": loop.number}
                         for loop in fs.loops]
    if instruments:
        spec["instruments"] = [_write_instrument(u) for u in instruments]
    if fs.streams:
        spec["streams"] = [_write_stream(s) for s in fs.streams]
    if fs.stream_table_sections:
        spec["stream_table_sections"] = [list(sec) for sec in fs.stream_table_sections]
    # Only what was changed, so a spec written by a sheet that left the
    # table alone is the same file it was before these options existed.
    table = {f.name: getattr(fs.stream_table, f.name)
             for f in dataclass_fields(StreamTableOptions)
             if getattr(fs.stream_table, f.name) != f.default}
    if table:
        spec["stream_table"] = table
    if fs.title_block is not None:
        spec["title_block"] = _write_title_block(fs.title_block)
    if fs.annotations:
        spec["annotations"] = [_write_annotation(a) for a in fs.annotations]
    return spec


def _write_common(unit: Unit, entry: dict[str, Any]) -> dict[str, Any]:
    if unit.variant != "default":
        entry["variant"] = unit.variant
    if unit.description:
        entry["description"] = unit.description
    if unit.reference:
        entry["reference"] = unit.reference
    for key in ("width", "height", "label_pos"):
        if getattr(unit, key) is not None:
            entry[key] = getattr(unit, key)
    if unit.new_line_number:
        entry["new_line_number"] = True
    return entry


def _write_composition(unit: Unit, entry: dict[str, Any]) -> dict[str, Any]:
    """The parts asked for, where they are not the ones the class draws.

    Written the way everything else here is -- only what differs from a
    default -- and the defaults come from the class, through the same
    call its constructor makes. They have to: a reactor's agitator and a
    column's internals follow from the *body*, since a stirred shell
    gets a stirrer and a tubular one does not, so a table here would be
    that rule written down a second time and free to disagree with the
    first.

    ``None`` is written out as ``null`` rather than left off. A stated
    empty is not an unstated one -- ``Column(internals=None)`` is a bare
    shell somebody asked for -- and leaving it off is what read back as
    the eight decks a column draws when nobody says otherwise.

    The unit's own composition goes back in, because one part can rule
    another out: a reactor with internals has no agitator unless one was
    asked for, so the default for ``agitator`` is only knowable
    alongside ``internals``. Asking without it would write
    ``agitator: null`` onto every packed-bed reactor -- true, and noise,
    since reading the file back suppresses it again anyway.
    """
    cls = type(unit)
    stated = {key: getattr(unit, key) for key in cls.COMPOSITION}
    for key, default in cls.composition_defaults(unit.variant, stated).items():
        value = getattr(unit, key)
        if value != default:
            entry[key] = value
    # Where the class folds a keyword into the variant, the two are one
    # word and only one of them may be written. It is the keyword: the
    # variant spelling of a separator's characteristic is deprecated and
    # goes at 0.2.0, so writing the fold back out would hand the reader
    # a warning today and a refusal then -- on a sheet nobody had
    # edited. ``_write_instrument`` drops a folded variant for the same
    # reason and by the same means.
    folded = cls.COMPOSITION_VARIANT
    if folded and entry.get(folded) is not None:
        entry.pop("variant", None)
    return entry


def _write_placement(unit: Unit, entry: dict[str, Any]) -> dict[str, Any]:
    if unit.pin_ is not None:
        pin: dict[str, Any] = {}
        # The coordinates as the author gave them, and the nozzle each
        # was measured to. Writing ``pin_``'s corner instead -- which is
        # what this did -- writes the *consequence* of a placement under
        # one transform, so a sheet written and read back was the #294
        # defect again, with the relation that survives a turn thrown
        # away at the file boundary. A relation is what has to be
        # written, exactly as it is what has to be stored.
        intent = pin_intent(unit)
        for key in ("x", "y"):
            if key in intent:
                pin[key] = intent[key][1]
        for key in ("col", "row"):
            value = getattr(unit.pin_, key)
            if value is not None:
                pin[key] = value
        named = {axis: port for axis, (port, _) in intent.items() if port is not None}
        if named:
            # One nozzle for every stated axis is the ordinary case and
            # is written as ``pin()`` takes it: ``port: inlet``. The
            # axis-by-axis mapping is for the pin built out of two calls
            # that named different nozzles, or only one of them, which
            # no shorthand can say.
            ports = set(named.values())
            pin["port"] = (ports.pop() if len(ports) == 1 and len(named) == len(intent)
                           else dict(sorted(named.items())))
        if unit.pin_.orientation:
            pin["orientation"] = int(unit.pin_.orientation)
        mirror = _MIRROR_NAMES.get((unit.pin_.mirrored, unit.pin_.mirror_y))
        if mirror:
            pin["mirrored"] = mirror
        entry["pin"] = pin
    if unit._port_faces:
        entry["port_faces"] = dict(unit._port_faces)
    return entry


def _write_connection_faces(unit, entry: dict[str, Any],
                            default_input: str, default_output: str,
                            omit_bare_single: bool = False) -> None:
    """``inputs``/``outputs``/``port_order``, for :class:`Block` and for
    :class:`~pandid.units.Tank`/:class:`~pandid.units.Vessel`'s own
    family mechanism -- the same shape, since both hold ``{port: face}``
    in ``_faces`` and answer through :attr:`input_faces`/
    :attr:`output_faces`/:meth:`ports_on`; only where the *default* face
    comes from differs, which is why the caller resolves it first.

    The two families are written as the bare count where every
    connection is on its default face, which is the shorthand the
    constructor takes; one that puts an input on a face the default
    does not name is only describable as a list.

    ``omit_bare_single`` drops a key entirely at a single connection on
    the default face -- ``Tank("TK-1")`` is a whole nozzle set with
    nothing to say, exactly as omitting ``supports=`` is, where
    ``inputs: 1`` would be writing the default down. **Not** set for
    :class:`Block`, which has no connection-free shape to default to at
    all (a block with none is refused outright) and so always writes
    both.

    The order along a face is separate, since the two lists above
    interleave one face's inputs and outputs and cannot carry a
    sequence: an ``order_on()`` that put an output before an input
    would otherwise be written back out drawn the other way round.
    Written only where a face's order is not the declared one.
    """
    for key, faces, default in (
        ("inputs", unit.input_faces, default_input),
        ("outputs", unit.output_faces, default_output),
    ):
        if omit_bare_single and len(faces) == 1 and faces[0] == default:
            continue
        entry[key] = len(faces) if all(f == default for f in faces) else list(faces)
    declared = [port.name for port in (*unit.inlets, *unit.outlets)]
    port_order = {
        face: [port.name for port in unit.ports_on(face)]
        for face in ("N", "S", "E", "W")
    }
    port_order = {
        face: order for face, order in port_order.items()
        if order != [name for name in declared if name in order]
    }
    if port_order:
        entry["port_order"] = port_order


def _write_unit(unit: Unit) -> dict[str, Any]:
    kind = type(unit).__name__
    if kind not in _CLASSES:
        # A spec naming a class the reader cannot construct is worse
        # than no spec at all, so refuse here rather than at whatever
        # reads the file.
        raise SpecError(
            f"{unit.name!r} is a {kind}, which is not one of the built-in equipment "
            f"classes, so it cannot be written to a spec; available kinds: {sorted(_CLASSES)}"
        )
    # The tag, not the name: a header tapped twice is two entries
    # carrying one label, and reading them back re-derives the names the
    # flowsheet tells the taps apart by. A tee has no tag, so its name
    # is written instead.
    entry: dict[str, Any] = {"kind": kind, "name": unit.tag or unit.name}
    _write_common(unit, entry)
    _write_composition(unit, entry)
    if isinstance(unit, unit_types.Block):
        _write_connection_faces(unit, entry, unit.DEFAULT_INPUT_FACE, unit.DEFAULT_OUTPUT_FACE)
    elif isinstance(unit, (unit_types.Tank, unit_types.Vessel)):
        # The same two keys, over the other mechanism that carries them
        # (see ``pandid.units._MultiPortVessel``): the default face is
        # not one fixed string here, since the vendored artwork's own
        # anchor differs by variant, and a single connection on it is
        # dropped rather than written as ``inputs: 1`` -- unlike a
        # Block, a plain ``Tank("TK-1")`` is a whole nozzle set already.
        _write_connection_faces(unit, entry, unit.default_input_face(),
                                unit.default_output_face(), omit_bare_single=True)
    elif isinstance(unit, unit_types.Mixer):
        entry["n_inlets"] = len(unit.inlets)
    elif isinstance(unit, unit_types.Splitter):
        entry["n_outlets"] = len(unit.outlets)
    elif isinstance(unit, (unit_types.Column, unit_types.Reactor)):
        # A single feed is the class's own shape and spells its nozzle
        # `feed`, so writing the count would be writing the default
        # down.
        if len(unit.feeds) > 1:
            entry["n_feeds"] = len(unit.feeds)
        # Only a Column has a stage to name, and only where the author
        # gave one: an unstated ``feed_stages`` is the even spread, which
        # is what leaving the key off already means.
        if isinstance(unit, unit_types.Column) and unit.feed_stages is not None:
            entry["feed_stages"] = list(unit.feed_stages)
        if isinstance(unit, unit_types.Column):
            # Only a Column draws, and only Reactor is silent on the
            # count above -- a draw has no singular spelling to fall
            # back to, so unlike a feed's, zero is the count that means
            # "leave this key off" rather than one.
            if len(unit.draws) > 0:
                entry["n_draws"] = len(unit.draws)
            if unit.draw_stages is not None:
                entry["draw_stages"] = list(unit.draw_stages)
    elif isinstance(unit, unit_types.Tee):
        # Only a returning tee. A takeoff is the ordinary case and is
        # what a tee without the word already is.
        if unit.branch_direction != "outlet":
            entry["branch"] = unit.branch_direction
    elif isinstance(unit, unit_types.Reducer):
        # Only an expansion. A reduction is what a reducer without the
        # word already is, so writing it would be writing the default
        # down.
        if unit.large_end != "inlet":
            entry["large_end"] = unit.large_end
    elif isinstance(unit, unit_types.Conveyor):
        # Always written: it is how long the belt is, and nothing else
        # on the entry records it.
        entry["length"] = unit.length
        # Only when it is not the drawing's own roller or bore. Writing
        # the default down would rewrite every conveyor entry ever
        # exported to say what leaving the key out already says.
        if unit.diameter != unit.default_diameter():
            entry["diameter"] = unit.diameter
    elif isinstance(unit, unit_types._NormallyPositioned):
        # Only when closed. "Open" is not a convention a P&ID draws, it
        # is the absence of one, so writing it down would be writing the
        # default down.
        if unit.normal_position != "open":
            entry["normal_position"] = unit.normal_position
        # Only a valve has an actuator, and only a declared fail
        # position is written: an undeclared valve is one the sheet says
        # nothing about, not one that fails somewhere in particular.
        fail = getattr(unit, "fail", "")
        if fail:
            entry["fail"] = fail
    elif isinstance(unit, _Boundary):
        # Only when set: a flag standing for one line leaving the sheet
        # is the ordinary case, and it is what a flag without the word
        # already means.
        if unit.header:
            entry["header"] = True
    return _write_placement(unit, entry)


def _write_instrument(inst: Instrument) -> dict[str, Any]:
    # A primary element's balloon carries the element's tag rather than
    # one of its own, so it is written by naming the element; see
    # :func:`_read_balloon`.
    entry: dict[str, Any] = (
        {"balloon_of": inst._marks.name} if inst._marks is not None
        else {"type": inst.type, "number": inst.number}
    )
    _write_common(inst, entry)
    # The two axes apart again. ``_write_common`` wrote the registry's
    # spelling, which folds them together, and ``panel`` and ``aux``
    # fold to a ``variant`` the constructor refuses: reading such a file
    # back would raise on a sheet nobody had edited.
    entry.pop("variant", None)
    if inst.symbol_type != "default":
        entry["variant"] = inst.symbol_type
    if inst.display != "field":
        entry["display"] = inst.display
    if inst.quadrants:
        by_name = {name: list(codes) for name, letter in _QUADRANT_KEYS.items()
                   for codes in [inst.quadrants.get(letter, ())] if codes}
        if by_name:
            entry["quadrants"] = by_name
    if inst._marks is not None:
        entry["at"] = inst.at
        if inst.offset != 46.0:
            entry["offset"] = inst.offset
        if inst.angle != 90.0:
            entry["angle"] = inst.angle
        # Down the same road as every other unit. A balloon that was
        # pinned or had a nozzle turned is placed where the author put
        # it, and leaving here without writing that dropped it in a way
        # no comparison could see: neither direction carried it, so
        # ``to_dict`` of the sheet read back matched the file it came
        # from while the drawing had moved.
        return _write_placement(inst, entry)
    if inst.host is not None:
        # Name a stream by the port it leaves, not by its number:
        # auto-numbering owns that name and re-derives it as the sheet
        # grows, and a spec must survive that.
        entry[inst.relation] = (
            [inst.host.source.owner.name, inst.host.source.name]
            if isinstance(inst.host, Stream) else inst.host.name
        )
        entry["at"] = inst.at
        if inst.offset != 45.0:
            entry["offset"] = inst.offset
        if inst.angle != 90.0:
            entry["angle"] = inst.angle
    return _write_placement(inst, entry)


def _write_stream(stream: Stream) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "from": [stream.source.owner.name, stream.source.name],
        "to": [stream.dest.owner.name, stream.dest.name],
    }
    if stream.kind != "material":
        entry["kind"] = stream.kind
    if not stream.auto_named:
        entry["name"] = stream.name
    if stream.draw_as_recycle:
        entry["draw_as_recycle"] = True
    for key in LINE_NUMBER_FIELDS:
        value = getattr(stream, key)
        # The sequence auto-numbering assigned is a result, not intent:
        # writing it would pin a number the engine re-derives from the
        # topology.
        if value is not None and not (key == "sequence" and value == stream._auto_sequence):
            entry[key] = value
    for key in ("color", "dasharray"):
        if getattr(stream, key) is not None:
            entry[key] = getattr(stream, key)
    if stream.ends is not None:
        # A pair goes out as a list, which is what it came in as and
        # what YAML writes anyway; one name for both ends stays one
        # name.
        entry["ends"] = (stream.ends if isinstance(stream.ends, str)
                         else list(stream.ends))
    if stream.route is not None and stream.route.manual:
        entry["via"] = [list(point) for point in stream.route.waypoints]
    if stream.properties:
        entry["properties"] = dict(stream.properties)
    if stream.tabulate:
        entry["tabulate"] = True
    return entry


def _write_title_block(block: TitleBlock) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    for field in dataclass_fields(TitleBlock):
        if field.name == "revisions":
            continue
        value = getattr(block, field.name)
        if value != field.default:
            entry[field.name] = value
    if block.revisions:
        entry["revisions"] = [
            {f.name: getattr(rev, f.name) for f in dataclass_fields(Revision)
             if getattr(rev, f.name)}
            for rev in block.revisions
        ]
    return entry


def _write_annotation(box: Annotation | TableBox) -> dict[str, Any]:
    # equipment_list()/notes()/legend() are constructors, not types:
    # what they build is a plain Annotation, so that is what comes back
    # out. The rows are identical, so the drawing is.
    entry: dict[str, Any] = {"type": "table" if isinstance(box, TableBox) else "annotation"}
    if box.title:
        entry["title"] = box.title
    if isinstance(box, TableBox):
        if box.headers:
            entry["headers"] = list(box.headers)
        entry["rows"] = [list(row) for row in box.rows]
        if box.col_align:
            entry["col_align"] = list(box.col_align)
    else:
        entry["rows"] = [row if isinstance(row, str) else list(row) for row in box.rows]
    entry["align"] = box.align
    if box.position is not None:
        entry["position"] = list(box.position)
    if box.margin:
        entry["margin"] = box.margin
    width = getattr(box, "width", None)  # only Annotation sizes up
    if width is not None:
        entry["width"] = width
    if box.font_size != 11.0:
        entry["font_size"] = box.font_size
    return entry


# --------------------------------------------------------------
# File loaders
# --------------------------------------------------------------


def from_json(path: str | Path) -> Flowsheet:
    """Build a flowsheet from a JSON spec file (stdlib only)."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SpecError(f"{path}: not valid JSON, {e.msg} at line {e.lineno}, column {e.colno}")
    return from_dict(data)


_YAML_LOADER: Any = None


def _core_schema_loader(yaml_module) -> Any:
    """A safe loader restricted to the YAML **1.2** core schema.

    PyYAML implements YAML 1.1, where ``on``, ``off``, ``yes``, ``no``
    and ``N`` are booleans and an unquoted date is a ``datetime.date``.
    That silently turns a balloon's ``at: N`` into ``False`` and a
    revision's ``date:`` into an object: two traps sprung by writing the
    format exactly as documented. YAML 1.2 dropped both, and only
    ``true``/``false`` are booleans here.
    """
    global _YAML_LOADER
    if _YAML_LOADER is None:
        dropped = {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp"}

        class Loader(yaml_module.SafeLoader):
            pass

        Loader.yaml_implicit_resolvers = {
            char: [(tag, pattern) for tag, pattern in resolvers if tag not in dropped]
            for char, resolvers in yaml_module.SafeLoader.yaml_implicit_resolvers.items()
        }
        Loader.add_implicit_resolver(
            "tag:yaml.org,2002:bool",
            re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
            list("tTfF"),
        )
        _YAML_LOADER = Loader
    return _YAML_LOADER


def from_yaml(path: str | Path) -> Flowsheet:
    """Build a flowsheet from a YAML spec file.

    YAML is the friendliest format to hand-write, but parsing it is not
    something the standard library does, so it is the one optional
    extra.
    """
    try:
        import yaml
    except ImportError as e:
        raise ImportError(
            "Reading a flowsheet from YAML needs PyYAML, which is not installed. "
            "Install it with:  pip install 'pandid[yaml]'  (or: pip install PyYAML). "
            "Flowsheet.from_dict() and Flowsheet.from_json() need no extra packages."
        ) from e
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.load(text, Loader=_core_schema_loader(yaml))
    except yaml.YAMLError as e:
        raise SpecError(f"{path}: not valid YAML, {e}") from None
    if data is None:
        raise SpecError(f"{path} is empty; a spec needs at least a 'name'")
    return from_dict(data)
