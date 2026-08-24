"""
Example 21: Alumina Refinery A900, the Bayer process as one PFD

Bauxite in at the west, smelter-grade alumina out at the east, and a
caustic liquor circuit that closes on itself in between. That circuit is
the process: soda dissolves the gibbsite out of the ore at temperature,
the mud is settled and washed out of it, the alumina is crystallised
back out as hydrate, and the liquor -- minus its alumina and plus the
water the washing added -- is concentrated and sent round to the mill
again. Nothing on this sheet is drawn as leaving the liquor circuit
except with the residue, with the product, or up an evaporator's vapour
line.

The sheet is the largest in the gallery, and it is sized to its own
drawing rather than to a page: fifty-six streams side by side is wider
than any standard sheet takes.

**What is simplified, and it is a lot.** A refinery is far bigger than
one drawing, so each item below stands for the train it belongs to:

- one digester for the six to ten in series that a real charge passes
  through, and two flash stages for the eight to twelve of a blow-off
  train;
- one settler and one washer for a five- or six-stage counter-current
  decantation circuit;
- two precipitators for a tank farm of ten to fourteen, and two
  hydrocyclones for the three classification stages that separate
  product hydrate from coarse and fine seed;
- ``EV-901`` for a multiple-effect falling-film evaporation train, drawn
  at its last effect's conditions.

Left off the sheet entirely, because each is a plant of its own: lime
burning and causticisation, oxalate and organics removal, residue
disposal, product cooling and gas cleaning downstream of ``CY-903``, and
every utility distribution header.

**There is no bucket elevator on this sheet**, though pandid draws two.
A Bayer circuit moves wet solids by pump and dry solids by belt and air
slide; the one place a lift would go -- hydrate to a calciner feed bin
-- is a belt in every refinery drawn here. A machine put on a sheet
because the library owns the symbol is a machine an engineer has to ask
about.

The stream table is a coherent mass balance rather than plausible
numbers: 212 t/h of dry bauxite makes 100 t/h of alumina, the caustic
and the dissolved alumina both return to the values they left the
evaporator with, and every unit's inlets add up to its outlets.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Conveyor,
    Cooler,
    Cyclone,
    FallingFilmEvaporator,
    Feed,
    FilterPress,
    Flowsheet,
    FluidizedBedCalciner,
    Furnace,
    JawCrusher,
    Mill,
    Product,
    Pump,
    Reactor,
    RotaryDrumFilter,
    Separator,
    ShellAndTubeExchanger,
    Tank,
    Tee,
    Thickener,
)
from pandid.document import Revision, TableBox, TitleBlock, equipment_list, notes
from pandid.portgeom import pinned_x, pinned_y

# --- Stream property table --------------------------------------------
# Rows render in first-seen key order, so every stream below carries the
# same keys and an empty value renders as "-". The composition rows are
# mass fractions of the total flow above them; "Caustic (Na2O)" is the
# refinery's own unit for soda, since every liquor concentration in a
# Bayer plant is quoted as Na2O and not as NaOH.
PROPERTY_ROWS = (
    "Temperature (C)", "Pressure (bara)", "Total Flow (t/h)", "Solids (% w/w)",
    "Water", "Caustic (Na2O)", "Dissolved Al2O3", "Bauxite / Residue",
    "Hydrate Al(OH)3", "Alumina Al2O3", "Flocculant", "Air / Flue Gas",
    "Fuel Gas",
)

PROPERTIES = {
    "S-901": ("25", "1.0", "212", "100.0", "", "", "", "1.000", "", "", "", "", ""),
    "S-902": ("25", "1.0", "212", "100.0", "", "", "", "1.000", "", "", "", "", ""),
    "S-903": ("60", "4.0", "2300", "0.0", "0.834", "0.123", "0.043", "", "", "", "", "", ""),
    "S-904": ("57", "1.5", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-905": ("60", "1.3", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-906": ("80", "1.2", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-907": ("100", "1.1", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-908": ("100", "1.0", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-909": ("101", "6.5", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-910": ("145", "5.5", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-911": ("145", "5.0", "2512", "2.2", "0.785", "0.113", "0.080", "0.022", "", "", "", "", ""),
    "S-912": ("125", "2.4", "78.0", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-913": ("125", "2.4", "2434", "2.3", "0.779", "0.116", "0.082", "0.023", "", "", "", "", ""),
    "S-914": ("105", "1.2", "74.0", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-915": ("105", "1.2", "2360", "2.4", "0.772", "0.120", "0.085", "0.024", "", "", "", "", ""),
    "S-916": ("170", "8.0", "185", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-917": ("170", "7.8", "185", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-918": ("125", "2.3", "78.0", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-919": ("105", "1.1", "74.0", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-920": ("73", "1.0", "444", "0.0", "0.955", "0.026", "0.019", "", "", "", "", "", ""),
    "S-921": ("100", "1.0", "1.0", "10.0", "0.735", "0.096", "0.068", "0.100", "", "", "", "", ""),
    "S-922": ("100", "1.0", "2805", "2.0", "0.801", "0.105", "0.074", "0.020", "", "", "", "", ""),
    "S-923": ("25", "1.0", "2.0", "", "0.995", "", "", "", "", "", "0.005", "", ""),
    "S-924": ("100", "1.0", "2807", "2.0", "0.801", "0.105", "0.074", "0.020", "", "", "trace", "", ""),
    "S-925": ("100", "1.0", "2620", "0.0", "0.817", "0.107", "0.076", "3.8E-05", "", "", "", "", ""),
    "S-926": ("90", "4.0", "20.0", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-927": ("100", "3.5", "2639", "0.0", "0.818", "0.106", "0.075", "", "", "", "", "", ""),
    "S-928": ("100", "1.0", "187", "30.0", "0.572", "0.075", "0.053", "0.299", "", "", "", "", ""),
    "S-929": ("60", "2.0", "400", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-930": ("73", "1.0", "587", "9.5", "0.864", "0.024", "0.017", "0.095", "", "", "", "", ""),
    "S-931": ("73", "1.0", "143", "39.2", "0.581", "0.016", "0.011", "0.392", "", "", "", "", ""),
    "S-932": ("75", "3.0", "2639", "0.0", "0.818", "0.106", "0.075", "", "", "", "", "", ""),
    "S-933": ("62", "1.0", "400", "30.0", "0.593", "0.079", "0.028", "", "0.300", "", "", "", ""),
    "S-934": ("73", "1.0", "3039", "3.9", "0.789", "0.103", "0.069", "", "0.039", "", "", "", ""),
    "S-935": ("68", "1.0", "3039", "7.0", "0.778", "0.103", "0.049", "", "0.070", "", "", "", ""),
    "S-936": ("62", "1.0", "3039", "9.0", "0.771", "0.103", "0.036", "", "0.090", "", "", "", ""),
    "S-937": ("62", "1.0", "340", "45.0", "0.466", "0.062", "0.022", "", "0.450", "", "", "", ""),
    "S-938": ("62", "1.0", "2699", "4.4", "0.810", "0.108", "0.038", "", "0.044", "", "", "", ""),
    "S-939": ("62", "1.0", "2299", "0.0", "0.848", "0.113", "0.040", "", "", "", "", "", ""),
    "S-940": ("80", "3.0", "150", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-941": ("66", "1.0", "325", "0.0", "0.912", "0.065", "0.023", "", "", "", "", "", ""),
    "S-942": ("70", "1.0", "165", "92.7", "0.073", "", "", "", "0.927", "", "", "", ""),
    "S-943": ("25", "1.0", "5.0", "", "0.600", "0.400", "", "", "", "", "", "", ""),
    "S-944": ("63", "1.0", "2629", "0.0", "0.855", "0.108", "0.037", "", "", "", "", "", ""),
    "S-945": ("150", "4.7", "100", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-946": ("150", "4.5", "100", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-947": ("60", "0.20", "329", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-948": ("60", "0.20", "2300", "0.0", "0.834", "0.123", "0.043", "", "", "", "", "", ""),
    "S-949": ("25", "1.0", "120", "", "", "", "", "", "", "", "", "1.000", ""),
    "S-950": ("15", "3.0", "6.0", "", "", "", "", "", "", "", "", "", "1.000"),
    "S-951": ("1050", "1.0", "126", "", "", "", "", "", "", "", "", "1.000", ""),
    "S-952": ("1000", "1.0", "98.0", "100.0", "", "", "", "", "", "1.000", "", "", ""),
    "S-953": ("1000", "1.0", "193", "1.0", "0.337", "", "", "", "", "0.010", "", "0.653", ""),
    "S-954": ("1000", "1.0", "191", "0.0", "0.340", "", "", "", "", "", "", "0.660", ""),
    "S-955": ("1000", "1.0", "2.0", "100.0", "", "", "", "", "", "1.000", "", "", ""),
    "S-956": ("1000", "1.0", "100", "100.0", "", "", "", "", "", "1.000", "", "", ""),
}


def main():
    fs = Flowsheet("Alumina Refinery A900")

    # --- Grinding -----------------------------------------------------
    # Ore in at the top and product out of the bottom on both machines:
    # ISO 10628-2's group 11 draws one connection tick above the top edge
    # and one below the bottom edge on every one of its twelve rows, and
    # nothing here turns them.
    bauxite = fs.add(Feed("ROM Bauxite", reference="PFD-101"))
    crusher = fs.add(JawCrusher("CR-901",
                                description="Bauxite Jaw Crusher"))
    # Cake and ore are dropped onto a belt rather than piped into it, so
    # the tail nozzle comes off the top face rather than off the end.
    ore_belt = fs.add(Conveyor("CV-901", length=200,
                               description="Crushed Bauxite Conveyor"))
    ore_belt.nozzle("feed", "N")
    # The mill feed chute takes ore over its lip and spent liquor through
    # a spray bar, and the two arrive at one connection on the drawing:
    # wet grinding is what makes the liquor circuit start here rather
    # than at digestion.
    mill_tee = fs.add(Tee(branch="inlet"))
    # ``Mill`` and not ``Mill(variant="roller")``: a Bayer circuit grinds
    # in a rod or ball mill, ISO 10628-2 has an item for neither, and the
    # general mill body (11.8 X8086) is what the standard leaves for
    # them. The four characteristics it does give -- hammer, impact,
    # roller, vibration -- would each be a claim about the machine that
    # is not true of a tumbling mill.
    mill = fs.add(Mill("ML-901", description="Bauxite Ball Mill"))

    # --- Digestion ----------------------------------------------------
    # Two interchangers ahead of the desilication tanks and one live
    # steam heater behind the charge pump, which is where the pressure
    # break really is: desilication is an eight-hour atmospheric hold and
    # only what leaves it is pumped to digestion pressure.
    interchanger_1 = fs.add(ShellAndTubeExchanger(
        "E-901", variant="straight_tubes", width=150, height=45,
        description="Digestion Heat Interchanger No. 1"))
    interchanger_2 = fs.add(ShellAndTubeExchanger(
        "E-902", variant="straight_tubes", width=150, height=45,
        description="Digestion Heat Interchanger No. 2"))
    # ``Reactor`` rather than ``Tank``: a desilication tank is stirred,
    # and ISO composes a stirred vessel out of a shell, a group-28
    # agitator and the item 20.6 drive motor above it -- which is what
    # ``agitator=`` draws and what ``Tank`` has no way to ask for.
    desilication = fs.add(Reactor(
        "TK-901", agitator="turbine", width=80, height=170,
        description="Desilication Tank"))
    charge_pump = fs.add(Pump("P-901", description="Digester Charge Pump"))
    steam_heater = fs.add(ShellAndTubeExchanger(
        "E-903", variant="straight_tubes", width=150, height=45,
        description="Live Steam Digestion Heater"))
    # 145 C and 5 bara: the low-temperature route, which is what a
    # gibbsitic bauxite is digested at. ``variant="jacketed"`` is the
    # heated body, and the agitator is named so the vessel keeps the
    # slurry in suspension at the residence time the reaction needs.
    digester = fs.add(Reactor(
        "D-901", variant="jacketed", agitator="turbine", width=90,
        height=210, description="Digester"))

    # --- Flash train --------------------------------------------------
    # Counter-current, and that is the whole of the arrangement: the
    # hotter flash heats the feed nearer the digester and the cooler one
    # heats it further back. Drawn the other way round each vapour would
    # arrive at a stream already hotter than itself.
    flash_1 = fs.add(Separator("V-901", width=70, height=130,
                               description="First Flash Tank"))
    flash_2 = fs.add(Separator("V-902", width=70, height=130,
                               description="Second Flash Tank"))
    mp_steam = fs.add(Feed("MP Steam", reference="PCD-903"))
    # ``header=True`` on the four condensate flags: a return header takes
    # from wherever it is tapped and is lettered the same way at each
    # tap, which is why the same flag may be drawn more than once. The
    # two are different headers and not one -- what drains the flash
    # vapour heaters is process condensate the refinery washes with, and
    # what drains the live steam heater and the evaporator is boiler
    # condensate that goes back to the power station.
    steam_condensate = fs.add(Product("Steam Condensate", header=True,
                                      reference="PCD-903"))
    flash_condensate_1 = fs.add(Product("Process Condensate", header=True,
                                        reference="PCD-902"))
    flash_condensate_2 = fs.add(Product("Process Condensate", header=True,
                                        reference="PCD-902"))

    # --- Dilution, settling and mud washing ---------------------------
    # A ``Tank`` and not three tees: the blow-off, the washer overflow
    # that dilutes it and the returning filter residue meet in a tank
    # with hold-up, which is a tagged item on any refinery's equipment
    # list. Its box is drawn larger than the default so the three inlets
    # clear ISO 128-20's spacing between parallel lines.
    dilution = fs.add(Tank("M-901", inputs=3, width=70, height=90,
                           description="Blow-off Dilution Tank"))
    floc_tee = fs.add(Tee(branch="inlet"))
    flocculant = fs.add(Feed("Flocculant", reference="PCD-904"))
    # A thickener, drawn as one. Through 0.1.3 these two were
    # ``Separator(characteristic="gravity")`` -- ISO item 8.3 X8031, a
    # separating vessel carrying the group-29 settling arrow -- because
    # that was the nearest thing in the library. It is a tall
    # hopper-bottomed drum, which is the shape of a dust collector; a
    # thickener is wide and shallow with a raked floor, and the rake is
    # the machine. ``rake=`` is what draws it, defaulting to ISO item
    # 28.4 C2021's cross-beam.
    #
    # 150 x 120 and not the default 100 x 80: the two settling machines
    # are the largest items in a Bayer plant and they are drawn like it,
    # at the artwork's own 5:4 so nothing in the drawing is stretched.
    settler = fs.add(Thickener("TH-901", width=150, height=120,
                               description="Red Mud Settler"))
    wash_tee = fs.add(Tee(branch="inlet"))
    wash_water = fs.add(Feed("Mud Wash Water", reference="PCD-902"))
    washer = fs.add(Thickener("TH-902", width=150, height=120,
                              description="Red Mud Washer"))
    residue = fs.add(Product("Washed Residue to Storage",
                             reference="PFD-905"))

    # --- Security filtration ------------------------------------------
    # A filter press makes **two products** and this one uses both of the
    # nozzles that say so: ``cake`` is the residue and the lime precoat
    # it was laid on, and it goes back to the dilution tank rather than
    # off the sheet. ``wash_in`` is the displacement wash that pushes
    # pregnant liquor out of the cake before the plates are opened --
    # 20 t/h of caustic liquor is worth recovering and worth drawing.
    security_filter = fs.add(FilterPress(
        "F-901", width=140, height=70,
        description="Security Filter"))
    filter_wash = fs.add(Feed("Hot Condensate", reference="PCD-902"))
    # A single-stream cooler: the cooling water is a connection on the
    # symbol rather than a side of it, so the sheet draws one line and
    # not three. The real duty is done by flash cooling against the
    # returning spent liquor, which is a train of its own.
    liquor_cooler = fs.add(Cooler("E-904",
                                  description="Pregnant Liquor Cooler"))

    # --- Precipitation ------------------------------------------------
    seed_tee = fs.add(Tee(branch="inlet"))
    # 85 x 180 and not 80 x 180: the stirred vessel carries the item 20.6
    # drive motor, a circle the composition sizes off the box above it,
    # so a box out of the artwork's own shape draws that circle as an
    # oval. validate() reports it, and this is the shape it asks for.
    precipitator_1 = fs.add(Reactor(
        "PR-901", agitator="turbine", width=85, height=180,
        description="Precipitator No. 1"))
    precipitator_2 = fs.add(Reactor(
        "PR-902", agitator="turbine", width=85, height=180,
        description="Precipitator No. 2"))

    # --- Classification -----------------------------------------------
    # ``variant="cyclone"`` and not a characteristic: ISO 14617-1 4.5
    # names X2618 by registration number as a symbol in its own right,
    # and the helical vortex inside it appears nowhere in group 29, so
    # there is nothing to compose a hydrocyclone out of.
    #
    # Two stages where a refinery has three: the primary takes the
    # product-size hydrate out of the bottom and the secondary sends the
    # fines back as seed, which is what makes precipitation a crystalliser
    # rather than a once-through vessel.
    classifier_1 = fs.add(Cyclone(
        "CY-901", width=90, height=140,
        description="Primary Classifying Cyclone"))
    classifier_2 = fs.add(Cyclone(
        "CY-902", width=90, height=140,
        description="Secondary Classifying Cyclone"))

    # --- Hydrate filtration and calcination ---------------------------
    # The second machine on the sheet using ``wash_in`` and ``cake``, and
    # the one the product specification depends on: soda left in the
    # cake is soda in the alumina, so the wash here is a duty rather
    # than a recovery.
    hydrate_filter = fs.add(RotaryDrumFilter(
        "F-902", width=140, height=80,
        description="Hydrate Filter"))
    hydrate_wash = fs.add(Feed("Hydrate Wash Water", reference="PCD-902"))
    hydrate_belt = fs.add(Conveyor("CV-902", length=200,
                                   description="Washed Hydrate Conveyor"))
    hydrate_belt.nozzle("feed", "N")
    # The fuel is burned in a chamber of its own and the hot gas
    # fluidises the bed, so the fuel and the combustion air land on
    # ``FH-901`` and the duct goes to the calciner's own ``air`` nozzle,
    # under the distributor grid. Through 0.1.3 there was a tee here
    # instead: the calciner was a ``FluidizedBedDryer``, whose gas
    # connection is on the casing wall rather than in a windbox, so the
    # hot duct had to be teed into the hydrate feed line.
    combustion = fs.add(Furnace("FH-901", width=100, height=120,
                                description="Calciner Combustion Chamber"))
    air = fs.add(Feed("Combustion Air"))
    fuel = fs.add(Feed("Fuel Gas", reference="PCD-905"))
    # A calciner, drawn as one. Through 0.1.3 this was a fluidised-bed
    # *drier*, which has a feed and a product and nothing else, so the
    # calcined alumina and the spent gas left together on one nozzle and
    # ``CY-903`` was where the sheet had to part them.
    #
    # ``CA-901.product`` is the bed's own draw and ``CA-901.offgas`` the
    # freeboard's, which is what the machine really has, so the cyclone
    # below is now on the gas line where it belongs -- catching the two
    # tonnes an hour of alumina the gas carries out with it.
    #
    # ``CA-901.fuel`` is left unpiped on purpose: this calciner has no
    # burner of its own, and the nozzle is there for the fired kilns that
    # do.
    calciner = fs.add(FluidizedBedCalciner(
        "CA-901", width=120, height=200, description="Alumina Calciner"))
    product_cyclone = fs.add(Cyclone(
        "CY-903", width=90, height=140,
        description="Calciner Product Cyclone"))
    # The catch is product, so it rejoins the product line at a junction
    # rather than reaching the flag on a second run of its own: two lines
    # onto one flag arrive at the same point and share the last of it,
    # which reads as a tee drawn without one.
    product_tee = fs.add(Tee(branch="inlet"))
    offgas = fs.add(Product("Calciner Off-Gas to Gas Cleaning",
                            reference="PFD-902"))
    alumina = fs.add(Product("Alumina to Cooling and Storage",
                             reference="PFD-902"))

    # --- Spent liquor -------------------------------------------------
    # Where the circuit closes. The classifier overflow and the hydrate
    # filtrate are one liquor, the make-up replaces the soda that leaves
    # chemically bound in the residue, and the evaporator takes off
    # exactly the water the washing put in -- 329 t/h of it, which is
    # what makes the returning stream the same 2300 t/h the mill was fed.
    spent_tank = fs.add(Tank("M-902", inputs=3, width=70, height=90,
                              description="Spent Liquor Tank"))
    caustic = fs.add(Feed("Caustic Soda Make-up", reference="PCD-906"))
    # An effect of a falling-film train, drawn as one. Through 0.1.3 this
    # was a ``KettleReboiler``: a shell with a heated bundle in it and a
    # weir draw at the end, which was the nearest drawing the library
    # had, and which says the machine returns boil-up to a tower. It does
    # not -- its vapour is 329 t/h of water leaving the circuit, and
    # ``EV-901.vapor`` is the nozzle that says so.
    #
    # 100 x 200, the artwork's own 1:2: a falling-film body is tall
    # because the tubes are, which is the point of the machine.
    evaporator = fs.add(FallingFilmEvaporator(
        "EV-901", width=100, height=200,
        description="Spent Liquor Evaporator"))
    lp_steam = fs.add(Feed("LP Steam", reference="PCD-903"))
    evap_condensate = fs.add(Product("Steam Condensate", header=True,
                                     reference="PCD-903"))
    evap_vapour = fs.add(Product("Evaporator Vapour", reference="PCD-902"))
    liquor_pump = fs.add(Pump("P-902", description="Spent Liquor Pump"))

    # --- Placement ----------------------------------------------------
    # A tee is a 12-unit square with a port on the middle of each face it
    # uses, so half its width is the offset from a junction to the corner
    # it is pinned by.
    tee_w = 12.0
    slurry_y = 480.0        # the two interchangers' elevation
    digest_y = 600.0        # the live steam heater and the digester
    settle_y = 1130.0       # dilution to precipitation, one elevation
    calcine_y = 1840.0      # the calcination train

    bauxite.pin(port="outlet", x=180, y=110)
    crusher.pin(port="feed", x=210, y=150)
    ore_belt.pin(port="feed", x=210, y=280)
    # A belt whose tail nozzle has been moved onto the top face is
    # positioned by that nozzle, and its head is then a roller's radius
    # below the drop -- so the run out of it is on the *head's*
    # elevation, which is what everything downstream is pinned to.
    ore_run_y = pinned_y(ore_belt, "discharge")
    mill_tee.pin(port="inlet", x=460, y=ore_run_y)
    mill.pin(port="feed", x=570, y=340)

    interchanger_1.pin(port="tube_in", x=760, y=slurry_y)
    interchanger_2.pin(port="tube_in", x=1010, y=slurry_y)
    desilication.pin(port="feed", x=1260, y=slurry_y)
    charge_pump.pin(port="suction", x=1400, y=620)
    steam_heater.pin(port="tube_in", x=1580, y=digest_y)
    digester.pin(port="feed", x=1860, y=digest_y)
    flash_1.pin(port="feed", x=2080, y=740)
    flash_2.pin(port="feed", x=2320, y=880)

    # Read off the artwork rather than written down: every one of these
    # is a nozzle position the symbol owns, so nothing here has to be
    # re-derived when a box changes size or a train is spread out.
    hx1_shell_in_x = pinned_x(interchanger_1, "shell_in")
    hx2_shell_in_x = pinned_x(interchanger_2, "shell_in")
    hx1_drain_x = pinned_x(interchanger_1, "shell_out")
    hx2_drain_x = pinned_x(interchanger_2, "shell_out")
    heater_steam_x = pinned_x(steam_heater, "shell_in")
    heater_drain_x = pinned_x(steam_heater, "shell_out")
    desil_draw_x = pinned_x(desilication, "outlet")
    digester_draw_x = pinned_x(digester, "outlet")
    flash_1_axis_x = pinned_x(flash_1, "vapor")
    flash_2_axis_x = pinned_x(flash_2, "vapor")

    mp_steam.pin(port="outlet", x=1560, y=400)
    steam_condensate.pin(port="inlet", x=1760, y=790)
    flash_condensate_1.pin(port="inlet", x=1180, y=700)
    flash_condensate_2.pin(port="inlet", x=920, y=790)

    dilution.pin(port="in_2", x=200, y=settle_y)
    floc_tee.pin(port="inlet", x=400, y=settle_y)
    # East of the three lanes that reach M-901's inlets: a flag's drawn
    # box is its arrow *and its lettering*, and the lettering runs back
    # the way the flag points, so a flag pinned over a lane is crossed by
    # a line that misses the arrow entirely.
    flocculant.pin(port="outlet", x=330, y=1250)
    settler.pin(port="feed", x=460, y=settle_y)
    security_filter.pin(port="inlet", x=700, y=settle_y)
    filter_wash.pin(port="outlet", x=640, y=880)
    liquor_cooler.pin(port="inlet", x=980, y=settle_y)

    wash_tee.pin(port="inlet", x=560, y=1430)
    washer.pin(port="feed", x=640, y=1430)
    wash_water.pin(port="outlet", x=470, y=1520)
    residue.pin(port="inlet", x=880, y=1660)

    seed_tee.pin(port="inlet", x=1180, y=settle_y)
    precipitator_1.pin(port="feed", x=1280, y=settle_y)
    precipitator_2.pin(port="feed", x=1460, y=1270)
    classifier_1.pin(port="feed", x=1660, y=1400)
    classifier_2.pin(port="feed", x=1920, y=1180)

    hydrate_filter.pin(port="inlet", x=2150, y=1700)
    hydrate_wash.pin(port="outlet", x=2200, y=1500)
    hydrate_belt.pin(port="feed", x=2220, y=calcine_y)
    hydrate_run_y = pinned_y(hydrate_belt, "discharge")
    calciner.pin(port="feed", x=2520, y=hydrate_run_y)
    # On the calciner's own off-gas elevation rather than on the hydrate
    # run: the cyclone is now on the gas line, and a machine pinned to
    # the line it is not on is a machine the router has to reach round.
    product_cyclone.pin(port="feed", x=2790, y=1720)
    # Under the cyclone's own apex and on the calciner's product
    # elevation, so the catch falls straight into the run and the run is
    # straight. ``mirrored="y"`` turns the branch onto the north face,
    # which is the one thing a tee's placement says.
    product_tee.pin(port="inlet",
                    x=pinned_x(product_cyclone, "underflow") - tee_w / 2,
                    y=pinned_y(calciner, "product"), mirrored="y")
    combustion.pin(port="inlet", x=2260, y=2060)
    air.pin(port="outlet", x=2160, y=2000)
    fuel.pin(port="outlet", x=2180, y=2230)
    combustion_gas_y = pinned_y(combustion, "outlet")
    offgas.pin(port="inlet", x=2960, y=1680)
    alumina.pin(port="inlet", x=2980, y=pinned_y(calciner, "product"))

    spent_tank.pin(port="in_1", x=1350, y=1800)
    # Level with the nozzle it feeds rather than at a height of its own:
    # 1863 was 25 below M-902's third inlet, which is under the 50 the
    # flag measures across the run, so the line stepped into the flag's
    # own box and back out of it instead of running straight in.
    caustic.pin(port="outlet", x=1230, y=pinned_y(spent_tank, "in_3"))
    evaporator.pin(port="feed", x=1550, y=1980)
    lp_steam.pin(port="outlet", x=1330,
                 y=pinned_y(evaporator, "heating_in"))
    evap_condensate.pin(
        port="inlet", x=1820,
        y=pinned_y(evaporator, "condensate"))
    evap_vapour.pin(port="inlet", x=1700, y=1830)
    liquor_pump.pin(port="suction", x=1800, y=2220)

    cake_x = pinned_x(security_filter, "cake")
    mud_draw_x = pinned_x(settler, "underflow")
    classifier_1_axis_x = pinned_x(classifier_1, "overflow")
    classifier_2_axis_x = pinned_x(classifier_2, "overflow")
    product_axis_x = pinned_x(product_cyclone, "overflow")
    evap_bottoms_x = pinned_x(evaporator, "concentrate")
    evap_vapour_x = pinned_x(evaporator, "vapor")
    spent_in_2_y = pinned_y(spent_tank, "in_2")
    spent_draw_x = pinned_x(spent_tank, "outlet")

    # Every lane a line takes when it runs back the way it came, written
    # down once. Three of them reach the dilution tank's inlets, three
    # more carry the seed, the spent liquor and the hydrate filtrate out
    # of the precipitation area, and the last is the one the whole
    # circuit comes home on. A number here is a promise to every other
    # route on the sheet that this strip of paper is taken.
    lane_blowoff, lane_dilution, lane_residue = 140.0, 110.0, 170.0
    lane_home_x, lane_home_y = 60.0, 2260.0
    lane_vapour_1, lane_vapour_2 = 300.0, 250.0
    lane_dilution_y, lane_residue_y = 1350.0, 1330.0
    lane_spent_y, lane_spent_x = 940.0, 1215.0
    lane_seed_y = 1560.0
    lane_filtrate_y, lane_filtrate_x = 1620.0, 1290.0
    lane_blowoff_y = 965.0
    lane_return_y = 340.0

    # --- Grinding and digestion ---------------------------------------
    # Declared in stream-number order, which is the order the table
    # reads. A number is drawn once, on the first segment declared, so a
    # service running through more than one item starts with the run it
    # belongs on.
    fs.connect(bauxite.outlet, crusher.feed, name="S-901")
    fs.connect(crusher.discharge, ore_belt.feed, name="S-902")
    fs.connect(ore_belt.discharge, mill_tee.inlet, name="S-902")
    # The one line on the sheet that makes it a circuit, declared here
    # rather than where the liquor comes from so the table reads in
    # number order. It goes the long way round on purpose: a recycle
    # drawn across the middle of a sheet this size is a line nobody can
    # follow, so it runs the border instead and arrives at the mill feed
    # chute from underneath.
    fs.connect(liquor_pump.discharge, mill_tee.branch, name="S-903",
               draw_as_recycle=True).via(
                   [(pinned_x(liquor_pump, "discharge"), lane_home_y),
                    (lane_home_x, lane_home_y),
                    (lane_home_x, lane_return_y),
                    (pinned_x(mill_tee) + tee_w / 2, lane_return_y)])
    fs.connect(mill_tee.outlet, mill.feed, name="S-904").via([(570, ore_run_y)])
    fs.connect(mill.discharge, interchanger_1.tube_in, name="S-905").via(
        [(570, slurry_y)])
    fs.connect(interchanger_1.tube_out, interchanger_2.tube_in, name="S-906")
    fs.connect(interchanger_2.tube_out, desilication.feed, name="S-907")
    fs.connect(desilication.outlet, charge_pump.suction, name="S-908").via(
        [(desil_draw_x, 620)])
    fs.connect(charge_pump.discharge, steam_heater.tube_in, name="S-909")
    fs.connect(steam_heater.tube_out, digester.feed, name="S-910")

    # --- The flash train and the interchange --------------------------
    fs.connect(digester.outlet, flash_1.feed, name="S-911").via(
        [(digester_draw_x, 740)])
    # Pinned by hand: the vapour has to climb over the digester and the
    # desilication tank to reach the heater it belongs to, and left to
    # itself the router takes it through both. The two lanes cross, and
    # they cross because the interchange is counter-current: the hotter
    # flash serves the heater nearer the digester and the cooler one the
    # heater further back.
    fs.connect(flash_1.vapor, interchanger_2.port("shell_in"),
               name="S-912").via([(flash_1_axis_x, lane_vapour_1),
                                  (hx2_shell_in_x, lane_vapour_1)])
    fs.connect(flash_1.liquid, flash_2.feed, name="S-913").via(
        [(flash_1_axis_x, 880)])
    fs.connect(flash_2.vapor, interchanger_1.port("shell_in"),
               name="S-914").via([(flash_2_axis_x, lane_vapour_2),
                                  (hx1_shell_in_x, lane_vapour_2)])

    # The blow-off crosses the sheet on its own lane, drops onto the
    # dilution tank's top inlet and is the sheet's fold: everything above
    # this line is drawn left to right and so is everything below it.
    fs.connect(flash_2.liquid, dilution.port("in_1"), name="S-915").via(
        [(flash_2_axis_x, lane_blowoff_y), (lane_blowoff, lane_blowoff_y),
         (lane_blowoff, pinned_y(dilution, "in_1"))])

    fs.connect(mp_steam.outlet, steam_heater.port("shell_in"),
               name="S-916").via([(heater_steam_x, 400)])
    fs.connect(steam_heater.port("shell_out"), steam_condensate.inlet,
               name="S-917").via([(heater_drain_x, 790)])
    fs.connect(interchanger_2.port("shell_out"), flash_condensate_1.inlet,
               name="S-918").via([(hx2_drain_x, 700)])
    fs.connect(interchanger_1.port("shell_out"), flash_condensate_2.inlet,
               name="S-919").via([(hx1_drain_x, 790)])

    # --- Dilution and settling ----------------------------------------
    fs.connect(washer.port("overflow"), dilution.port("in_2"),
               name="S-920").via([(810, 1430), (810, lane_dilution_y),
                                  (lane_dilution, lane_dilution_y),
                                  (lane_dilution, settle_y)])
    fs.connect(security_filter.port("cake"), dilution.port("in_3"),
               name="S-921").via(
                   [(cake_x, lane_residue_y), (lane_residue, lane_residue_y),
                    (lane_residue,
                     pinned_y(dilution, "in_3"))])
    fs.connect(dilution.outlet, floc_tee.inlet, name="S-922")
    # East along the flag's own elevation and then up the riser: one
    # waypoint short of that and the two ends are joined by a slope,
    # which ISO 15519-1 12.1 does not allow a connecting line and
    # tests/test_route_invariants.py catches.
    fs.connect(flocculant.outlet, floc_tee.branch, name="S-923").via(
        [(pinned_x(floc_tee) + tee_w / 2, 1250)])
    fs.connect(floc_tee.outlet, settler.feed, name="S-924")

    fs.connect(settler.port("overflow"), security_filter.inlet, name="S-925")
    fs.connect(filter_wash.outlet, security_filter.port("wash_in"),
               name="S-926").via(
                   [(pinned_x(security_filter, "wash_in"), 880)])
    fs.connect(security_filter.outlet, liquor_cooler.inlet, name="S-927")

    # --- Mud washing --------------------------------------------------
    fs.connect(settler.port("underflow"), wash_tee.inlet, name="S-928").via(
        [(mud_draw_x, 1430)])
    fs.connect(wash_water.outlet, wash_tee.branch, name="S-929").via(
        [(pinned_x(wash_tee) + tee_w / 2, 1520)])
    fs.connect(wash_tee.outlet, washer.feed, name="S-930")
    fs.connect(washer.port("underflow"), residue.inlet, name="S-931").via(
        [(pinned_x(washer, "underflow"), 1660)])

    # --- Precipitation and classification -----------------------------
    fs.connect(liquor_cooler.outlet, seed_tee.inlet, name="S-932")
    fs.connect(classifier_2.port("underflow"), seed_tee.branch,
               name="S-933").via([(classifier_2_axis_x, lane_seed_y),
                                  (pinned_x(seed_tee) + tee_w / 2, lane_seed_y)])
    fs.connect(seed_tee.outlet, precipitator_1.feed, name="S-934")
    fs.connect(precipitator_1.outlet, precipitator_2.feed, name="S-935").via(
        [(pinned_x(precipitator_1, "outlet"),
          1270)])
    fs.connect(precipitator_2.outlet, classifier_1.feed, name="S-936").via(
        [(pinned_x(precipitator_2, "outlet"),
          1400)])
    fs.connect(classifier_1.port("underflow"), hydrate_filter.inlet,
               name="S-937").via([(classifier_1_axis_x, 1700)])
    fs.connect(classifier_1.port("overflow"), classifier_2.feed,
               name="S-938").via([(classifier_1_axis_x, 1180)])
    # Up over the precipitators and down the far side of them: the spent
    # liquor is leaving the area it was made in, and the lane it takes is
    # the one the seed return does not.
    fs.connect(classifier_2.port("overflow"), spent_tank.port("in_1"),
               name="S-939").via([(classifier_2_axis_x, lane_spent_y),
                                  (lane_spent_x, lane_spent_y),
                                  (lane_spent_x, 1800)])

    # --- Hydrate filtration and calcination ---------------------------
    fs.connect(hydrate_wash.outlet, hydrate_filter.port("wash_in"),
               name="S-940").via(
                   [(pinned_x(hydrate_filter, "wash_in"), 1500)])
    fs.connect(hydrate_filter.outlet, spent_tank.port("in_2"),
               name="S-941").via(
                   [(2340, 1700), (2340, lane_filtrate_y),
                    (lane_filtrate_x, lane_filtrate_y),
                    (lane_filtrate_x, spent_in_2_y)])
    fs.connect(hydrate_filter.port("cake"), hydrate_belt.feed, name="S-942")
    fs.connect(hydrate_belt.discharge, calciner.feed, name="S-942")

    # --- Spent liquor -------------------------------------------------
    fs.connect(caustic.outlet, spent_tank.port("in_3"), name="S-943")
    # Round the outside of the shell rather than into the top of it: the
    # evaporator's process side is fed at the bottom, which is where a
    # kettle body puts its shell nozzle and where an effect of a
    # falling-film train is fed in any case.
    fs.connect(spent_tank.outlet, evaporator.feed,
               name="S-944").via([(spent_draw_x, 1980)])
    fs.connect(lp_steam.outlet, evaporator.heating_in, name="S-945")
    fs.connect(evaporator.condensate, evap_condensate.inlet, name="S-946")
    fs.connect(evaporator.vapor, evap_vapour.inlet,
               name="S-947").via([(evap_vapour_x, 1830)])
    fs.connect(evaporator.concentrate, liquor_pump.suction,
               name="S-948").via([(evap_bottoms_x, 2220)])

    # --- Calcination --------------------------------------------------
    fs.connect(air.outlet, combustion.inlet, name="S-949")
    fs.connect(fuel.outlet, combustion.fuel, name="S-950").via(
        [(pinned_x(combustion, "fuel"), 2230)])
    # Into the windbox from below, which is where a fluidised bed's gas
    # goes in and where the symbol draws the nozzle. The chamber sits
    # lower than the calciner's floor on purpose, so the duct is one
    # corner rather than a loop under the machine.
    fs.connect(combustion.outlet, calciner.air, name="S-951").via(
        [(pinned_x(calciner, "air"), combustion_gas_y)])
    # The product leaves the bed over its own weir on a nozzle of its
    # own, which is what a calciner symbol bought this sheet.
    fs.connect(calciner.product, product_tee.inlet, name="S-952")
    fs.connect(calciner.offgas, product_cyclone.feed, name="S-953")
    fs.connect(product_cyclone.port("overflow"), offgas.inlet,
               name="S-954").via([(product_axis_x, 1680)])
    # Two tonnes an hour of alumina the gas carried out of the freeboard
    # with it, dropped back into the product.
    fs.connect(product_cyclone.port("underflow"), product_tee.branch,
               name="S-955")
    fs.connect(product_tee.outlet, alumina.inlet, name="S-956")

    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Water", "Mass Fraction")]

    # --- Title strip --------------------------------------------------
    # date= is stated rather than left blank: left blank, the renderer
    # fills in today's.
    fs.title_block = TitleBlock(
        title="Alumina Refinery",
        subtitle="A900 Process Flow Diagram 1",
        drawing_number="PFD-901",
        project="Bayer Process Alumina Refinery",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        date="14/08/26",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "26/06/26", "Issued for internal review", "AA"),
            Revision("B", "24/07/26", "Second flash stage added", "AA"),
            Revision("C", "14/08/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )

    # --- Sheet furniture ----------------------------------------------
    # include= is named row by row in process order. The five tees are
    # left out: a junction in the piping is bought by the line and has no
    # tag to schedule.
    fs.add_annotation(equipment_list(fs, align="top-right", include=[
        "CR-901", "CV-901", "ML-901", "E-901", "E-902", "TK-901", "P-901",
        "E-903", "D-901", "V-901", "V-902", "M-901", "TH-901", "TH-902",
        "F-901", "E-904", "PR-901", "PR-902", "CY-901", "CY-902", "F-902",
        "CV-902", "M-902", "EV-901", "P-902", "FH-901", "CA-901", "CY-903",
    ]))
    fs.add_annotation(TableBox(
        title="UTILITIES SUMMARY",
        headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in",
                 "T_out"],
        rows=[
            ["MP Steam", "E-903", "106800", "51.4", "170 C", "170 C"],
            ["LP Steam", "EV-901", "61100", "27.8", "150 C", "150 C"],
            ["Fuel Gas", "FH-901", "83300", "1.67", "15 C", "-"],
            ["Combustion Air", "FH-901", "-", "33.3", "25 C", "1050 C"],
            ["Cooling Water", "E-904", "-57300", "685", "25 C", "45 C"],
            ["Mud Wash Water", "TH-902", "-", "111", "60 C", "-"],
            ["Hydrate Wash Water", "F-902", "-", "41.7", "80 C", "-"],
        ],
        col_align=["l", "l", "r", "r", "c", "c"],
        align="bottom-right",
    ))
    fs.add_annotation(notes([
        "Each item stands for the train it belongs to: one digester for "
        "six to ten, two flash stages for eight to twelve, one settler "
        "and one washer for a six-stage decantation circuit, two "
        "precipitators for a tank farm of twelve.",
        "TH-901 and TH-902 are drawn with the ISO 10628-2 item 28.4 "
        "C2021 cross-beam on the rake shaft. The drive above it is not "
        "drawn: it is a tagged item of its own.",
        "Soda leaving chemically bound in the residue is replaced by the "
        "make-up on S-943. Soda dissolved in the residue's entrained "
        "liquor is what the washing on TH-902 recovers.",
        "Lime burning, causticisation, oxalate removal, residue disposal "
        "and product cooling are not on this sheet.",
    ], title="GENERAL NOTES", numbered=True, align="top-left"))

    fs.render(out("alumina_refinery.svg"), border="zone",
              show_stream_table=True)
    print("Generated alumina_refinery.svg")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()
