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
            raise self.Empty("Queue is empty")

        if not self._condition.wait_for(lambda: bool(self._queue), timeout):
            raise self.Empty("Queue is empty (timeout)")

    def _wait_for_space(self, block: bool, timeout: float | None) -> None:
        """Wait for capacity. The condition lock must already be held."""
        self._validate_timeout(timeout)

        if self.maxsize <= 0 or len(self._queue) < self.maxsize:
            return
        if not block:
            raise self.Full("Queue is full")

        if not self._condition.wait_for(
            lambda: len(self._queue) < self.maxsize,
            timeout,
        ):
            raise self.Full("Queue is full (timeout)")

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




# class FastQueueOld:
#     """ custom fast queue for high-performance hook handling """

#     class Full(Exception):
#         """Exception raised by put() when queue is full."""
#         pass

#     class Empty(Exception):
#         """Exception raised by get() when queue is empty."""
#         pass

#     def __init__(self, maxsize: int = 0):
#         self.maxsize = maxsize
#         self._queue = collections.deque()
#         self._condition = threading.Condition()

#     def put(self, item, block: bool = True, timeout: float = None) -> bool:
#         """Add an item to the queue.

#         Returns True if successful, raises FastQueue.Full exception if space is unavailable.
#         """
#         with self._condition:
#             if self.maxsize > 0:
#                 if not block:
#                     if len(self._queue) >= self.maxsize:
#                         raise FastQueue.Full("Queue is full")
#                 else:
#                     # Wait until space opens up or timeout expires
#                     end_time = time.time() + timeout if timeout is not None else 0
#                     while len(self._queue) >= self.maxsize:
#                         if timeout is not None:
#                             remaining = end_time - time.time()
#                             if remaining <= 0:
#                                 raise FastQueue.Full("Queue is full (timeout)")
#                             self._condition.wait(remaining)
#                         else:
#                             self._condition.wait()

#             self._queue.append(item)
#             self._condition.notify()  # Awaken waiting consumers
#             return True


#     def get(self, block: bool = True, timeout: float = None):
#         """Remove and return an item from the queue.

#         Raises FastQueue.Empty exception if data is unavailable.
#         """
#         with self._condition:
#             if not block:
#                 if not self._queue:
#                     raise FastQueue.Empty("Queue is empty")
#             else:
#                 # Wait until data arrives or timeout expires
#                 end_time = time.time() + timeout if timeout is not None else 0
#                 while not self._queue:
#                     if timeout is not None:
#                         remaining = end_time - time.time()
#                         if remaining <= 0:
#                             raise FastQueue.Empty("Queue is empty (timeout)")
#                         self._condition.wait(remaining)
#                     else:
#                         self._condition.wait()

#             item = self._queue.popleft()
#             self._condition.notify()  # Awaken waiting producers
#             return item

#     def append(self, item : Any):
#         """Alias for put() to maintain compatibility with list-like behavior."""
#         return self.put(item)

#     def push(self, item : Any):
#         """Alias for put() to maintain compatibility with stack-like behavior."""
#         return self.put(item)

#     def pop(self, block: bool = True, timeout: float = None):
#         """Remove and return an item from the front of the queue.

#         Raises FastQueue.Empty exception if data is unavailable.
#         """
#         return self.get(block, timeout)

#     def popleft(self, block: bool = True, timeout: float = None):
#         """Remove and return an item from the front of the queue.

#         Raises FastQueue.Empty exception if data is unavailable.
#         """
#         return self.get(block, timeout)

#     def popback(self, block: bool = True, timeout: float = None):
#         """Remove and return an item from the back of the queue.

#         Raises FastQueue.Empty exception if data is unavailable.
#         """
#         with self._condition:
#             if not block:
#                 if not self._queue:
#                     raise FastQueue.Empty("Queue is empty")
#             else:
#                 # Wait until data arrives or timeout expires
#                 end_time = time.time() + timeout if timeout is not None else 0
#                 while not self._queue:
#                     if timeout is not None:
#                         remaining = end_time - time.time()
#                         if remaining <= 0:
#                             raise FastQueue.Empty("Queue is empty (timeout)")
#                         self._condition.wait(remaining)
#                     else:
#                         self._condition.wait()

#             item = self._queue.pop()
#             self._condition.notify()  # Awaken waiting producers
#             return item


#     def getbatch(self, max_batch_size: int, block: bool = True, timeout: float | None = None) -> list[Any]:
#         """Remove and return up to max_batch_size queued items."""

#         if max_batch_size <= 0:
#             return []

#         if timeout is not None and timeout < 0:
#             raise ValueError("timeout must be non-negative")

#         condition = self._condition
#         queue = self._queue

#         with condition:
#             if not block:
#                 if not queue:
#                     raise self.Empty("Queue is empty")

#             elif timeout is None:
#                 while not queue:
#                     condition.wait()

#             elif not condition.wait_for(lambda: bool(queue), timeout):
#                 raise self.Empty("Queue is empty (timeout)")

#             batch_size = min(max_batch_size, len(queue))
#             batch = [queue.popleft() for _ in range(batch_size)]

#             condition.notify_all()
#             return batch

#     def getall(self, block: bool = True, timeout: float | None = None) -> list:
#         """Remove and return all currently queued items.

#         When block is True, wait until at least one item is available.
#         Raises FastQueue.Empty if no data becomes available.
#         """
#         if timeout is not None and timeout < 0:
#             raise ValueError("timeout must be non-negative")

#         with self._condition:
#             if not block:
#                 if not self._queue:
#                     raise self.Empty("Queue is empty")

#             elif timeout is None:
#                 while not self._queue:
#                     self._condition.wait()

#             else:
#                 available = self._condition.wait_for(
#                     lambda: bool(self._queue),
#                     timeout=timeout,
#                 )
#                 if not available:
#                     raise self.Empty("Queue is empty (timeout)")

#             items = list(self._queue)
#             self._queue.clear()

#             # Multiple producers may now be able to add items.
#             self._condition.notify_all()

#             return items

#     def qsize(self) -> int:
#         """Return the approximate size of the queue."""
#         with self._condition:
#             return len(self._queue)

#     def remove(self, item: Any, failOnMissing: bool = False) -> bool:
#         """Remove the first occurrence of an item from the queue.

#         Raises ValueError if the item is not present.
#         Awakens waiting producers since space has freed up.

#         :returns: True if the item was removed, False if not found, or exception
#         """
#         with self._condition:
#             try:
#                 # deque.remove() is optimized in C, but shifts memory under the hood
#                 self._queue.remove(item)
#                 result = True
#             except ValueError:
#                 if failOnMissing:
#                     raise ValueError("item not in queue")
#                 result = False

#             # Notify any blocked producers that a slot has opened up
#             self._condition.notify()
#         return result

#     def removeCallback(self, callback: Callable[[Any], None]):
#         """ remove items based on a callback - the callback gets the item and returns true if the item should be removed """
#         result = False
#         with self._condition:
#             for item in self._queue:
#                 if callback(item):
#                     # deque.remove() is optimized in C, but shifts memory under the hood
#                     self._queue.remove(item)
#                     result = True

#                 # Notify any blocked producers that a slot has opened up
#             if result:
#                 self._condition.notify()
#         return result


#     def clear(self):
#         """Clear all items from the queue."""
#         with self._condition:
#             self._queue.clear()
#             self._condition.notify_all()  # Notify all waiting threads

#     @property
#     def __items__(self) -> List[Any]:
#         """Return a point-in-time snapshot list of all items currently in the queue."""
#         with self._condition:
#             return list(self._queue)

#     def __len__(self) -> int:
#         """Return the current size of the queue using len()."""
#         with self._condition:
#             return len(self._queue)

#     def __contains__(self, item: Any) -> bool:
#         """Check if an item exists in the queue using the 'in' operator."""
#         with self._condition:
#             return item in self._queue

#     def __iter__(self):
#         """Return a snapshot iterator over the current items without holding the lock."""
#         return iter(self.__items__)


#     def empty(self) -> bool:
#         """Return True if the queue is empty, False otherwise."""
#         with self._condition:
#             return not self._queue

#     def full(self) -> bool:
#         """Return True if the queue is full, False otherwise."""
#         with self._condition:
#             return self.maxsize > 0 and len(self._queue) >= self.maxsize

# T = TypeVar("T")


# class FastQueue(Generic[T]):
#     """Thread-safe queue with deque-compatible helper methods."""

#     class Full(Exception):
#         """Raised when an item cannot be added because the queue is full."""

#     class Empty(Exception):
#         """Raised when an item cannot be retrieved because the queue is empty."""

#     def __init__(self, maxsize: int = 0, name: str = None) -> None:
#         if maxsize < 0:
#             raise ValueError("maxsize must be non-negative")
#         self.name = name
#         self.maxsize = maxsize
#         self._queue: collections.deque[T] = collections.deque()
#         self._condition = threading.Condition()

#     def _wait_for_item(self, block: bool, timeout: float | None) -> bool:
#         """Wait until an item is available.

#         The condition lock must already be held.
#         """
#         if __debug__ and timeout is not None and timeout < 0:
#             raise ValueError("timeout must be non-negative")

#         if self._queue:
#             return True

#         if not block:
#             raise self.Empty("Queue is empty")

#         if timeout is None:
#             while not self._queue:
#                 self._condition.wait()
#                 time.sleep(0)  # yield to other threads
#             return

#         available = self._condition.wait_for(
#             lambda: bool(self._queue),
#             timeout=timeout,
#         )

#         if not available:
#             raise self.Empty("Queue is empty (timeout)")

#     def _wait_for_space(self, block: bool, timeout: float | None) -> None:
#         """Wait until queue space is available.

#         The condition lock must already be held.
#         """
#         if timeout is not None and timeout < 0:
#             raise ValueError("timeout must be non-negative")

#         if self.maxsize <= 0 or len(self._queue) < self.maxsize:
#             return

#         if not block:
#             raise self.Full("Queue is full")

#         if timeout is None:
#             while len(self._queue) >= self.maxsize:
#                 self._condition.wait()
#             return

#         available = self._condition.wait_for(
#             lambda: len(self._queue) < self.maxsize,
#             timeout=timeout,
#         )

#         if not available:
#             raise self.Full("Queue is full (timeout)")

#     def put(self, item: T, block: bool = True, timeout: float | None = None) -> bool:
#         """Add an item to the back of the queue."""

#         with self._condition:
#             self._wait_for_space(block, timeout)
#             self._queue.append(item)

#             # Wake one waiting consumer.
#             self._condition.notify()

#         return True

#     def put_coalesce(self, item: T, key_fn, block: bool = True, timeout: float | None = None) -> bool:
#         """Replace the queued item with the same key, otherwise append.

#         Axis HID can outrun mapping. Keeping one pending sample per axis
#         avoids replaying a second of stick history into vJoy.
#         """
#         key = key_fn(item) if key_fn is not None else None
#         with self._condition:
#             self._wait_for_space(block, timeout)
#             if key is not None:
#                 for index, existing in enumerate(self._queue):
#                     try:
#                         if key_fn(existing) == key:
#                             self._queue[index] = item
#                             self._condition.notify()
#                             return True
#                     except Exception:
#                         continue
#             self._queue.append(item)
#             self._condition.notify()
#         return True

#     def putleft(self, item: T, block: bool = True, timeout: float | None = None) -> bool:
#         """Add an item to the front of the queue."""

#         with self._condition:
#             self._wait_for_space(block, timeout)
#             self._queue.appendleft(item)
#             self._condition.notify()

#         return True

#     def get(self, block: bool = True, timeout: float | None = None) -> T:
#         """Remove and return the first item."""

#         with self._condition:
#             self._wait_for_item(block, timeout)
#             item = self._queue.popleft()

#             # Wake one waiting producer.
#             self._condition.notify()

#             return item

#     def all_tasks_done(self) -> bool:
#         """Check if all tasks in the queue are done."""
#         with self._condition:
#             return not self._queue

#     def getNowait(self) -> list[T]:
#         """Remove and return all items currently in the queue without blocking."""

#         with self._condition:
#             if not self._queue:
#                 return []

#             items = list(self._queue)
#             self._queue.clear()

#             self._condition.notify_all()
#             return items

#     def get_nowait(self) -> T:
#         """Remove and return the first item without blocking."""

#         return self.get(block=False)

#     def put_nowait(self, item: T) -> bool:
#         """Add an item without blocking."""

#         return self.put(item, block=False)

#     def append(self, item: T) -> bool:
#         """Add an item to the back of the queue."""

#         return self.put(item)

#     def appendleft(self, item: T) -> bool:
#         """Add an item to the front of the queue."""

#         return self.putleft(item)

#     def push(self, item: T) -> bool:
#         """Add an item to the back of the queue."""

#         return self.put(item)

#     def pop(self, block: bool = True, timeout: float | None = None) -> T:
#         """Remove and return the last item."""

#         with self._condition:
#             self._wait_for_item(block, timeout)
#             item = self._queue.pop()
#             self._condition.notify()
#             return item

#     def popback(self, block: bool = True, timeout: float | None = None) -> T:
#         """Alias for pop()."""

#         return self.pop(block, timeout)

#     def popleft(self, block: bool = True, timeout: float | None = None) -> T:
#         """Remove and return the first item."""

#         return self.get(block, timeout)

#     def getbatch(self, max_batch_size: int, block: bool = True, timeout: float | None = None) -> list[T]:
#         """Remove and return up to max_batch_size items from the front."""

#         if max_batch_size <= 0:
#             return []

#         with self._condition:
#             self._wait_for_item(block, timeout)

#             batch_size = min(max_batch_size, len(self._queue))
#             batch = [self._queue.popleft() for _ in range(batch_size)]

#             # Multiple producers may now be able to continue.
#             self._condition.notify_all()

#             return batch

#     def getall(self, block: bool = True, timeout: float | None = None) -> list[T]:
#         """Remove and return all currently queued items."""

#         with self._condition:
#             self._wait_for_item(block, timeout)

#             items = list(self._queue)
#             self._queue.clear()

#             self._condition.notify_all()
#             return items

#     def remove(self, item: T, fail_on_missing: bool = False) -> bool:
#         """Remove the first occurrence of item."""

#         with self._condition:
#             try:
#                 self._queue.remove(item)
#             except ValueError:
#                 if fail_on_missing:
#                     raise ValueError("item not in queue") from None
#                 return False

#             self._condition.notify()
#             return True

#     def remove_callback(self, callback: Callable[[T], bool]) -> bool:
#         """Remove all items for which callback(item) returns True."""

#         with self._condition:
#             original_size = len(self._queue)

#             if original_size == 0:
#                 return False

#             retained: collections.deque[T] = collections.deque()

#             for item in self._queue:
#                 if not callback(item):
#                     retained.append(item)

#             removed_count = original_size - len(retained)

#             if removed_count == 0:
#                 return False

#             self._queue = retained

#             if removed_count == 1:
#                 self._condition.notify()
#             else:
#                 self._condition.notify_all()

#             return True

#     def removeCallback(self, callback: Callable[[T], bool]) -> bool:
#         """Compatibility alias for remove_callback()."""

#         return self.remove_callback(callback)

#     def clear(self) -> None:
#         """Remove all items from the queue."""

#         with self._condition:
#             if not self._queue:
#                 return

#             self._queue.clear()
#             self._condition.notify_all()

#     def qsize(self) -> int:
#         """Return the current queue size."""

#         with self._condition:
#             return len(self._queue)

#     def empty(self) -> bool:
#         """Return True when the queue is empty."""

#         with self._condition:
#             return not self._queue

#     def full(self) -> bool:
#         """Return True when the bounded queue is full."""

#         with self._condition:
#             return self.maxsize > 0 and len(self._queue) >= self.maxsize

#     def snapshot(self) -> list[T]:
#         """Return a point-in-time list of queued items."""

#         with self._condition:
#             return list(self._queue)

#     @property
#     def items(self) -> list[T]:
#         """Return a point-in-time list of queued items."""

#         return self.snapshot()

#     @property
#     def __items__(self) -> list[T]:
#         """Compatibility property returning a queue snapshot."""

#         return self.snapshot()

#     def __len__(self) -> int:
#         with self._condition:
#             return len(self._queue)

#     def __contains__(self, item: object) -> bool:
#         with self._condition:
#             return item in self._queue

#     def __iter__(self) -> Iterator[T]:
#         """Iterate over a snapshot without holding the queue lock."""
#         return iter(self.snapshot())

#     def __bool__(self) -> bool:
#         return not self.empty()

#     def __repr__(self) -> str:
#         with self._condition:
#             return f"{type(self).__name__}(maxsize={self.maxsize}, items={list(self._queue)!r})"
