"""
Example 4: Instrumentation and control loops (ISA-5.1)

Two loops on a surge drum -- ``FE-101 -> FT-101 -> FIC-101`` on the flow and
``V-101 -> LT-101 -> LIC-101`` on the level -- each closing on a control valve,
plus two level alarms and an interlock teed off the level measurement.

Every balloon is anchored to a host with ``add_instrument(..., on=...)``:

- ``on=`` a **stream** taps the line: ``at=`` is the point along its routed
  path, ``offset=`` how far the balloon stands off the tap (``offset=0`` leaves
  an in-line primary element on the line), and ``angle=`` which way it
  branches, measured from the flow direction so a re-route cannot spin it.
- ``on=`` a **unit** mounts the balloon on equipment, ``at=`` naming the face.

``fs.add_loop(variable, number)`` declares a loop and its members are tagged
from it: a balloon by passing the loop where the number would go, a valve
through ``loop.tag(...)``. The loop checks each member's first letter, so a
``TT`` put on a flow loop raises at the line that wrote it. The interlock
square is in no loop and takes a literal number. Signal line types come from
``connect(kind=...)``: ``"electric"`` (dashed), ``"pneumatic"`` (slash ticks),
``"data"``/``"software"`` (dash-dot), ``"capillary"``.

The equipment is pinned; the instrumentation is placed entirely by its hosts.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Feed, Fitting, Flowsheet, Product, Valve, Vessel
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Flow Control Loop")

    # A loop is the measured variable and the number together, so both being
    # numbered 101 still makes F-101 and L-101 two loops and not one.
    flow = fs.add_loop("F", 101)
    level = fs.add_loop("L", 101)

    # One elevation across the sheet, so every unit is pinned by the nozzle
    # that has to land on it: pin(port=...) asks the symbol where its own
    # nozzle sits. A boundary flag is pinned at the tip of its arrow.
    run_y = 195

    feed = fs.add(Feed("Feed")).pin(port="outlet", x=110, y=run_y)
    fv = fs.add(Valve(flow.tag("FV"), variant="control")).pin(
        x=270, port="inlet", y=run_y)
    drum = fs.add(Vessel("V-101", description="Surge Drum")).pin(
        x=420, port="inlet", y=run_y)
    fe = fs.add(Fitting(flow.tag("FE"), variant="orifice",
                        description="Feed Orifice Plate")).pin(
        x=180, port="inlet", y=run_y)
    # Flipped so the actuator faces the controller under the drum and the
    # signal drops straight in rather than climbing over the valve.
    lv = fs.add(Valve(level.tag("LV"), variant="control")).pin(
        x=640, port="inlet", y=run_y, mirrored="y")
    prod = fs.add(Product("Product")).pin(port="inlet", x=790, y=run_y)
    # Two pins: how high the PSV stands is a free choice and stays a corner,
    # while the axis its riser has to land on is read off the drum's nozzle.
    psv = fs.add(Valve("PSV-101", variant="relief")).pin(y=55).pin(
        port="inlet", x=420 + port_offset(drum, "vent")[0])
    flare = fs.add(Product("To Flare", reference="P&ID-902")).pin(x=630, y=5)

    fs.connect(feed.outlet, fe.inlet)
    fs.connect(fe.outlet, fv.inlet)
    fs.connect(fv.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    # Flow loop. The transmitter hangs off the orifice plate and the controller
    # off the transmitter; ``variant="shared"`` is the circle-in-a-square a
    # controller takes, against the bare circle of ``"panel"``.
    ft = fs.add_instrument("FT", flow, on=fe, at="N", offset=62)
    fic = fs.add_instrument("FIC", flow, on=ft, at="N", offset=125, angle=35, variant="shared")
    # Output off the bottom of the balloon: on the default east face the signal
    # leaves away from the valve below and has to double back to reach it.
    fic.nozzle("sig_out", "S")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")

    # Level loop, the same three parts hung off the drum instead of a fitting.
    lt = fs.add_instrument("LT", level, on=drum, at="S", offset=70)
    lic = fs.add_instrument("LIC", level, on=lt, at="S", offset=95, variant="shared")
    # Both alarms hang off the controller rather than off each other, and each
    # takes a *face* rather than an angle so its line leaves the balloon
    # radially and lands square on the next -- BS ISO 15519-1 §12.1 and §12.4
    # require a functional connection to run orthogonally. Which face is forced:
    # north is the measurement in, east is the output to LV-101, so the two
    # alarms take the two that are left.
    fs.add_instrument("LAH", level, on=lic, at="W", offset=78, variant="shared")
    fs.add_instrument("LAL", level, on=lic, at="S", offset=78, variant="shared")

    # The interlock takes no face: it is teed off the measurement line, and
    # ``on=`` a stream measures ``at=`` along the *routed* path, so the square
    # rides wherever the router puts it. angle=90 branches perpendicular to a
    # run that is already orthogonal -- east off a line running south, which is
    # the side LAH-101 is not on.
    measurement = fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.add_instrument("I", 1, on=measurement, at=0.5, offset=44, angle=90, variant="logic")
    fs.connect(lic.sig_out, lv.actuator, kind="electric")

    fs.render(out("control_loop.svg"))
    print("Generated control_loop.svg")


if __name__ == "__main__":
    main()
