# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - GremlinEx is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import annotations

import collections
import threading
from collections.abc import Callable, Iterator
from typing import Generic, TypeVar


T = TypeVar("T")
K = TypeVar("K")


class FastQueue(Generic[T]):
    """A small, thread-safe FIFO queue backed by :class:`collections.deque`"""

    __slots__ = ("name", "maxsize", "_queue", "_condition")

    class Full(Exception):
        """Raised when an item cannot be added because the queue is full."""

    class Empty(Exception):
        """Raised when an item cannot be retrieved because the queue is empty."""

    def __init__(self, maxsize: int = 0, name: str | None = None) -> None:
        if maxsize < 0:
            raise ValueError("maxsize must be non-negative")

        self.name = name
        self.maxsize = maxsize
        self._queue: collections.deque[T] = collections.deque()
        self._condition = threading.Condition()

    @staticmethod
    def _validate_timeout(timeout: float | None) -> None:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative")

    def _wait_for_item(self, block: bool, timeout: float | None) -> None:
        """Wait for an item. The condition lock must already be held."""
        self._validate_timeout(timeout)

        if self._queue:
            return
        if not block:
            raise self.Empty("Queue is empty") # @IgnoreException

        if not self._condition.wait_for(lambda: bool(self._queue), timeout):
            raise self.Empty("Queue is empty (timeout)")  # @IgnoreException

    def _wait_for_space(self, block: bool, timeout: float | None) -> None:
        """Wait for capacity. The condition lock must already be held."""
        self._validate_timeout(timeout)

        if self.maxsize <= 0 or len(self._queue) < self.maxsize:
            return
        if not block:
            raise self.Full("Queue is full")  # @IgnoreException

        if not self._condition.wait_for(
            lambda: len(self._queue) < self.maxsize,
            timeout,
        ):
            raise self.Full("Queue is full (timeout)")  # @IgnoreException

    def _notify_producer(self) -> None:
        if self.maxsize > 0:
            self._condition.notify()

    def _notify_all_producers(self) -> None:
        if self.maxsize > 0:
            self._condition.notify_all()

    def put(self, item: T, block: bool = True, timeout: float | None = None) -> bool:
        with self._condition:
            self._wait_for_space(block, timeout)
            self._queue.append(item)
            self._condition.notify()
        return True

    def put_nowait(self, item: T) -> bool:
        return self.put(item, block=False)

    def putleft(self, item: T, block: bool = True, timeout: float | None = None) -> bool:
        with self._condition:
            self._wait_for_space(block, timeout)
            self._queue.appendleft(item)
            self._condition.notify()
        return True

    def put_coalesce(
        self,
        item: T,
        key_fn: Callable[[T], K | None] | None,
        block: bool = True,
        timeout: float | None = None,
    ) -> bool:
        """Replace a queued item with the same key, or append a new item.

        Replacement is attempted before waiting for capacity. This is both
        faster under load and allows coalescing when the queue is already full.
        """
        key = key_fn(item) if key_fn is not None else None

        with self._condition:
            if key is not None:
                for index, existing in enumerate(self._queue):
                    try:
                        if key_fn(existing) == key:  # type: ignore[misc]
                            self._queue[index] = item
                            return True
                    except Exception:
                        continue

            self._wait_for_space(block, timeout)

            # Another producer may have inserted this key while this producer
            # was waiting for capacity, so check once more before appending.
            if key is not None:
                for index, existing in enumerate(self._queue):
                    try:
                        if key_fn(existing) == key:  # type: ignore[misc]
                            self._queue[index] = item
                            return True
                    except Exception:
                        continue

            self._queue.append(item)
            self._condition.notify()
        return True

    def get(self, block: bool = True, timeout: float | None = None) -> T:
        with self._condition:
            self._wait_for_item(block, timeout)
            item = self._queue.popleft()
            self._notify_producer()
            return item

    def get_nowait(self) -> T:
        return self.get(block=False)

    def pop(self, block: bool = True, timeout: float | None = None) -> T:
        with self._condition:
            self._wait_for_item(block, timeout)
            item = self._queue.pop()
            self._notify_producer()
            return item

    def popback(self, block: bool = True, timeout: float | None = None) -> T:
        return self.pop(block, timeout)

    def popleft(self, block: bool = True, timeout: float | None = None) -> T:
        return self.get(block, timeout)

    def getbatch(
        self,
        max_batch_size: int,
        block: bool = True,
        timeout: float | None = None,
    ) -> list[T]:
        if max_batch_size <= 0:
            return []

        with self._condition:
            self._wait_for_item(block, timeout)
            count = min(max_batch_size, len(self._queue))
            items = [self._queue.popleft() for _ in range(count)]
            self._notify_all_producers()
            return items

    def getall(self, block: bool = True, timeout: float | None = None) -> list[T]:
        with self._condition:
            self._wait_for_item(block, timeout)
            items = list(self._queue)
            self._queue.clear()
            self._notify_all_producers()
            return items

    def empty(self) -> bool:
        """Return True when there are no queued items."""
        with self._condition:
            return not bool(self._queue)

    def getNowait(self) -> list[T]:
        """Compatibility helper: remove all currently queued items."""
        with self._condition:
            if not self._queue:
                return []
            items = list(self._queue)
            self._queue.clear()
            self._notify_all_producers()
            return items

    def remove(self, item: T, fail_on_missing: bool = False) -> bool:
        with self._condition:
            try:
                self._queue.remove(item)
            except ValueError:
                if fail_on_missing:
                    raise ValueError("item not in queue") from None
                return False
            self._notify_producer()
            return True

    def remove_callback(self, callback: Callable[[T], bool]) -> bool:
        with self._condition:
            original_size = len(self._queue)
            if not original_size:
                return False

            retained = collections.deque(
                item for item in self._queue if not callback(item)
            )
            if len(retained) == original_size:
                return False

            self._queue = retained
            self._notify_all_producers()
            return True

    def removeCallback(self, callback: Callable[[T], bool]) -> bool:
        return self.remove_callback(callback)

    def clear(self) -> None:
        with self._condition:
            if self._queue:
                self._queue.clear()
                self._notify_all_producers()

    def append(self, item: T) -> bool:
        return self.put(item)

    def appendleft(self, item: T) -> bool:
        return self.putleft(item)

    def push(self, item: T) -> bool:
        return self.put(item)

    def all_tasks_done(self) -> bool:
        """Compatibility helper; reports whether the queue is currently empty."""
        return self.empty()

    def qsize(self) -> int:
        with self._condition:
            return len(self._queue)

    def empty(self) -> bool:
        with self._condition:
            return not self._queue

    def full(self) -> bool:
        with self._condition:
            return self.maxsize > 0 and len(self._queue) >= self.maxsize

    def snapshot(self) -> list[T]:
        with self._condition:
            return list(self._queue)

    @property
    def items(self) -> list[T]:
        return self.snapshot()

    @property
    def __items__(self) -> list[T]:
        return self.snapshot()

    def __len__(self) -> int:
        return self.qsize()

    def __contains__(self, item: object) -> bool:
        with self._condition:
            return item in self._queue

    def __iter__(self) -> Iterator[T]:
        return iter(self.snapshot())

    def __bool__(self) -> bool:
        return not self.empty()

    def __repr__(self) -> str:
        with self._condition:
            return (
                f"{type(self).__name__}(maxsize={self.maxsize}, "
                f"items={list(self._queue)!r})"
            )

