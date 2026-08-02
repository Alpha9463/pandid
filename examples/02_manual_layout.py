"""
Example 2: Manual placement, and the debug overlay

Two ways to put a unit on the sheet:

- ``pin(x=, y=)`` places the unit's **top-left corner**.
- ``pin(port=..., y=)`` places a **nozzle**, working the corner out backwards.

Both take the same kind of number, and neither point is drawn on an issued
sheet, so ``debug=True`` shows them: a faded red grid, a red cross on every
``pin(x=, y=)`` point, a blue dot on every port, and the coordinate written
against each. It is scaffolding for whoever is writing the placement -- off by
default, and no issued sheet should carry it.

The two trains draw the same geometry, the top pinned by the corner and the
bottom by the nozzle. ``via([...])`` is the third override: explicit orthogonal
waypoints for one stream.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units


def main():
    fs = Flowsheet("Manual Override Example")

    # --- Top train: pinned by the corner ---------------------------------
    # Three corners; each nozzle then lands wherever its own symbol puts it, so
    # these numbers only line up against today's artwork.
    f1 = fs.add(units.Feed("F-1")).pin(x=60, y=105)
    e1 = fs.add(units.HeatExchanger("E-1")).pin(x=210, y=100)
    p1 = fs.add(units.Product("P-1")).pin(x=430, y=105)

    # --- Bottom train: pinned by the nozzle -------------------------------
    # The same drawing 200 units lower. The elevation is written once and each
    # unit hung off it by nozzle; stepping along the row is still the corner's
    # job, so the second pin() names only y and leaves the first call's x
    # alone. Nothing here measures the artwork.
    run_y = 330
    f2 = fs.add(units.Feed("F-2")).pin(x=60).pin(port="outlet", y=run_y)
    e2 = fs.add(units.HeatExchanger("E-2")).pin(x=210).pin(port="tube_in", y=run_y)
    p2 = fs.add(units.Product("P-2")).pin(x=430).pin(port="inlet", y=run_y)

    fs.connect(f1.outlet, e1.tube_in)
    fs.connect(e1.tube_out, p1.inlet)
    fs.connect(f2.outlet, e2.tube_in)

    # via() waypoints are absolute pixels and the router uses them verbatim.
    fs.connect(e2.tube_out, p2.inlet).via([
        (360, 330),
        (360, 380),
        (410, 380),
        (410, 330),
    ])

    out_file = out("manual_layout.svg")
    fs.render(out_file, debug=True)
    print(f"Flowsheet rendered successfully to {out_file}")


if __name__ == "__main__":
    main()
