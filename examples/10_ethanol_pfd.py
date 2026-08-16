"""
Example 10: Ethanol Purification A300, a full A3 process flow diagram

Fermentation broth is fed to the beer column T-301. The overhead
condenses to azeotropic ethanol, part of it returned as reflux; the
bottoms are cooled in HX-301, dosed with flocculant and dewatered in
the filter press F-301, which sends filtrate to effluent and drops its
cake onto the belt BC-301. Example 11 draws the same unit as a P&ID.

Drawn at a fixed ``page_size="A3"``, so the zone grid is a property of
the page rather than of the drawing: a note reading "F-301 in zone C-2"
still points at C-2 after the next revision moves it. The sheet carries
the zone-ruled frame, a title strip with revision history, an equipment
list, off-page connectors, a sectioned stream property table and a
utilities summary.
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

# --- Stream property table --------------------------------------------
# Rows render in first-seen key order, so every stream carries the same
# keys; values are drawn verbatim and an empty one renders as "-".
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

    # --- Equipment ----------------------------------------------------
    broth = fs.add(Feed("Fermentation Broth", reference="PFD-201"))
    floc = fs.add(Feed("Flocculant", reference="PCD-301"))
    water = fs.add(Feed("RO Water", reference="PCD-301"))

    # Sieve trays: the beer arrives carrying yeast and grain solids, so
    # the deck has to be one with no pocket to settle in and no moving
    # part to seize -- a large-hole perforated deck. The stripper runs
    # base-loaded, so nothing is given up in turndown for it.
    col = fs.add(Column("T-301", internals="sieve_tray", trays=18,
                        width=110, height=250, label_pos="center",
                        description="Beer Column"))
    cond = fs.add(HeatExchanger("E-301", variant="condenser", width=64,
                                height=64,
                                description="T-301 Overhead Condenser"))
    drum = fs.add(Vessel("V-301", variant="horizontal", width=110,
                         height=36, description="T-301 Reflux Drum"))
    # A Tee, not a Splitter: it draws no symbol and takes no tag, so it
    # puts no row in the equipment list.
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
    # A press makes **two products** and has a nozzle for each: the
    # filtrate leaves ``outlet`` on the east wall and the cake leaves
    # ``cake`` through the floor. Reached by ``port()`` rather than as an
    # attribute, because only the cake-forming variants have them --
    # ``press.cake`` type-checking clean on a bag filter would be a
    # nozzle the machine does not have. ``wash_in`` is offered too and
    # this sheet does not use it.
    press = fs.add(Filter("F-301", variant="press", width=120, height=60,
                          description="Membrane Pressure Filter Press"))
    belt = fs.add(Conveyor("BC-301", length=120,
                           description="Filter Cake Conveyor Belt"))
    belt.nozzle("feed", "N")            # cake is dropped onto the belt, not piped

    ethanol = fs.add(Product("Azeotropic Ethanol", reference="PFD-302"))
    effluent = fs.add(Product("Wastewater", reference="PCD-302"))
    cake = fs.add(Product("Biomass Filter Cake", reference="PFD-501"))

    # --- Placement ----------------------------------------------------
    # A tee is a 12-unit square with a port on the middle of each face
    # it uses, so half its width is the offset from a junction to the
    # corner it is pinned by.
    tee_w = 12.0
    col_x, col_y, col_w = 430.0, 180.0, 110.0
    col.pin(x=col_x, y=col_y)
    col_axis = col_x + col_w / 2                    # distillate / bottoms line
    # Asked of the symbol, not measured off it: Column places its feed
    # by a rule (n_feeds=) and has no fixed fraction to write down.
    col_feed_y = col_y + port_offset(col, "feed")[1]
    col_reflux_y = col_y + port_offset(col, "reflux_in")[1]

    broth.pin(x=140, y=col_feed_y - 25)             # flag tip meets the feed nozzle

    # mirrored="y" puts the shell inlet underneath, so the overhead
    # rises into it straight.
    cond_w = 64.0
    cond.pin(x=col_axis - cond_w / 2, y=56, mirrored="y")

    # orientation=90 puts the tee's run down the page and its branch
    # west. 68/91.5 is where the horizontal drum's draw sits in its own
    # box.
    drum_x, drum_y, drum_w = 700.0, 100.0, 110.0
    drum.pin(x=drum_x, y=drum_y)
    drum_draw_x = drum_x + (68 / 91.5) * drum_w      # liquid draw down the shell
    refl.pin(x=drum_draw_x - tee_w / 2, y=col_reflux_y - tee_w / 2, orientation=90)
    ethanol.pin(x=1330, y=250)

    # Low enough that the boilup rises into the return nozzle.
    reb.pin(x=640, y=420)

    hx_y, hx_h = 510.0, 45.0
    hx.pin(x=900, y=hx_y)
    hx_axis_y = hx_y + hx_h / 2                     # dewatering train runs on it

    # Both make-up feeds land on M-301's west wall a nozzle pitch apart.
    mix1_y, mix1_h = 620.0, 100.0
    mix1.pin(x=560, y=mix1_y)
    floc.pin(x=140, y=545)                          # every flag tip on one line
    water.pin(x=140, y=mix1_y + 0.573 * mix1_h - 25)

    mix2.pin(x=1120, y=hx_axis_y - 15)              # in_1 level with the cooler
    press.pin(x=1250, y=hx_axis_y - 20)
    filtrate_y = press.pin_.y + port_offset(press, "outlet")[1]
    cake_x = press.pin_.x + port_offset(press, "cake")[0]
    effluent.pin(port="inlet", x=1440, y=filtrate_y)
    # The belt runs under the press, so the cake drops out of the floor
    # onto its tail and is thrown off the far end.
    belt_y = 715.0
    belt.pin(port="feed", x=cake_x, y=belt_y)
    cake.pin(port="inlet",
             x=belt.pin_.x + port_offset(belt, "discharge")[0] + 40,
             y=belt.pin_.y + port_offset(belt, "discharge")[1])

    # --- Connections --------------------------------------------------
    # Declared in stream-number order, which is the order the table
    # reads. A number is drawn once, on the first segment declared, so
    # each group starts with the run it belongs on.
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
    # Two products out of one machine, on the two nozzles the machine
    # has. Teeing off the filtrate and calling one leg the cake said the
    # solids leave in the liquid line, which is the opposite of what a
    # press does.
    fs.connect(press.port("outlet"), effluent.inlet, name="S-310")
    fs.connect(press.port("cake"), belt.feed, name="S-501")
    fs.connect(belt.discharge, cake.inlet, name="S-501")

    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Ethanol", "Mass Fraction")]

    # --- Title strip --------------------------------------------------
    # date= and scale= are stated rather than left blank: left blank,
    # the renderer fills in today's date and the ratio it fitted the
    # sheet at.
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

    # --- Sheet furniture ----------------------------------------------
    # include= names the rows: the two tees carry no tag to schedule.
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
