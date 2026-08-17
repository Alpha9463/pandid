"""
Example 2: Manual placement, and the debug overlay

Two ways to put a unit on the sheet:

- ``pin(x=, y=)`` places the unit's **top-left corner**. A ``Feed`` or a
  ``Product`` is the exception: its flag has one nozzle and no drawn
  corner, so the coordinate places the tip.
- ``pin(port=..., y=)`` places a **nozzle**, working the corner out
  backwards.

Neither point is drawn on an issued sheet, so ``debug=True`` shows them:
a faded red grid, a red cross on every ``pin(x=, y=)`` point, a blue dot
on every port, and the coordinate written against each. It is
scaffolding for whoever is writing the placement -- off by default.

The two trains draw the same geometry, the top exchanger pinned by the
corner and the bottom one by the nozzle. ``via([...])`` is the third
override: explicit orthogonal waypoints for one stream.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Feed, Flowsheet, HeatExchanger, Product


def main():
    fs = Flowsheet("Manual Override Example")

    # --- Top train: the exchanger pinned by its corner -----------------
    # Its nozzles land wherever its own symbol puts them, so the 100
    # here only meets the flags' 130 against today's artwork.
    f1 = fs.add(Feed("F-1")).pin(x=110, y=130)
    e1 = fs.add(HeatExchanger("E-1")).pin(x=210, y=100)
    p1 = fs.add(Product("P-1")).pin(x=430, y=130)

    # --- Bottom train: the exchanger pinned by its nozzle --------------
    # The same drawing 200 units lower. The elevation is written once
    # and every unit hung off it; stepping along the row is still the
    # corner's job, so the exchanger's second pin() names only y.
    run_y = 330
    f2 = fs.add(Feed("F-2")).pin(x=110, y=run_y)
    e2 = fs.add(HeatExchanger("E-2")).pin(x=210).pin(port="tube_in", y=run_y)
    p2 = fs.add(Product("P-2")).pin(x=430, y=run_y)

    fs.connect(f1.outlet, e1.tube_in)
    fs.connect(e1.tube_out, p1.inlet)
    fs.connect(f2.outlet, e2.tube_in)

    # via() waypoints are absolute pixels, used verbatim.
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
