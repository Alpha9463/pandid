"""
Example 2: Manual Layout and Routing

Demonstrates pixel-level control with two overrides:

- ``pin(x=, y=)`` places a unit at exact SVG coordinates. Align the port
  heights and the connecting streams run dead straight.
- ``via([...])`` forces a stream along explicit orthogonal waypoints, overriding
  the auto-router for that one stream.

Port height cheat-sheet (local y within the symbol): Feed outlet and Product
inlet sit at y+25; the heat-exchanger tube side sits at y+30. So a Feed/Product
pinned 5px *above* an exchanger lines the stream up perfectly.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units


def main():
    fs = Flowsheet("Manual Override Example")

    # Top train, pinned so every port is on the same line: straight runs.
    f1 = fs.add(units.Feed("F-1")).pin(x=60, y=105)
    e1 = fs.add(units.HeatExchanger("E-1")).pin(x=210, y=100)
    p1 = fs.add(units.Product("P-1")).pin(x=430, y=105)

    # Bottom train: the same idea, 200px lower.
    f2 = fs.add(units.Feed("F-2")).pin(x=60, y=305)
    e2 = fs.add(units.HeatExchanger("E-2")).pin(x=210, y=300)
    p2 = fs.add(units.Product("P-2")).pin(x=430, y=305)

    # These auto-route into clean straight lines because the pins are aligned.
    fs.connect(f1.outlet, e1.tube_in)
    fs.connect(e1.tube_out, p1.inlet)
    fs.connect(f2.outlet, e2.tube_in)

    # via() override: deliberately dip this run down and bring it back up to
    # enter P-2 horizontally (e.g. to clear a walkway). The waypoints are
    # absolute pixels; the router uses them verbatim.
    fs.connect(e2.tube_out, p2.inlet).via([
        (360, 330),
        (360, 380),
        (410, 380),
        (410, 330),
    ])

    out_file = out("manual_layout.svg")
    fs.render(out_file)
    print(f"Flowsheet rendered successfully to {out_file}")


if __name__ == "__main__":
    main()
