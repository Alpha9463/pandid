# PFD Topology Model (M0 + M1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure-data topology core of the PFD engine — `Flowsheet`, `Unit` (+ built-in types), `Port`, `Stream`, `Component` — with `connect()` validation and `to_dict()` serialization, plus project scaffolding, all under TDD.

**Architecture:** Three-layer design (topology / geometry / render) from the spec; this plan implements **only the topology layer** — permanent semantic objects that carry no coordinates and no SVG. Streams connect **port → port**; each port holds at most one stream (fan-in/out is modelled with multiple ports). Recycle detection, layout, routing, and rendering are later milestones and are out of scope here.

**Tech Stack:** Python ≥ 3.10 (stdlib only for the core), `hatchling` build backend, `pytest` for tests. Zero runtime dependencies.

## Global Constraints

- **Python ≥ 3.10** (uses `X | None` syntax and modern dataclasses).
- **Zero runtime dependencies** for the core; `pytest` is the only dev dependency.
- **License: Apache-2.0** (`LICENSE` file is the canonical Apache 2.0 text).
- **Import/package name: `pfd`** (lowercase). PyPI distribution name is out of scope for this plan.
- **Topology objects carry NO coordinates and NO SVG** — placement/routing/rendering belong to later milestones.
- **Each port holds at most one stream.** Multi-stream units (Mixer/Splitter) use multiple ports.
- **Recycle is never user-declared.** `Stream.is_recycle` defaults to `False` and is set later by the layout engine (not in this plan).
- **TDD:** every task writes a failing test first, then the minimal implementation. **Commit after every task.**

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, build backend, Python floor, dev deps |
| `LICENSE` | Apache-2.0 canonical text |
| `pfd/__init__.py` | Public API re-exports (`Flowsheet`, `units`, `Component`) |
| `pfd/components.py` | `Component` (species registry entry) |
| `pfd/ports.py` | `Port` (named nozzle; holds ≤ 1 stream) |
| `pfd/streams.py` | `Stream` (port → port connection) |
| `pfd/units.py` | `Unit` base + port-declaration mechanism + built-in unit types (this module is also the public `units` namespace) |
| `pfd/flowsheet.py` | `Flowsheet` container: `add()`, `connect()` validation, `to_dict()` |
| `tests/test_scaffold.py` | Package imports and installs |
| `tests/test_model.py` | `Component`, `Port`, `Stream` construction |
| `tests/test_units.py` | Unit base, port-as-attribute/dict access, built-in types, variable ports |
| `tests/test_flowsheet.py` | `add()`, `connect()` validation, energy auto-detection |
| `tests/test_serialize.py` | `to_dict()` output |
| `tests/test_integration.py` | End-to-end flowsheet assembly |

**Import graph (no cycles):** `ports` and `components` depend on nothing; `streams` depends on nothing at runtime (string-annotated); `units` imports `ports`; `flowsheet` imports `streams`. `units` never imports `flowsheet`.

**Note on the old skeleton:** the existing untracked `PFD/` package (`units.py`, `streams.py`, `figure.py`) is superseded by this design and is moved aside in Task 1. macOS is case-insensitive, so `PFD` and `pfd` collide — Task 1 handles the rename safely via a scratch backup.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `LICENSE`
- Create: `pfd/__init__.py`
- Create: `tests/test_scaffold.py`
- Move aside: `PFD/` (old skeleton → scratch backup)

**Interfaces:**
- Consumes: nothing.
- Produces: an installable `pfd` package importable as `import pfd`; `pfd.__version__` string.

- [ ] **Step 1: Move the old skeleton aside (avoids macOS case collision)**

```bash
mkdir -p "/private/tmp/claude-501/-Users-alexanderson-Library-CloudStorage-OneDrive-TheUniversityofQueensland-University-projects-py-chemengg/3cd8e41a-0b07-47d0-a40c-0973a8e56efc/scratchpad/backup"
mv PFD "/private/tmp/claude-501/-Users-alexanderson-Library-CloudStorage-OneDrive-TheUniversityofQueensland-University-projects-py-chemengg/3cd8e41a-0b07-47d0-a40c-0973a8e56efc/scratchpad/backup/PFD_skeleton"
```
Expected: `PFD/` no longer exists in the repo; a fresh lowercase `pfd/` can now be created without colliding.

- [ ] **Step 2: Fetch the canonical Apache-2.0 license text**

```bash
curl -sL https://www.apache.org/licenses/LICENSE-2.0.txt -o LICENSE
test -s LICENSE && head -1 LICENSE
```
Expected: prints `                                 Apache License` (non-empty file).

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "pfd"
version = "0.0.1"
description = "Generate chemical-engineering Process Flow Diagrams with automatic layout and orthogonal stream routing."
readme = "README.md"
requires-python = ">=3.10"
license = "Apache-2.0"
authors = [{ name = "Alex Anderson" }]
keywords = ["chemical-engineering", "process-flow-diagram", "pfd", "flowsheet"]
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7"]

[tool.hatch.build.targets.wheel]
packages = ["pfd"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: Write `pfd/__init__.py`**

```python
"""pfd — a Python engine for chemical-engineering Process Flow Diagrams.

Public API (topology layer):
    from pfd import Flowsheet, units, Component
"""

__version__ = "0.0.1"

from pfd.components import Component
from pfd.flowsheet import Flowsheet
from pfd import units

__all__ = ["Flowsheet", "Component", "units", "__version__"]
```

Note: this imports modules created in later tasks. Until Task 6, `import pfd` will fail — so for Task 1 only, temporarily reduce `__init__.py` to just the docstring and `__version__`, then restore the full version in Task 6 (Step 6 below re-adds the imports). Write this minimal form now:

```python
"""pfd — a Python engine for chemical-engineering Process Flow Diagrams."""

__version__ = "0.0.1"
```

- [ ] **Step 5: Write the failing scaffold test**

```python
# tests/test_scaffold.py
def test_package_imports():
    import pfd
    assert pfd.__version__ == "0.0.1"
```

- [ ] **Step 6: Install editable and run the test**

```bash
pip install -e ".[dev]"
pytest tests/test_scaffold.py -v
```
Expected: install succeeds; test PASSES.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml LICENSE pfd/__init__.py tests/test_scaffold.py
git commit -m "chore: scaffold pfd package (Apache-2.0, hatchling, pytest)"
```

---

### Task 2: Component and Port

**Files:**
- Create: `pfd/components.py`
- Create: `pfd/ports.py`
- Create: `tests/test_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Component(name: str, formula: str | None = None)`
  - `Port(name: str, owner, direction: str, role: str, side: str | None = None)` with mutable attribute `stream: Stream | None = None` (defaults `None`, `repr=False`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model.py
from pfd.components import Component
from pfd.ports import Port


def test_component_holds_name_and_formula():
    c = Component("Water", formula="H2O")
    assert c.name == "Water"
    assert c.formula == "H2O"


def test_component_formula_optional():
    assert Component("Nitrogen").formula is None


def test_port_fields_and_default_stream():
    p = Port(name="outlet", owner=None, direction="outlet", role="feed")
    assert p.name == "outlet"
    assert p.direction == "outlet"
    assert p.role == "feed"
    assert p.side is None
    assert p.stream is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pfd.components'`.

- [ ] **Step 3: Write `pfd/components.py`**

```python
"""Component — an entry in a flowsheet's chemical-species registry.

Carries no thermophysical data yet; a future mass/energy balance backend
attaches property calculations here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Component:
    name: str
    formula: str | None = None
```

- [ ] **Step 4: Write `pfd/ports.py`**

```python
"""Port — a named nozzle on a unit; the attachment point for a stream.

A port belongs to exactly one unit, has a direction ("inlet"/"outlet") and a
role (e.g. "feed", "vapor", "energy"), and holds at most one stream. Named
port anchors are what the (future) router targets; roles/sides are hints the
(future) renderer and layout engine consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.streams import Stream
    from pfd.units import Unit


@dataclass
class Port:
    name: str
    owner: "Unit | None" = field(repr=False)
    direction: str  # "inlet" | "outlet"
    role: str
    side: str | None = None
    stream: "Stream | None" = field(default=None, repr=False)
```

Note: a dataclass field with `repr=False` and no default (`owner`) must precede fields with defaults. Reorder so `owner` keeps no default but sits before `side`/`stream`; `direction` and `role` also have no default. The order above (`name`, `owner`, `direction`, `role`, `side`, `stream`) is valid because only `side` and `stream` have defaults and they come last.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_model.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add pfd/components.py pfd/ports.py tests/test_model.py
git commit -m "feat: add Component and Port dataclasses"
```

---

### Task 3: Stream

**Files:**
- Create: `pfd/streams.py`
- Modify: `tests/test_model.py` (append)

**Interfaces:**
- Consumes: `Port` (as `source`/`dest`, duck-typed via string annotation).
- Produces: `Stream(name: str, source, dest, kind: str = "material", is_recycle: bool = False, tear_hint: bool = False)`.

- [ ] **Step 1: Write the failing test (append to `tests/test_model.py`)**

```python
from pfd.streams import Stream


def test_stream_defaults():
    src = Port(name="outlet", owner=None, direction="outlet", role="feed")
    dst = Port(name="inlet", owner=None, direction="inlet", role="feed")
    s = Stream(name="S1", source=src, dest=dst)
    assert s.name == "S1"
    assert s.source is src
    assert s.dest is dst
    assert s.kind == "material"
    assert s.is_recycle is False
    assert s.tear_hint is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model.py::test_stream_defaults -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pfd.streams'`.

- [ ] **Step 3: Write `pfd/streams.py`**

```python
"""Stream — a connection from one outlet Port to one inlet Port.

`kind` is "material" or "energy". `is_recycle` is COMPUTED later by the layout
engine's cycle-detection phase and must never be set by API callers. `tear_hint`
lets a caller nudge which stream is chosen as a tear/back-edge in ambiguous
cycles; it is advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.ports import Port


@dataclass
class Stream:
    name: str
    source: "Port"
    dest: "Port"
    kind: str = "material"
    is_recycle: bool = False
    tear_hint: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_model.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pfd/streams.py tests/test_model.py
git commit -m "feat: add Stream dataclass"
```

---

### Task 4: Unit base class + port-declaration mechanism

**Files:**
- Create: `pfd/units.py`
- Create: `tests/test_units.py`

**Interfaces:**
- Consumes: `Port` from `pfd.ports`.
- Produces:
  - `Unit(name: str)` base with class attrs `kind: str` and `_PORTS: list[tuple[str, str, str]]` (each `(name, direction, role)`).
  - Instance attrs: `name`, `flowsheet` (`None` until added), `ports: dict[str, Port]`, `params: dict`.
  - Method `_add_port(name, direction, role, side=None) -> Port` (registers in `ports` dict AND sets it as an attribute).
  - Method `port(name) -> Port`.
  - Ports accessible as attributes: `unit.<port_name>`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_units.py
import pytest
from pfd.units import Unit
from pfd.ports import Port


class _Widget(Unit):
    kind = "widget"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


def test_unit_declares_ports_as_dict_and_attributes():
    w = _Widget("W-1")
    assert w.name == "W-1"
    assert w.kind == "widget"
    assert set(w.ports) == {"inlet", "outlet"}
    # dict access
    assert isinstance(w.port("inlet"), Port)
    # attribute access
    assert w.inlet is w.ports["inlet"]
    assert w.outlet.direction == "outlet"
    assert w.inlet.owner is w


def test_unit_starts_unattached_with_empty_params():
    w = _Widget("W-1")
    assert w.flowsheet is None
    assert w.params == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_units.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pfd.units'`.

- [ ] **Step 3: Write the `Unit` base in `pfd/units.py`**

```python
"""Unit operations and the built-in unit-type library.

Each Unit subclass declares its named ports via the class attribute `_PORTS`
(a list of `(name, direction, role)` tuples), or, for variable-port units,
by adding ports in `__init__`. Ports are exposed both as a `ports` dict and as
attributes (e.g. `pump.suction`).

This module is also the public `units` namespace: `from pfd import units`.
"""

from __future__ import annotations

from pfd.ports import Port


class Unit:
    kind: str = "unit"
    _PORTS: list[tuple[str, str, str]] = []

    def __init__(self, name: str):
        self.name = name
        self.flowsheet = None
        self.ports: dict[str, Port] = {}
        self.params: dict = {}
        for spec in self._PORTS:
            self._add_port(*spec)

    def _add_port(self, name: str, direction: str, role: str,
                  side: str | None = None) -> Port:
        port = Port(name=name, owner=self, direction=direction, role=role, side=side)
        self.ports[name] = port
        setattr(self, name, port)
        return port

    def port(self, name: str) -> Port:
        return self.ports[name]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_units.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pfd/units.py tests/test_units.py
git commit -m "feat: add Unit base with port-declaration mechanism"
```

---

### Task 5: Built-in unit types (fixed and variable ports)

**Files:**
- Modify: `pfd/units.py` (append unit-type classes)
- Modify: `tests/test_units.py` (append)

**Interfaces:**
- Consumes: `Unit`, `_add_port` from Task 4.
- Produces these classes in `pfd.units`: `Feed`, `Product`, `Pump`, `Compressor`, `Valve`, `Vessel` (`Tank` alias), `HeatExchanger`, `Heater`, `Cooler`, `Reactor`, `Separator`, `Column`, `Mixer(name, n_inlets=2)`, `Splitter(name, n_outlets=2)`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_units.py`)**

```python
from pfd import units as U  # noqa: E402


def test_fixed_port_units_have_expected_ports():
    assert set(U.Feed("F").ports) == {"outlet"}
    assert set(U.Product("P").ports) == {"inlet"}
    assert set(U.Pump("K").ports) == {"suction", "discharge"}
    assert set(U.HeatExchanger("E").ports) == {"hot_in", "hot_out", "cold_in", "cold_out"}
    assert set(U.Separator("V").ports) == {"feed", "vapor", "liquid"}
    assert set(U.Column("T").ports) == {
        "feed", "distillate", "bottoms", "reboiler_duty", "condenser_duty"
    }


def test_reactor_duty_is_energy_role():
    r = U.Reactor("R")
    assert r.duty.role == "energy"
    assert r.feed.direction == "inlet"
    assert r.outlet.direction == "outlet"


def test_mixer_variable_inlets():
    m = U.Mixer("M", n_inlets=3)
    assert set(m.ports) == {"in_1", "in_2", "in_3", "outlet"}
    assert m.in_2.direction == "inlet"
    assert m.outlet.direction == "outlet"


def test_splitter_variable_outlets():
    s = U.Splitter("S", n_outlets=3)
    assert set(s.ports) == {"inlet", "out_1", "out_2", "out_3"}
    assert s.out_3.direction == "outlet"


def test_tank_is_vessel_alias():
    assert U.Tank is U.Vessel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_units.py -k "fixed_port or reactor_duty or variable or alias" -v`
Expected: FAIL with `AttributeError: module 'pfd.units' has no attribute 'Feed'`.

- [ ] **Step 3: Append the unit-type classes to `pfd/units.py`**

```python
class Feed(Unit):
    kind = "feed"
    _PORTS = [("outlet", "outlet", "feed")]


class Product(Unit):
    kind = "product"
    _PORTS = [("inlet", "inlet", "product")]


class Pump(Unit):
    kind = "pump"
    _PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class Compressor(Unit):
    kind = "compressor"
    _PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class Valve(Unit):
    kind = "valve"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Vessel(Unit):
    kind = "vessel"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


Tank = Vessel


class HeatExchanger(Unit):
    kind = "hex"
    _PORTS = [
        ("hot_in", "inlet", "process"),
        ("hot_out", "outlet", "process"),
        ("cold_in", "inlet", "process"),
        ("cold_out", "outlet", "process"),
    ]


class Heater(Unit):
    kind = "heater"
    _PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("duty", "inlet", "energy"),
    ]


class Cooler(Unit):
    kind = "cooler"
    _PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("duty", "outlet", "energy"),
    ]


class Reactor(Unit):
    kind = "reactor"
    _PORTS = [
        ("feed", "inlet", "feed"),
        ("outlet", "outlet", "process"),
        ("duty", "inlet", "energy"),
    ]


class Separator(Unit):
    kind = "separator"
    _PORTS = [
        ("feed", "inlet", "feed"),
        ("vapor", "outlet", "vapor"),
        ("liquid", "outlet", "liquid"),
    ]


class Column(Unit):
    kind = "column"
    _PORTS = [
        ("feed", "inlet", "feed"),
        ("distillate", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
        ("reboiler_duty", "inlet", "energy"),
        ("condenser_duty", "outlet", "energy"),
    ]


class Mixer(Unit):
    kind = "mixer"

    def __init__(self, name: str, n_inlets: int = 2):
        super().__init__(name)
        for i in range(1, n_inlets + 1):
            self._add_port(f"in_{i}", "inlet", "process")
        self._add_port("outlet", "outlet", "process")


class Splitter(Unit):
    kind = "splitter"

    def __init__(self, name: str, n_outlets: int = 2):
        super().__init__(name)
        self._add_port("inlet", "inlet", "process")
        for i in range(1, n_outlets + 1):
            self._add_port(f"out_{i}", "outlet", "process")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_units.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pfd/units.py tests/test_units.py
git commit -m "feat: add built-in unit-type library"
```

---

### Task 6: Flowsheet — add() and connect() with validation

**Files:**
- Create: `pfd/flowsheet.py`
- Modify: `pfd/__init__.py` (restore full public API)
- Create: `tests/test_flowsheet.py`

**Interfaces:**
- Consumes: `Stream` from `pfd.streams`; `Unit`/`Port` (duck-typed).
- Produces:
  - `Flowsheet(name: str, direction: str = "LR")` with attrs `units`, `streams`, `components`.
  - `add(unit) -> unit` (sets `unit.flowsheet = self`).
  - `add_component(component) -> component`.
  - `connect(src, dst, *, kind="material", name=None, tear_hint=False) -> Stream`.
  - Validation rules: `src` must be outlet; `dst` must be inlet; both owners must be added to this flowsheet; neither port already connected; auto stream name `S{n}`; energy auto-detection when both port roles ∈ {"energy", "utility"}.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_flowsheet.py
import pytest
from pfd import Flowsheet, units as U


def _fs():
    fs = Flowsheet("Test")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("K-101"))
    prod = fs.add(U.Product("Prod"))
    return fs, feed, pump, prod


def test_connect_creates_stream_and_marks_ports():
    fs, feed, pump, prod = _fs()
    s = fs.connect(feed.outlet, pump.suction)
    assert s in fs.streams
    assert s.name == "S1"
    assert s.kind == "material"
    assert feed.outlet.stream is s
    assert pump.suction.stream is s


def test_auto_stream_names_increment():
    fs, feed, pump, prod = _fs()
    fs.connect(feed.outlet, pump.suction)
    s2 = fs.connect(pump.discharge, prod.inlet)
    assert s2.name == "S2"


def test_connect_rejects_wrong_directions():
    fs, feed, pump, prod = _fs()
    with pytest.raises(ValueError, match="must be an outlet"):
        fs.connect(pump.suction, prod.inlet)   # suction is an inlet
    with pytest.raises(ValueError, match="must be an inlet"):
        fs.connect(feed.outlet, pump.discharge)  # discharge is an outlet


def test_connect_rejects_already_connected_port():
    fs, feed, pump, prod = _fs()
    fs.connect(feed.outlet, pump.suction)
    with pytest.raises(ValueError, match="already connected"):
        fs.connect(feed.outlet, prod.inlet)  # feed.outlet reused


def test_connect_rejects_unit_not_added():
    fs, feed, pump, prod = _fs()
    stray = U.Product("Stray")  # never added to fs
    with pytest.raises(ValueError, match="added to this flowsheet"):
        fs.connect(pump.discharge, stray.inlet)


def test_energy_streams_auto_detected():
    fs = Flowsheet("Test")
    heater = fs.add(U.Heater("E-1"))   # heater.duty is an inlet energy port
    cooler = fs.add(U.Cooler("C-1"))   # cooler.duty is an outlet energy port
    s = fs.connect(cooler.duty, heater.duty)   # both roles == "energy"
    assert s.kind == "energy"


def test_named_connect_overrides_auto_name():
    fs, feed, pump, prod = _fs()
    s = fs.connect(feed.outlet, pump.suction, name="feed-to-pump")
    assert s.name == "feed-to-pump"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_flowsheet.py -v`
Expected: FAIL with `ImportError` (Flowsheet not yet exported) or `ModuleNotFoundError: No module named 'pfd.flowsheet'`.

- [ ] **Step 3: Write `pfd/flowsheet.py`**

```python
"""Flowsheet — the top-level container and the single source of truth for
connectivity. Units are added with `add()`; streams are created only through
`connect()`, which validates the connection and enforces the one-stream-per-port
rule.
"""

from __future__ import annotations

from pfd.streams import Stream

_ENERGY_ROLES = {"energy", "utility"}


class Flowsheet:
    def __init__(self, name: str, direction: str = "LR"):
        self.name = name
        self.direction = direction
        self.units: list = []
        self.streams: list[Stream] = []
        self.components: list = []

    def add(self, unit):
        unit.flowsheet = self
        self.units.append(unit)
        return unit

    def add_component(self, component):
        self.components.append(component)
        return component

    def connect(self, src, dst, *, kind: str = "material",
                name: str | None = None, tear_hint: bool = False) -> Stream:
        if src.direction != "outlet":
            raise ValueError(
                f"source port {src.owner.name}.{src.name} must be an outlet, "
                f"got {src.direction!r}"
            )
        if dst.direction != "inlet":
            raise ValueError(
                f"destination port {dst.owner.name}.{dst.name} must be an inlet, "
                f"got {dst.direction!r}"
            )
        if src.owner.flowsheet is not self or dst.owner.flowsheet is not self:
            raise ValueError(
                "both units must be added to this flowsheet before connecting"
            )
        if src.stream is not None:
            raise ValueError(
                f"port {src.owner.name}.{src.name} is already connected"
            )
        if dst.stream is not None:
            raise ValueError(
                f"port {dst.owner.name}.{dst.name} is already connected"
            )
        if kind == "material" and src.role in _ENERGY_ROLES and dst.role in _ENERGY_ROLES:
            kind = "energy"

        stream = Stream(
            name=name or f"S{len(self.streams) + 1}",
            source=src,
            dest=dst,
            kind=kind,
            tear_hint=tear_hint,
        )
        src.stream = stream
        dst.stream = stream
        self.streams.append(stream)
        return stream
```

- [ ] **Step 4: Restore the full public API in `pfd/__init__.py`**

```python
"""pfd — a Python engine for chemical-engineering Process Flow Diagrams.

Public API (topology layer):
    from pfd import Flowsheet, units, Component
"""

__version__ = "0.0.1"

from pfd.components import Component
from pfd.flowsheet import Flowsheet
from pfd import units

__all__ = ["Flowsheet", "Component", "units", "__version__"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_flowsheet.py tests/test_scaffold.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add pfd/flowsheet.py pfd/__init__.py tests/test_flowsheet.py
git commit -m "feat: add Flowsheet with connect() validation and public API"
```

---

### Task 7: Serialization — `to_dict()`

**Files:**
- Modify: `pfd/flowsheet.py` (add `to_dict`)
- Create: `tests/test_serialize.py`

**Interfaces:**
- Consumes: `Flowsheet`, units, streams from prior tasks.
- Produces: `Flowsheet.to_dict() -> dict` with keys `name`, `direction`, `components`, `units`, `streams` (each stream records `source`/`dest` as `[unit_name, port_name]` and includes `kind` and `is_recycle`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_serialize.py
from pfd import Flowsheet, Component, units as U


def test_to_dict_captures_topology():
    fs = Flowsheet("Demo", direction="LR")
    fs.add_component(Component("Water", "H2O"))
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("K-101"))
    fs.connect(feed.outlet, pump.suction, name="s-feed")

    d = fs.to_dict()
    assert d["name"] == "Demo"
    assert d["direction"] == "LR"
    assert d["components"] == ["Water"]

    unit_names = [u["name"] for u in d["units"]]
    assert unit_names == ["Feed", "K-101"]
    pump_entry = next(u for u in d["units"] if u["name"] == "K-101")
    assert {p["name"] for p in pump_entry["ports"]} == {"suction", "discharge"}

    assert d["streams"] == [
        {
            "name": "s-feed",
            "source": ["Feed", "outlet"],
            "dest": ["K-101", "suction"],
            "kind": "material",
            "is_recycle": False,
        }
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_serialize.py -v`
Expected: FAIL with `AttributeError: 'Flowsheet' object has no attribute 'to_dict'`.

- [ ] **Step 3: Add `to_dict` to `pfd/flowsheet.py`** (append as a method of `Flowsheet`)

```python
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "direction": self.direction,
            "components": [c.name for c in self.components],
            "units": [
                {
                    "name": u.name,
                    "kind": u.kind,
                    "ports": [
                        {"name": p.name, "direction": p.direction, "role": p.role}
                        for p in u.ports.values()
                    ],
                }
                for u in self.units
            ],
            "streams": [
                {
                    "name": s.name,
                    "source": [s.source.owner.name, s.source.name],
                    "dest": [s.dest.owner.name, s.dest.name],
                    "kind": s.kind,
                    "is_recycle": s.is_recycle,
                }
                for s in self.streams
            ],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_serialize.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pfd/flowsheet.py tests/test_serialize.py
git commit -m "feat: add Flowsheet.to_dict() serialization"
```

---

### Task 8: End-to-end integration test (the ammonia loop)

**Files:**
- Create: `tests/test_integration.py`

**Interfaces:**
- Consumes: the full public API.
- Produces: no new code — a realistic assembly that guards the API contract, including a recycle connection (which must succeed structurally even though `is_recycle` stays `False` until layout runs in a later milestone).

- [ ] **Step 1: Write the integration test**

```python
# tests/test_integration.py
from pfd import Flowsheet, units as U


def build_ammonia_loop():
    fs = Flowsheet("Ammonia Loop", direction="LR")
    feed = fs.add(U.Feed("Natural Gas"))
    reformer = fs.add(U.Reactor("R-101"))
    hx = fs.add(U.HeatExchanger("E-101"))
    sep = fs.add(U.Separator("V-101"))
    comp = fs.add(U.Compressor("K-101"))
    prod = fs.add(U.Product("Ammonia"))

    fs.connect(feed.outlet, reformer.feed)
    fs.connect(reformer.outlet, hx.hot_in)
    fs.connect(hx.hot_out, sep.feed)
    fs.connect(sep.vapor, comp.suction)
    fs.connect(comp.discharge, hx.cold_in)   # a recycle back-edge (not declared as such)
    fs.connect(sep.liquid, prod.inlet)
    return fs


def test_ammonia_loop_assembles():
    fs = build_ammonia_loop()
    assert len(fs.units) == 6
    assert len(fs.streams) == 6
    # Recycle is not user-declared; it stays False until the layout milestone.
    assert all(s.is_recycle is False for s in fs.streams)


def test_ammonia_loop_serializes_roundtrip_shape():
    d = build_ammonia_loop().to_dict()
    assert d["name"] == "Ammonia Loop"
    assert len(d["units"]) == 6
    assert len(d["streams"]) == 6
    # Every stream references real units by name.
    unit_names = {u["name"] for u in d["units"]}
    for s in d["streams"]:
        assert s["source"][0] in unit_names
        assert s["dest"][0] in unit_names
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -v`
Expected: all tests across all files PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: end-to-end ammonia-loop assembly and serialization"
```

---

## Self-Review

**1. Spec coverage (M0 + M1 portions of the design doc):**
- §11 licensing (Apache-2.0, zero core deps) → Task 1 ✓
- §12 module structure (`pfd/` package, per-file responsibilities) → Tasks 1–7 ✓ (geometry/layout/routing/render modules are later milestones, intentionally absent)
- §4 core data model: `Component` → Task 2; `Port` → Task 2; `Stream` → Task 3; `Unit` + built-in types + variable ports → Tasks 4–5; `Flowsheet` + `connect()` validation → Task 6; `to_dict()` → Task 7 ✓
- §4 `connect()` validation rules (direction, occupancy, cross-flowsheet, energy auto-detect, auto-naming) → Task 6 ✓
- Recycle-never-declared invariant → enforced by absence of a `kind="recycle"` path and `is_recycle` defaulting False; guarded in Task 8 ✓
- **Intentionally deferred** (not gaps): `Placement`/`Route`/`pin()`/`.via()` (geometry, M2–M5), layout engine (M3), router (M4), renderer + symbols (M2), `State`/balance (future). These are out of this plan's scope by design.

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N". Every code and test step shows complete content. The Apache license is fetched via an exact canonical URL, not hand-waved. ✓

**3. Type consistency:** `Port(name, owner, direction, role, side=None, stream=None)` used identically in Tasks 2, 4, 6. `Stream(name, source, dest, kind, is_recycle, tear_hint)` consistent across Tasks 3, 6, 7. `_add_port(name, direction, role, side=None)` signature matches all call sites in Tasks 4–5. `connect(...)` return type (`Stream`) consumed consistently in Tasks 6–8. `to_dict()` shape asserted in Task 7 matches the emitter. ✓

One consistency note applied: `pfd/__init__.py` is written minimally in Task 1 (so `import pfd` works before later modules exist) and restored to the full re-export form in Task 6 — Task 1 Step 4 documents this explicitly.
