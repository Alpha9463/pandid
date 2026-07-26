"""Build a flowsheet from data — the declarative spec format.

The topology API (``fs.add`` / ``fs.connect``) assumes whoever wants a drawing
writes Python. Most process engineers do not: the equipment list and the stream
table already exist, in a spreadsheet or a YAML file, and retyping them as code
is what stops the drawing getting made. This module is the other door — a plain
mapping describing the same flowsheet, plus the serializer that writes one back
out, so a diagram round-trips through data:

    fs = Flowsheet.from_dict(spec)     # plain dict, no dependencies
    fs = Flowsheet.from_json(path)     # stdlib only
    fs = Flowsheet.from_yaml(path)     # needs the optional PyYAML extra
    spec = fs.to_dict()                # feeds straight back into from_dict()

The spec is *validated*, not interpreted: an unknown key is an error rather than
a silent no-op, because a typo in a hand-written file must not quietly drop a
nozzle off the sheet. Every message names the entry it came from
(``units[3] 'P-101'``) and lists what would have been accepted, in the style of
:meth:`pfd.units.Unit.port`.

The format::

    name: Feed Metering Skid          # required; everything else is optional
    stream_naming_scheme: "S{n}"
    components: [{name: Water, formula: H2O}]

    units:
      - {kind: Feed, name: Raw Feed, reference: PFD-100, pin: {x: 60, y: 275}}
      - {kind: Fitting, name: ST-101, variant: strainer, description: Strainer}
      - {kind: Mixer, name: M-100, n_inlets: 2}
      - {kind: Vessel, name: V-101, variant: horizontal, width: 130, height: 42,
         port_faces: {inlet: N}, pin: {x: 680, y: 210, mirrored: y}}

    instruments:
      - {type: LIC, number: 101, variant: panel,
         on: V-101, at: S, offset: 115, port_faces: {sig_out: W}}

    streams:
      - {from: [Raw Feed, outlet], to: [ST-101, inlet]}
      - {from: [LIC-101, sig_out], to: [FV-101, actuator], kind: electric}
      - {from: [FV-200, outlet], to: [M-100, in_2], tear_hint: true,
         properties: {"Temperature (C)": 25 C}}

    stream_table_sections: [[Benzene, Mass Fraction]]
    title_block: {title: ..., revisions: [{rev: A, date: ..., by: AA}]}
    annotations: [{type: equipment_list, align: top-right}]
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import fields as dataclass_fields
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from pfd import units as unit_types
from pfd.components import Component
from pfd.document import Annotation, Revision, TableBox, TitleBlock, equipment_list, legend, notes
from pfd.flowsheet import Flowsheet
from pfd.ports import Port
from pfd.streams import Stream
from pfd.units import Instrument, Unit


class SpecError(ValueError):
    """A flowsheet spec could not be understood.

    A :class:`ValueError`, so existing ``except ValueError`` handlers still
    catch it; a distinct class so a tool loading user files can tell "your spec
    is wrong" apart from "the engine is unhappy".
    """


# ---------------------------------------------------------------------------
# Primitive validation. Each helper takes the dotted path of the value it is
# checking so the message points at the line the author has to fix.
# ---------------------------------------------------------------------------


def _suggest(value: Any, candidates) -> str:
    """``" (did you mean 'variant'?)"`` when a typo is close to a real name."""
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
    # Returned unchanged rather than coerced to float: a whole-number coordinate
    # is drawn as "120", a float one as "120.0", so widening here would rewrite
    # the SVG of every flowsheet that went through a spec.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"{where} must be a number, got {value!r}")
    return value


def _integer(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f"{where} must be a whole number, got {value!r}")
    return value


def _flag(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise SpecError(f"{where} must be true or false, got {value!r}")
    return value


def _fail_from(error: Exception, where: str) -> SpecError:
    """Re-raise a library error against the spec entry that provoked it."""
    message = error.args[0] if error.args else str(error)
    return SpecError(f"{where}: {message}")


# ---------------------------------------------------------------------------
# The equipment registry
# ---------------------------------------------------------------------------


def _snake(name: str) -> str:
    out = [name[0].lower()]
    for char in name[1:]:
        out.append(f"_{char.lower()}" if char.isupper() else char)
    return "".join(out)


_CLASSES: dict[str, type[Unit]] = {
    name: getattr(unit_types, name) for name in unit_types.__all__ if name != "Unit"
}

# A spec is hand-written, so accept every name the reader might reasonably use:
# the class name from the README (``HeatExchanger``), its snake_case spelling,
# and the internal ``Unit.kind`` tag (``hex``).
_ALIASES: dict[str, str] = {}
for _name, _cls in _CLASSES.items():
    for _alias in (_name, _snake(_name), _cls.kind):
        _ALIASES[_alias.lower()] = _name


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
            "'units:' — that is where their tag (type/number) and attachment "
            "(on/at/offset/angle) live"
        )
    return _CLASSES[name]


# ---------------------------------------------------------------------------
# Reading: spec -> Flowsheet
# ---------------------------------------------------------------------------

_TOP_KEYS = {
    "name", "stream_naming_scheme", "components", "units",
    "instruments", "streams", "stream_table_sections", "title_block", "annotations",
}
# Keys the format no longer has. A file written against the old one names the
# sheet it wants; saying so beats "unknown key" and beats honouring it silently.
_RETIRED_KEYS = {
    "direction": "the layout engine only draws left to right, so it never did anything",
}
_PIN_KEYS = {"x", "y", "col", "row", "orientation", "mirrored"}
_UNIT_KEYS = {
    "kind", "name", "variant", "description", "reference", "width", "height",
    "label_pos", "significant", "pin", "port_faces",
}
_INSTRUMENT_KEYS = {
    "type", "number", "variant", "description", "reference", "width", "height",
    "label_pos", "on", "at", "offset", "angle", "pin", "port_faces",
}
_STREAM_KEYS = {
    "from", "to", "kind", "name", "tear_hint", "properties", "via", "color", "dasharray",
}
_COMPONENT_KEYS = {"name", "formula"}
_VARIABLE_PORTS = {"n_inlets": "Mixer", "n_outlets": "Splitter"}


def from_dict(spec: Mapping[str, Any]) -> Flowsheet:
    """Build a :class:`~pfd.flowsheet.Flowsheet` from a declarative mapping.

    Raises :class:`SpecError` — a :class:`ValueError` — naming the offending
    entry for anything it cannot honour.
    """
    where = "the flowsheet spec"
    data = _mapping(spec, where)
    for key, why in _RETIRED_KEYS.items():
        if key in data:
            raise SpecError(f"{where}: {key!r} is no longer part of the spec — {why}; remove it")
    _check_keys(data, _TOP_KEYS, where)
    if "name" not in data:
        raise SpecError(f"{where} needs a 'name' (the flowsheet's title)")

    scheme = data.get("stream_naming_scheme", "S{n}")
    fs = Flowsheet(
        _text(data["name"], f"{where}: 'name'"),
        stream_naming_scheme=_text(scheme, f"{where}: 'stream_naming_scheme'"),
    )

    for i, entry in enumerate(_sequence(data.get("components", []), "components")):
        fs.add_component(_read_component(entry, f"components[{i}]"))

    for i, entry in enumerate(_sequence(data.get("units", []), "units")):
        _read_unit(fs, entry, f"units[{i}]")

    # Instruments are created before the streams so a controller output can be
    # connected, but attached afterwards because a balloon may hang off a line
    # that does not exist yet.
    pending = []
    for i, entry in enumerate(_sequence(data.get("instruments", []), "instruments")):
        where_i = f"instruments[{i}]"
        pending.append((_read_instrument(fs, entry, where_i), _mapping(entry, where_i), where_i))

    for i, entry in enumerate(_sequence(data.get("streams", []), "streams")):
        _read_stream(fs, entry, f"streams[{i}]")

    for inst, entry, where_i in pending:
        _attach_instrument(fs, inst, entry, where_i)

    fs.stream_table_sections = [
        _read_section(entry, f"stream_table_sections[{i}]")
        for i, entry in enumerate(_sequence(data.get("stream_table_sections", []),
                                            "stream_table_sections"))
    ]
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
    for key, owner in _VARIABLE_PORTS.items():
        if cls.__name__ == owner:
            allowed.add(key)
        elif key in data:
            raise SpecError(f"{where}: only a {owner} takes {key!r}, not a {cls.__name__}")
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
    try:
        unit = cls(name, **kwargs)
    except ValueError as e:
        raise _fail_from(e, where) from None

    _read_common(fs, unit, data, where)
    return unit


def _read_instrument(fs: Flowsheet, entry: Any, where: str) -> Instrument:
    data = _mapping(entry, where)
    _check_keys(data, _INSTRUMENT_KEYS, where)
    if "type" not in data:
        raise SpecError(
            f"{where} needs a 'type' — the ISA functional letters, e.g. "
            "{type: FT, number: 101} for FT-101"
        )
    type_ = _text(data["type"], f"{where}.type")
    number = data.get("number", "")
    if not isinstance(number, (str, int)) or isinstance(number, bool):
        raise SpecError(f"{where}.number must be a loop number or text, got {number!r}")

    kwargs: dict[str, Any] = {}
    for key in ("variant", "description", "reference"):
        if key in data:
            kwargs[key] = _text(data[key], f"{where}.{key}")
    for key in ("width", "height"):
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    inst = Instrument(type_, number, **kwargs)
    _read_common(fs, inst, data, f"{where} {inst.name!r}")
    return inst


def _read_common(fs: Flowsheet, unit: Unit, data: Mapping[str, Any], where: str) -> None:
    """Apply the fields every unit shares, then register it on the flowsheet."""
    if "label_pos" in data:
        unit.label_pos = _text(data["label_pos"], f"{where}.label_pos")
    if "significant" in data:
        unit.significant = _flag(data["significant"], f"{where}.significant")
    try:
        fs.add(unit)
    except ValueError as e:
        raise _fail_from(e, where) from None
    if "pin" in data:
        _read_pin(unit, data["pin"], f"{where}.pin")
    if "port_faces" in data:
        _read_port_faces(unit, data["port_faces"], f"{where}.port_faces")


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
    try:
        unit.pin(**kwargs)
    except ValueError as e:
        raise _fail_from(e, where) from None


def _read_port_faces(unit: Unit, entry: Any, where: str) -> None:
    for port_name, face in _mapping(entry, where).items():
        _find_port(unit, port_name, where)
        try:
            unit.nozzle(port_name, _text(face, f"{where}.{port_name}"))
        except ValueError as e:
            raise _fail_from(e, f"{where}.{port_name}") from None


def _find_port(unit: Unit, name: Any, where: str) -> Port:
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
                f"{where}: an endpoint is [unit, port] — exactly two items — got {list(entry)!r}"
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
    if "tear_hint" in data:
        kwargs["tear_hint"] = _flag(data["tear_hint"], f"{where}.tear_hint")
    try:
        stream = fs.connect(src, dst, **kwargs)
    except ValueError as e:
        raise _fail_from(e, where) from None

    for key in ("color", "dasharray"):
        if key in data:
            setattr(stream, key, _text(data[key], f"{where}.{key}"))
    if "properties" in data:
        stream.properties = _read_properties(data["properties"], f"{where}.properties")
    if "via" in data:
        stream.via(_read_waypoints(data["via"], f"{where}.via"))
    return stream


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
    """Resolve an instrument's ``on:`` — a unit/stream name, or a tapped port."""
    if isinstance(entry, str):
        unit = next((u for u in fs.units if u.name == entry), None)
        stream = next((s for s in fs.streams if s.name == entry), None)
        if unit is not None and stream is not None:
            raise SpecError(
                f"{where}: {entry!r} names both a unit and a stream; identify the stream "
                "as [unit, port] — the port it leaves from — instead"
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
    if "on" not in data:
        stray = [key for key in ("at", "offset", "angle") if key in data]
        if stray:
            raise SpecError(
                f"{where}: {stray} only mean something with 'on' — the stream or unit the "
                "balloon is anchored to"
            )
        return
    host = _read_host(fs, data["on"], f"{where}.on")
    kwargs: dict[str, Any] = {}
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
            f"{where}: a section is [before_key, heading] — the property row the heading "
            f"is injected above — got {pair!r}"
        )
    return _text(pair[0], f"{where}[0]"), _text(pair[1], f"{where}[1]")


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
    """The ``align`` / ``position`` / ``margin`` trio every sheet box shares."""
    out: dict[str, Any] = {}
    if "align" in data:
        out["align"] = _text(data["align"], f"{where}.align")
    if "position" in data:
        pair = _sequence(data["position"], f"{where}.position")
        if len(pair) != 2:
            raise SpecError(
                f"{where}.position: an absolute placement is [x, y] — the box's top-left "
                f"corner — got {pair!r}"
            )
        out["position"] = (_number(pair[0], f"{where}.position[0]"),
                           _number(pair[1], f"{where}.position[1]"))
    for key in ("margin", "width", "font_size"):
        if key in data:
            out[key] = _number(data[key], f"{where}.{key}")
    return out


def _read_rows(entry: Any, where: str) -> list:
    """Annotation rows: a plain line, or cells that align into columns."""
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
        raise _fail_from(e, where) from None  # e.g. an align= outside the nine


# ---------------------------------------------------------------------------
# Writing: Flowsheet -> spec
# ---------------------------------------------------------------------------

_MIRROR_NAMES = {(True, False): "x", (False, True): "y", (True, True): "xy"}


def to_dict(fs: Flowsheet) -> dict:
    """Serialize a flowsheet to a spec :func:`from_dict` reads back.

    Only what differs from a default is written, so the output stays a file a
    human can read and edit. Placement *results* (``Frame``, routed paths,
    computed stream numbers) are left out: they are the engine's output, not the
    author's intent, and re-deriving them is the whole point of the engine.
    """
    if not isinstance(fs.stream_naming_scheme, str):
        raise SpecError(
            "a callable stream_naming_scheme cannot be written to a spec; use a format "
            "string such as 'S{n}'"
        )
    spec: dict[str, Any] = {"name": fs.name}
    if fs.stream_naming_scheme != "S{n}":
        spec["stream_naming_scheme"] = fs.stream_naming_scheme
    if fs.components:
        spec["components"] = [
            c.name if c.formula is None else {"name": c.name, "formula": c.formula}
            for c in fs.components
        ]

    equipment = [u for u in fs.units if not isinstance(u, Instrument)]
    instruments = [u for u in fs.units if isinstance(u, Instrument)]
    if equipment:
        spec["units"] = [_write_unit(u) for u in equipment]
    if instruments:
        spec["instruments"] = [_write_instrument(u) for u in instruments]
    if fs.streams:
        spec["streams"] = [_write_stream(s) for s in fs.streams]
    if fs.stream_table_sections:
        spec["stream_table_sections"] = [list(sec) for sec in fs.stream_table_sections]
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
    if unit.significant:
        entry["significant"] = True
    return entry


def _write_placement(unit: Unit, entry: dict[str, Any]) -> dict[str, Any]:
    if unit.pin_ is not None:
        pin: dict[str, Any] = {}
        for key in ("x", "y", "col", "row"):
            value = getattr(unit.pin_, key)
            if value is not None:
                pin[key] = value
        if unit.pin_.orientation:
            pin["orientation"] = int(unit.pin_.orientation)
        mirror = _MIRROR_NAMES.get((unit.pin_.mirrored, unit.pin_.mirror_y))
        if mirror:
            pin["mirrored"] = mirror
        entry["pin"] = pin
    if unit._port_faces:
        entry["port_faces"] = dict(unit._port_faces)
    return entry


def _write_unit(unit: Unit) -> dict[str, Any]:
    kind = type(unit).__name__
    if kind not in _CLASSES:
        # A spec naming a class the reader cannot construct is worse than no
        # spec at all, so refuse here rather than at whatever reads the file.
        raise SpecError(
            f"{unit.name!r} is a {kind}, which is not one of the built-in equipment "
            f"classes, so it cannot be written to a spec; available kinds: {sorted(_CLASSES)}"
        )
    entry: dict[str, Any] = {"kind": kind, "name": unit.name}
    _write_common(unit, entry)
    if isinstance(unit, unit_types.Mixer):
        entry["n_inlets"] = sum(1 for p in unit.ports if p.startswith("in_"))
    elif isinstance(unit, unit_types.Splitter):
        entry["n_outlets"] = sum(1 for p in unit.ports if p.startswith("out_"))
    return _write_placement(unit, entry)


def _write_instrument(inst: Instrument) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": inst.type, "number": inst.number}
    _write_common(inst, entry)
    if inst.host is not None:
        # Name a stream by the port it leaves, not by its number: auto-numbering
        # owns that name and re-derives it as the sheet grows, and a spec must
        # survive that.
        entry["on"] = (
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
    if stream.tear_hint:
        entry["tear_hint"] = True
    for key in ("color", "dasharray"):
        if getattr(stream, key) is not None:
            entry[key] = getattr(stream, key)
    if stream.route is not None and stream.route.manual:
        entry["via"] = [list(point) for point in stream.route.waypoints]
    if stream.properties:
        entry["properties"] = dict(stream.properties)
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
    # equipment_list()/notes()/legend() are constructors, not types: what they
    # build is a plain Annotation, so that is what comes back out. The rows are
    # identical, so the drawing is.
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
    width = getattr(box, "width", None)  # only an Annotation sizes itself
    if width is not None:
        entry["width"] = width
    if box.font_size != 11.0:
        entry["font_size"] = box.font_size
    return entry


# ---------------------------------------------------------------------------
# File loaders
# ---------------------------------------------------------------------------


def from_json(path: str | Path) -> Flowsheet:
    """Build a flowsheet from a JSON spec file (standard library only)."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SpecError(f"{path}: not valid JSON — {e.msg} at line {e.lineno}, column {e.colno}")
    return from_dict(data)


_YAML_LOADER: Any = None


def _core_schema_loader(yaml_module) -> Any:
    """A safe loader restricted to the YAML **1.2** core schema.

    PyYAML implements YAML 1.1, where ``on``, ``off``, ``yes`` and ``no`` are
    booleans and an unquoted date is a ``datetime.date``. That silently turns an
    instrument's ``on:`` key into ``True`` and a revision's ``date:`` into an
    object — two traps sprung by writing the format exactly as documented. YAML
    1.2 dropped both, and only ``true``/``false`` are booleans here.
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
    something the standard library does, so it is the one optional extra.
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
        raise SpecError(f"{path}: not valid YAML — {e}") from None
    if data is None:
        raise SpecError(f"{path} is empty; a spec needs at least a 'name'")
    return from_dict(data)
