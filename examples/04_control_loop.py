"""
Example 4: Instrumentation and control loops (ISA-5.1)

Two loops on a surge drum -- ``FE-101 -> FT-101 -> FIC-101`` on the flow
and ``V-101 -> LT-101 -> LIC-101`` on the level -- each closing on a
control valve, plus two level alarms lettered beside their controller
and an interlock teed off the level measurement.

Each balloon is placed against something, and which keyword names it
says what the two have to do with each other:

- ``sensing=`` the balloon reads it, so a line is drawn between them.
  A **stream** taps the line: ``at=`` is the point along its routed
  path, ``offset=`` how far the balloon stands off the tap, and
  ``angle=`` which way it branches, measured from the flow direction so
  a re-route cannot spin it. A **unit** taps a face, ``at=`` naming it.
- ``acting_on=`` the balloon commands it.
- ``near=`` neither: the balloon only sits there and nothing is drawn.
  What reaches the valve is a signal, stated with ``connect()``.

``display="central"`` is ISO 15519-2 Table 1's single bar, "Information
available in central control system"; a field balloon carries none.

``fs.add_loop(variable, number)`` declares a loop and its members are
tagged from it: a balloon by passing the loop where the number would go,
a valve through ``loop.element(...)`` if it is a primary element and
``loop.tag(...)`` if it is the final one. The loop checks the letters of
everything lettered from the measured variable, so a ``TT`` put on a
flow loop raises at the line that wrote it. The interlock square is in
no loop and takes a literal number.

``add_balloon()`` moves the orifice plate's tag into a balloon on a
short impulse line, which is how a P&ID draws a primary element: the
fitting itself is left unlettered.

Signal line types come from ``connect(kind=...)``: ``"electric"``
(dashed), ``"pneumatic"`` (slash ticks), ``"data"``/``"software"``
(dash-dot), ``"capillary"``.

The equipment is pinned; the instrumentation is placed by its hosts.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Feed, Fitting, Flowsheet, Product, Valve, Vessel
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Flow Control Loop")

    # A loop is the measured variable and the number together, so both
    # being numbered 101 still makes F-101 and L-101 two loops.
    flow = fs.add_loop("F", 101)
    level = fs.add_loop("L", 101)

    # One elevation across the sheet, so every unit is pinned by the
    # nozzle that has to land on it. A boundary flag is pinned at its
    # arrow tip.
    run_y = 195

    feed = fs.add(Feed("Feed")).pin(port="outlet", x=110, y=run_y)
    fv = fs.add(Valve(flow.tag("FV"), variant="control")).pin(
        x=270, port="inlet", y=run_y)
    drum = fs.add(Vessel("V-101", description="Surge Drum")).pin(
        x=420, port="inlet", y=run_y)
    fe = fs.add(Fitting(flow.element("FE"), variant="orifice",
                        description="Feed Orifice Plate")).pin(
        x=180, port="inlet", y=run_y)
    # Flipped so the actuator faces the controller under the drum.
    lv = fs.add(Valve(level.tag("LV"), variant="control")).pin(
        x=640, port="inlet", y=run_y, mirrored="y")
    prod = fs.add(Product("Product")).pin(port="inlet", x=790, y=run_y)
    # Two pins: how high the PSV stands is a free choice and stays a
    # corner, while the axis its riser lands on is read off the nozzle.
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

    # Flow loop. The plate's tag moves into a balloon on the impulse
    # line, so the fitting draws none. offset= is measured from the
    # face, so 38 stands the balloon centre a diameter off the run and
    # 23 leaves FT-101's edge on FE-101's: the pair reads as one column.
    fe_b = fs.add_balloon(fe, at="N", offset=38)
    ft = fs.add_instrument("FT", flow, near=fe_b, at="N", offset=23)
    # ``variant="shared"`` is the circle-in-a-square a controller takes;
    # its bar comes from the square, which is the control room already.
    fic = fs.add_instrument("FIC", flow, near=ft, at="N", offset=110, angle=35,
                            variant="shared")
    # Output off the bottom: on the default east face the signal leaves
    # away from the valve below and has to double back to reach it.
    fic.nozzle("sig_out", "S")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")

    # Level loop: the same three parts, hung off the drum.
    lt = fs.add_instrument("LT", level, sensing=drum, at="S", offset=70)
    lic = fs.add_instrument("LIC", level, near=lt, at="S", offset=95, variant="shared")
    # The alarms are lettering in the controller's own quadrants, not
    # balloons: ISO 15519-2 5.2.5 is a shall, and an alarm is a function
    # of this controller rather than a second instrument. High above the
    # centre line, low below, and no face is spent on either.
    lic.annotate(high="LAH", low="LAL")

    # The interlock takes no face: ``sensing=`` a stream measures ``at=``
    # along the *routed* path, so the square rides wherever the router
    # puts it. angle=90 branches east off a line running south.
    measurement = fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.add_instrument("I", 1, sensing=measurement, at=0.5, offset=44, angle=90,
                      variant="logic")
    fs.connect(lic.sig_out, lv.actuator, kind="electric")

    fs.render(out("control_loop.svg"))
    print("Generated control_loop.svg")


if __name__ == "__main__":
    main()
