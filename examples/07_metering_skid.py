"""
Example 7: Feed conditioning and metering skid

Exercises the inline fittings and actuated valves: feed is strained, pumped,
metered through a rotameter, throttled by a motor-operated valve, held in a
surge vessel protected by a spring relief valve, and checked through a sight
glass on the way out.

Everything sits on one spine so the runs are straight. The only rise is across
the pump, whose discharge nozzle is above its suction — which is what a pump
actually looks like, not a routing artefact.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units


def main():
    fs = Flowsheet("Feed Metering Skid")

    # --- Equipment -------------------------------------------------------
    feed = fs.add(units.Feed("Raw Feed", reference="PFD-100"))
    strainer = fs.add(units.Fitting("ST-101", variant="strainer",
                                    description="Suction Strainer"))
    pump = fs.add(units.Pump("P-101", description="Feed Pump"))
    meter = fs.add(units.Fitting("FI-101", variant="rotameter",
                                 description="Variable-Area Flow Meter"))
    fv = fs.add(units.Valve("FV-101", variant="motor",
                            description="Motor-Operated Throttle Valve"))
    surge = fs.add(units.Vessel("V-101", width=90, height=140,
                                description="Surge Vessel"))
    psv = fs.add(units.Valve("PSV-101", variant="psv", width=40, height=68,
                             description="Vessel Relief Valve"))
    flare = fs.add(units.Product("To Flare", reference="PFD-900"))
    glass = fs.add(units.Fitting("SG-101", variant="sight_glass",
                                 description="Sight Glass"))
    prod = fs.add(units.Product("To Unit 200", reference="PFD-200"))

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle height, not by corner: each symbol carries its ports at
    # a fixed fraction of its box, so matching those fractions is what makes a
    # run straight. Suction spine at y=300, discharge spine at y=280.
    feed.pin(x=60, y=275)              # flag tip sits at y + 25
    strainer.pin(x=190, y=280)         # ports at y + 20
    pump.pin(x=280, y=270)             # suction y + 30, discharge y + 10
    meter.pin(x=430, y=265)            # ports at y + 15
    # Flipped top-to-bottom so the motor operator faces down, on the same side
    # as the controller: otherwise the signal has to climb over the vessel to
    # reach it. Mirroring moves the process ports to y + 14.7.
    fv.pin(x=540, y=265.3, mirrored="y")
    surge.pin(x=680, y=210)            # inlet/outlet at half height
    glass.pin(x=850, y=267.5)          # ports at y + 12.5
    prod.pin(x=980, y=255)

    # Relief stack: the PSV takes flow in its base and discharges from its side,
    # so it stands directly over the vessel's relief nozzle.
    surge_vent_x = 680 + (31 / 62) * 90
    psv.pin(x=surge_vent_x - (10.5 / 27.8) * 40, y=110)
    flare.pin(x=900, y=110 + (30.2 / 47.2) * 68 - 25)

    # --- Connections -----------------------------------------------------
    fs.connect(feed.outlet, strainer.inlet)
    fs.connect(strainer.outlet, pump.suction)
    fs.connect(pump.discharge, meter.inlet)
    fs.connect(meter.outlet, fv.inlet)
    fs.connect(fv.outlet, surge.inlet)
    fs.connect(surge.outlet, glass.inlet)
    fs.connect(glass.outlet, prod.inlet)

    fs.connect(surge.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    # Level controller on the vessel driving the throttle valve's operator.
    # Hung below rather than beside it: the east side is the outlet run, and an
    # instrument placed into equipment is a hard validation error, not a nudge.
    # A balloon has no fixed sides, so the engine takes the signal out on the
    # face the valve is actually on rather than letting the run double back.
    lic = fs.add_instrument("LIC", 101, on=surge, at="S", offset=115,
                            variant="panel")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")

    fs.render(out("metering_skid.svg"))
    print("Generated metering_skid.svg")


if __name__ == "__main__":
    main()
