import threading
import time

import pytest


@pytest.fixture(autouse=True)
def no_leftover_io_threads():
    """Every test must stop the links it started (docs/plans/hcl.md, step 5)."""
    yield
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        left = [t for t in threading.enumerate() if t.name == "hcl-io" and t.is_alive()]
        if not left:
            return
        time.sleep(0.01)
    pytest.fail(f"I/O threads still running after the test: {left}")
