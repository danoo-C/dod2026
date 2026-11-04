"""Helpers shared by the async tests. Same style as src/hcl/tests/support.py:
no pytest plugin, and waiting for conditions with a deadline instead of
sleeping a fixed time."""

import asyncio
import functools
import time

import pytest

__all__ = ["run", "until"]


def run(test):
    """Run an async test body in a plain test function, with an overall time limit.
    functools.wraps keeps the signature, so pytest still passes fixtures."""
    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        asyncio.run(asyncio.wait_for(test(*args, **kwargs), timeout=12))
    return wrapper


async def until(cond, timeout=3.0, what="condition"):
    """Wait for cond() with a deadline."""
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        await asyncio.sleep(0.005)
