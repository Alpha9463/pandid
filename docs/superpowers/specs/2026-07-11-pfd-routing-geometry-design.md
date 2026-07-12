# PFD routing solidity + honest geometry API — design

**Date:** 2026-07-11
**Status:** Approved, in progress
**Branch:** cleanup/repo-review

## Goal

Make the auto-router genuinely solid, and make user-specified coordinates
behave correctly (all constraints satisfied, nothing silently broken, nothing
out of bounds). Along the way, replace the `Placement` class — which conflates
three unrelated concerns — with a model that separates user *intent* from
engine *result*. Keep the backend clean and the public API small and friendly.

Source of truth for project intent: `pfd-project-goals` memory — a lean,
zero-dependency, spec-true engine that lets chemical engineers produce
industry-standard PFDs.

## Root causes found (evidence, not guesses)

1. **Port geometry is computed four times and they disagree.**
   `routing/visibility.py`, `routing/__init__.py`, `layout/coordinates.py`, and
   `render/svg.py` each independently recompute a port's screen position,
   effective width/height, and mirror flip. `render/svg.py` (the source→dest
   endpoints at lines ~291–297) does **not** apply the `mirrored` flip that the
   router applies. Any mirrored unit (e.g. `FV-200` in example 03) therefore has
   its drawn endpoints on the wrong side from where its route was computed — the
   visible "disconnected stub" in the distillation recycle. The renderer always
   draws source→waypoints→dest, so the break is geometry *disagreement*, not a
   missing line.

2. **The router can silently give up.** `DefaultRouter.route` has two `continue`
   paths that leave `stream.route = None`, and the A*-failure fallback L-shape is
   drawn straight through obstacles with no collision check and no diagnostic.

3. **No flow spine.** `assign_coordinates` maps `row → y` linearly and only
   re-aligns degree-1 terminals. Mid-chain units float at mismatched elevations;
   vertical-symbol ports (reactor top-in/bottom-out) force large detours
   (the ammonia S3 excursion to the sheet edge and back).

4. **`Placement` conflates intent, result, and intrinsic size**, and uses
   `x is None` to mean "not user-pinned" — so layout is not idempotent and the
   engine cannot distinguish a pinned coordinate from a computed one. There are
   also two ways to set placement (`pin()` and the raw `Placement(x, y)`
   back-door used by example 03), the positional one being fragile.

## Design

### 1. Geometry model — split intent from result

- `Unit.pin_: Pin | None` — user **intent** only. Set exclusively via
  `pin(col=, row=, x=, y=, orientation=, mirrored=)`. `Pin` exposes
  `is_fixed_xy` (both x and y given) and `has_grid` (col or row given).
- `Unit.frame: Frame | None` — the **result**: `Frame(x, y, w, h, orientation,
  mirrored)`. Written **only** by the layout engine, for **every** unit.
  Read by the router and the renderer.
- Layout is **idempotent**: it recomputes `frame` from `pin_` + topology each
  run, never from a previous `frame`.
- Intrinsic size resolves in one place (explicit `width`/`height`, else the
  symbol default; feed/product get dynamic width from their label).
- Delete `Placement` and the `unit.placement = Placement(x, y)` back-door.
  Migrate example 03 to `pin(x=, y=)`.

### 2. One port-geometry resolver

A single function set — `port_anchor(unit, port) -> (x, y, outward_dir)` plus a
projection helper — computes a port's absolute anchor, outward normal, and
projection point from `unit.frame` + its symbol, applying mirror and scale
**once**. The visibility graph, the router, the coordinate-alignment pass, and
the renderer all call it. This removes the four-way duplication and, by
construction, fixes the render/router mirror disagreement.

### 3. Router contract — never a silent stub

- Every non-manual stream ends with `route.waypoints` whose first point equals
  the source anchor and last equals the dest anchor. No `continue`-to-`None`.
- If A* finds no path, fall back to a **connected** orthogonal path
  (collision-aware where feasible; a direct L/Z as the guaranteed last resort)
  and record a diagnostic on the stream/flowsheet.
- `via()` waypoints are honored but validated against their ports.

### 4. Layout quality (auto)

- Establish a consistent primary-flow baseline (spine) and extend port
  alignment beyond degree-1 terminals to mid-chain units so the main line stays
  straight where topology allows.
- Handle port sides so vertical symbols (columns, reactors) stop forcing
  up-and-over U-turns for horizontal flow.
- Driven per-diagram in the loop (Phase 3), reproducing each defect before
  fixing it (systematic-debugging).

### 5. Validation — `fs.validate() -> list[Issue]`

- **Hard** (raise from `render()`/`to_svg()` unless explicitly suppressed):
  overlapping unit frames, out-of-bounds or negative pinned coordinates,
  duplicate coordinates that collide.
- **Soft** (collected on `fs.warnings`, never fatal): a stream route crossing a
  unit body, excessive detour, label collisions, non-orthogonal segments.
- `render()`/`to_svg()` run `validate()` first.

### 6. Iterate loop (execution)

Grow a `gallery/` of flowsheets: the three existing examples plus stress cases —
a multi-recycle loop, two parallel trains sharing a header, a ~15-unit
auto-layout sheet, and a half-pinned/half-auto sheet. Each round:

1. Render every diagram.
2. Rasterize with `rsvg-convert` (aspect-preserving; `cairosvg` needs native
   cairo which is absent here, and `qlmanage` force-crops to square).
3. Inspect visually **and** run `validate()` + geometry assertions.
4. Dispatch a fix agent for the worst issue (reproduce → fix → review).
5. Re-render; repeat until **every** diagram is clean and `validate()` is empty.

## Build order

1. **Phase 1** — geometry model (`Pin`/`Frame`) + port resolver. Foundation;
   keep all existing tests green through the migration.
2. **Phase 2** — router contract + `fs.validate()`.
3. **Phase 3** — layout quality, loop-driven across the gallery.

## Testing

Extend `tests/test_routing_quality.py` with invariants:
- every routed stream's endpoints equal its source/dest anchors;
- no route crosses a unit interior beyond tolerance;
- pinned coordinates are honored exactly in the resulting `frame`;
- `validate()` flags injected overlaps / out-of-bounds pins;
- layout is idempotent (running it twice yields identical frames).

## Non-goals

- No new runtime dependencies (rasterization tooling is dev-only).
- No unrelated refactoring beyond what serves routing/geometry solidity.
- No change to the topology API (`add`/`connect`/ports) beyond removing the
  `Placement` back-door.
