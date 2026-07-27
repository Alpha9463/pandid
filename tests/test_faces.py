"""Automatic port-face selection: the engine picking which face a movable port
is piped from, given where the unit at the other end of the stream landed."""

from pandid import Flowsheet, units
from pandid.portgeom import port_anchor


def _drum_fed_from(x, y, *, fs=None, **drum_pin):
    """A horizontal separator at (200, 200) fed by a flag whose tip is (x, y).

    The drum's ``feed`` is the movable nozzle: its symbol authors a coordinate
    on the west head, the north shell and the east head, so where the flag sits
    is the only thing that can decide between them.
    """
    fs = fs if fs is not None else Flowsheet("faces")
    drum = fs.add(units.Separator("V-1", variant="horizontal"))
    drum.pin(x=200, y=200, **drum_pin)
    flag = fs.add(units.Feed("F")).pin(x=x - 50, y=y - 25)
    fs.connect(flag.outlet, drum.feed)
    return fs, drum


# --- taking the face the peer is actually on ---------------------------------


def test_a_peer_overhead_takes_the_north_shell():
    fs, drum = _drum_fed_from(220, 60)
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "N"


def test_a_peer_astern_takes_the_far_head():
    """The east head, which no example names by hand — the engine reaches it on
    the same evidence it reaches the north shell on."""
    fs, drum = _drum_fed_from(500, 215)
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "E"


def test_a_peer_ahead_leaves_the_home_nozzle_alone():
    fs, drum = _drum_fed_from(20, 215)
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "W"


def test_the_face_is_named_in_drawn_space():
    """The alternate is authored on the symbol's north head, so on a unit flipped
    top-to-bottom it is drawn on the south. A peer *below* is what reaches it."""
    fs, drum = _drum_fed_from(220, 400, mirrored="y")
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "S"


# --- what selection must not touch -------------------------------------------


def test_an_explicit_nozzle_beats_the_engine():
    fs, drum = _drum_fed_from(220, 60)
    drum.nozzle("feed", "E")
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "E"
    assert "feed" not in drum.frame.port_faces


def test_a_nozzle_fixed_by_physics_is_never_considered():
    """A column's bottoms leaves the bottom whatever is drawn above it: its
    symbol authors one placement, so there is nothing to choose between."""
    fs = Flowsheet("gravity")
    col = fs.add(units.Column("T-1")).pin(x=300, y=400)
    sump = fs.add(units.Product("Bottoms")).pin(x=300, y=100)
    fs.connect(col.bottoms, sump.inlet)
    fs.layout()
    assert port_anchor(col, col.frame, "bottoms")[2] == "S"
    assert col.frame.port_faces == {}


def test_a_feed_family_is_fixed_the_way_a_single_nozzle_is():
    """Each member of a column's feed family has exactly one placement — the
    family spreads *along* the shell wall, it does not offer other walls — so
    selection has nothing to choose between and leaves every one of them where
    the symbol put it."""
    fs = Flowsheet("extractive")
    col = fs.add(units.Column("T-302", n_feeds=2)).pin(x=300, y=200)
    solvent = fs.add(units.Feed("Solvent")).pin(x=80, y=250)
    wash = fs.add(units.Feed("Wash")).pin(x=80, y=330)
    fs.connect(solvent.outlet, col.feed_1)
    fs.connect(wash.outlet, col.feed_2)
    fs.layout()
    assert port_anchor(col, col.frame, "feed_1")[2] == "W"
    assert port_anchor(col, col.frame, "feed_2")[2] == "W"
    assert col.frame.port_faces == {}
    # ...and they are two nozzles, not one drawn twice.
    assert port_anchor(col, col.frame, "feed_1") != port_anchor(col, col.frame, "feed_2")


def test_a_kettles_bottoms_draw_is_a_fixed_target_its_peer_aims_at():
    """The draw is on the shell bottom and offers nothing else, so it is what a
    movable port at the other end of the line gets scored against."""
    fs = Flowsheet("reboiler")
    reb = fs.add(units.HeatExchanger("E-702", variant="kettle")).pin(x=300, y=200)
    # Hung so its north shell nozzle is directly under the draw, which is the
    # face a straight drop reaches.
    drum = fs.add(units.Separator("V-1", variant="horizontal")).pin(x=365, y=380)
    fs.connect(reb.bottoms, drum.feed)
    fs.layout()
    assert port_anchor(reb, reb.frame, "bottoms")[2] == "S"
    assert reb.frame.port_faces == {}
    assert drum.frame.port_faces == {"feed": "N"}


def test_a_port_with_no_stream_keeps_its_home():
    fs, drum = _drum_fed_from(220, 60)
    fs.layout()
    # vapor and liquid are unconnected: no peer, so no evidence either way.
    assert set(drum.frame.port_faces) == {"feed"}


def test_the_kill_switch_restores_the_symbols_own_nozzles():
    fs, drum = _drum_fed_from(220, 60, fs=Flowsheet("faces", auto_faces=False))
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "W"
    assert drum.frame.port_faces == {}


# --- the choice is a result, not intent --------------------------------------


def test_the_pick_never_becomes_the_authors_intent():
    """A spec written back out has to describe the sheet the author asked for,
    not the one the engine drew, or reloading it would freeze this run's pick."""
    fs, drum = _drum_fed_from(220, 60)
    fs.layout()
    assert drum.frame.port_faces == {"feed": "N"}
    assert drum._port_faces == {}
    assert "port_faces" not in next(u for u in fs.to_dict()["units"] if u["name"] == "V-1")


def test_laying_the_sheet_out_twice_draws_it_the_same_way():
    fs, drum = _drum_fed_from(220, 60)
    fs.layout()
    fs.route()
    first = dict(drum.frame.port_faces)
    fs.layout()
    fs.route()
    assert dict(drum.frame.port_faces) == first == {"feed": "N"}


def test_a_balloons_pick_survives_being_re_placed_by_the_router():
    """An attached balloon is placed again once its host line is routed, which
    replaces its frame — and its frame is where the pick lives."""
    fs = Flowsheet("loop")
    feed = fs.add(units.Feed("Feed")).pin(x=60, y=270)
    fv = fs.add(units.Valve("FV-1", variant="control")).pin(x=260, y=280)
    vessel = fs.add(units.Vessel("V-1", width=90, height=140)).pin(x=480, y=210)
    prod = fs.add(units.Product("P")).pin(x=700, y=265)
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, vessel.inlet)
    fs.connect(vessel.outlet, prod.inlet)
    lic = fs.add_instrument("LIC", 101, on=vessel, at="S", offset=115, variant="panel")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")
    fs.layout()
    fs.route()
    assert lic.frame.port_faces == {"sig_out": "W"}
    assert port_anchor(lic, lic.frame, "sig_out")[2] == "W"


# --- the engine must not draw a contradiction --------------------------------


def test_two_signals_from_the_same_side_do_not_land_on_one_point():
    """Both of a controller's signals come from above, and the cheapest face for
    each is the same one. Two live connections on a single point is a hard
    validation error, so the second takes the next-cheapest free face."""
    fs = Flowsheet("stack")
    fv = fs.add(units.Valve("FV-1", variant="control")).pin(x=300, y=180)
    feed = fs.add(units.Feed("F")).pin(x=100, y=175)
    prod = fs.add(units.Product("P")).pin(x=520, y=175)
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    lt = fs.add(units.Instrument("LT-101")).pin(x=300, y=400)
    lic = fs.add(units.Instrument("LIC-101", variant="panel")).pin(x=300, y=520)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")
    fs.layout()
    faces = {port_anchor(lic, lic.frame, name)[2] for name in ("sig_in", "sig_out")}
    assert len(faces) == 2
    assert [i for i in fs.validate() if i.code == "coincident-ports"] == []


# --- ordering within the layout run ------------------------------------------


def test_the_label_dodges_the_face_the_engine_chose():
    """Label placement reads the faces connected nozzles occupy, so it has to run
    after selection: on the home nozzle this drum's tag would go to the top,
    which is exactly where the feed now enters."""
    fs, drum = _drum_fed_from(220, 60)
    fs.layout()
    assert drum.frame.label_pos == "bottom"
