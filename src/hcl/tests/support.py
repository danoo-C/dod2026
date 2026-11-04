"""Helpers shared by the async tests (test_link, test_serial)."""

import asyncio
import functools
import time

import pytest

from hcl.testing import FAST  # shortened timings, so tests stay fast

__all__ = ["FAST", "run", "until", "next_of"]


def run(test):
    """Run an async test body in a plain test function, with an overall time limit.
    (No pytest plugin needed for async tests.) functools.wraps keeps the test's
    signature visible, so pytest still passes fixtures like monkeypatch."""
    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        asyncio.run(asyncio.wait_for(test(*args, **kwargs), timeout=9))
    return wrapper


async def until(cond, timeout=3.0, what="condition"):
    """Wait for cond() with a deadline, instead of sleeping a fixed time."""
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        await asyncio.sleep(0.005)


async def next_of(stream, kind, timeout=3.0):
    """The next event of the given type, skipping others."""
    async def find():
        async for event in stream:
            if isinstance(event, kind):
                return event
        pytest.fail(f"stream ended before a {kind.__name__}")
    return await asyncio.wait_for(find(), timeout)
