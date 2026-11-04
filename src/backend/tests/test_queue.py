"""The queue's rules (docs/backend.md 8), with a fake clock: `now` is just a number."""

import pytest

from dod.bus import QueueJoined, QueueLeft, TurnEnded, TurnStarted
from dod.control.queue import Queue

TURN, INACTIVE = 180, 30


def queue():
    return Queue(turn_seconds=TURN, inactive_seconds=INACTIVE)


def kinds(events):
    """Events as short tuples, easy to compare."""
    out = []
    for e in events:
        match e:
            case QueueJoined(session=s, position=p):
                out.append(("joined", s, p))
            case QueueLeft(session=s, reason=r):
                out.append(("left", s, r))
            case TurnStarted(session=s, waiting=w):
                out.append(("started", s, w))
            case TurnEnded(session=s, reason=r):
                out.append(("ended", s, r))
    return out


def busy(q, *sessions, now=0):
    """These sessions join at `now`, all connected; the first gets control."""
    for s in sessions:
        q.connected(s, now)
        q.join(s, now)


def keep_active(q, session, until, start=0, every=10):
    """`session` sends a command every few seconds."""
    events = []
    t = start
    while t <= until:
        q.activity(session, t)
        events += q.tick(t)
        t += every
    return events


# --- joining, the first turn ----------------------------------------------------


def test_the_first_visitor_gets_control_at_once():
    q = queue()
    q.connected("a", 0)
    assert kinds(q.join("a", 0)) == [("joined", "a", 1), ("started", "a", 0)]
    assert q.controller == "a" and q.position("a") == 0 and q.turn_ends_at == TURN


def test_the_next_ones_wait_in_order():
    q = queue()
    busy(q, "a")
    assert kinds(q.join("b", 1)) == [("joined", "b", 1)]
    assert kinds(q.join("c", 2)) == [("joined", "c", 2)]
    assert q.waiting == ("b", "c") and q.position("b") == 1 and q.position("c") == 2
    assert q.position("nobody") is None


def test_joining_twice_changes_nothing():
    q = queue()
    busy(q, "a", "b")
    assert q.join("a", 5) == [] and q.join("b", 5) == []
    assert q.waiting == ("b",)


# --- the turn's length ------------------------------------------------------------


def test_the_turn_ends_after_3_minutes_when_someone_waits():
    q = queue()
    busy(q, "a", "b")
    assert keep_active(q, "a", TURN - 1) == []
    assert kinds(q.tick(TURN)) == [("ended", "a", "time"), ("started", "b", 0)]
    assert q.controller == "b" and q.turn_ends_at == TURN + TURN


def test_with_nobody_waiting_the_turn_goes_on():
    q = queue()
    busy(q, "a")
    assert keep_active(q, "a", 3 * TURN) == []
    assert q.controller == "a" and q.turn_over


def test_an_over_turn_ends_as_soon_as_someone_joins():
    q = queue()
    busy(q, "a")
    keep_active(q, "a", TURN + 60)
    q.connected("b", TURN + 61)
    assert kinds(q.join("b", TURN + 61)) == [("joined", "b", 1), ("ended", "a", "time"), ("started", "b", 0)]


# --- songs ------------------------------------------------------------------------


def test_their_songs_end_ends_the_turn():
    q = queue()
    busy(q, "a", "b")
    q.song_started("a", 10)
    assert kinds(q.song_ended(100)) == [("ended", "a", "song"), ("started", "b", 0)]


def test_their_songs_end_with_nobody_waiting_makes_the_turn_over():
    q = queue()
    busy(q, "a")
    q.song_started("a", 10)
    assert q.song_ended(100) == []
    assert q.controller == "a" and q.turn_over
    q.connected("b", 120)
    assert kinds(q.join("b", 120))[-2:] == [("ended", "a", "song"), ("started", "b", 0)]


def test_a_song_from_the_previous_turn_doesnt_end_the_next():
    q = queue()
    busy(q, "a", "b")
    q.song_started("a", TURN - 20)  # a picks a song just before the turn ends
    keep_active(q, "a", TURN - 1, start=TURN - 20)
    assert kinds(q.tick(TURN)) == [("ended", "a", "time"), ("started", "b", 0)]
    q.activity("b", TURN + 30)
    assert q.song_ended(TURN + 50) == []  # a's song ends during b's turn
    assert q.controller == "b" and not q.turn_over


def test_a_stopped_song_doesnt_end_the_turn():
    q = queue()
    busy(q, "a", "b")
    q.song_started("a", 10)
    q.song_stopped(20)  # a picked a preset instead
    assert q.tick(21) == [] and q.controller == "a" and not q.turn_over


def test_a_song_from_the_main_screen_doesnt_end_the_turn():
    q = queue()
    busy(q, "a", "b")
    q.song_started("main", 10)
    q.activity("a", 20)
    assert q.song_ended(25) == [] and q.controller == "a"


# --- inactivity -------------------------------------------------------------------


def test_no_command_for_30_s_loses_control_even_with_nobody_waiting():
    q = queue()
    busy(q, "a")
    q.activity("a", 10)
    assert q.tick(39) == []
    assert kinds(q.tick(40)) == [("ended", "a", "inactive")]
    assert q.controller is None


def test_inactivity_passes_control_to_the_next():
    q = queue()
    busy(q, "a", "b")
    assert kinds(q.tick(INACTIVE)) == [("ended", "a", "inactive"), ("started", "b", 0)]


def test_offline_for_30_s_loses_control():
    q = queue()
    busy(q, "a", "b")
    q.activity("a", 5)
    q.disconnected("a", 10)
    assert q.tick(39) == []  # 29 s offline
    assert kinds(q.tick(40)) == [("ended", "a", "inactive"), ("started", "b", 0)]


def test_a_reload_keeps_control():
    q = queue()
    busy(q, "a", "b")
    q.activity("a", 10)
    q.disconnected("a", 10)
    q.connected("a", 12)  # the page reloaded
    q.activity("a", 13)
    assert q.tick(40) == [] and q.controller == "a"


def test_their_own_song_keeps_them_active_even_offline():
    q = queue()
    busy(q, "a", "b")
    q.song_started("a", 5)
    q.disconnected("a", 6)  # phone locked while watching the song
    assert q.tick(100) == [] and q.controller == "a"  # 94 s offline
    q.song_stopped(110)  # the clock starts again when the song is over
    assert q.tick(139) == []
    assert kinds(q.tick(140)) == [("ended", "a", "inactive"), ("started", "b", 0)]


def test_offline_before_the_turn_counts_from_the_turn_start():
    q = queue()
    busy(q, "a")
    q.connected("b", 0)
    q.join("b", 0)
    q.disconnected("b", 5)
    q.leave("a", 10)  # b's turn starts while b is offline
    assert q.controller == "b"
    assert q.tick(39) == []  # 34 s offline, but only 29 s of it during the turn
    assert kinds(q.tick(40)) == [("ended", "b", "inactive")]


def test_a_waiting_visitor_offline_for_30_s_leaves_the_queue():
    q = queue()
    busy(q, "a", "b", "c")
    q.disconnected("b", 10)
    q.activity("a", 30)
    assert q.tick(39) == []
    assert kinds(q.tick(40)) == [("left", "b", "gone")]
    assert q.waiting == ("c",)


# --- leaving, rejoining -----------------------------------------------------------


def test_leaving_while_waiting():
    q = queue()
    busy(q, "a", "b", "c")
    assert kinds(q.leave("b", 5)) == [("left", "b", "left")]
    assert q.waiting == ("c",) and q.position("c") == 1


def test_the_controller_leaving_passes_control():
    q = queue()
    busy(q, "a", "b")
    assert kinds(q.leave("a", 5)) == [("ended", "a", "left"), ("started", "b", 0)]


def test_after_a_turn_rejoining_is_at_the_back():
    q = queue()
    busy(q, "a", "b", "c")
    keep_active(q, "a", TURN - 1)
    q.tick(TURN)  # a's turn is over, b plays
    assert q.position("a") is None  # nobody is put back in line automatically
    q.join("a", TURN + 1)
    assert q.waiting == ("c", "a")


def test_leaving_when_not_in_the_queue():
    assert queue().leave("x", 0) == []


# --- admin ------------------------------------------------------------------------


def test_skip():
    q = queue()
    busy(q, "a", "b")
    assert kinds(q.skip(5)) == [("ended", "a", "skipped"), ("started", "b", 0)]
    assert kinds(q.skip(6)) == [("ended", "b", "skipped")]
    assert q.skip(7) == []


def test_pause_and_resume():
    q = queue()
    busy(q, "a", "b")
    q.pause(100)
    assert keep_active(q, "a", 500, start=100) == []  # time doesn't end the turn while paused
    q.leave("a", 501)
    assert q.controller is None and q.waiting == ("b",)  # ...and nobody new gets a turn
    assert kinds(q.resume(502)) == [("started", "b", 0)]


def test_resuming_adds_the_paused_time():
    q = queue()
    busy(q, "a", "b")
    q.pause(100)
    keep_active(q, "a", 160, start=100)
    q.resume(160)
    assert q.turn_ends_at == TURN + 60
    assert keep_active(q, "a", TURN + 59, start=160) == []
    assert kinds(q.tick(TURN + 60))[0] == ("ended", "a", "time")


def test_inactivity_still_counts_while_paused():
    q = queue()
    busy(q, "a", "b")
    q.pause(0)
    assert kinds(q.tick(INACTIVE)) == [("ended", "a", "inactive")]
    assert q.controller is None


def test_bad_timings():
    with pytest.raises(ValueError):
        Queue(turn_seconds=0, inactive_seconds=30)
