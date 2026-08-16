"""
Example 13: Mineral Concentrate Dewatering A400, a solids-handling PFD

The first sheet in the gallery that is not a fluids plant. A flotation
concentrate arrives as a dilute slurry and leaves as a dry,
magnetics-free powder, and everything between those two flags is a
solid-liquid or a solid-gas separation: a thickener, a vacuum belt
filter, a rotary dryer, the cyclone that takes the dried product back
out of the gas that dried it, and the scrubber that cleans what is left
before it reaches the stack.

Drawn as a PFD -- an equipment list, a stream table sectioned into a
"Mass Fraction" block, a utilities summary and an arrowhead on every
process line, with no instrument balloon, signal line or valve anywhere
on it.

Sized to the drawing rather than to a page: twenty-four streams side by
side is a wider table than A3 takes beside a utilities summary.
``page_size="A2"`` draws the same sheet on real paper.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Blower,
    Conveyor,
    Cyclone,
    Dryer,
    Feed,
    Filter,
    Flowsheet,
    Funnel,
    Furnace,
    GravitySeparator,
    MagneticSeparator,
    PeristalticPump,
    Product,
    Reducer,
    ScrewPump,
    Scrubber,
    Tank,
    Tee,
    Vent,
)
from pandid.document import Revision, TableBox, TitleBlock, equipment_list
from pandid.portgeom import port_offset

# --- Stream property table --------------------------------------------
# Rows render in first-seen key order, so every stream below carries the
# same keys and an empty value renders as "-".
PROPERTY_ROWS = (
    "Temperature (C)", "Pressure (bara)", "Total Flow (t/h)", "Solids (% w/w)",
    "Water", "Concentrate", "Tramp Metal", "Flocculant", "Air / Flue Gas",
    "Fuel Gas",
)

PROPERTIES = {
    "S-401": ("28", "1.4", "224.0", "28.0", "0.720", "0.2800", "2.2E-05", "",
              "", ""),
    "S-402": ("20", "3.0", "0.630", "", "1.000", "", "", "", "", ""),
    "S-403": ("20", "1.0", "0.002", "100.0", "", "", "", "1.000", "", ""),
    "S-404": ("20", "1.0", "0.632", "0.32", "0.997", "", "", "3.2E-03", "",
              ""),
    "S-405": ("20", "2.0", "0.632", "0.32", "0.997", "", "", "3.2E-03", "",
              ""),
    "S-406": ("28", "1.2", "224.63", "27.9", "0.721", "0.2792", "2.2E-05",
              "8.9E-06", "", ""),
    "S-407": ("28", "1.0", "120.1", "0.01", "1.000", "1.0E-04", "", "", "",
              ""),
    "S-408": ("28", "1.2", "104.5", "60.0", "0.400", "0.5998", "4.8E-05",
              "1.9E-05", "", ""),
    "S-409": ("28", "2.5", "104.5", "60.0", "0.400", "0.5998", "4.8E-05",
              "1.9E-05", "", ""),
    "S-410": ("28", "1.0", "35.6", "0.10", "0.999", "1.0E-03", "", "5.6E-05",
              "", ""),
    "S-411": ("28", "1.0", "68.9", "91.0", "0.090", "0.9099", "7.3E-05", "",
              "", ""),
    "S-412": ("15", "1.0", "30.5", "", "", "", "", "", "1.000", ""),
    "S-413": ("15", "2.0", "0.43", "", "", "", "", "", "", "1.000"),
    "S-414": ("650", "0.99", "30.93", "", "0.031", "", "", "", "0.969", ""),
    # Temperature deliberately blank, which renders as "-".
    "S-415": ("", "0.98", "99.83", "62.8", "0.072", "0.6280", "5.0E-05", "",
              "0.300", ""),
    "S-416": ("115", "0.98", "99.83", "62.8", "0.072", "0.6280", "5.0E-05", "",
              "0.300", ""),
    "S-417": ("115", "0.97", "37.03", "0.35", "0.187", "3.5E-03", "", "",
              "0.809", ""),
    "S-418": ("28", "3.0", "41.5", "", "1.000", "", "", "", "", ""),
    "S-419": ("62", "0.96", "78.53", "0.17", "0.616", "1.7E-03", "", "",
              "0.382", ""),
    "S-420": ("62", "1.0", "35.08", "", "0.146", "trace", "", "", "0.854",
              ""),
    "S-421": ("62", "1.0", "43.45", "0.30", "0.997", "3.0E-03", "", "", "",
              ""),
    "S-422": ("110", "1.0", "62.80", "99.5", "0.005", "0.9949", "8.0E-05", "",
              "", ""),
    "S-423": ("110", "1.0", "62.79", "99.5", "0.005", "0.995", "", "", "",
              ""),
    "S-424": ("110", "1.0", "0.005", "100.0", "", "", "1.000", "", "", ""),
}


def main():
    fs = Flowsheet("Mineral Concentrate Dewatering A400")

    # --- Flocculant make-up -------------------------------------------
    water = fs.add(Feed("Raw Water", reference="PCD-402"))
    # Not in ``document._MAJOR_EQUIPMENT``, so it spends no equipment-
    # list row, like the tees and reducers below.
    funnel = fs.add(Funnel("FN-401",
                           description="Flocculant Charging Funnel"))
    charge = fs.add(Tee(branch="inlet"))
    # ``Tank`` has no agitated variant and ``Reactor``, which draws one,
    # is the wrong symbol for a reagent tank, so the stirrer is not
    # drawn.
    tank = fs.add(Tank("TK-401", variant="conical_bottom",
                       description="Flocculant Make-up Tank"))
    dose = fs.add(PeristalticPump(
        "P-402", description="Flocculant Dosing Pump"))

    # --- Thickening ---------------------------------------------------
    concentrate = fs.add(Feed("Flotation Concentrate",
                              reference="PFD-302"))
    floc = fs.add(Tee(branch="inlet"))
    # ``overflow`` is the high draw off the launder wall and
    # ``underflow`` the low one out of the apex, which is what the
    # stencil draws.
    thickener = fs.add(GravitySeparator(
        "TH-401", description="Concentrate Thickener"))
    overflow = fs.add(Product("Recovered Water", reference="PCD-402"))

    # --- Filtration ---------------------------------------------------
    underflow_pump = fs.add(ScrewPump(
        "P-401", description="Thickener Underflow Pump"))
    # ``large_end="outlet"`` turns the second one into an expander.
    suction_red = fs.add(Reducer("RD-401", variant="eccentric",
                                 description="P-401 Suction Reducer"))
    disch_red = fs.add(Reducer("RD-402", variant="concentric",
                               large_end="outlet",
                               description="P-401 Discharge Expander"))
    # Left as a variant: no class in ``pandid.devices`` covers the
    # liquid belt filter, and ``DustCollector``'s ``belt`` aliases to
    # ``gas_belt``, a different symbol on a gas casing.
    # A belt filter makes **two products** and has a nozzle for each: the
    # filtrate leaves ``outlet`` on the east wall and the cake leaves
    # ``cake`` through the floor. Both are reached by ``port()`` rather
    # than as attributes, because only the four cake-forming variants
    # carry them -- ``f.cake`` type-checking clean on a bag filter would
    # be a nozzle the machine does not have. ``wash_in`` is offered too
    # and this sheet does not use it.
    belt_filter = fs.add(Filter("FL-401", variant="belt", width=60,
                                height=110,
                                description="Concentrate Belt Filter"))
    filtrate = fs.add(Product("Filtrate", reference="PCD-402"))
    # Cake is dropped onto a belt, not piped into it, so the tail nozzle
    # comes off the top face rather than off the end.
    conveyor = fs.add(Conveyor("CV-401", length=150,
                               description="Filter Cake Conveyor"))
    conveyor.nozzle("feed", "N")

    # --- Drying -------------------------------------------------------
    air = fs.add(Feed("Ambient Air"))
    gas = fs.add(Feed("Natural Gas", reference="PCD-403"))
    # ``Furnace`` and not ``Heater``: the difference between the two
    # classes is the ``fuel`` nozzle, and the fuel line is why this item
    # is here.
    heater = fs.add(Furnace("FH-401", description="Dryer Air Heater"))
    # The dryer's feed breeching is bought and tagged with the dryer, so
    # it is a tee rather than an item of its own.
    breeching = fs.add(Tee(branch="inlet"))
    # **Two nozzles where the plant has four.** ``units.Dryer`` declares
    # only ``feed`` and ``product``, so the solids chute and the gas
    # duct at each end share one connection. It costs the drawing S-416,
    # which carries the whole product in the gas. A ``Dryer`` with gas
    # nozzles of its own is the fix, and this sheet wants redrawing
    # around them.
    dryer = fs.add(Dryer("DR-401",
                         description="Concentrate Rotary Dryer"))

    # --- Product recovery and dust capture ----------------------------
    # Neither draw is named for which one is wanted, so the product is
    # the ``underflow`` and the gas still to be cleaned is the
    # ``overflow``.
    cyclone = fs.add(Cyclone(
        "CY-401", description="Product Recovery Cyclone"))
    scrub_water = fs.add(Feed("Scrubbing Water", reference="PCD-402"))
    scrub_tee = fs.add(Tee(branch="inlet"))
    # The water ties in on the duct upstream rather than on the body, so
    # the tee above carries it and the vessel takes one feed.
    scrubber = fs.add(Scrubber(
        "SC-401", description="Dryer Exhaust Scrubber"))
    effluent = fs.add(Product("Scrubber Effluent", reference="PCD-402"))
    # Induced draught, so the fan is last and FH-401's air inlet is a
    # plain flag rather than a second machine.
    fan = fs.add(Blower("BL-401", description="Dryer Exhaust Fan"))
    # A Vent draws real piping rather than an off-page flag.
    stack = fs.add(Vent("VE-401", variant="exhaust_head", width=45,
                        height=36,
                        description="Dryer Exhaust Head"))

    # Read ``underflow`` as the reject leg: the stencil draws the reject
    # leaving the apex. variant= is stated rather than defaulted, since
    # MagneticSeparator draws both bodies and this sheet means the
    # permanent one.
    magnet = fs.add(MagneticSeparator(
        "MS-401", variant="permanent_magnet",
        description="Product Magnetic Separator"))
    product = fs.add(Product("Dry Concentrate", reference="PFD-402"))
    tramp = fs.add(Product("Tramp Metal"))

    # --- Placement ----------------------------------------------------
    # A tee is a 12-unit square with a port on the middle of each face
    # it uses, so half its width is the offset from a junction to the
    # corner it is pinned by.
    tee_w = 12.0
    feed_y = 140.0                      # the concentrate feed line
    water_y = 230.0                     # the make-up water line, below it
    dose_x = 336.0                      # the flocculant riser

    concentrate.pin(port="outlet", x=90, y=feed_y)
    water.pin(port="outlet", x=90, y=water_y)

    # The powder drops into the fill line, so the funnel stands over the
    # tee with its stem on the branch's centreline.
    charge.pin(mirrored="y").pin(port="inlet", x=130, y=water_y)
    funnel.pin(port="outlet", x=charge.pin_.x + tee_w / 2, y=water_y - 20)

    tank.pin(port="inlet", x=200, y=260)
    # Both the pump's connections are on its crown, so the discharge
    # riser has to clear the tank. That is what puts the pump east of
    # the shell.
    dose.pin(port="discharge", x=dose_x, y=430)

    floc.pin(port="branch", x=dose_x, y=feed_y + tee_w / 2)
    thickener.pin(port="feed", x=380, y=feed_y)
    overflow.pin(port="inlet", x=520, y=feed_y)     # dead level off the launder

    # The eccentric reducer's outlet sits 2.4 units above its inlet,
    # which is where the .4 in the via() coordinate below comes from.
    suction_y = 330.0
    underflow_pump.pin(port="suction", x=520.7, y=suction_y)
    # Both reducers stand a spool clear of the pump, and the gap is the
    # label's rather than the piping's: a reducer's tag plate is three
    # times the width of the fitting, so hard against the casing it
    # trips the halo invariants.
    suction_red.pin(port="outlet", x=478, y=suction_y)
    disch_red.pin(port="inlet", x=624, y=suction_y)
    belt_filter.pin(port="inlet", x=670, y=suction_y)
    cake_x = belt_filter.pin_.x + port_offset(belt_filter, "cake")[0]

    # Straight out of the east wall on the filter's own elevation, which
    # is what the filtrate leg is: nothing is drawn between the machine
    # and the boundary.
    filtrate.pin(port="inlet", x=800, y=suction_y)

    # The belt runs under the filter, so the cake drops out of the floor
    # onto its tail and throws off into the breeching.
    belt_y, dryer_y = 480.0, 490.0
    conveyor.pin(port="feed", x=cake_x, y=belt_y)
    breeching.pin(port="inlet", x=950, y=dryer_y)
    dryer.pin(port="feed", x=1000, y=dryer_y)

    # The burner sits at grade under the feed end. Its fuel arrives from
    # below, the only face the stencil's fuel nozzle offers.
    heater.pin(port="inlet", x=860, y=654.5)
    air.pin(port="outlet", x=790, y=654.5)   # clear of the burner wall
    gas.pin(port="outlet", x=750, y=740)
    hot_gas_x = breeching.pin_.x + tee_w / 2

    cyclone.pin(port="feed", x=1180, y=322)
    # Above the gas riser rather than beside it: the scrub-water line
    # has to cross the duct's line of travel without crossing the duct
    # itself.
    scrub_tee.pin(mirrored="y").pin(port="inlet", x=1255, y=132)
    scrub_water.pin(port="outlet", x=1180, y=85)
    scrubber.pin(port="feed", x=1300, y=132)
    effluent.pin(port="inlet", x=1400, y=280)
    fan.pin(port="suction", x=1440, y=132)
    stack.pin(port="inlet", x=fan.pin_.x + port_offset(fan, "discharge")[0],
              y=60)

    magnet.pin(port="feed", x=1300, y=532)
    product.pin(port="inlet", x=1430, y=532)
    tramp.pin(port="inlet", x=1430, y=680)

    # --- Connections --------------------------------------------------
    # Declared in stream-number order, which is the order the table
    # reads. A number is drawn once, on the first segment declared, so a
    # service that runs through more than one item starts with the run
    # it belongs on.
    fs.connect(concentrate.outlet, floc.inlet, name="S-401")

    fs.connect(water.outlet, charge.inlet, name="S-402")
    fs.connect(funnel.outlet, charge.branch, name="S-403")
    fs.connect(charge.outlet, tank.inlet, name="S-404")

    fs.connect(tank.outlet, dose.suction, name="S-405")
    fs.connect(dose.discharge, floc.branch, name="S-405")
    fs.connect(floc.outlet, thickener.feed, name="S-406")

    fs.connect(thickener.overflow, overflow.inlet, name="S-407")

    # Straight down out of the cone. Left to itself the router steps the
    # riser 34 units east past the thickener's skirt, into RD-401's tag.
    fs.connect(thickener.underflow, suction_red.inlet, name="S-408").via(
        [(420, 332.4)])
    fs.connect(suction_red.outlet, underflow_pump.suction, name="S-408")

    fs.connect(underflow_pump.discharge, disch_red.inlet, name="S-409")
    fs.connect(disch_red.outlet, belt_filter.inlet, name="S-409")

    # Two products out of one machine, on the two nozzles the machine
    # has. Teeing off the discharge and calling one leg the cake said
    # the solids leave in the liquid line, which is the opposite of what
    # a belt filter does.
    fs.connect(belt_filter.port("outlet"), filtrate.inlet, name="S-410")

    fs.connect(belt_filter.port("cake"), conveyor.feed, name="S-411")
    fs.connect(conveyor.discharge, breeching.inlet, name="S-411")

    fs.connect(air.outlet, heater.inlet, name="S-412")
    fs.connect(gas.outlet, heater.fuel, name="S-413").via([(900, 740)])
    # Pinned by hand: left to itself the router takes the burner duct
    # the long way round the dryer.
    fs.connect(heater.outlet, breeching.branch, name="S-414").via(
        [(hot_gas_x, 654.5 + 25)])

    fs.connect(breeching.outlet, dryer.feed, name="S-415")
    fs.connect(dryer.product, cyclone.feed, name="S-416")

    fs.connect(cyclone.overflow, scrub_tee.inlet, name="S-417")
    fs.connect(scrub_water.outlet, scrub_tee.branch, name="S-418")
    fs.connect(scrub_tee.outlet, scrubber.feed, name="S-419")

    fs.connect(scrubber.vapor, fan.suction, name="S-420")
    fs.connect(fan.discharge, stack.inlet, name="S-420")
    fs.connect(scrubber.liquid, effluent.inlet, name="S-421")

    fs.connect(cyclone.underflow, magnet.feed, name="S-422")
    fs.connect(magnet.overflow, product.inlet, name="S-423")
    fs.connect(magnet.underflow, tramp.inlet, name="S-424")

    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Water", "Mass Fraction")]

    # --- Title strip --------------------------------------------------
    # date= is stated rather than left blank: left blank, the renderer
    # fills in today's.
    fs.title_block = TitleBlock(
        title="Mineral Dewatering",
        subtitle="A400 Process Flow Diagram 1",
        drawing_number="PFD-401",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        date="12/09/25",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "22/08/25", "Issued for internal review", "AA"),
            Revision("B", "05/09/25", "Dryer exhaust scrubber added", "AA"),
            Revision("C", "12/09/25", "Issued For Review", "AA", "JS", "RL"),
        ],
    )

    # --- Sheet furniture ----------------------------------------------
    # include= is named row by row in process order. The four tees, the
    # funnel, the two reducers and the exhaust head are left out: all
    # eight are bulk items bought by the line.
    fs.add_annotation(equipment_list(fs, align="top", include=[
        "TK-401", "P-402", "TH-401", "P-401", "FL-401", "CV-401", "FH-401",
        "DR-401", "CY-401", "MS-401", "SC-401", "BL-401",
    ]))
    fs.add_annotation(TableBox(
        title="UTILITIES SUMMARY",
        headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in",
                 "T_out"],
        rows=[
            ["Natural Gas", "FH-401", "5972", "0.119", "15 C", "-"],
            ["Ambient Air", "FH-401", "-", "8.47", "15 C", "650 C"],
            ["Raw Water", "TK-401", "-", "0.175", "20 C", "-"],
            ["Scrubbing Water", "SC-401", "-1638", "11.53", "28 C", "62 C"],
        ],
        col_align=["l", "l", "r", "r", "c", "c"],
        align="bottom-right",
    ))

    fs.render(out("mineral_dewatering.svg"), border="zone",
              show_stream_table=True)
    print("Generated mineral_dewatering.svg")


if __name__ == "__main__":
    main()
