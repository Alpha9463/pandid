"""
Example 13: Mineral Concentrate Dewatering A400, a solids-handling PFD

The first sheet in the gallery that is not a fluids plant. A flotation
concentrate arrives as a dilute slurry and leaves as a dry, magnetics-free
powder, and everything between those two flags is a solid-liquid or a
solid-gas separation: a thickener, a vacuum belt filter, a rotary dryer, the
cyclone that takes the dried product back out of the gas that dried it, and
the scrubber that cleans what is left before it reaches the stack. Crushing,
grinding and flotation are upstream of the concentrate flag and off this
sheet.

**Drawn as a PFD.** ``professional_examples/PFD_301.pdf`` and ``PFD_302.pdf``
are the models on disk, and between them they carry no instrument balloon, no
signal line and no valve; what they do carry is an equipment list, a stream
table sectioned into a "Mass Fraction" block, a utilities summary, and an
arrowhead on every process line. That is ISO 15519-2 §4.2's earliest issue (p.5) --
"In the start of a project the representation in process flow diagrams (PFD)
is pure functional" -- and this is that issue of this unit. The alternative was
a full instrument set, and a dewatering circuit's real control narrative is bed
level, cake moisture and dryer outlet temperature on four closed loops; drawing
a third of it to fill space would say less than drawing none.

**Gravity is the geometry.** ISO 15519-1 §11.4.2 (p.23) names the cyclone
separator, symbol X 2618, as one of the drawings that "must not be turned",
because gravity is a functionality of it; §13.1 (p.28) says the sheet should
follow the symbol -- "With such equipment, where the gravity is an essential
or important function, for example in a chemical process, the vertical view
principle should be used." So the thickener takes its underflow out of the
apex and its overflow off the wall, the cyclone hangs over the magnet it drops
its catch into, the dryer's burner sits at grade under the feed end, and
nothing on the sheet is turned. Seven of the symbols here carry
``gravity_fixed=True`` in the registry and would be refused if it were.

**Sized to the drawing, not to a page.** ``10`` and ``11`` are the fixed-A3
pair, and ``14`` joins them; this sheet is the other kind, as ``03`` and
``08`` are. Twenty-four
streams side by side is a wider table than A3 takes beside a utilities summary,
and a fixed page has only two answers to that -- refuse the render or shrink
the drawing. ``page_size="A2"`` draws this same sheet on real paper for anyone
who wants it.

Sixteen tagged items, twelve of them scheduled, and the argument for each is
in the comment beside it. What a solids circuit has that a fluids one does not
is worth reading for: the cake is *dropped* onto a belt rather than piped, the
dryer's discharge is one connection carrying two phases, and four of its five
junctions are tees that **combine** rather than split.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units
from pandid.document import Revision, TableBox, TitleBlock, equipment_list
from pandid.portgeom import port_offset

# --- Stream property table -------------------------------------------------
# PFD_301's row set, less the components this unit does not have and plus the
# one number a mineral circuit is run on: the solids concentration of every
# stream, which is what says whether a thing is a slurry, a paste, a cake or a
# powder. Rows render in first-seen key order, so every stream carries the same
# keys in the same order, and an empty value renders as "-".
#
# The balance closes on total flow, and it is meant to be checked rather than
# admired: 297.06 t/h in over the five inlet flags, 297.03 t/h out over the
# five outlet flags and VE-401, and no item out by more than 0.04 t/h across
# itself. Component by component it is looser: the fractions are quoted to
# three or four figures, which leaves a few tens of kilograms an hour of
# rounding in the water column across the thickener and the cyclone.
# The numbers are an illustrative balance and not a simulation -- there is no
# psychrometry behind the dryer and no settling model behind the thickener --
# but they conserve mass everywhere, which is the only reason to put numbers on
# a drawing at all. "Tramp Metal" is carried as a component of its own rather
# than folded into the concentrate, because the whole argument for MS-401 is
# that the stream leaving it is not the stream that arrived, and a table that
# hid the difference would not show that.
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
    # No temperature. The cake and the burner gas arrive at the breeching and
    # start drying in the same instant, so there is no equilibrium the two
    # reach and nothing an adiabatic mixing sum would be true of. A dryer
    # datasheet quotes the two inlets it has -- 650 C of gas onto 28 C of cake
    # -- and so does this table, one column each side of this one.
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

    # --- Flocculant make-up ----------------------------------------------
    # A thickener does not settle without a polymer, and the polymer is bought
    # as a dry powder that has to be wetted, aged and diluted before it is any
    # use. That package is four items and one of them is not plant at all.
    water = fs.add(units.Feed("Raw Water", reference="PCD-402"))
    # FN-401 is where the bags go in: 25 kg of dry polymer tipped by hand, one
    # a shift. It is drawn as the open cone it is, and it discharges into the
    # *fill line* rather than through the tank roof, because powder dropped on
    # a still surface floats, hydrates on one side and sinks as gel; wetted in
    # falling water it disperses. A funnel is a piping item bought by the line,
    # so it is not in ``document._MAJOR_EQUIPMENT`` and spends no row of the
    # equipment list.
    funnel = fs.add(units.Funnel("FN-401",
                                 description="Flocculant Charging Funnel"))
    charge = fs.add(units.Tee(branch="inlet"))
    # The conical bottom is the whole reason this is a Tank and not a Vessel:
    # what is made up here is a viscous solution carrying undissolved gel, a
    # flat floor keeps a heel of it that the next batch never sees, and the
    # cone drains the batch out to the pump instead, leaving nothing to carry
    # over and blind a filter cloth two items downstream. The stirrer this tank
    # certainly has is not drawn: ``Tank`` has no agitated variant, and
    # ``Reactor``, which draws one, is the wrong symbol for a reagent tank. Nor
    # is the ageing time a polymer needs before use, or the post-dilution water
    # at the injection point -- both belong to the make-up package and to its
    # own sheet.
    tank = fs.add(units.Tank("TK-401", variant="conical_bottom",
                             description="Flocculant Make-up Tank"))
    # A hose pump, and not for novelty. The only wetted part is the hose, so
    # there is no seal to leak and no gland water to dilute a dose measured in
    # grams per tonne; the flow is the speed and nothing else, which is what
    # makes a dosing rate a number an operator can dial; it runs dry between
    # batches without damage; and it does not shear a long-chain polymer on the
    # way to the point of use, which a centrifugal pump does well enough to
    # undo the make-up entirely. Both its connections are drawn on the crown,
    # which is where a hose pump's really are, and that is what shapes the
    # piping around it below.
    dose = fs.add(units.Pump("P-402", variant="peristaltic",
                             description="Flocculant Dosing Pump"))

    # --- Thickening -------------------------------------------------------
    concentrate = fs.add(units.Feed("Flotation Concentrate",
                                    reference="PFD-302"))
    floc = fs.add(units.Tee(branch="inlet"))
    # The thickener does two jobs and the sheet needs both: it lifts the feed
    # from 28 % solids to something a filter can take, and it recovers 120 of
    # the 224 t/h that arrive, in one step, as water clean enough to use again.
    # Its two draws are what the "gravity separator, settling chamber" stencil
    # is -- a high draw off the wall and a low one out of the apex.
    #
    # Those two ports are called ``vapor`` and ``liquid``, which is wrong here
    # and is a wart the library documents rather than hides: ``Separator``'s
    # docstring says the mechanical separators took ``overflow``/``underflow``
    # and that ``cyclone``, ``gravity`` and ``electrostatic`` kept the phase
    # names only because 0.1.0 shipped them. Read ``vapor`` as the overflow
    # launder and ``liquid`` as the underflow cone. The sheet says which is
    # which in its stream names, so no reader of the drawing has to know.
    thickener = fs.add(units.Separator("TH-401", variant="gravity",
                                       description="Concentrate Thickener"))
    overflow = fs.add(units.Product("Recovered Water", reference="PCD-402"))

    # --- Filtration -------------------------------------------------------
    # A 60 % solids underflow is a paste with a yield stress, not a liquid. A
    # centrifugal slurry pump will move it and plenty of plants use one, but it
    # moves whatever its head and the line resistance between them settle on,
    # and a thickener needs the opposite: a rate the operator sets, because the
    # underflow rate is the only handle there is on bed level and on discharge
    # density. A progressing-cavity pump displaces a fixed volume per turn, so
    # the rate *is* the speed; it holds that rate against a filter whose
    # backpressure moves through the cycle; and it delivers without the
    # pulsation a reciprocating pump would put into a filter feed box.
    underflow_pump = fs.add(units.Pump("P-401", variant="screw",
                                       description="Thickener Underflow Pump"))
    # Eccentric on the suction, flat side up: a concentric body there leaves a
    # pocket against the roof of the line for air to collect in, and a PC pump
    # that loses suction runs its rubber stator dry and cooks it in seconds.
    # The stencil is drawn flat on top for exactly this arrangement. Concentric
    # on the discharge, where the line is full and running and the symmetric
    # body is what a piping drawing puts there. Neither carries a row in the
    # equipment list: a reducer is bulk piping bought by the line, like the
    # tees around it.
    suction_red = fs.add(units.Reducer("RD-401", variant="eccentric",
                                       description="P-401 Suction Reducer"))
    disch_red = fs.add(units.Reducer("RD-402", variant="concentric",
                                     large_end="outlet",
                                     description="P-401 Discharge Expander"))
    # A horizontal vacuum belt filter: the cloth runs flat under a vacuum box,
    # the cake builds along it, and it can be washed *on the belt* before it is
    # thrown off the end. That last part is why it beats a press here -- a
    # concentrate carries soluble salts a smelter charges for, and the cheapest
    # place to wash them out is the belt the cake is already lying on.
    #
    # The vacuum itself is not on this sheet, and that is a boundary rather than
    # an omission: the vacuum box, the filtrate receiver and the pump that pulls
    # them are a package bought with the filter and drawn on the vendor's own
    # sheet. What crosses this drawing is the cake off the head end and the
    # filtrate out of the receiver, which is why S-410 is quoted at atmospheric.
    belt_filter = fs.add(units.Filter("FL-401", variant="belt", width=60,
                                      height=110,
                                      description="Concentrate Belt Filter"))
    # Cake and filtrate part at the filter's discharge: one stream in, two out,
    # and a junction in the piping rather than a piece of plant. A tee is drawn
    # as nothing at all and carries no tag, so it puts no symbol on the sheet
    # and no row in the equipment list. The other three junctions here are the
    # reverse -- ``branch="inlet"`` tees where a second stream *joins* a run --
    # and they are drawn identically, because a tee does not know which way the
    # fluid in its branch is going.
    cake_tee = fs.add(units.Tee())
    filtrate = fs.add(units.Product("Filtrate", reference="PCD-402"))
    # Cake is dropped onto a belt, not piped into it, so the tail nozzle comes
    # off the top face rather than off the end.
    conveyor = fs.add(units.Conveyor("CV-401", length=150,
                                     description="Filter Cake Conveyor"))
    conveyor.nozzle("feed", "N")

    # --- Drying -----------------------------------------------------------
    air = fs.add(units.Feed("Ambient Air"))
    gas = fs.add(units.Feed("Natural Gas", reference="PCD-403"))
    # Direct gas fired: 6 MW of drying duty bought as a burner and a combustion
    # chamber rather than as a steam coil and the boiler behind it, which is
    # what a mineral dryer of this size is. ``Furnace`` and not ``Heater``
    # because the difference between those two classes is the ``fuel`` nozzle,
    # and the fuel line is the reason this item exists.
    heater = fs.add(units.Furnace("FH-401", description="Dryer Air Heater"))
    # Where the hot gas meets the cake is the dryer's own feed breeching:
    # bought with the dryer, tagged with it, and on no equipment list of its
    # own. So it is a tee, and the sheet shows two lines meeting and nothing
    # else. The *run* keeps its number through it, exactly as it does through
    # the dosing tees, so no third stream is invented at a junction whose
    # mixing temperature nobody would quote.
    breeching = fs.add(units.Tee(branch="inlet"))
    # A co-current direct-fired rotary drum. Co-current is not decoration: the
    # hottest gas meets the wettest solid, so the surface sits at the wet-bulb
    # temperature while there is free water to evaporate and the concentrate
    # never sees flame temperature, which matters for a sulphide where the
    # alternative is oxidising the product a flotation circuit was built to
    # make.
    #
    # **The two nozzles are the library's and not the plant's, and the sheet
    # does not pretend otherwise.** A real rotary dryer has four connections:
    # a solids chute and a gas inlet at the feed hood, a solids chute and a gas
    # offtake at the discharge. ``units.Dryer`` declares ``feed`` and
    # ``product`` and no more, so two of the four have to share. Co-current
    # firing is what makes that survivable rather than absurd, because both
    # inlets really are at the feed end and both outlets really are at the
    # discharge end, so the pairing is at least the right pairing. What it
    # costs is that the discharge as drawn carries the whole product in the
    # gas, where a drum's gas carries only the fines it entrains: read S-416 as
    # the discharge breeching and CY-401 as the knock-out box on it. A
    # ``Dryer`` with gas nozzles of its own is the fix, and this sheet wants
    # redrawing around them when it has them.
    dryer = fs.add(units.Dryer("DR-401",
                               description="Concentrate Rotary Dryer"))

    # --- Product recovery and dust capture --------------------------------
    # The drum's discharge is dried concentrate riding in the gas that dried
    # it, and the cyclone is what parts them: the catch out of the apex is the
    # product, and the gas off the top is what still has to be cleaned.
    # ``Separator``'s docstring picks this exact service out as the reason its
    # two draws are not named for which one is wanted -- "a cyclone on a spray
    # dryer recovers its product from the underflow, and the identical cyclone
    # on a vent line throws that same catch away".
    cyclone = fs.add(units.Separator("CY-401", variant="cyclone",
                                     description="Product Recovery Cyclone"))
    scrub_water = fs.add(units.Feed("Scrubbing Water", reference="PCD-402"))
    scrub_tee = fs.add(units.Tee(branch="inlet"))
    # The water ties in upstream of the vessel because that is where a venturi
    # scrubber's water goes: injected into the throat, with the body below it
    # the separator that takes the wetted dust back out. Drawn that way the
    # tie-in is on the sheet, which it has to be -- a scrubber with no water on
    # it is not a scrubber -- and the 0.13 t/h of dust the cyclone missed
    # leaves in the effluent rather than up the stack.
    scrubber = fs.add(units.Separator("SC-401", variant="scrubber",
                                      description="Dryer Exhaust Scrubber"))
    effluent = fs.add(units.Product("Scrubber Effluent", reference="PCD-402"))
    # Induced draught, and last on purpose. Everything from the burner to the
    # scrubber then runs below atmospheric, so hot gas and dust cannot blow out
    # of the drum's end seals into the building; and the fan is the one place
    # on the circuit where the gas is neither hot nor laden, which is what
    # keeps a wheel turning at that speed from wearing out of balance. The
    # combustion air is drawn in by the same draught, which is why FH-401's
    # inlet is a plain ambient-air flag and not a second fan.
    fan = fs.add(units.Blower("BL-401", description="Dryer Exhaust Fan"))
    # The stack gas leaves the scrubber saturated at 62 C, so the stack rains.
    # An exhaust head caps it, keeps the weather out, and drains what condenses
    # on the way up instead of letting it run back down onto the fan. It is
    # drawn as real piping rather than as an off-page flag, which is what a
    # Vent is for, and like the funnel and the two reducers it is a line item
    # and is scheduled nowhere.
    stack = fs.add(units.Vent("VE-401", variant="exhaust_head", width=45,
                              height=36,
                              description="Dryer Exhaust Head"))

    # A suspended permanent magnet over the dry product, and it is here rather
    # than anywhere upstream for a reason about magnets and not about space.
    # Grinding media chips and liner steel travel with a concentrate all the
    # way from the mill, but a magnet only takes metal it can lift clear of the
    # burden: in a 60 % solids underflow or in a wet cake the steel is buried
    # and stays buried. Dry and free-flowing out of the cyclone is the only
    # state on this sheet in which one works at all. The stencil draws the
    # reject leaving the apex rather than lifted off the top, which is a
    # suspended magnet drawn upside down; read it as the reject leg, which is
    # what the low draw of every mechanical separator in the registry is.
    # What it protects is downstream
    # of the sheet -- tramp iron is a smelter penalty and a hazard in the
    # customer's feed system -- so the magnetics go to a bin and the
    # concentrate goes to storage. Permanent and not electromagnetic: the duty
    # is lifting discrete pieces of steel out of a thin, dry bed, and a
    # permanent circuit does that with no rectifier, no cooling and no supply to
    # lose. An electromagnet earns its complication where the field has to reach
    # down into a deep burden, or has to be switched off to drop what it has
    # caught -- neither of which is true of 5 kg an hour of discrete steel.
    magnet = fs.add(units.Separator("MS-401", variant="permanent_magnet",
                                    description="Product Magnetic Separator"))
    product = fs.add(units.Product("Dry Concentrate", reference="PFD-402"))
    tramp = fs.add(units.Product("Tramp Metal"))

    # --- Placement --------------------------------------------------------
    # Equipment is positioned by NOZZLE, not by its top-left corner: a port
    # sits at a fixed fraction of its symbol's box, so lining two items up
    # means matching those fractions and never measuring one off the artwork.
    # A tee is a 12-unit square with a port on the middle of each face it uses,
    # so half its width is the whole of the offset from a junction to the
    # corner it is pinned by.
    tee_w = 12.0
    feed_y = 140.0                      # the concentrate feed line
    water_y = 230.0                     # the make-up water line, below it
    dose_x = 336.0                      # the flocculant riser

    concentrate.pin(port="outlet", x=90, y=feed_y)
    water.pin(port="outlet", x=90, y=water_y)

    # The powder drops into the fill line, so the funnel stands over the tee
    # with its stem on the branch's centreline.
    charge.pin(mirrored="y").pin(port="inlet", x=130, y=water_y)
    funnel.pin(port="outlet", x=charge.pin_.x + tee_w / 2, y=water_y - 20)

    tank.pin(port="inlet", x=200, y=260)
    # A hose pump takes both connections on its crown, so the tank cannot
    # simply sit on top of it: the line leaves the cone, runs along underneath
    # and comes back down into the suction. The riser off the discharge is what
    # fixes the rest -- it has to clear the tank on its way up to the dosing
    # point, so the pump stands east of the shell rather than under it.
    dose.pin(port="discharge", x=dose_x, y=430)

    # Dosed into the feed line rather than into the tank or the launder. A
    # polymer wants *some* shear after injection -- enough to distribute it
    # through the slurry and let flocs grow -- and then no more, because past
    # that point every fitting tears apart what it has built. The last stretch
    # of feed pipe is the usual compromise and is what the tee sits on. A real
    # plant doses into the feedwell at several points, which is a level of
    # detail a PFD does not carry.
    floc.pin(port="branch", x=dose_x, y=feed_y + tee_w / 2)
    thickener.pin(port="feed", x=380, y=feed_y)
    overflow.pin(port="inlet", x=520, y=feed_y)     # dead level off the launder

    # The underflow drops out of the apex and turns east into the pump. The
    # eccentric reducer is the step in the line: its outlet sits 2.4 units
    # above its inlet, so the crown of the run stays flat across it and the
    # step is all on the invert, which is the whole point of the fitting.
    suction_y = 330.0
    underflow_pump.pin(port="suction", x=520.7, y=suction_y)
    # Both reducers stand a spool clear of the pump rather than bolted to its
    # nozzles, and the gap is the label's and not the piping's. A reducer is
    # sixteen units of drawing carrying a five-character tag, so its plate is
    # three times the width of the fitting and overhangs it either way; hard
    # against the casing, both plates take a bite out of P-401's outline, and
    # the two invariants that catch it -- no halo over a symbol, no halo over
    # a line that is not its own -- leave one window each. RD-401's is between
    # the underflow riser and the pump, RD-402's between the pump and the
    # filter, and each fitting is set at the middle of its own.
    suction_red.pin(port="outlet", x=478, y=suction_y)
    disch_red.pin(port="inlet", x=624, y=suction_y)
    belt_filter.pin(port="inlet", x=670, y=suction_y)

    cake_tee.pin(port="inlet", x=740, y=suction_y)
    # Set west of FH-401's tag rather than under the dryer. The burner's plate
    # is written above its box and is wider than the box is, so a flag any
    # further east has that plate through its own outline; the gas riser into
    # the burner's underside rules out writing the tag below it instead.
    filtrate.pin(port="inlet", x=770, y=560)

    # The belt runs under the cake leg, so the cake drops onto its tail rather
    # than being piped into its end, and throws off into the breeching.
    belt_y, dryer_y = 480.0, 490.0
    conveyor.pin(port="feed", x=cake_tee.pin_.x + tee_w + 38, y=belt_y)
    breeching.pin(port="inlet", x=950, y=dryer_y)
    dryer.pin(port="feed", x=1000, y=dryer_y)

    # The burner box sits at grade under the feed end and its duct climbs into
    # the breeching. Its own air comes in level off an ambient flag; the fuel
    # arrives from below, which is the only face the stencil's fuel nozzle
    # offers and is where a gas train really runs.
    heater.pin(port="inlet", x=860, y=654.5)
    air.pin(port="outlet", x=790, y=654.5)   # clear of the burner wall
    gas.pin(port="outlet", x=750, y=740)
    hot_gas_x = breeching.pin_.x + tee_w / 2

    cyclone.pin(port="feed", x=1180, y=322)
    # Above the gas riser rather than beside it: the scrub-water line crosses
    # the duct's line of travel, and the only place on this sheet where it can
    # do that without crossing the duct itself is over the top of it.
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

    # --- Connections ------------------------------------------------------
    # Declared in stream-number order, which is the order the table reads. A
    # number is drawn once, on the first segment declared, so a service that
    # runs through more than one item starts with the run the number belongs
    # on: the underflow through its eccentric reducer, the filter feed through
    # its expander and the filter itself, the stack gas through its fan.
    #
    # **Every tee ends a number.** ``10``'s reflux tee keeps one straight
    # through, and it is right to: both legs off that drum are the same fluid
    # at the same conditions, so the junction is a pure takeoff and nothing
    # about the stream changes across it. Not one of the five junctions here is
    # like that. Four of them add a second material to the run and the fifth
    # parts a cake from a filtrate, so each one has a stream on its downstream
    # side that no upstream column is true of -- and a table that carried the
    # cake's 68.9 t/h on the line into DR-401, which is really carrying 99.8,
    # would be a mass balance that does not close written on a drawing that
    # claims one.
    fs.connect(concentrate.outlet, floc.inlet, name="S-401")

    fs.connect(water.outlet, charge.inlet, name="S-402")
    fs.connect(funnel.outlet, charge.branch, name="S-403")
    fs.connect(charge.outlet, tank.inlet, name="S-404")

    fs.connect(tank.outlet, dose.suction, name="S-405")
    fs.connect(dose.discharge, floc.branch, name="S-405")
    fs.connect(floc.outlet, thickener.feed, name="S-406")

    fs.connect(thickener.port("vapor"), overflow.inlet, name="S-407")

    # Straight down out of the cone. Left to itself the router steps the riser
    # 34 units east on its way past the thickener's skirt, and it lands in the
    # only clear window RD-401's tag has.
    fs.connect(thickener.port("liquid"), suction_red.inlet, name="S-408").via(
        [(420, 332.4)])
    fs.connect(suction_red.outlet, underflow_pump.suction, name="S-408")

    fs.connect(underflow_pump.discharge, disch_red.inlet, name="S-409")
    fs.connect(disch_red.outlet, belt_filter.inlet, name="S-409")
    fs.connect(belt_filter.outlet, cake_tee.inlet, name="S-409")

    fs.connect(cake_tee.branch, filtrate.inlet, name="S-410")

    fs.connect(cake_tee.outlet, conveyor.feed, name="S-411")
    fs.connect(conveyor.discharge, breeching.inlet, name="S-411")

    fs.connect(air.outlet, heater.inlet, name="S-412")
    fs.connect(gas.outlet, heater.fuel, name="S-413").via([(900, 740)])
    # Pinned by hand: left to itself the router takes the burner duct the long
    # way round the dryer. Up the east side of the breeching and straight into
    # the branch is the run the plant has.
    fs.connect(heater.outlet, breeching.branch, name="S-414").via(
        [(hot_gas_x, 654.5 + 25)])

    fs.connect(breeching.outlet, dryer.feed, name="S-415")
    fs.connect(dryer.product, cyclone.feed, name="S-416")

    fs.connect(cyclone.port("vapor"), scrub_tee.inlet, name="S-417")
    fs.connect(scrub_water.outlet, scrub_tee.branch, name="S-418")
    fs.connect(scrub_tee.outlet, scrubber.feed, name="S-419")

    fs.connect(scrubber.port("vapor"), fan.suction, name="S-420")
    fs.connect(fan.discharge, stack.inlet, name="S-420")
    fs.connect(scrubber.port("liquid"), effluent.inlet, name="S-421")

    fs.connect(cyclone.port("liquid"), magnet.feed, name="S-422")
    fs.connect(magnet.port("overflow"), product.inlet, name="S-423")
    fs.connect(magnet.port("underflow"), tramp.inlet, name="S-424")

    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Water", "Mass Fraction")]

    # --- Title strip ------------------------------------------------------
    # The date is stated rather than left blank, so the sheet renders the same
    # today as it did at issue.
    fs.title_block = TitleBlock(
        title="Mineral Dewatering",
        subtitle="A400 Process Flow Diagram 1",
        drawing_number="PFD-401",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        date="12/09/25",
        drawn_by="AA", checked_by="RG", approved_by="HVL",
        revisions=[
            Revision("A", "22/08/25", "Issued for internal review", "AA"),
            Revision("B", "05/09/25", "Dryer exhaust scrubber added", "AA"),
            Revision("C", "12/09/25", "Issued For Review", "AA", "RG", "HVL"),
        ],
    )

    # --- Sheet furniture --------------------------------------------------
    # Named row by row in process order rather than in declaration order, which
    # is what a schedule reads like. The five tees, the funnel, the two
    # reducers and the exhaust head carry no row: all nine are bulk items
    # bought by the line, and none of them has a datasheet behind it.
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
