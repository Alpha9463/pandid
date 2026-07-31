"""
Example 4: Instrumentation & control loops (ISA-5.1)

A P&ID balloon belongs *on* what it measures, so every instrument here is
anchored to a host with ``add_instrument(..., on=...)``:

- ``on=`` a **stream** taps the line. ``at=`` is the point along its routed
  path, ``offset=`` how far the balloon stands off the tap (``offset=0`` leaves
  an in-line primary element sitting on the line), and ``angle=`` which way it
  branches, measured from the flow direction, so a re-route cannot spin it.
- ``on=`` a **unit** mounts the balloon on equipment, ``at=`` naming the face.
- Alarms are ordinary balloons fanned off their controller's loop, each one a
  dead end; the interlock is the ``"logic"`` square teed off the *measurement*
  signal line on a dashed line of its own.

Each loop is three symbols and not two, because a control-room balloon has no
process connection of its own: an element or a tap, a transmitter reading it,
and the controller reading the transmitter. ``FE-101 -> FT-101 -> FIC-101`` on
the flow, ``V-101 -> LT-101 -> LIC-101`` on the level.

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
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Flow Control Loop")

    # Both loops are numbered 101. A loop is the measured variable and the
    # number together, so F-101 and L-101 are two loops and not one.
    flow = fs.add_loop("F", 101)
    level = fs.add_loop("L", 101)

    # The process runs at one elevation across the sheet, so every unit on it is
    # pinned by the nozzle that has to land there: pin(port=...) asks the symbol
    # where its own nozzle sits, and nothing here writes down half a valve body.
    # A boundary flag is pinned at the tip of its arrow, which is where its line
    # reaches it.
    run_y = 195

    feed = fs.add(units.Feed("Feed")).pin(port="outlet", x=110, y=run_y)
    fv = fs.add(units.Valve(flow.tag("FV"), variant="control")).pin(
        x=270, port="inlet", y=run_y)
    drum = fs.add(units.Vessel("V-101", description="Surge Drum")).pin(
        x=420, port="inlet", y=run_y)
    fe = fs.add(units.Fitting(flow.tag("FE"), variant="orifice",
                              description="Feed Orifice Plate")).pin(
        x=180, port="inlet", y=run_y)
    # The actuator faces the controller under the drum, so its signal drops
    # straight in rather than climbing over the valve to reach a stem on top.
    lv = fs.add(units.Valve(level.tag("LV"), variant="control")).pin(
        x=640, port="inlet", y=run_y, mirrored="y")
    prod = fs.add(units.Product("Product")).pin(port="inlet", x=790, y=run_y)
    # A PSV is tagged as plain text beside the symbol, not in a balloon. It
    # stands over the drum's relief nozzle, so its inlet is pinned on that
    # nozzle's x; how high it stands is a free choice and stays a corner.
    psv = fs.add(units.Valve("PSV-101", variant="relief")).pin(y=55).pin(
        port="inlet", x=420 + port_offset(drum, "vent")[0])
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
    #
    # A controller is a *circle in a square*, ``variant="shared"``, and never
    # the bare circle of ``"panel"``. CHEE4001 p.13 reads the two shapes apart:
    # "A circle on its own represents an instrument that gives a measurement or
    # readout. It has no controlling function. A circle within a square shows
    # that the instrument has some controlling function." The location bar
    # ``"panel"`` adds says where the thing lives, not what it does, so an FIC
    # drawn that way is a sheet asserting that its controller does not control.
    # Nine of the ten controllers on the issued reference sheet are squared.
    ft = fs.add_instrument("FT", flow, on=fe, at="N", offset=62)
    fic = fs.add_instrument("FIC", flow, on=ft, at="N", offset=125, angle=35, variant="shared")
    # The controller lands almost directly above the valve it drives, so take
    # its output off the bottom of the balloon: on the default east face the
    # signal leaves away from the valve and has to double back to reach it.
    fic.nozzle("sig_out", "S")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")

    # Level loop: the transmitter is mounted on the drum and the controller
    # reads *it*, which is the same three parts as the flow loop above. The
    # drum-to-LT line is impulse tubing and draws solid; the LT-to-LIC line is a
    # measurement and draws dashed. Running the drum straight into the
    # controller instead would give a control-room faceplate a process tap of
    # its own and leave the loop with no measurement signal to trip from.
    lt = fs.add_instrument("LT", level, on=drum, at="S", offset=70)
    lic = fs.add_instrument("LIC", level, on=lt, at="S", offset=95, variant="shared")
    # Both alarms read the controller, so both hang off it. Chaining one to the
    # other would draw the low alarm as though the high alarm fed it.
    #
    # Each takes a *face* at the default angle, so its impulse line leaves the
    # balloon radially and lands square on the next one. BS ISO 15519-1 §12.1
    # requires a functional connection to run horizontally or vertically, and
    # §12.4 requires the junctions to be at right angles; these are ISO 15519-2
    # §5.1.1 functional connection lines, so the rule is theirs too. A branch
    # taken at any other angle from a *circle* also has to leave along a tangent,
    # which draws a line grazing the balloon instead of meeting it.
    #
    # Which face each one gets is forced. The measurement arrives from LT-101
    # into the north and the output leaves to the east towards LV-101: put a
    # balloon on that east face and its tap and the output are drawn one on top
    # of the other as far as the output's first corner. So the controller has
    # two faces to give, and they go to the two alarms.
    fs.add_instrument("LAH", level, on=lic, at="W", offset=78)
    fs.add_instrument("LAL", level, on=lic, at="S", offset=78)

    # The interlock takes no face at all: it is teed off the *measurement*
    # signal line, which is what the issued sheet does with every trip on it --
    # loops 301 and 304 off PT->PIC and LT->LIC, 322 off the two stubs
    # downstream of LI-322, 323 off the TI-323 trunk, four out of four on the
    # measurement side. ISO 15519-2 Figure 17 b) draws the same arrangement:
    # the line for the switching function SLL leaves the *measurement point's*
    # letter code string, not the controller's command to its valve. A plant
    # trips on the level it reads and not on what the controller happened to
    # ask the valve for, and a trip taken off the output stops working the
    # moment the loop is put on manual.
    #
    # Hanging it on an alarm instead would draw the alarm as driving it, and an
    # alarm that acts is lettered S or Z rather than A -- ISO 15519-2 Table 2
    # note 9: "Shall only be used for separate alarm control functions. If
    # control functions S and Z at time of action also trigger an alarm/message,
    # then the A shall not be used in addition to the in front letter codes S or
    # Z." An LAL with an output is a mis-lettered LSL. §7.2.4 is the same rule
    # from the line's end: "Signal lines for different types of control
    # functions should not be joined."
    #
    # ``on=`` a stream measures ``at=`` along its *routed* path, so the square
    # rides the measurement wherever the router puts it, and angle=90 branches
    # perpendicular to a run that is already orthogonal: east off a line running
    # south, which is the side LAH-101 is not on.
    measurement = fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.add_instrument("I", 1, on=measurement, at=0.5, offset=44, angle=90, variant="logic")
    fs.connect(lic.sig_out, lv.actuator, kind="electric")

    fs.render(out("control_loop.svg"))
    print("Generated control_loop.svg")


if __name__ == "__main__":
    main()
