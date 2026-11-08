"""Check automatic port-face selection against the placed peer unit."""

import pytest

from pandid import Flowsheet, units
from pandid.portgeom import port_anchor
from pandid.routing import DefaultRouter


def _drum_fed_from(x, y, *, fs=None, **drum_pin):
    """Build a horizontal separator fed by one boundary flag."""
    fs = fs if fs is not None else Flowsheet("faces")
    drum = fs.add(units.Separator("V-1", variant="horizontal"))
    drum.pin(x=200, y=200, **drum_pin)
    flag = fs.add(units.Feed("F")).pin(x=x, y=y)
    fs.connect(flag.outlet, drum.feed)
    return fs, drum


# --- Selection by peer position ----------------------------------------------


@pytest.mark.parametrize(
    "x, y, pin, face",
    [
        (220, 60, {}, "N"),
        (500, 215, {}, "E"),
        (20, 215, {}, "W"),
        (220, 400, {"mirrored": "y"}, "S"),
    ],
    ids=["overhead-north-shell", "astern-far-head", "ahead-home-nozzle", "mirrored-drawn-face"],
)
def test_the_feed_takes_the_face_toward_its_peer(x, y, pin, face):
    """Select the feed placement facing the peer, named as drawn."""
    fs, drum = _drum_fed_from(x, y, **pin)
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == face


# --- Ports selection leaves alone --------------------------------------------


def test_an_explicit_nozzle_beats_the_engine():
    """Keep a face the author chose with ``nozzle()``."""
    fs, drum = _drum_fed_from(220, 60)
    drum.nozzle("feed", "E")
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "E"
    assert "feed_1" not in drum.frame.port_faces


def test_a_nozzle_fixed_by_physics_is_never_considered():
    """Leave a port with one declared placement on its face."""
    fs = Flowsheet("gravity")
    col = fs.add(units.Column("T-1")).pin(x=300, y=400)
    sump = fs.add(units.Product("Bottoms")).pin(x=300, y=100)
    fs.connect(col.bottoms, sump.inlet)
    fs.layout()
    assert port_anchor(col, col.frame, "bottoms")[2] == "S"
    assert col.frame.port_faces == {}


def test_a_feed_family_is_fixed_the_way_a_single_nozzle_is():
    """Leave every member of a column feed family on the west wall."""
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
    # The family members occupy separate nozzles.
    assert port_anchor(col, col.frame, "feed_1") != port_anchor(col, col.frame, "feed_2")


def test_a_draw_family_is_fixed_on_the_east_wall_a_feed_never_reaches():
    """Leave every member of a column draw family on the east wall."""
    fs = Flowsheet("sidestream")
    col = fs.add(units.Column("T-401", n_draws=2)).pin(x=300, y=200)
    heavy = fs.add(units.Product("Heavy Naphtha")).pin(x=500, y=250)
    light = fs.add(units.Product("Light Naphtha")).pin(x=500, y=330)
    fs.connect(col.draw_1, heavy.inlet)
    fs.connect(col.draw_2, light.inlet)
    fs.layout()
    assert port_anchor(col, col.frame, "draw_1")[2] == "E"
    assert port_anchor(col, col.frame, "draw_2")[2] == "E"
    assert col.frame is not None
    assert col.frame.port_faces == {}
    assert port_anchor(col, col.frame, "draw_1") != port_anchor(col, col.frame, "draw_2")


def test_a_kettles_bottoms_draw_is_a_fixed_target_its_peer_aims_at():
    """Score a movable port against its peer's fixed nozzle."""
    fs = Flowsheet("reboiler")
    reb = fs.add(units.HeatExchanger("E-702", variant="kettle")).pin(x=300, y=200)
    # Place the drum's north nozzle directly below the kettle's draw.
    drum = fs.add(units.Separator("V-1", variant="horizontal")).pin(x=365, y=380)
    fs.connect(reb.bottoms, drum.feed)
    fs.layout()
    assert port_anchor(reb, reb.frame, "bottoms")[2] == "S"
    assert reb.frame.port_faces == {}
    assert drum.frame.port_faces == {"feed_1": "N"}


def test_a_port_with_no_stream_keeps_its_home():
    """Select faces only for connected ports."""
    fs, drum = _drum_fed_from(220, 60)
    fs.layout()
    assert set(drum.frame.port_faces) == {"feed_1"}


def test_the_kill_switch_restores_the_symbols_own_nozzles():
    """Keep home placements when ``auto_faces`` is disabled."""
    fs, drum = _drum_fed_from(220, 60, fs=Flowsheet("faces", auto_faces=False))
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "W"
    assert drum.frame.port_faces == {}


@pytest.mark.parametrize(
    ("auto_faces", "explicit", "face"),
    [(True, False, "N"), (True, True, "E"), (False, False, "W")],
)
def test_recovered_escape_preserves_selected_and_authored_faces(
    auto_faces: bool, explicit: bool, face: str
) -> None:
    """Keep the resolved nozzle face while recovering an outward escape."""
    fs, drum = _drum_fed_from(220, 60, fs=Flowsheet("faces", auto_faces=auto_faces))
    if explicit:
        drum.nozzle("feed", "E")
    fs.layout()
    assert drum.frame is not None
    before = dict(drum.frame.port_faces)
    assert port_anchor(drum, drum.frame, "feed")[2] == face

    fs.route(DefaultRouter())

    assert port_anchor(drum, drum.frame, "feed")[2] == face
    assert drum.frame.port_faces == before


# --- Reactor side outlets and blocked faces ----------------------------------


def _reactor_discharging_to(x, y, *, blocker=None, **sheet):
    """Build a pinned reactor whose outlet feeds one product flag."""
    fs = Flowsheet("reactor", **sheet)
    reactor = fs.add(units.Reactor("R-1")).pin(x=300, y=200)
    flag = fs.add(units.Product("P")).pin(x=x, y=y)
    if blocker is not None:
        fs.add(units.Vessel("V-1", width=40, height=40, label_pos="center")).pin(
            x=blocker[0], y=blocker[1]
        )
    fs.connect(reactor.outlet, flag.inlet)
    return fs, reactor


@pytest.mark.parametrize(
    ("x", "y", "face"),
    [(600, 150, "E"), (60, 150, "W"), (331, 500, "S"), (600, 450, "S")],
)
def test_a_reactor_outlet_takes_a_side_only_when_it_saves_a_bend(x, y, face):
    """Select a side outlet only when it needs no more bends than the floor."""
    fs, reactor = _reactor_discharging_to(x, y)
    fs.layout()
    assert port_anchor(reactor, reactor.frame, "outlet")[2] == face


def test_a_reactor_outlet_stays_on_the_floor_without_automatic_faces():
    """Keep the floor outlet when ``auto_faces`` is disabled."""
    fs, reactor = _reactor_discharging_to(600, 150, auto_faces=False)
    fs.layout()
    assert port_anchor(reactor, reactor.frame, "outlet")[2] == "S"
    assert reactor.frame.port_faces == {}


def test_an_explicit_reactor_outlet_face_beats_the_engine():
    """Keep a reactor outlet face the author chose with ``nozzle()``."""
    fs, reactor = _reactor_discharging_to(600, 150)
    reactor.nozzle("outlet", "S")
    fs.layout()
    assert port_anchor(reactor, reactor.frame, "outlet")[2] == "S"
    assert reactor.frame.port_faces == {}


@pytest.mark.parametrize(
    ("x", "y", "blocker", "faces"),
    [(600, 150, (370, 294), {"S"}), (331, 500, (311, 340), {"E", "W"})],
)
def test_a_face_whose_stub_crosses_a_unit_is_skipped(x, y, blocker, faces):
    """Skip a face whose outward stub crosses another unit."""
    fs, reactor = _reactor_discharging_to(x, y, blocker=blocker)
    fs.layout()
    assert port_anchor(reactor, reactor.frame, "outlet")[2] in faces
    fs.route()
    assert not any(issue.code == "route-crosses-unit" for issue in fs.validate())


# --- A choice is derived geometry, not author intent -------------------------


def test_the_pick_never_becomes_the_authors_intent():
    """Keep an automatic choice out of the serialized model."""
    fs, drum = _drum_fed_from(220, 60)
    fs.layout()
    assert drum.frame.port_faces == {"feed_1": "N"}
    assert drum._port_faces == {}
    assert "port_faces" not in next(u for u in fs.to_dict()["units"] if u["name"] == "V-1")


def test_laying_the_sheet_out_twice_draws_it_the_same_way():
    """Repeat the same choice on a second layout and route."""
    fs, drum = _drum_fed_from(220, 60)
    fs.layout()
    fs.route()
    first = dict(drum.frame.port_faces)
    fs.layout()
    fs.route()
    assert dict(drum.frame.port_faces) == first == {"feed_1": "N"}


def test_a_balloons_pick_survives_being_re_placed_by_the_router():
    """Keep an attached balloon's choice when routing replaces its frame."""
    fs = Flowsheet("loop")
    feed = fs.add(units.Feed("Feed")).pin(x=60, y=270)
    fv = fs.add(units.Valve("FV-1", actuator="diaphragm")).pin(x=260, y=280)
    vessel = fs.add(units.Vessel("V-1", width=90, height=140)).pin(x=480, y=210)
    prod = fs.add(units.Product("P")).pin(x=700, y=265)
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, vessel.inlet)
    fs.connect(vessel.outlet, prod.inlet)
    lic = fs.add_instrument("LIC", 101, sensing=vessel, face="S", offset=115, display="central")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")
    fs.layout()
    fs.route()
    assert lic.frame.port_faces == {"sig_out": "W"}
    assert port_anchor(lic, lic.frame, "sig_out")[2] == "W"


# --- Selection never creates a validation error ------------------------------


def test_two_signals_from_the_same_side_do_not_land_on_one_point():
    """Give two signals with the same cheapest face separate faces."""
    fs = Flowsheet("stack")
    fv = fs.add(units.Valve("FV-1", actuator="diaphragm")).pin(x=300, y=180)
    feed = fs.add(units.Feed("F")).pin(x=100, y=175)
    prod = fs.add(units.Product("P")).pin(x=520, y=175)
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    lt = fs.add(units.Instrument("LT-101")).pin(x=300, y=400)
    lic = fs.add(units.Instrument("LIC-101", display="central")).pin(x=300, y=520)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")
    fs.layout()
    faces = {port_anchor(lic, lic.frame, name)[2] for name in ("sig_in", "sig_out")}
    assert len(faces) == 2
    assert [i for i in fs.validate() if i.code == "coincident-ports"] == []


# --- Order within a layout run -----------------------------------------------


def test_the_label_dodges_the_face_the_engine_chose():
    """Place the label after face selection."""
    fs, drum = _drum_fed_from(220, 60)
    fs.layout()
    assert drum.frame.label_pos == "bottom"
