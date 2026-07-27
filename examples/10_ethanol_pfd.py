"""
Example 10: Ethanol Purification A300 — a full A3 process flow diagram

A complete issue-ready sheet, drawn at a fixed ``page_size="A3"`` so the zone
grid is a property of the page rather than of the drawing: a note reading
"F-301 in zone C-2" still points at C-2 after the next revision moves it.

The unit is the front end of a fuel-ethanol purification train. Fermentation
broth is fed to the beer column T-301, whose overhead condenses to azeotropic
ethanol and whose bottoms are cooled in HX-301 before the biosolids are
flocculated out: the flocculant is made up with RO water in M-301, dosed into
the beer in M-302, and the slurry is dewatered in the membrane filter press
F-301, which sends filtrate to effluent and cake off the sheet.

Everything a real drawing carries is on it: the zone-ruled A3 frame, the title
strip with its revision history, an equipment list docked top-centre, off-page
connectors carrying the drawing they tie into, a sectioned stream property
table along the foot, and a utilities summary beside the title strip.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pfd import Flowsheet, units
from pfd.document import Revision, TableBox, TitleBlock, equipment_list

# --- Stream property table -------------------------------------------------
# Rows render in first-seen key order, so every stream carries the same keys in
# the same order. Values are strings drawn verbatim; the unit lives in the row
# label, which is where a stream table puts it. An empty value renders as "-".
PROPERTY_ROWS = (
    "Temperature (C)", "Pressure (bar)", "Vapour Fraction", "Total Flow (kg/s)",
    "Ethanol", "Water", "CO2", "Biosolids", "Monosaccharides", "SO4", "MEG",
    "Flocculant",
)

PROPERTIES = {
    "S-301": ("35", "1", "0", "38.93", "0.047", "0.887", "3.08E-05", "0.060",
              "3.73E-03", "2.00E-03", "", ""),
    "S-303": ("25", "1", "0", "0.0088", "", "", "", "", "", "", "", "1.000"),
    "S-304": ("25", "1", "0", "0.167", "", "1.000", "", "", "", "", "", ""),
    "S-305": ("68", "1", "0", "2.01", "0.916", "0.084", "5.96E-04", "", "", "",
              "", ""),
    "S-306": ("100", "1", "0.044", "36.93", "trace", "0.930", "", "0.064",
              "3.93E-03", "2.11E-03", "", ""),
    "S-307": ("35", "1", "0", "36.93", "trace", "0.930", "", "0.064",
              "3.93E-03", "2.11E-03", "", ""),
    "S-308": ("25", "1", "0", "0.175", "", "0.950", "", "", "", "", "", "0.050"),
    "S-309": ("35", "1", "0", "37.10", "trace", "0.930", "", "0.063",
              "3.91E-03", "2.10E-03", "", "2.36E-04"),
    "S-310": ("35", "1", "0", "34.30", "trace", "0.990", "", "3.86E-03",
              "4.16E-03", "2.23E-03", "", "1.28E-05"),
    "S-501": ("35", "1", "0", "2.80", "", "0.199", "", "0.797", "8.35E-04",
              "4.49E-04", "", "0.003"),
}


def main():
    fs = Flowsheet("Ethanol Purification A300")

    # --- Equipment -------------------------------------------------------
    broth = fs.add(units.Feed("Fermentation Broth", reference="PFD-201"))
    floc = fs.add(units.Feed("Flocculant", reference="PCD-301"))
    water = fs.add(units.Feed("RO Water", reference="PCD-301"))

    col = fs.add(units.Column("T-301", width=110, height=250, label_pos="center",
                              description="Beer Column"))
    # Overhead: the tower vapour is totally condensed and collected, and the
    # receiver sends the whole condensate off the sheet as product.
    cond = fs.add(units.HeatExchanger("E-301", variant="condenser", width=64,
                                      height=64,
                                      description="T-301 Overhead Condenser"))
    drum = fs.add(units.Vessel("V-301", variant="horizontal", width=110,
                               height=36, description="T-301 Reflux Drum"))
    # The sump drains into the kettle; what boils returns to the tower as
    # boilup and what does not overflows the weir as the bottoms product.
    reb = fs.add(units.HeatExchanger("E-302", variant="kettle", width=120,
                                     height=44,
                                     description="T-301 Kettle Reboiler"))
    hx = fs.add(units.HeatExchanger("HX-301", variant="straight_tubes", width=150,
                                    height=45,
                                    description="Beer Column Bottoms Cooling"))
    mix1 = fs.add(units.Reactor("M-301", n_feeds=2, width=80, height=100,
                                description="Flocculant Activation Mixer Tank"))
    mix2 = fs.add(units.Mixer("M-302", n_inlets=2,
                              description="Beer Flocculant Mixer Tank"))
    press = fs.add(units.Filter("F-301", variant="press", width=120, height=60,
                                description="Membrane Pressure Filter Press"))
    # Filtrate and cake leave the press on separate legs, so its discharge is
    # drawn as the junction where the two products part and each takes a stream
    # number of its own.
    disch = fs.add(units.Splitter("SP-301", n_outlets=2,
                                  description="F-301 Discharge"))

    ethanol = fs.add(units.Product("Azeotropic Ethanol", reference="PFD-302"))
    effluent = fs.add(units.Product("Wastewater", reference="PCD-302"))
    cake = fs.add(units.Product("Biomass Filter Cake", reference="PFD-501"))

    # --- Placement -------------------------------------------------------
    # Equipment is positioned by NOZZLE, not by its top-left corner: a port sits
    # at a fixed fraction of its symbol's box, so lining two items up means
    # matching those fractions. Everything below is either a dead-straight run
    # or a single corner, bar the sump line, which leaves the tower downward and
    # has to climb back into the kettle's underside.
    col_x, col_y, col_w, col_h = 430.0, 180.0, 110.0, 250.0
    col.pin(x=col_x, y=col_y)
    col_axis = col_x + col_w / 2                    # distillate / bottoms line
    col_feed_y = col_y + 0.65 * col_h               # feed nozzle, down the shell

    broth.pin(x=140, y=col_feed_y - 25)             # flag tip meets the feed nozzle

    # Condenser over the tower on the same axis, flipped top-to-bottom so its
    # hot inlet is underneath: the overhead then rises into it dead straight.
    cond_w = 64.0
    cond.pin(x=col_axis - cond_w / 2, y=56, mirrored="y")

    # Drum clear to the right of the tower, so the condensate leaves the
    # condenser's crown, runs over the top of the sheet and drops onto it.
    drum.pin(x=700, y=150)
    ethanol.pin(x=1330, y=230)

    # Kettle off the tower bottom, low enough that the boilup rises into the
    # return nozzle instead of having to drop back down to it.
    reb.pin(x=640, y=420)

    # Bottoms cooler on the kettle's weir draw. The process runs left to right
    # through the shell, so it takes the exchanger's W-E pair of nozzles and the
    # cooling water the N-S pair, which is the way a shell-and-tube is drawn.
    hx_y, hx_h = 510.0, 45.0
    hx.pin(x=900, y=hx_y)
    hx_axis_y = hx_y + hx_h / 2                     # dewatering train runs on it

    # Flocculant make-up below the tower, dosed into the beer downstream of the
    # cooler. Both make-up feeds land on the tank's west wall a nozzle pitch
    # apart, so the two flags stand well clear of each other and route in.
    mix1_y, mix1_h = 620.0, 100.0
    mix1.pin(x=560, y=mix1_y)
    floc.pin(x=140, y=545)                          # every flag tip on one line
    water.pin(x=140, y=mix1_y + 0.573 * mix1_h - 25)

    mix2.pin(x=1120, y=hx_axis_y - 15)              # in_1 level with the cooler
    press.pin(x=1250, y=hx_axis_y - 20)
    disch.pin(x=1420, y=hx_axis_y - 15)
    effluent.pin(x=1540, y=hx_axis_y - 25)          # flag tip on the filtrate leg
    cake.pin(x=1540, y=700)

    # --- Connections -----------------------------------------------------
    # Declared in stream-number order, which is the order the table reads.
    #
    # The tower overhead and the reboiler circuit are each one service from the
    # tower to where the material leaves it, so every segment of one carries the
    # same number rather than being numbered piece by piece. A number is drawn
    # once, on the first segment declared, so each group starts with the run the
    # number belongs on.
    fs.connect(broth.outlet, col.feed, name="S-301")
    fs.connect(floc.outlet, mix1.feed_1, name="S-303")
    fs.connect(water.outlet, mix1.feed_2, name="S-304")

    fs.connect(drum.outlet, ethanol.inlet, name="S-305")
    fs.connect(col.distillate, cond.hot_in, name="S-305")
    fs.connect(cond.hot_out, drum.inlet, name="S-305")

    fs.connect(col.bottoms, reb.cold_in, name="S-306")
    fs.connect(reb.cold_out, col.boilup_in, name="S-306", tear_hint=True)
    fs.connect(reb.bottoms, hx.cold_in, name="S-306")

    fs.connect(hx.cold_out, mix2.in_1, name="S-307")
    fs.connect(mix1.outlet, mix2.in_2, name="S-308")

    fs.connect(mix2.outlet, press.inlet, name="S-309")
    fs.connect(press.outlet, disch.inlet, name="S-309")
    fs.connect(disch.out_1, effluent.inlet, name="S-310")
    fs.connect(disch.out_2, cake.inlet, name="S-501")

    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Ethanol", "Mass Fraction")]

    # --- Title strip -----------------------------------------------------
    # The date is stated rather than left blank, so the sheet renders the same
    # today as it did at issue.
    fs.title_block = TitleBlock(
        title="Ethanol Purification",
        subtitle="A300 Process Flow Diagram 1",
        drawing_number="PFD-301",
        company="THE UNIVERSITY OF QUEENSLAND",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        date="30/08/25",
        drawn_by="AA", checked_by="RG", approved_by="HVL",
        revisions=[
            Revision("A", "30/07/25", "Issued for internal review", "AA"),
            Revision("B", "20/08/25", "Flocculation package added", "AA"),
            Revision("C", "30/08/25", "Issued For Review", "AA", "RG", "HVL"),
        ],
    )

    # --- Sheet furniture -------------------------------------------------
    # The list is named row by row: the condenser, drum and reboiler are tagged
    # plant on this sheet and belong on it, while the discharge junction is a
    # branch in the piping and does not.
    fs.add_annotation(equipment_list(fs, align="top", include=[
        "T-301", "E-301", "V-301", "E-302", "HX-301", "M-301", "M-302", "F-301",
    ]))
    fs.add_annotation(TableBox(
        title="UTILITIES SUMMARY",
        headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in",
                 "T_out"],
        rows=[
            ["Cold Water", "HX-301", "-13161", "630.7", "25 C", "30 C"],
            ["Cold Water", "E-301", "-5645", "270.5", "25 C", "30 C"],
            ["High Pressure Steam", "E-302", "19112", "11.116", "250 C",
             "249 C"],
        ],
        col_align=["l", "l", "r", "r", "c", "c"],
        align="bottom-right",
    ))

    fs.render(out("ethanol_pfd.svg"), page_size="A3", border="zone",
              show_stream_table=True)
    print("Generated ethanol_pfd.svg")


if __name__ == "__main__":
    main()
