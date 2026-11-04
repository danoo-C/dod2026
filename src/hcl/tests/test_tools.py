"""The tools (docs/hcl.md 9): their logic against the simulated board, and each
command line once as a real process, including Ctrl-C."""

import os
import re
import signal
import subprocess
import sys
import time

import pytest

from hcl import Frame, open_link
from hcl.link import Link, LinkOptions
from hcl.tools import bench, pattern, repl
from hcl.transport import Transport, TransportError
from hcl.testing import sim_link
from hcl.transport.sim import SimTransport
from support import FAST, run


class Out(list):
    """Collects what a tool prints."""

    def __call__(self, line):
        self.append(line)

    def text(self):
        return "\n".join(self)


class SilentTransport(Transport):
    def open(self):
        pass

    def read(self, max_bytes, timeout):
        time.sleep(timeout)
        return b""

    def write(self, data):
        pass

    def close(self):
        pass


class MissingTransport(SilentTransport):
    def open(self):
        raise TransportError("no such port")


# --- pattern ------------------------------------------------------------------


def test_pattern_steps():
    steps = pattern.steps(10)
    assert len(steps) == 3 + 10 + 8 + 8 + 16 + 1
    assert all(isinstance(f, Frame) and f.led_count == 10 for _, f, _ in steps)
    red = steps[0][1]
    assert red.strip == bytes([60, 0, 0]) * 10  # RGB in; the link converts to the board's order
    walk_3 = steps[3 + 2][1]
    assert walk_3.strip[6:9] == bytes([60, 60, 60]) and walk_3.strip.count(0) == 27
    column_1 = steps[3 + 10 + 8][1]
    assert column_1.matrix == bytes([0x80] * 8)  # bit 7 = leftmost pixel
    assert steps[-1][1] == Frame.blank(10)
    assert "COLOR_ORDER" in steps[0][0]


@run
async def test_pattern_runs_against_the_board():
    link, board = sim_link()
    out = Out()
    # at 10x every step still lasts longer than a round trip, so (nearly) every step reaches the board
    assert await pattern.pattern(link, speed=10, out=out) == 0
    assert out[0] == "board: firmware 0.0.0, simulated, 10 LEDs, GRB, protocol 1"
    assert out[-1] == "done"
    assert board.strip_rgb() == bytes(30) and board.picture.matrix == bytes(8)  # ends with everything off
    assert board.frames_received >= len(pattern.steps(10)) - 3


@run
async def test_pattern_without_a_board(monkeypatch):
    monkeypatch.setattr(pattern, "CONNECT_TIMEOUT", 0.3)
    out = Out()
    link = Link(MissingTransport(), url="/dev/ttyUSB9", options=LinkOptions(**FAST))
    assert await pattern.pattern(link, out=out) == 1
    assert "no board answered" in out.text() and "no such port" in out.text()


# --- bench --------------------------------------------------------------------


@run
async def test_bench_fast_board_passes():
    link, _ = sim_link("sim?latency_ms=2", max_fps=1000)
    out = Out()
    assert await bench.bench(link, seconds=1.5, out=out) == 0, out.text()
    assert out[-1].startswith("PASS")
    assert re.search(r"round trip\s+min [\d.]+ ms, avg [\d.]+ ms, max [\d.]+ ms", out.text())


@run
async def test_bench_slow_board_fails_and_respects_the_latency():
    link, _ = sim_link("sim?latency_ms=30", max_fps=1000)
    out = Out()
    assert await bench.bench(link, seconds=1.5, out=out) == 1
    fps = float(re.search(r"= ([\d.]+) fps", out.text()).group(1))
    assert 10 < fps <= 34  # can't be faster than one round trip of 30 ms allows
    assert "FAIL: only" in out[-1]


@run
async def test_bench_reports_lost_frames():
    link, _ = sim_link("sim?latency_ms=2&drop=0.3&seed=1", max_fps=1000)
    out = Out()
    assert await bench.bench(link, seconds=1.5, out=out) == 1
    assert "ACK timeouts" in out[-1]


# --- repl ---------------------------------------------------------------------


def test_repl_against_the_board():
    t = SimTransport()
    out = Out()
    assert repl.repl(t, out=out) == 0, out.text()
    assert t.board.in_repl
    assert "board says: entering repl" in out
    assert "board prints: >>>" in out
    assert out[-1] == "the board is at the REPL now; mpremote can take over"


def test_repl_when_main_py_doesnt_answer(monkeypatch):
    monkeypatch.setattr(repl, "HELLO_TIMEOUT", 0.3)
    out = Out()
    assert repl.repl(SilentTransport(), out=out) == repl.EXIT_NO_ANSWER
    assert "already at the >>> prompt" in out.text() and "BOOT" in out.text()


def test_repl_without_a_port():
    out = Out()
    assert repl.repl(MissingTransport(), out=out) == 1
    assert "can't open the port: no such port" in out.text()


# --- the command lines, as real processes ---------------------------------------


def tool(name, *args, env=None, timeout=20):
    return subprocess.run([sys.executable, "-m", f"hcl.tools.{name}", *args], capture_output=True, text=True,
                          timeout=timeout, env=(os.environ | (env or {})))


def test_monitor_cli():
    r = tool("monitor", "--url", "sim", "--seconds", "2.5", "--send")
    assert r.returncode == 0, r.stderr
    assert "board connected: firmware 0.0.0, simulated, 10 LEDs, GRB" in r.stdout
    assert "board prints: rst:0x1 (POWERON_RESET)" in r.stdout
    last = [line for line in r.stdout.splitlines() if " fps " in line][-1]
    assert "connected" in last and float(re.search(r"([\d.]+) fps", last).group(1)) > 10


def test_monitor_takes_the_url_from_dod_serial():
    r = tool("monitor", "--seconds", "0.5", env={"DOD_SERIAL": "sim?latency_ms=1"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("monitoring sim?latency_ms=1")


def test_monitor_stops_cleanly_on_ctrl_c():
    proc = subprocess.Popen([sys.executable, "-m", "hcl.tools.monitor", "--url", "sim"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().startswith("monitoring")
        time.sleep(1.2)
        proc.send_signal(signal.SIGINT)
        stdout, stderr = proc.communicate(timeout=5)
    finally:
        proc.kill()
    assert proc.returncode == 130
    assert "stopped" in stderr and "Traceback" not in stderr


def test_bench_cli():
    r = tool("bench", "--url", "sim?latency_ms=2", "--seconds", "1.5")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_pattern_cli():
    r = tool("pattern", "--url", "sim", "--speed", "40")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "strip: every LED RED" in r.stdout and r.stdout.rstrip().endswith("done")


def test_repl_cli():
    r = tool("repl", "--url", "sim")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "mpremote can take over" in r.stdout


@pytest.mark.parametrize("name", ["monitor", "pattern", "bench", "repl"])
def test_bad_url_is_a_usage_error(name):
    r = tool(name, "--url", "sim?nonsense=1")
    assert r.returncode == 2
    assert "error: unknown sim option 'nonsense'" in r.stderr
