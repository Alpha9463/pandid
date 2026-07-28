"""
Example 4: Instrumentation & control loops (ISA-5.1)

A P&ID balloon belongs *on* what it measures, so every instrument here is
anchored to a host with ``add_instrument(..., on=...)``:

- ``on=`` a **stream** taps the line. ``at=`` is the point along its routed
  path, ``offset=`` how far the balloon stands off the tap (``offset=0`` leaves
  an in-line primary element sitting on the line), and ``angle=`` which way it
  branches, measured from the flow direction, so a re-route cannot spin it.
- ``on=`` a **unit** mounts the balloon on equipment, ``at=`` naming the face.
- Alarms are ordinary balloons on their controller's loop; the interlock is the
  ``"logic"`` square hung under it on a dashed line.

``fs.add_loop(variable, number)`` declares the loop the number belongs to, and
each member is tagged from it: a balloon by passing the loop where the number
would go, a valve through ``loop.tag(...)``. The letters stay on the member and
the loop checks the first of them, so a ``TT`` put on a flow loop raises at the
line that wrote it. The interlock square is in no loop and takes a literal
number, which is what a symbol with no measured variable should do.

Both loops close on a final control element: the controller output lands on
``Valve.actuator``. Signal line types come from ``connect(kind=...)``:
``"electric"`` (dashed), ``"pneumatic"`` (slash ticks), ``"data"``/``"software"``
(dash-dot), ``"capillary"``.

The equipment is pinned so the drawing reads as a sheet rather than a rank
order. The instrumentation below it is placed entirely by its hosts.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units


def main():
    fs = Flowsheet("Flow Control Loop")

    # Both loops are numbered 101. A loop is the measured variable and the
    # number together, so F-101 and L-101 are two loops and not one.
    flow = fs.add_loop("F", 101)
    level = fs.add_loop("L", 101)

    feed = fs.add(units.Feed("Feed")).pin(x=60, y=170)
    fv = fs.add(units.Valve(flow.tag("FV"), variant="control")).pin(x=270, y=180)
    drum = fs.add(units.Vessel("V-101", description="Surge Drum")).pin(x=420, y=145)
    fe = fs.add(units.Fitting(flow.tag("FE"), variant="orifice",
                              description="Feed Orifice Plate")).pin(x=180, y=180)
    # The actuator faces the controller under the drum, so its signal drops
    # straight in rather than climbing over the valve to reach a stem on top.
    lv = fs.add(units.Valve(level.tag("LV"), variant="control")).pin(
        x=640, y=180, mirrored="y")
    prod = fs.add(units.Product("Product")).pin(x=790, y=170)
    # A PSV is tagged as plain text beside the symbol, not in a balloon.
    psv = fs.add(units.Valve("PSV-101", variant="relief")).pin(x=441, y=55)
    flare = fs.add(units.Product("To Flare", reference="P&ID-902")).pin(x=630, y=5)

    fs.connect(feed.outlet, fe.inlet)
    fs.connect(fe.outlet, fv.inlet)
    fs.connect(fv.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    # Flow loop: FE-101 is the orifice plate in the line, drawn as the fitting
    # it is. The transmitter reading it stands over it on an impulse line, and
    # the controller sits off to one side driving the control valve. The
    # element carries the loop's tag, so the balloon above it is the
    # transmitter rather than a second FE.
    ft = fs.add_instrument("FT", flow, on=fe, at="N", offset=62)
    fic = fs.add_instrument("FIC", flow, on=ft, at="N", offset=125, angle=35, variant="panel")
    # The controller lands almost directly above the valve it drives, so take
    # its output off the bottom of the balloon: on the default east face the
    # signal leaves away from the valve and has to double back to reach it.
    fic.nozzle("sig_out", "S")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")

    # Level loop: controller mounted on the drum, its alarm pair alongside on
    # the same loop, interlock square hung underneath.
    lic = fs.add_instrument("LIC", level, on=drum, at="S", offset=90, variant="panel")
    # Both alarms read the controller, so both hang off it. Chaining one to the
    # other would draw the low alarm as though the high alarm fed it.
    fs.add_instrument("LAH", level, on=lic, at="W", offset=78, angle=62)
    fs.add_instrument("LAL", level, on=lic, at="W", offset=78, angle=118)
    fs.add_instrument("I", 1, on=lic, at="S", offset=44, variant="logic")
    fs.connect(lic.sig_out, lv.actuator, kind="electric")

    fs.render(out("control_loop.svg"))
    print("Generated control_loop.svg")


if __name__ == "__main__":
    main()
