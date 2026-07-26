"""
Example 4: Instrumentation & control loops (ISA-5.1)

A P&ID balloon belongs *on* what it measures, so every instrument here is
anchored to a host with ``add_instrument(..., on=...)``:

- ``on=`` a **stream** taps the line. ``at=`` is the point along its routed
  path, ``offset=`` how far the balloon stands off the tap (``offset=0`` leaves
  an in-line primary element sitting on the line), and ``angle=`` which way it
  branches — measured from the flow direction, so a re-route cannot spin it.
- ``on=`` a **unit** mounts the balloon on equipment, ``at=`` naming the face.
- Alarms are ordinary balloons sharing their controller's loop number; the
  interlock is the ``"logic"`` square hung under it on a dashed line.

Both loops close on a final control element: the controller output lands on
``Valve.actuator``. Signal line types come from ``connect(kind=...)``:
``"electric"`` (dashed), ``"pneumatic"`` (slash ticks), ``"data"``/``"software"``
(dash-dot), ``"capillary"``.

The equipment is pinned so the drawing reads as a sheet rather than a rank
order — the instrumentation below it is placed entirely by its hosts.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pfd import Flowsheet, units


def main():
    fs = Flowsheet("Flow Control Loop")

    feed = fs.add(units.Feed("Feed")).pin(x=60, y=170)
    fv = fs.add(units.Valve("FV-101", variant="control")).pin(x=270, y=180)
    drum = fs.add(units.Vessel("V-101", description="Surge Drum")).pin(x=420, y=145)
    lv = fs.add(units.Valve("LV-101", variant="control")).pin(x=640, y=180)
    prod = fs.add(units.Product("Product")).pin(x=790, y=170)
    # A PSV is tagged as plain text beside the symbol, not in a balloon.
    psv = fs.add(units.Valve("PSV-101", variant="relief")).pin(x=441, y=55)
    flare = fs.add(units.Product("To Flare", reference="P&ID-902")).pin(x=630, y=5)

    line = fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    # Flow loop: orifice plate in the line, transmitter above it on the same
    # impulse line, controller off to one side driving the control valve.
    fs.add_instrument("FE", 101, on=line, at=0.5, offset=0)
    ft = fs.add_instrument("FT", 101, on=line, at=0.5, offset=62)
    fic = fs.add_instrument("FIC", 101, on=ft, at="N", offset=125, angle=35, variant="panel")
    # The controller lands almost directly above the valve it drives, so take
    # its output off the bottom of the balloon: on the default east face the
    # signal leaves away from the valve and has to double back to reach it.
    fic.nozzle("sig_out", "S")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")

    # Level loop: controller mounted on the drum, its alarm pair alongside on
    # the same loop number, interlock square hung underneath.
    lic = fs.add_instrument("LIC", 101, on=drum, at="S", offset=90, variant="panel")
    lah = fs.add_instrument("LAH", 101, on=lic, at="W", offset=50)
    fs.add_instrument("LAL", 101, on=lah, at="W", offset=50)
    fs.add_instrument("I", 1, on=lic, at="S", offset=44, variant="logic")
    fs.connect(lic.sig_out, lv.actuator, kind="electric")

    fs.render(out("control_loop.svg"))
    print("Generated control_loop.svg")


if __name__ == "__main__":
    main()
