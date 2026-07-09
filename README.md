# pfd (Process Flow Diagram) Engine

`pfd` is a zero-dependency, pure-Python visualization engine for Chemical Engineering Process Flow Diagrams (PFDs). It transforms abstract topological flowsheet definitions into publication-quality orthogonal SVG diagrams.

## Features

- **Topology-First API**: Define your process using intuitive, typed units (Reactors, Columns, Heat Exchangers) and streams.
- **Smart Orthogonal Routing**: Built-in A* router with jump-gaps for stream crossings and automatic parallel segment separation.
- **Cycle Breaking**: Automatically detects recycle streams and routes them in designated outer lanes.
- **Zero Runtime Dependencies**: The core engine relies only on the Python standard library.
- **SVG Rendering**: Generates clean, scalable vector graphics suitable for web dashboards and reports.

## Installation

This package requires Python 3.10+.

```bash
pip install .
```
*(Note: tests require `pytest`)*

## Quick Start

Create an auto-layout process flow diagram in just a few lines of code:

```python
from pfd import Flowsheet, units as U

# 1. Initialize the flowsheet
fs = Flowsheet("Ammonia Loop")

# 2. Add equipment
feed     = fs.add(U.Feed("Natural Gas"))
mixer    = fs.add(U.Mixer("M-101"))
reformer = fs.add(U.Reactor("R-101"))
hx       = fs.add(U.HeatExchanger("E-101"))
sep      = fs.add(U.Separator("V-101"))
comp     = fs.add(U.Compressor("K-101"))
prod     = fs.add(U.Product("Ammonia"))

# 3. Connect ports — streams are created port -> port
fs.connect(feed.outlet,     mixer.in_1)
fs.connect(mixer.outlet,    reformer.feed)
fs.connect(reformer.outlet, hx.hot_in)
fs.connect(hx.hot_out,      sep.feed)
fs.connect(sep.vapor,       comp.suction)
fs.connect(comp.discharge,  mixer.in_2)   # engine detects this as the recycle
fs.connect(sep.liquid,      prod.inlet)

# 4. Render (layout + routing run automatically)
fs.render("ammonia_loop.svg")
```

The engine automatically layers the units, detects the compressor → mixer stream as a recycle (routing it back around the outside), and routes every stream orthogonally.

## Manual Overrides

If you need pixel-perfect control, `pfd` allows you to override the automatic layout engine:

```python
# Pin equipment to exact (x, y) coordinates
hx = fs.add(U.HeatExchanger("E-1")).pin(x=100, y=50)

# Manually specify orthogonal routing waypoints for a stream
fs.connect(feed.outlet, hx.cold_in).via([(130, 65), (130, 110)])
```

## Examples

Check out the `examples/` directory for full, runnable scripts:

- `examples/01_ammonia_loop.py`: Demonstrates the fully automated layout, layering, and recycle detection.
- `examples/02_manual_layout.py`: Demonstrates `pin()` and `.via()` manual overrides.
- `examples/03_distillation_train.py`: A larger two-column train with a recycle, a stream property table, and P&ID-style framing.

## Architecture

`pfd` follows a strict 3-layer architecture:
1. **Topology (`pfd/flowsheet.py`, `pfd/units.py`)**: Defines units, ports, and stream connectivity.
2. **Geometry (`pfd/layout/`, `pfd/routing/`)**: Solves Sugiyama-style layered layout, assigns absolute coordinates, and runs orthogonal A* routing.
3. **Render (`pfd/render/svg.py`)**: Draws the final SVG, resolving crossings into visual jump-gaps.

## License

Apache 2.0
