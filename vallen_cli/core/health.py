"""VALLEN CLI — Provider health monitoring with background polling.

Polls the active provider every N seconds and notifies the TUI
via a callback when status changes (connected → offline, offline → connected).
"""

from __future__ import annotations

import asyncio
from typing import Callable, Any

from ..providers.base import ProviderStatus
from ..providers.registry import get_registry

# How often to poll (seconds)
POLL_INTERVAL = 15.0
# On reconnect, poll faster
RECONNECT_INTERVAL = 5.0
# Max retries before giving up and polling slowly
MAX_FAST_RETRIES = 6


class HealthMonitor:
    """Background task that polls the active provider and fires callbacks."""

    def __init__(self) -> None:
        self._status: ProviderStatus = ProviderStatus.UNKNOWN
        self._task: asyncio.Task | None = None
        self._callbacks: list[Callable[[ProviderStatus], Any]] = []
        self._running = False

    def on_status_change(self, callback: Callable[[ProviderStatus], Any]) -> None:
        """Register a callback fired when status changes."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[ProviderStatus], Any]) -> None:
        self._callbacks = [c for c in self._callbacks if c is not callback]

    @property
    def status(self) -> ProviderStatus:
        return self._status

    def start(self) -> None:
        """Start background polling."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._poll_loop())

    def stop(self) -> None:
        """Stop background polling."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def check_now(self) -> ProviderStatus:
        """Immediate one-shot health check."""
        registry = get_registry()
        new_status = await registry.check_active()
        self._update_status(new_status)
        return new_status

    def _update_status(self, new_status: ProviderStatus) -> None:
        if new_status != self._status:
            self._status = new_status
            for cb in self._callbacks:
                try:
                    result = cb(new_status)
                    # If callback returns a coroutine, schedule it
                    if asyncio.iscoroutine(result):
                        asyncio.ensure_future(result)
                except Exception:
                    pass

    async def _poll_loop(self) -> None:
        registry = get_registry()
        fast_retries = 0

        while self._running:
            try:
                new_status = await registry.check_active()
                prev = self._status
                self._update_status(new_status)

                # Adjust polling interval based on state
                if new_status == ProviderStatus.OFFLINE:
                    # Poll faster when offline to detect reconnect
                    fast_retries = min(fast_retries + 1, MAX_FAST_RETRIES)
                    interval = RECONNECT_INTERVAL
                elif new_status == ProviderStatus.CONNECTED and prev != ProviderStatus.CONNECTED:
                    # Just reconnected — stay fast for one cycle
                    fast_retries = 0
                    interval = RECONNECT_INTERVAL
                else:
                    fast_retries = 0
                    interval = POLL_INTERVAL

            except asyncio.CancelledError:
                break
            except Exception:
                interval = POLL_INTERVAL

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break


# Singleton
_monitor: HealthMonitor | None = None


def get_health_monitor() -> HealthMonitor:
    global _monitor
    if _monitor is None:
        _monitor = HealthMonitor()
    return _monitor
