"""
Example 2: Manual placement, and the overlay that makes the coordinates readable

Two ways to put a unit on the sheet, drawn one above the other, and the render
argument that shows what they mean.

- ``pin(x=, y=)`` places the unit's **top-left corner**.
- ``pin(port=..., y=)`` places a **nozzle**, and works the corner out backwards.

Both are written as the same kind of number, and neither point is drawn on an
issued sheet, so the two are easy to confuse -- and confusing them is what puts
a dogleg in a run that should have been dead straight. ``debug=True`` is what
makes them visible. It rules a faded red grid carrying its own coordinates, puts
a red cross on the point every ``pin(x=, y=)`` sets and a blue dot on every
port, and writes the coordinate against each. Read a number off the drawing and
type it straight back into this file.

The two trains below draw the same geometry and say it two different ways. The
top one is pinned by the corner and the bottom one by the nozzle, and the
overlay shows why the second is the one to reach for: the bottom train's three
corners sit at three different elevations (305, 300 and 305) while its three
nozzles are all at 330, and 330 is the only number the source mentions.

The overlay is scaffolding for whoever is writing the placement, not part of the
drawing. It is off by default, and no sheet issued to anyone should carry it.

``via([...])`` is the third override shown here: explicit orthogonal waypoints
for one stream, overriding the auto-router for that stream alone.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units


def main():
    fs = Flowsheet("Manual Override Example")

    # --- Top train: pinned by the corner ---------------------------------
    # Three corners, and each nozzle then lands wherever its own symbol puts
    # it. The red crosses on the sheet are these six numbers. Lining a run up
    # this way means knowing that a Feed's outlet sits 25 units down its flag
    # and a heat exchanger's tube side 30 units down its box -- true of today's
    # artwork and of nothing else.
    f1 = fs.add(units.Feed("F-1")).pin(x=60, y=105)
    e1 = fs.add(units.HeatExchanger("E-1")).pin(x=210, y=100)
    p1 = fs.add(units.Product("P-1")).pin(x=430, y=105)

    # --- Bottom train: pinned by the nozzle -------------------------------
    # The same drawing, 200 units lower, said the other way round. A run is a
    # line at one elevation, so the elevation is written once and each unit is
    # hung off it by the nozzle that has to reach it. Stepping along the row is
    # still the corner's job, so x is pinned plainly; the second call names
    # only y, which leaves the x the first call set alone.
    #
    # Nothing here measures the artwork. Redraw the exchanger tomorrow and
    # these three still meet. The top train does not.
    run_y = 330
    f2 = fs.add(units.Feed("F-2")).pin(x=60).pin(port="outlet", y=run_y)
    e2 = fs.add(units.HeatExchanger("E-2")).pin(x=210).pin(port="tube_in", y=run_y)
    p2 = fs.add(units.Product("P-2")).pin(x=430).pin(port="inlet", y=run_y)

    # Both trains auto-route into straight lines, because both got their ports
    # onto one elevation. Only the second one said so.
    fs.connect(f1.outlet, e1.tube_in)
    fs.connect(e1.tube_out, p1.inlet)
    fs.connect(f2.outlet, e2.tube_in)

    # via() override: deliberately dip this run down and bring it back up to
    # enter P-2 horizontally (e.g. to clear a walkway). The waypoints are
    # absolute pixels; the router uses them verbatim. Either side of the
    # detour the run is still at the elevation pinned above.
    fs.connect(e2.tube_out, p2.inlet).via([
        (360, 330),
        (360, 380),
        (410, 380),
        (410, 330),
    ])

    # debug=True draws the overlay. Take it off and this is a plain sheet.
    out_file = out("manual_layout.svg")
    fs.render(out_file, debug=True)
    print(f"Flowsheet rendered successfully to {out_file}")


if __name__ == "__main__":
    main()
