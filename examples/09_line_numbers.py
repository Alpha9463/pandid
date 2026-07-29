"""
Example 9: Line numbers

The identifier that ties a line on the sheet to the line list, the stress
calculation and the isometric: `6"-P-1001-A1A` is size, service, sequence, spec.
Each line's components go in on `connect()` and the sequence is filled by the
same numbering that hands out `S1`, `S2`, so nothing has to be kept unique by
hand.

The two rules a line number inherits from the stream number are what make it
match the piping:

- it carries **through** a hand valve and a strainer, so one line keeps one
  number over its whole run;
- it **breaks** at a unit marked `new_line_number`, which is exactly where the
  spec breaks, at the control valve and across the relief valve.

The tail-pipe to flare shows the other half: `sequence` set by hand, for a line
that already exists on someone else's line list.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units
from pandid.document import Revision, TitleBlock
from pandid.portgeom import port_offset


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
    fv.new_line_number = True
    psv.new_line_number = True

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle, not by corner: pin(port=...) asks each symbol where its
    # own nozzle sits, so nothing here writes down half a valve body and no
    # in-line device can land off its run. A boundary flag is pinned at the tip
    # of its arrow, which is where its line reaches it.
    # The run off the feed flag is drawn long on purpose: a line number is a
    # dozen characters wide, and it is labelled on the longest segment it has.
    suction_y = 300
    discharge_y = 280

    feed.pin(port="outlet", x=110, y=suction_y)
    hv.pin(port="inlet", x=235, y=suction_y)
    strainer.pin(port="inlet", x=335, y=suction_y)
    # The one rise on the sheet, and it is the pump's own: its discharge nozzle
    # really does sit above its suction, which is what lifts the spine.
    pump.pin(port="suction", x=425, y=suction_y)
    fv.pin(port="inlet", x=575, y=discharge_y)
    surge.pin(port="inlet", x=725, y=discharge_y)
    prod.pin(port="inlet", x=925, y=discharge_y)

    # Relief stack: the PSV takes flow in its base and discharges from its side,
    # so it stands directly over the vessel's relief nozzle.
    # How high it stands is a free choice, so that one is pinned by the corner;
    # only the axis the riser has to land on is read as a nozzle.
    psv.pin(y=110).pin(port="inlet", x=725 + port_offset(surge, "vent")[0])
    flare.pin(port="inlet", x=945, y=110 + port_offset(psv, "outlet")[1])

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
        company="PANDID",
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

    # A line number is a P&ID's identifier, and this sheet is issued as one, so
    # it is drawn as one: its process lines carry no arrowheads, because flow
    # direction on a P&ID is read off the equipment and the line list.
    fs.render(out("line_numbers.svg"), border="zone", diagram="p&id",
              show_stream_table=True)
    print("Generated line_numbers.svg")
    for stream in fs.streams:
        print(f"  {stream.source.owner.name} -> {stream.dest.owner.name}: {stream.name}")


if __name__ == "__main__":
    main()
