# shared/events.py

from collections import defaultdict
from typing import Callable, Any


class EventBus:
    def __init__(self):
        self._subscribers = defaultdict(list)

    def subscribe(self, event_name: str, callback: Callable[[Any], None]):
        self._subscribers[event_name].append(callback)

    def emit(self, event_name: str, data=None):
        for callback in self._subscribers[event_name]:
            callback(data)
