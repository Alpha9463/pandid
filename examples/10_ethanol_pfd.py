"""
Example 10: Ethanol Purification A300, a full A3 process flow diagram

A complete issue-ready sheet, drawn at a fixed ``page_size="A3"`` so the zone
grid is a property of the page rather than of the drawing: a note reading
"F-301 in zone C-2" still points at C-2 after the next revision moves it.

The unit is the front end of a fuel-ethanol purification train. Fermentation
broth is fed to the beer column T-301, whose overhead condenses to azeotropic
ethanol, part of it returned to the tower as reflux and the rest taken as
product, and whose bottoms are cooled in HX-301 before the biosolids are
flocculated out: the flocculant is made up with RO water in M-301, dosed into
the beer in M-302, and the slurry is dewatered in the membrane filter press
F-301, which sends filtrate to effluent and drops its cake onto the belt
BC-301 to leave the sheet.

Two places on it are junctions rather than plant -- the drum's draw parting
into reflux and distillate, the press's discharge into filtrate and cake -- and
both are drawn as the :class:`~pandid.units.Tee` they are, which puts no symbol
on the drawing and no row in the equipment list.

Everything a real drawing carries is on it: the zone-ruled A3 frame, the title
strip with its revision history, an equipment list docked top-centre, off-page
connectors carrying the drawing they tie into, a sectioned stream property
table along the foot, and a utilities summary. Example 11 is the P&ID of the
same unit.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Column,
    Conveyor,
    Feed,
    Filter,
    Flowsheet,
    HeatExchanger,
    Mixer,
    Product,
    Reactor,
    Tee,
    Vessel,
)
from pandid.document import Revision, TableBox, TitleBlock, equipment_list
from pandid.portgeom import port_offset

# --- Stream property table -------------------------------------------------
# Rows render in first-seen key order, so every stream carries the same keys in
# the same order. Values are strings drawn verbatim; the unit lives in the row
# label. An empty value renders as "-".
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
    broth = fs.add(Feed("Fermentation Broth", reference="PFD-201"))
    floc = fs.add(Feed("Flocculant", reference="PCD-301"))
    water = fs.add(Feed("RO Water", reference="PCD-301"))

    col = fs.add(Column("T-301", width=110, height=250, label_pos="center",
                        description="Beer Column"))
    cond = fs.add(HeatExchanger("E-301", variant="condenser", width=64,
                                height=64,
                                description="T-301 Overhead Condenser"))
    drum = fs.add(Vessel("V-301", variant="horizontal", width=110,
                         height=36, description="T-301 Reflux Drum"))
    # A Tee, not a Splitter: the reflux parts from the distillate in the piping,
    # so it is drawn as nothing at all and carries no tag. A Splitter would put
    # an item on the drawing and a row in the equipment list.
    refl = fs.add(Tee())
    reb = fs.add(HeatExchanger("E-302", variant="kettle", width=120,
                               height=44,
                               description="T-301 Kettle Reboiler"))
    hx = fs.add(HeatExchanger("HX-301", variant="straight_tubes", width=150,
                              height=45,
                              description="Beer Column Bottoms Cooling"))
    mix1 = fs.add(Reactor("M-301", n_feeds=2, width=80, height=100,
                          description="Flocculant Activation Mixer Tank"))
    mix2 = fs.add(Mixer("M-302", n_inlets=2,
                        description="Beer Flocculant Mixer Tank"))
    press = fs.add(Filter("F-301", variant="press", width=120, height=60,
                          description="Membrane Pressure Filter Press"))
    # The second tee, and unlike the first one the size and the service both
    # change across it, so new_line_number breaks the run's number there.
    disch = fs.add(Tee())
    disch.new_line_number = True
    belt = fs.add(Conveyor("BC-301", length=120,
                           description="Filter Cake Conveyor Belt"))
    belt.nozzle("feed", "N")            # cake is dropped onto the belt, not piped

    ethanol = fs.add(Product("Azeotropic Ethanol", reference="PFD-302"))
    effluent = fs.add(Product("Wastewater", reference="PCD-302"))
    cake = fs.add(Product("Biomass Filter Cake", reference="PFD-501"))

    # --- Placement -------------------------------------------------------
    # Positioned by NOZZLE, not by top-left corner: a port sits at a fixed
    # fraction of its symbol's box, so lining two items up means matching those
    # fractions. A tee is a 12-unit square with a port on the middle of each
    # face it uses, so half its width is the offset from a junction to the
    # corner it is pinned by.
    tee_w = 12.0
    col_x, col_y, col_w = 430.0, 180.0, 110.0
    col.pin(x=col_x, y=col_y)
    col_axis = col_x + col_w / 2                    # distillate / bottoms line
    # Asked of the symbol rather than measured off it: the feed is placed by a
    # rule (Column takes n_feeds=) and has no fixed fraction to write down.
    col_feed_y = col_y + port_offset(col, "feed")[1]       # feed, down the shell
    col_reflux_y = col_y + port_offset(col, "reflux_in")[1]  # reflux, up the shell

    broth.pin(x=140, y=col_feed_y - 25)             # flag tip meets the feed nozzle

    # mirrored="y" flips the condenser so its shell inlet is underneath and the
    # overhead rises into it dead straight.
    cond_w = 64.0
    cond.pin(x=col_axis - cond_w / 2, y=56, mirrored="y")

    # The tee is quarter-turned and set on the elevation of the tower's reflux
    # nozzle, which puts its run down the page and its branch out west: the
    # reflux leaves level with the nozzle it returns to and the distillate
    # carries on down. 68/91.5 is where the horizontal drum's draw sits in its
    # own box.
    drum_x, drum_y, drum_w = 700.0, 100.0, 110.0
    drum.pin(x=drum_x, y=drum_y)
    drum_draw_x = drum_x + (68 / 91.5) * drum_w      # liquid draw down the shell
    refl.pin(x=drum_draw_x - tee_w / 2, y=col_reflux_y - tee_w / 2, orientation=90)
    ethanol.pin(x=1330, y=250)

    # Low enough that the boilup rises into the return nozzle rather than
    # dropping back down to it.
    reb.pin(x=640, y=420)

    # The process takes the cooler's W-E pair of nozzles and the cooling water
    # the shell's N-S pair, so the dewatering train runs along hx_axis_y.
    hx_y, hx_h = 510.0, 45.0
    hx.pin(x=900, y=hx_y)
    hx_axis_y = hx_y + hx_h / 2                     # dewatering train runs on it

    # Both make-up feeds land on M-301's west wall a nozzle pitch apart, so the
    # two flags stand clear of each other and route in.
    mix1_y, mix1_h = 620.0, 100.0
    mix1.pin(x=560, y=mix1_y)
    floc.pin(x=140, y=545)                          # every flag tip on one line
    water.pin(x=140, y=mix1_y + 0.573 * mix1_h - 25)

    mix2.pin(x=1120, y=hx_axis_y - 15)              # in_1 level with the cooler
    press_h = 60.0
    press.pin(x=1250, y=hx_axis_y - 20)
    press_out_y = hx_axis_y - 20 + press_h / 2      # discharge, mid-shell
    disch.pin(x=1400, y=press_out_y - tee_w / 2)
    effluent.pin(x=1540, y=press_out_y - 25)        # flag tip on the filtrate leg
    # The belt runs under the branch, so the cake drops onto its tail rather
    # than being piped into its end, and throws off into the flag at its head.
    belt_y, belt_tail = 715.0, 10.0                 # tail nozzle, in from the end
    belt.pin(x=disch.pin_.x + tee_w / 2 - belt_tail, y=belt_y)
    cake.pin(x=1546, y=belt_y + belt_tail - 25)

    # --- Connections -----------------------------------------------------
    # Declared in stream-number order, which is the order the table reads. The
    # overhead and the reboiler circuit are one service each, so every segment
    # takes the same number; a number is drawn once, on the first segment
    # declared, so each group starts with the run the number belongs on.
    fs.connect(broth.outlet, col.feed, name="S-301")
    fs.connect(floc.outlet, mix1.feed_1, name="S-303")
    fs.connect(water.outlet, mix1.feed_2, name="S-304")

    fs.connect(refl.outlet, ethanol.inlet, name="S-305")
    fs.connect(col.distillate, cond.shell_in, name="S-305")
    fs.connect(cond.shell_out, drum.inlet, name="S-305")
    fs.connect(drum.outlet, refl.inlet, name="S-305")
    fs.connect(refl.branch, col.reflux_in, name="S-305", draw_as_recycle=True)

    fs.connect(col.bottoms, reb.shell_in, name="S-306")
    fs.connect(reb.shell_out, col.boilup_in, name="S-306", draw_as_recycle=True)
    fs.connect(reb.bottoms, hx.tube_in, name="S-306")

    fs.connect(hx.tube_out, mix2.in_1, name="S-307")
    fs.connect(mix1.outlet, mix2.in_2, name="S-308")

    fs.connect(mix2.outlet, press.inlet, name="S-309")
    fs.connect(press.outlet, disch.inlet, name="S-309")
    fs.connect(disch.outlet, effluent.inlet, name="S-310")
    fs.connect(disch.branch, belt.feed, name="S-501")
    fs.connect(belt.discharge, cake.inlet, name="S-501")

    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Ethanol", "Mass Fraction")]

    # --- Title strip -----------------------------------------------------
    # The date is stated rather than left blank, so the sheet renders the same
    # today as it did at issue. scale="NTS" for the same kind of reason: a blank
    # cell makes the sheet report the ratio the renderer fitted it at, and a
    # flow diagram has no scale to report -- CHEE4001 p.1 asks only that it "be
    # roughly in proportion (not necessarily to scale)".
    #
    # All three initials are fictional, as they are on 03 and 09. AA is the
    # repo's author.
    fs.title_block = TitleBlock(
        title="Ethanol Purification",
        subtitle="A300 Process Flow Diagram 1",
        drawing_number="PFD-301",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1", scale="NTS",
        date="30/08/25",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "30/07/25", "Issued for internal review", "AA"),
            Revision("B", "20/08/25", "Flocculation package added", "AA"),
            Revision("C", "30/08/25", "Issued For Review", "AA", "JS", "RL"),
        ],
    )

    # --- Sheet furniture -------------------------------------------------
    # Named row by row rather than swept up: the two tees are bulk piping bought
    # by the line and carry no tag to schedule.
    fs.add_annotation(equipment_list(fs, align="top", include=[
        "T-301", "E-301", "V-301", "E-302", "HX-301", "M-301", "M-302", "F-301",
        "BC-301",
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
