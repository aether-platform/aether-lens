import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable, List, Optional


class EventTransport(ABC):
    """Abstract base class for event transports."""

    @abstractmethod
    async def emit(self, event: Any):
        pass


class JSONLinesTransport(EventTransport):
    """Transport that outputs events as JSON Lines to stdout."""

    async def emit(self, event: Any):
        if hasattr(event, "to_json"):
            line = event.to_json()
        else:
            import json

            line = json.dumps(event)
        print(line, flush=True)


class CallbackTransport(EventTransport):
    """Transport that proxies events to a callback function."""

    def __init__(self, callback: Callable):
        self.callback = callback

    async def emit(self, event: Any):
        if asyncio.iscoroutinefunction(self.callback):
            await self.callback(event)
        else:
            self.callback(event)


class EventEmitter:
    """Orchestrates event emission across multiple abstracted transports."""

    def __init__(self, transports: Optional[List[EventTransport]] = None):
        self.transports = transports or []

    def add_transport(self, transport: EventTransport):
        self.transports.append(transport)

    def emit(self, event: Any):
        """
        Emits an event to all registered transports.
        Spawns asyncio tasks for each transport's emit method.
        """
        for transport in self.transports:
            # We use create_task to ensure non-blocking emission
            # especially when called from within the pipeline
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(transport.emit(event))
            except RuntimeError:
                # Fallback for sync contexts if no loop is running
                # (Though the pipeline is primarily async)
                pass
