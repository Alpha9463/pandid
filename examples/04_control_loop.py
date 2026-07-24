"""
Example 4: Instrumentation & control loop (ISA-5.1)

Demonstrates the instrumentation subsystem:

- ``Instrument`` balloons whose ``name`` is the tag (drawn inside, ISA-style:
  functional letters over the loop number). Variants pick the balloon style /
  location: ``"field"`` (bare circle, default), ``"panel"`` (single bar),
  ``"aux"`` (double bar), ``"shared"`` (DCS square), ``"computer"`` (hexagon).
- Signal line types via ``connect(kind=...)``: ``"electric"`` (dashed),
  ``"pneumatic"`` (double-slash ticks), ``"data"``/``"software"`` (dash-dot),
  ``"capillary"``.
- A control valve (``Valve`` variant ``"control"``) on the process line.
"""

from pfd import Flowsheet, units


def main():
    fs = Flowsheet("Flow Control Loop")

    # Process line with a control valve.
    feed = fs.add(units.Feed("Feed"))
    fv = fs.add(units.Valve("FV-101", variant="control"))
    prod = fs.add(units.Product("Product"))
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)

    # Instrument loop: transmitter -> controller -> computing relay -> recorder.
    ft = fs.add(units.Instrument("FT-101"))                    # field flow transmitter
    fic = fs.add(units.Instrument("FIC-101", variant="panel")) # panel-mounted controller
    fy = fs.add(units.Instrument("FY-101", variant="computer")) # computing relay
    fr = fs.add(units.Instrument("FR-101", variant="shared"))   # shared/DCS recorder

    fs.connect(ft.sig_out, fic.sig_in, kind="electric")    # 4-20 mA, dashed
    fs.connect(fic.sig_out, fy.sig_in, kind="pneumatic")   # 3-15 psi, slash ticks
    fs.connect(fy.sig_out, fr.sig_in, kind="data")         # fieldbus, dash-dot

    fs.render("control_loop.svg")
    print("Generated control_loop.svg")


if __name__ == "__main__":
    main()
