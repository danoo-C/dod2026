"""The background tasks' supervisor (docs/backend.md 4.2): a task that crashes
is logged and restarted after a second; it never takes the others down."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

RESTART_SECONDS = 1.0


class Supervisor:
    def __init__(self, restart_seconds: float = RESTART_SECONDS) -> None:
        self._restart = restart_seconds
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self.restarts: dict[str, int] = {}

    def start(self, name: str, run: Callable[[], Awaitable[None]]) -> None:
        """Run `run()` as a task, again and again if it crashes or ends."""
        if name in self._tasks:
            raise ValueError(f"a task called {name!r} is already running")
        self.restarts[name] = 0
        self._tasks[name] = asyncio.create_task(self._guard(name, run), name=name)

    async def _guard(self, name: str, run: Callable[[], Awaitable[None]]) -> None:
        while True:
            try:
                await run()
                log.warning("task %s ended; restarting it in %.0f s", name, self._restart)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("task %s crashed; restarting it in %.0f s", name, self._restart)
            self.restarts[name] += 1
            await asyncio.sleep(self._restart)

    @property
    def running(self) -> list[str]:
        return [name for name, task in self._tasks.items() if not task.done()]

    async def stop(self) -> None:
        """Cancel every task and wait until they are gone."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
