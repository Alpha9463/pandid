# PFD Engine — Design Spec

**Date:** 2026-07-08
**Status:** Approved direction, ready for implementation planning
**Author:** Alex Anderson (with Claude)

---

## 1. Purpose & Vision

A Python library for programmatically generating chemical-engineering **Process Flow Diagrams (PFDs)** with a clean, well-defined API for other developers. The differentiating capabilities are:

- **Automatic "smart" block placement** — the developer defines *what connects to what*, not pixel coordinates.
- **Partial-manual layout** — pin a few blocks; the engine places the rest around them.
- **Smart orthogonal stream routing** — right-angle stream lines that avoid equipment and minimise crossings.
- **Automatic recycle detection** — the engine identifies feedback/recycle streams itself; the user never declares them.

The library is the **open-source foundation** (Apache-2.0) of a larger commercial vision: a **mass/energy (M&E) balance engine** and a **web interface** built *on top of* this core as separate products. The core data model is therefore designed so M&E balance can be added later **without a rewrite**.

### Goals
1. Define a PFD from an object model (units + ports + streams) with no coordinates required.
2. Produce publication-quality **static SVG**, with **PDF/PNG** export.
3. Auto-layout + auto-route by default; allow targeted manual override.
4. Pure-Python, permissively licensed, clean `pip install` — no system binaries, JVM, or Node runtime.
5. A topology data model that a future SM or EO balance solver can consume unchanged.

### Non-Goals (v1)
- Mass/energy balance solving (future, commercial — but the model is designed for it).
- Interactive/web rendering or a GUI editor (future, commercial — the renderer is behind an interface so a web backend can be added).
- Full P&ID instrumentation (ISA-5.1 control loops); v1 targets PFD-level equipment.
- A full libavoid-grade edge-routing *nudging* optimiser (v1 ships a good-enough router + manual escape hatch).

---

## 2. Requirements (from brainstorming)

| Dimension | Decision |
|---|---|
| Output | Static **SVG** first (PDF/PNG via conversion); render backend is pluggable so a web renderer can come later |
| Symbols | **Pluggable symbol registry**: generic typed boxes now, custom vector symbols registrable per unit type |
| Dependencies | **Pure-Python**, permissive licenses only; clean `pip install`; no native/JVM/JS runtime |
| License | **Apache-2.0** (permissive + explicit patent grant; commercial-friendly) |
| Connection model | **Named ports/nozzles**; streams connect **port → port** |
| Recycles | **First-class and auto-detected** — user never declares a stream as a recycle |
| Layout engine | **Built from scratch** (differentiating IP; no dependency-license risk) |

---

## 3. Architecture — Three Hard-Separated Layers

The central design decision. Topology never holds coordinates or SVG; geometry is a pure, recomputable function of topology; rendering consumes both. This is what lets auto-layout, manual override, and M&E balance coexist without entangling.

```
┌─────────────────────────────────────────────────────────────┐
│  TOPOLOGY (permanent, semantic — what M&E balance consumes)  │
│  Flowsheet · Component · Unit · Port · Stream · State        │
└───────────────┬─────────────────────────────────────────────┘
                │  pure data; NO coordinates, NO SVG
   ┌────────────┴───────────┐
   ▼                        ▼
┌──────────────────┐   ┌──────────────────────────────────────┐
│ GEOMETRY         │   │  (future, commercial) BALANCE ENGINE  │
│ (recomputable)   │   │  sequential-modular OR emit-to-Pyomo  │
│ Placement·Route  │   │  reads topology, writes Port/Stream   │
│ LayoutEngine     │   │  State; reuses recycle/tear analysis  │
│ Router           │   └──────────────────────────────────────┘
└────────┬─────────┘
         ▼
┌──────────────────────────────────────────────────────────────┐
│  RENDERING  — Renderer protocol                               │
│  SymbolRegistry (SVG templates + named port anchors)          │
│  SvgRenderer → .svg  → (cairosvg) → .pdf/.png                 │
│  (future) WebRenderer implements the same protocol            │
└──────────────────────────────────────────────────────────────┘
```

**Invariant:** deleting the entire geometry layer and recomputing it must reproduce an equivalent diagram. Topology objects carry no `x`/`y`.

---

## 4. Core Data Model (Topology Layer)

Plain `dataclasses` in v1 (zero dependencies). Modelled on IDAES `Port`/`Arc` and `pyDEXPI`'s Pydantic P&ID model — both industry references converge on this shape. (Pydantic is a candidate later for validation/DEXPI interop; not required for v1.)

```python
class Flowsheet:
    name: str
    direction: str = "LR"              # "LR" | "TB"
    components: list[Component]         # species registry (for future balance)
    units: list[Unit]
    streams: list[Stream]

    def add(self, unit: Unit) -> Unit
    def connect(self, src: Port, dst: Port, *, kind: str = "material",
                name: str | None = None, tear_hint: bool = False) -> Stream
    def layout(self, engine: LayoutEngine | None = None) -> None   # fills geometry layer
    def render(self, path: str, *, backend: str = "svg", **opts) -> None
    def to_dict(self) -> dict          # serialization (SFILES2-style text form optional)

class Unit:                            # base; subclasses declare their ports
    name: str
    kind: str                          # symbol-registry lookup key ("reactor", ...)
    ports: dict[str, Port]             # named ports declared by the subclass
    params: dict                       # design params (duty, area, ...) — balance reads later
    placement: Placement | None = None # GEOMETRY layer, optional user pin

    def pin(self, *, col=None, row=None, x=None, y=None,
            orientation=0) -> "Unit"   # grid (col,row) primary; (x,y) pixels = hard override
    def port(self, name: str) -> Port  # dict access for variable-port units
    # named ports are ALSO exposed as attributes: reactor.feed, hx.hot_in, ...

class Port:
    name: str
    owner: Unit
    direction: str                     # "inlet" | "outlet"
    role: str                          # "feed","vapor","liquid","utility","energy", ...
    side: str | None = None            # optional anchor hint: "N"|"S"|"E"|"W"
    state: State | None = None         # <-- M&E balance writes here later

class Stream:
    name: str
    source: Port
    dest: Port
    kind: str = "material"             # "material" | "energy"  (NOT "recycle")
    state: State | None = None         # material streams carry flow/composition later
    route: Route | None = None         # GEOMETRY layer

    @property
    def is_recycle(self) -> bool       # COMPUTED by layout(); read-only; never declared

class State:                           # future-facing; pluggable thermo backend (ChEDL `thermo`, MIT)
    components: dict[str, float]        # composition
    molar_flow: float; mass_flow: float
    T: float; P: float
    vapor_fraction: float; enthalpy: float

class Component:                        # species registry entry
    name: str
    formula: str | None = None
    # thermo-backend handle attached later
```

### Built-in unit types (v1)
Each declares its named ports. Illustrative set — extensible via subclassing:

| `units.*` | `kind` | Ports (name : direction/role) |
|---|---|---|
| `Feed` | `feed` | `outlet` (outlet/feed) |
| `Product` | `product` | `inlet` (inlet/product) |
| `Mixer` | `mixer` | `in_1..in_N` (inlet), `outlet` (outlet) — **variable ports** |
| `Splitter` | `splitter` | `inlet`, `out_1..out_N` — **variable ports** |
| `Pump` | `pump` | `suction` (inlet), `discharge` (outlet) |
| `Compressor` | `compressor` | `suction`, `discharge` |
| `HeatExchanger` | `hex` | `hot_in`,`hot_out`,`cold_in`,`cold_out` |
| `Heater`/`Cooler` | `heater` | `inlet`,`outlet`, `duty` (energy) |
| `Reactor` | `reactor` | `feed` (inlet), `outlet`, optional `duty` (energy) |
| `Separator` | `separator` | `feed`, `vapor` (outlet), `liquid` (outlet) |
| `Column` | `column` | `feed`,`distillate`,`bottoms`,`reboiler_duty`,`condenser_duty` |
| `Valve` | `valve` | `inlet`,`outlet` |
| `Tank`/`Vessel` | `vessel` | `inlet`,`outlet` |

Variable-port units (Mixer/Splitter) are why `port()`/dict access exists alongside attribute access; attribute access is the primary idiom for fixed-port units.

### `connect()` validation
- `src` must be an `outlet`, `dst` an `inlet` (or role-compatible); raise `ValueError` otherwise.
- A port may hold at most one stream unless the unit type allows fan-out (Splitter outlets) / fan-in (Mixer inlets).
- Reject connecting a port to itself or across two different `Flowsheet`s.
- `kind` defaults to `"material"`; auto-set to `"energy"` when both ports have `role in {"energy","utility"}`.

---

## 5. Geometry Layer (recomputable)

```python
class Placement:
    x: float; y: float                 # pixels, top-left (resolved from grid or pin)
    width: float; height: float
    orientation: float = 0             # degrees; mirror flags as needed
    col: int | None; row: int | None   # layout-grid cell (from auto-layout or pin)

class Route:
    waypoints: list[tuple[float, float]]   # orthogonal polyline, port-anchor to port-anchor
    lane: int | None = None                # routing-lane assignment (for recycles/parallels)
    manual: bool = False                   # True if user-specified via .via([...])
```

Produced by the layout + routing engines, or overridden by the user. Fully derived from topology (+ pins/waypoints). Never persisted as source-of-truth.

---

## 6. Layout Engine (from scratch — Sugiyama-style layered layout)

Interface so alternate backends (future Graphviz/OGDF) can slot in:

```python
class LayoutEngine(Protocol):
    def layout(self, fs: Flowsheet) -> None: ...   # writes Placement on each Unit
```

Default engine phases:

**Phase 0 — Cycle breaking / recycle detection.**
Build directed graph (material streams only). Identify feed units (no material inlets) as roots; if none exists (closed loop), pick the highest-flow/degree node or a `tear_hint`. Compute a **feedback arc set** (greedy Eades–Lin–Smyth heuristic) to obtain a DAG. Edges in the FAS are the recycles → set `Stream.is_recycle = True`. A `tear_hint=True` stream is preferred as the arc to cut when a cycle offers several choices. **This analysis is reused by the future SM balance solver as its tear streams.**

**Phase 1 — Layer (rank) assignment.**
Longest-path layering on the DAG assigns each unit a rank (column for LR). Honour pinned `col` as a hard constraint. Insert **virtual nodes** for streams spanning multiple ranks (needed for both crossing reduction and clean routing).

**Phase 2 — Crossing reduction (ordering within ranks).**
Iterative median/barycenter heuristic with down/up sweeps to order units within each rank, minimising stream crossings. Honour pinned `row` as a fixed position.

**Phase 3 — Coordinate assignment.**
Map (col, row) → pixels using per-unit symbol sizes + configurable rank/node gaps. Apply a straightening/alignment pass (simplified Brandes–Köpf) to align chained units and reduce bends.

**Phase 4 — Port-anchor resolution.**
For each placed unit + its symbol template, compute the **absolute (x, y) of every named port anchor**. These exact anchor points are the router's terminals.

**Pinning semantics:** `pin(col, row)` participates as a hard constraint in Phases 1–2 (cooperates with auto-layout). `pin(x, y)` is an absolute pixel override applied in Phase 3 (escape hatch; may fight layout — documented).

---

## 7. Routing Engine (from scratch — orthogonal connector routing)

Based on the standard visibility-graph + A* + bend-penalty method (Wybrow, Marriott & Stuckey, *Orthogonal Connector Routing*, GD 2009 — the algorithm behind libavoid), implemented in simplified pure-Python form.

```python
class Router(Protocol):
    def route(self, fs: Flowsheet) -> None: ...    # writes Route on each Stream
```

**Pipeline:**
1. **Obstacles:** unit bounding boxes expanded by a margin.
2. **Orthogonal visibility graph:** from every port anchor and every obstacle corner, shoot horizontal + vertical rays; intersections form candidate vertices connected by axis-aligned edges that don't cross obstacles. (A sparse geometry-derived graph, far better than a fixed raster.)
3. **A\* per stream:** from source-port anchor to dest-port anchor. Cost = segment length **+ a heavy per-bend penalty** → short, few-bend routes. Constrain the first segment to leave along the port's `side` (an outlet on the east face exits going east).
4. **Recycles:** routed in reserved lanes above/below the equipment band so they visibly loop back, with higher bend tolerance.
5. **Parallel-segment separation (v1 simplified):** assign overlapping parallel segments to distinct integer lanes via an offset/ordering pass — cheaper than full libavoid nudging.

**Manual override:** `stream.via([(x1,y1), (x2,y2), ...])` forces waypoints; the router simply connects them orthogonally. This is the pragmatic escape hatch for the minority of routes the auto-router draws poorly, deferring a full nudging optimiser to a later version.

**Known v1 limitation (documented):** no global crossing/nudging optimisation across all streams simultaneously; dense diagrams may need occasional `.via()` hints.

---

## 8. Rendering Layer

```python
class Renderer(Protocol):
    def render(self, fs: Flowsheet, path: str, **opts) -> None: ...

class SymbolRegistry:
    def register(self, kind: str, template: Symbol) -> None
    def get(self, kind: str) -> Symbol
    # ships a minimal built-in set; users register custom symbols per unit kind

class Symbol:
    svg: str                           # <symbol>/<defs> template or path geometry
    width: float; height: float
    ports: dict[str, tuple[float, float]]   # named port anchors in symbol-local coords
```

- **`SvgRenderer`** consumes topology + geometry, emits SVG (via `svgwrite` (MIT) or `lxml` (BSD)). Equipment drawn from registered symbols via `<use>`; streams as polylines with arrowheads; recycles styled distinctly (e.g. dashed / different colour); labels for units and streams.
- **PDF/PNG** via `cairosvg` behind an optional extra (`pip install pfd[pdf]`) so the SVG core has **zero non-permissive dependencies**.
- **Symbol seeding:** v1 ships a small hand-built generic set. The registry is designed so the **MIT-licensed `equinor/engineering-symbols`** set (SVG + named connection points) can be vendored/adapted later without API change.
- **Web later:** a future commercial `WebRenderer` implements the same `Renderer` protocol against the same topology+geometry — no core change.

---

## 9. Public API — Final Reference

```python
from pfd import Flowsheet, units

fs = Flowsheet("Ammonia Loop", direction="LR")

feed     = fs.add(units.Feed("Natural Gas"))
reformer = fs.add(units.Reactor("R-101"))
hx       = fs.add(units.HeatExchanger("E-101"))
sep      = fs.add(units.Separator("V-101"))
comp     = fs.add(units.Compressor("K-101"))
prod     = fs.add(units.Product("Ammonia"))

# Streams connect PORT -> PORT. Recycle is NOT declared — the engine detects it.
fs.connect(feed.outlet,     reformer.feed)
fs.connect(reformer.outlet, hx.hot_in)
fs.connect(hx.hot_out,      sep.feed)
fs.connect(sep.vapor,       comp.suction)
fs.connect(comp.discharge,  reformer.feed)     # engine finds this is a recycle back-edge
fs.connect(sep.liquid,      prod.inlet)

# Fully automatic:
fs.render("ammonia.svg")        # layout() + route() run implicitly if not already done
fs.render("ammonia.pdf")        # same geometry, PDF via cairosvg

# Partial manual override:
reformer.pin(col=2, row=0)                        # grid cell; cooperates with auto-layout
fs.connect(sep.vapor, comp.suction).via([(x1,y1)])# manual waypoints for one stream

# Introspection (useful for reports / future balance):
for s in fs.streams:
    print(s.name, "recycle" if s.is_recycle else "forward")
```

**Confirmed API decisions:**
- Connection syntax: `fs.connect(a.port, b.port)` — `Flowsheet.connect()` is the single source of truth for connectivity.
- Ports: attributes primary (`hx.hot_in`); `unit.port("name")`/dict access for variable-port units.
- Pinning: `pin(col, row)` grid-primary; `pin(x, y)` pixel override.
- Naming: `Flowsheet`, `units.Reactor`/`HeatExchanger`/`Separator`/…
- Import/package name: `import pfd` *(verify PyPI availability before first publish; fallbacks: `chem-pfd`, `pyflowdiagram`)*.
- `render(path)` infers format from file extension.
- **Recycle:** removed from the API; `stream.is_recycle` is computed and read-only.

---

## 10. Future: M&E Balance Readiness

No solver is built now, but the model is shaped so either paradigm drops in:

- **State object** on ports/streams holds composition + molar/mass flow + T/P/vapour-fraction/enthalpy; derived properties come from a pluggable thermo backend — **ChEDL `thermo`/`chemicals` (MIT)** is the intended permissive choice; `Cantera` (BSD) for reacting systems.
- **Solver-agnostic unit hook:** `Unit` gains a thin interface (`solve(inlets) -> outlets` for sequential-modular **or** `contribute_equations()` to emit into Pyomo for equation-oriented, IDAES-style). The data model doesn't change either way.
- **Recycle/tear reuse:** the Phase-0 feedback-arc-set already computed for layout is exactly the tear-stream set an SM solver needs; the topological order is the calculation order.
- **Serialization:** `to_dict()` / an SFILES2-style text form makes the topology diff-able and directly consumable by `networkx` (BSD) for tearing/ordering analysis.

This is the commercial layer — it sits *beside* the renderer, consuming the same open topology.

---

## 11. Dependencies & Licensing

- **License:** Apache-2.0 (`LICENSE` + SPDX headers). Commercial M&E engine and web UI are **separate products** on top; the core stays open.
- **Core (SVG output): near-zero deps** — `svgwrite` (MIT) or stdlib/`lxml` (BSD). Optionally `numpy` (BSD) for geometry math; may stay pure-Python.
- **Optional extras:**
  - `pfd[pdf]` → `cairosvg` (LGPL — used as an unmodified, dynamically-imported dependency only; core SVG path never needs it).
  - `pfd[analysis]` → `networkx` (BSD) for graph analysis / future tearing.
- **Explicitly avoided:** GPL/copyleft-in-source deps (`DWSIM`, OGDF core, likely `netgraph`), and native/JVM/JS runtimes (Graphviz binary, ELK).
- **Symbols:** built-in set is original work (Apache-2.0). `equinor/engineering-symbols` (MIT) may be vendored later with attribution.

---

## 12. Proposed Module Structure

```
pfd/
  __init__.py          # public API re-exports (Flowsheet, units, ...)
  flowsheet.py         # Flowsheet
  units.py             # Unit base + built-in unit types + port declarations
  ports.py             # Port
  streams.py           # Stream
  components.py        # Component registry
  state.py             # State (future balance; minimal stub in v1)
  geometry.py          # Placement, Route
  layout/
    __init__.py        # LayoutEngine protocol + default engine
    cycles.py          # feedback-arc-set / recycle detection (Phase 0)
    layering.py        # rank assignment (Phase 1)
    ordering.py        # crossing reduction (Phase 2)
    coordinates.py     # coordinate assignment + port anchors (Phases 3-4)
  routing/
    __init__.py        # Router protocol + default router
    visibility.py      # orthogonal visibility graph
    astar.py           # A* with bend penalty
  render/
    __init__.py        # Renderer protocol
    svg.py             # SvgRenderer
    symbols.py         # SymbolRegistry + built-in symbols
  serialize.py         # to_dict / SFILES2-style text form
  backends/            # (future) graphviz.py, ogdf.py — optional LayoutEngine impls
```

Existing skeleton (`PFD/units.py`, `PFD/streams.py`, `PFD/figure.py`) is superseded by this structure; the `UnitOperation.connections` dict and the standalone `Stream(source, destination)` are unified into the port-based model above. Package folder renamed `PFD/` → `pfd/` (lowercase import).

---

## 13. Testing Strategy

- **Topology unit tests:** port declarations, `connect()` validation (direction/role, duplicates, cross-flowsheet, self-connect), variable-port fan-in/out.
- **Recycle detection tests:** feed-forward (no recycles), single recycle, nested/interlocked recycles, self-loop, closed loop with no feed — assert the correct streams get `is_recycle`.
- **Layout tests:** rank assignment correctness, pinned col/row honoured, crossing-reduction reduces a known crossing count, virtual-node insertion for long edges.
- **Routing tests (property-based):** every route is axis-aligned; no segment passes through an obstacle; endpoints coincide with the correct port anchors; `.via()` waypoints are respected.
- **Rendering golden-file tests:** render reference flowsheets to SVG, compare against committed normalized SVG.
- **Example gallery** doubles as integration tests and documentation.

---

## 14. Roadmap / Milestones

- **M0 — Foundations:** rename package `pfd/`, `pyproject.toml`, Apache-2.0 `LICENSE`, CI (a `.github/lint.yml` already exists), test harness.
- **M1 — Topology model:** Flowsheet/Unit/Port/Stream/Component + `connect()` validation + `to_dict()`. Fully testable with no drawing.
- **M2 — Render pipeline (manual coords first):** SymbolRegistry + `SvgRenderer` drawing units at *manually placed* positions with straight/manual routes. Proves the end-to-end SVG path early (de-risks, mirrors how `pyflowsheet` works) + PDF via `cairosvg`.
- **M3 — Layout engine:** Phase 0–4 auto-placement. Diagrams draw from topology alone.
- **M4 — Routing engine:** visibility-graph + A* orthogonal auto-routing.
- **M5 — Overrides & polish:** `pin()`, `.via()`, recycle lanes, labels, styling.
- **M6 — Release:** docs, example gallery, PyPI publish.
- **Future (commercial):** M&E balance engine (SM iterator / Pyomo emit) + `State`/thermo backend; `WebRenderer` + interactivity.

Ordering rationale: M2 before M3/M4 gets a *visible, testable* diagram out of the pipeline before the hard algorithmic layers, so each subsequent layer has a rendering harness to validate against.

---

## 15. Open Questions / Risks

1. **PyPI name** — confirm `pfd` is available (fallback `chem-pfd` / `pyflowdiagram`). Distribution name may differ from the `import pfd` name.
2. **Router quality on dense diagrams** — v1 omits global nudging; mitigation is `.via()`. Revisit if real flowsheets look poor.
3. **Variable-port unit ergonomics** — Mixer/Splitter with N ports: finalise the `add_port()` / indexing API during M1.
4. **`cairosvg` LGPL** — acceptable as an optional, unmodified dependency; keep it out of the core so pure-SVG users pull only Apache/MIT/BSD code.
5. **Symbol fidelity** — how soon to adopt `equinor/engineering-symbols` vs. ship generic boxes; decouple via the registry so it's a non-breaking swap.

---

## 16. Summary

Build a permissively-licensed (Apache-2.0), pure-Python PFD library whose **topology model** copies the proven IDAES/pyDEXPI ports-and-streams shape; whose **layout** is a from-scratch Sugiyama engine (with automatic recycle detection as its first phase); whose **routing** is a from-scratch libavoid-style orthogonal router with a manual-waypoint escape hatch; and whose **rendering** emits SVG (PDF/PNG via optional `cairosvg`) through a pluggable symbol registry. The three-layer topology/geometry/render split keeps the core open while leaving clean seams for the commercial M&E balance engine and web renderer to attach later without a rewrite.
