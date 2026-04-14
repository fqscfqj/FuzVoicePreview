from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LruCache(Generic[K, V]):
    def __init__(self, *, max_entries: int):
        self._max_entries = max(1, int(max_entries))
        self._items: OrderedDict[K, V] = OrderedDict()
        self._lock = RLock()

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def get(self, key: K) -> V | None:
        with self._lock:
            value = self._items.get(key)
            if value is None:
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key: K, value: V) -> V:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._max_entries:
                self._items.popitem(last=False)
            return value
