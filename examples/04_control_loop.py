"""
Example 4: Instrumentation and control loops (ISA-5.1)

A surge drum with a flow loop (FE-101, FT-101, FIC-101 on FV-101), a
level loop (LT-101, LIC-101 on LV-101), two level alarms and an
interlock. The flow loop is built part by part with ``add_loop`` and
``add_instrument``; the level loop in one ``add_control_loop`` call.
The equipment is pinned; each instrument is placed against its host.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import ControlValve, Feed, Fitting, Flowsheet, Product, ReliefValve, Vessel
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Flow Control Loop")

    flow = fs.add_loop("F", 101)
    level = fs.add_loop("L", 101)

    # Pin every unit by the nozzle on the run's elevation.
    run_y = 195

    feed = fs.add(Feed("Feed")).pin(port="outlet", x=110, y=run_y)
    fv = fs.add(ControlValve(flow.tag("FV"))).pin(
        x=270, port="inlet", y=run_y)
    drum = fs.add(Vessel("V-101", description="Surge Drum")).pin(
        x=420, port="inlet", y=run_y)
    fe = fs.add(Fitting(flow.element("FE"), variant="orifice",
                        description="Feed Orifice Plate")).pin(
        x=180, port="inlet", y=run_y)
    # Flipped so the actuator faces the controller under the drum.
    lv = fs.add(ControlValve(level.tag("LV"))).pin(
        x=640, port="inlet", y=run_y, mirrored="y")
    prod = fs.add(Product("Product")).pin(port="inlet", x=790, y=run_y)
    # Pin the PSV's height by its corner and its x by its inlet.
    psv = fs.add(ReliefValve("PSV-101")).pin(y=55).pin(
        port="inlet", x=420 + port_offset(drum, "vent")[0])
    flare = fs.add(Product("To Flare", reference="P&ID-902")).pin(x=630, y=30)

    fs.connect(feed.outlet, fe.inlet)
    fs.connect(fe.outlet, fv.inlet)
    fs.connect(fv.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    # Flow loop. add_balloon moves the plate's tag into a balloon.
    fe_b = fs.add_balloon(fe, face="N", offset=38)
    ft = fs.add_instrument("FT", flow, near=fe_b, face="N", offset=23)
    fic = fs.add_instrument("FIC", flow, near=ft, face="N", offset=110, angle=35,
                            variant="shared")
    # Take the output off the south face, towards the valve.
    fic.nozzle("sig_out", "S")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")

    # Level loop: transmitter, controller and both signal lines in one
    # call, acting on the valve already in the run.
    level_loop = fs.add_control_loop(
        level, measuring=drum, acting_on=lv, face="S", offset=70,
        controller_face="S", controller_offset=95, output_kind="electric")
    # Letter the alarms in the controller's quadrants.
    level_loop.controller.annotate(high="LAH", low="LAL")

    # Interlock halfway along the level measurement line.
    fs.add_instrument("I", 1, sensing=level_loop.measurement, at=0.5, offset=44,
                      angle=90, variant="logic")

    fs.render(out("control_loop.svg"), diagram="p&id")
    print("Generated control_loop.svg")


if __name__ == "__main__":
    main()
