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
from pfd.flowsheet import Flowsheet
import pfd.units as U

# 1. Initialize Flowsheet
fs = Flowsheet("Ammonia Loop")

# 2. Add Equipment
feed = fs.add(U.Feed("Fresh Gas"))
comp = fs.add(U.Compressor("K-101"))
rx = fs.add(U.Reactor("R-101"))
flash = fs.add(U.Vessel("V-101"))
prod = fs.add(U.Product("NH3 Liquid"))
purge = fs.add(U.Product("Purge Gas"))

# 3. Connect Topology
fs.connect(feed.outlet, comp.suction)
fs.connect(comp.discharge, rx.feed)
fs.connect(rx.effluent, flash.feed)
fs.connect(flash.liquid, prod.inlet)
fs.connect(flash.vapor, purge.inlet)

# Recycle stream: Vapor from flash back to compressor
fs.connect(flash.vapor, comp.suction)

# 4. Render!
fs.render("ammonia_loop.svg")
```

The engine will automatically layer the units, break the recycle cycle (drawing the vapor return stream around the outside), and route all streams orthogonally.

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

## Architecture

`pfd` follows a strict 3-layer architecture:
1. **Topology (`pfd/flowsheet.py`, `pfd/units.py`)**: Defines units, ports, and stream connectivity.
2. **Geometry (`pfd/layout/`, `pfd/routing/`)**: Solves Sugiyama-style layered layout, assigns absolute coordinates, and runs orthogonal A* routing.
3. **Render (`pfd/render/svg.py`)**: Draws the final SVG, resolving crossings into visual jump-gaps.

## License

Apache 2.0
