"""
Example 9: Line numbers

The identifier that ties a line on the sheet to the line list, the stress
calculation and the isometric: `6"-P-1001-A1A` — size, service, sequence, spec.
Each line's components go in on `connect()` and the sequence is filled by the
same numbering that hands out `S1`, `S2`, so nothing has to be kept unique by
hand.

The two rules a line number inherits from the stream number are what make it
match the piping:

- it carries **through** a hand valve and a strainer, so one line keeps one
  number over its whole run;
- it **breaks** at a unit marked `significant` — which is exactly where the
  spec breaks, at the control valve and across the relief valve.

The tail-pipe to flare shows the other half: `sequence` set by hand, for a line
that already exists on someone else's line list.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pfd import Flowsheet, units
from pfd.document import Revision, TitleBlock


def main():
    fs = Flowsheet("Transfer and Relief")

    # --- Equipment -------------------------------------------------------
    feed = fs.add(units.Feed("Raw Feed", reference="PFD-100"))
    hv = fs.add(units.Valve("HV-101", description="Suction Isolation Valve"))
    strainer = fs.add(units.Fitting("ST-101", variant="strainer",
                                    description="Suction Strainer"))
    pump = fs.add(units.Pump("P-101", description="Transfer Pump"))
    fv = fs.add(units.Valve("FV-101", variant="control",
                            description="Discharge Control Valve"))
    surge = fs.add(units.Vessel("V-101", width=90, height=140,
                                description="Surge Vessel"))
    psv = fs.add(units.Valve("PSV-101", variant="psv", width=40, height=68,
                             description="Vessel Relief Valve"))
    flare = fs.add(units.Product("To Flare", reference="PFD-900"))
    prod = fs.add(units.Product("To Unit 200", reference="PFD-200"))

    # The control valve and the relief valve are the two spec breaks on this
    # sheet: rating and size both change across them, so the number must not
    # run through. The isolation valve and the strainer are ordinary in-line
    # items and keep the suction line whole.
    fv.significant = True
    psv.significant = True

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle height, not by corner: each symbol carries its ports at a
    # fixed fraction of its box, so matching those fractions is what makes a run
    # straight. Suction spine at y=300, discharge spine at y=280.
    # The run off the feed flag is drawn long on purpose: a line number is a
    # dozen characters wide, and it is labelled on the longest segment it has.
    feed.pin(x=60, y=275)              # flag tip sits at y + 25
    hv.pin(x=235, y=285)               # ports at y + 15
    strainer.pin(x=335, y=280)         # ports at y + 20
    pump.pin(x=425, y=270)             # suction y + 30, discharge y + 10
    fv.pin(x=575, y=265)               # ports at y + 15
    surge.pin(x=725, y=210)            # inlet/outlet at half height
    prod.pin(x=925, y=255)

    # Relief stack: the PSV takes flow in its base and discharges from its side,
    # so it stands directly over the vessel's relief nozzle.
    surge_vent_x = 725 + (31 / 62) * 90
    psv.pin(x=surge_vent_x - (10.5 / 27.8) * 40, y=110)
    flare.pin(x=945, y=110 + (30.2 / 47.2) * 68 - 25)

    # --- Connections -----------------------------------------------------
    # One line number over three segments: the components go on the first, and
    # the group takes it from there.
    suction = fs.connect(feed.outlet, hv.inlet, size='8"', service="P", spec="A1A")
    fs.connect(hv.outlet, strainer.inlet)
    fs.connect(strainer.outlet, pump.suction)

    discharge = fs.connect(pump.discharge, fv.inlet, size='6"', service="P", spec="A1A")
    downstream = fs.connect(fv.outlet, surge.inlet, size='6"', service="P", spec="D1B")
    to_unit = fs.connect(surge.outlet, prod.inlet, size='6"', service="P", spec="D1B")

    relief = fs.connect(surge.vent, psv.inlet, size='3"', service="P", spec="A1A")
    # An existing line, so its sequence comes off the line list rather than off
    # this drawing; the automatic sequence runs on regardless.
    tail = fs.connect(psv.outlet, flare.inlet, size='4"', service="FL",
                      sequence=2740, spec="A1A")

    # --- Line list -------------------------------------------------------
    conditions = [
        (suction, "25 C", "1.2 bara", "42000"),
        (discharge, "26 C", "9.5 bara", "42000"),
        (downstream, "26 C", "4.0 bara", "42000"),
        (to_unit, "26 C", "3.6 bara", "42000"),
        (relief, "26 C", "4.0 bara", "0"),
        (tail, "26 C", "1.1 bara", "0"),
    ]
    for stream, temperature, pressure, flow in conditions:
        stream.properties = {
            "Temperature": temperature,
            "Pressure": pressure,
            "Mass Flow (kg/h)": flow,
        }

    fs.title_block = TitleBlock(
        title="Transfer and Relief U100",
        subtitle="Piping and Instrumentation Diagram",
        drawing_number="P&ID-1009",
        project="Feed Transfer Package",
        company="THE UNIVERSITY OF QUEENSLAND",
        status="ISSUED FOR REVIEW",
        sheet="1",
        of_sheets="1",
        scale="NTS",
        drawn_by="A. Anderson",
        checked_by="J. Smith",
        # Fixed rather than left blank, so re-rendering the sheet does not move
        # the drawing by a day.
        date="2026-07-15",
        revisions=[
            Revision("A", "2026-06-20", "Issued for internal review", "AA"),
            Revision("B", "2026-07-15", "Line numbers added", "AA", "JS"),
        ],
    )

    fs.render(out("line_numbers.svg"), border="zone", show_stream_table=True)
    print("Generated line_numbers.svg")
    for stream in fs.streams:
        print(f"  {stream.source.owner.name} -> {stream.dest.owner.name}: {stream.name}")


if __name__ == "__main__":
    main()
