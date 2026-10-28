"""FastQueue API and concurrency checks: python tools/test_fastqueue.py."""

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.fastqueue import FastQueue  # noqa: E402


class FastQueueChecks(unittest.TestCase):
    def setUp(self):
        self.threads = []
        self.errors = []
        self.addCleanup(self.finish_threads)

    def spawn(self, callback):
        def run():
            try:
                callback()
            except BaseException as error:
                self.errors.append(error)

        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def finish_threads(self):
        for thread in self.threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive(), "queue worker did not finish")
        self.assertEqual(self.errors, [])

    def observe_wait(self, condition, ready):
        original_wait = condition.wait

        def wait(timeout=None):
            ready.release()
            return original_wait(timeout)

        return patch.object(condition, "wait", wait)

    def test_fifo_lifo_aliases_and_return_values(self):
        queue = FastQueue(name="test")
        self.assertEqual(queue.name, "test")
        for method, value in (("put", 2), ("append", 3), ("push", 4), ("putleft", 1), ("appendleft", 0)):
            self.assertTrue(getattr(queue, method)(value))
        self.assertEqual(queue.get(), 0)
        self.assertEqual(queue.popleft(), 1)
        self.assertEqual(queue.pop(), 4)
        self.assertEqual(queue.popback(), 3)
        self.assertEqual(queue.get_nowait(), 2)
        self.assertTrue(queue.all_tasks_done())

    def test_size_capacity_and_snapshots(self):
        with self.assertRaises(ValueError):
            FastQueue(-1)
        queue = FastQueue(2)
        self.assertFalse(queue)
        self.assertTrue(queue.empty())
        queue.put_nowait(1)
        snapshot, iterator = queue.snapshot(), iter(queue)
        queue.put(2)
        self.assertTrue(queue.full())
        self.assertEqual(len(queue), 2)
        self.assertEqual(queue.qsize(), 2)
        self.assertIn(2, queue)
        self.assertEqual(snapshot, [1])
        self.assertEqual(list(iterator), [1])
        self.assertEqual(queue.items, [1, 2])
        self.assertEqual(queue.__items__, [1, 2])
        self.assertIn("maxsize=2", repr(queue))
        self.assertFalse(FastQueue().full())

    def test_empty_and_full_nonblocking_operations(self):
        queue = FastQueue(1)
        for method, args in (("get", ()), ("pop", ()), ("getbatch", (2,)), ("getall", ())):
            with self.subTest(method=method), self.assertRaises(FastQueue.Empty):
                getattr(queue, method)(*args, block=False)
        with self.assertRaises(FastQueue.Empty):
            queue.get_nowait()
        self.assertEqual(queue.getNowait(), [])
        queue.put(1)
        for method in ("put", "putleft"):
            with self.subTest(method=method), self.assertRaises(FastQueue.Full):
                getattr(queue, method)(2, block=False)
        with self.assertRaises(FastQueue.Full):
            queue.put_nowait(2)

    def test_negative_timeouts_are_validated_with_data_or_space_available(self):
        for maxsize in (0, 1):
            queue = FastQueue(maxsize)
            for method in ("put", "putleft"):
                with self.subTest(maxsize=maxsize, method=method), self.assertRaises(ValueError):
                    getattr(queue, method)(1, timeout=-1)
            queue.put(1)
            for method, args in (("get", ()), ("pop", ()), ("getbatch", (1,)), ("getall", ())):
                with self.subTest(maxsize=maxsize, method=method), self.assertRaises(ValueError):
                    getattr(queue, method)(*args, timeout=-1)
            self.assertEqual(queue.snapshot(), [1])

    def test_zero_timeout_does_not_wait(self):
        queue = FastQueue(1)
        with self.assertRaises(FastQueue.Empty):
            queue.get(timeout=0)
        queue.put(1)
        with self.assertRaises(FastQueue.Full):
            queue.put(2, timeout=0)
        self.assertEqual(queue.get(timeout=0), 1)

    def test_full_and_partial_batch_drains(self):
        queue = FastQueue()
        self.assertEqual(queue.getbatch(0), [])
        self.assertEqual(queue.getbatch(-1), [])
        for value in range(7):
            queue.put(value)
        self.assertEqual(queue.getbatch(3), [0, 1, 2])
        self.assertEqual(queue.getbatch(10), [3, 4, 5, 6])
        queue.put(None)
        self.assertEqual(queue.getall(), [None])
        queue.put(8)
        self.assertEqual(queue.getNowait(), [8])

    def test_remove_and_callback_removal_preserve_order(self):
        queue = FastQueue()
        for value in range(6):
            queue.put(value)
        self.assertTrue(queue.remove(2))
        self.assertFalse(queue.remove(99))
        with self.assertRaises(ValueError):
            queue.remove(99, fail_on_missing=True)
        self.assertTrue(queue.removeCallback(lambda item: item % 2))
        self.assertEqual(queue.snapshot(), [0, 4])
        self.assertFalse(queue.remove_callback(lambda item: False))
        self.assertIsNone(queue.clear())
        self.assertTrue(queue.empty())

    def test_callback_exceptions_do_not_partially_remove_items(self):
        queue = FastQueue()
        for value in range(3):
            queue.put(value)

        def fail(item):
            if item == 1:
                raise RuntimeError("callback failed")
            return True

        with self.assertRaises(RuntimeError):
            queue.remove_callback(fail)
        self.assertEqual(queue.snapshot(), [0, 1, 2])
        with self.assertRaises(TypeError):
            queue.remove_callback(None)
        queue.clear()
        self.assertFalse(queue.remove_callback(None))

    def test_coalescing_keeps_first_slot_and_nonkeyed_items(self):
        queue = FastQueue()

        def key(item):
            return item[0] if isinstance(item, tuple) else None

        queue.put("button press")
        queue.put(("x", 1))
        queue.put(("y", 1))
        queue.put(("x", 2))
        queue.put("button release")
        queue.put_coalesce(("x", 3), key)
        self.assertEqual(queue.getall(), ["button press", ("x", 3), ("y", 1), ("x", 2), "button release"])

    def test_coalescing_replaces_when_full_and_rejects_unmatched_item(self):
        queue = FastQueue(1)
        queue.put(("x", 1))
        self.assertTrue(queue.put_coalesce(("x", 2), lambda item: item[0], block=False))
        with self.assertRaises(FastQueue.Full):
            queue.put_coalesce(("y", 1), lambda item: item[0], block=False)
        self.assertEqual(queue.get(), ("x", 2))
        queue.put_coalesce(1, None)
        self.assertEqual(queue.get(), 1)

    def test_coalescing_accepts_unhashable_keys_and_skips_bad_existing_keys(self):
        queue = FastQueue()
        queue.put("bad")
        queue.put((1, "old"))

        def key(item):
            if isinstance(item, str):
                raise ValueError("not a keyed item")
            return [item[0]]

        queue.put_coalesce((1, "new"), key)
        self.assertEqual(queue.snapshot(), ["bad", (1, "new")])
        with self.assertRaises(ValueError):
            queue.put_coalesce("bad new item", key)
        self.assertEqual(len(queue), 2)

    def test_coalescing_rescans_after_waiting_for_capacity(self):
        queue = FastQueue(2)
        queue.put(("old", 0))
        queue.put(("other", 0))
        ready = threading.Semaphore(0)
        with self.observe_wait(queue._not_full, ready):
            thread = self.spawn(lambda: queue.put_coalesce(("new", 1), lambda item: item[0], timeout=2))
            self.assertTrue(ready.acquire(timeout=1))
            with queue._condition:
                queue.get()
                queue.put(("new", 2))
                queue.get()
            thread.join(timeout=1)
        self.assertEqual(queue.getall(), [("new", 1)])

    def test_callbacks_can_reenter_queue_reads(self):
        queue = FastQueue()
        queue.put((1, "old"))

        def run():
            def key(item):
                self.assertEqual(queue.qsize(), 1)
                return item[0]

            queue.put_coalesce((1, "new"), key)
            queue.remove_callback(lambda item: bool(queue.snapshot()))

        self.spawn(run)

    def test_blocked_consumers_wake_for_all_insert_operations(self):
        for insertion in ("put", "putleft", "put_coalesce"):
            for removal, args in (("get", ()), ("pop", ()), ("getbatch", (3,)), ("getall", ())):
                with self.subTest(insertion=insertion, removal=removal):
                    queue = FastQueue()
                    ready = threading.Semaphore(0)
                    results = []
                    with self.observe_wait(queue._condition, ready):
                        thread = self.spawn(lambda: results.append(getattr(queue, removal)(*args, timeout=2)))
                        self.assertTrue(ready.acquire(timeout=1))
                        if insertion == "put_coalesce":
                            queue.put_coalesce(7, None)
                        else:
                            getattr(queue, insertion)(7)
                        thread.join(timeout=1)
                    self.assertEqual(results, [[7]] if removal in ("getbatch", "getall") else [7])

    def test_every_capacity_release_wakes_blocked_producer(self):
        removals = (
            lambda queue: queue.get(), lambda queue: queue.pop(),
            lambda queue: queue.getbatch(2), lambda queue: queue.getall(),
            lambda queue: queue.getNowait(), lambda queue: queue.remove(1),
            lambda queue: queue.remove_callback(lambda item: True), lambda queue: queue.clear(),
        )
        for index, remove in enumerate(removals):
            with self.subTest(removal=index):
                queue = FastQueue(1)
                queue.put(1)
                ready = threading.Semaphore(0)
                with self.observe_wait(queue._not_full, ready):
                    thread = self.spawn(lambda: queue.put(2, timeout=2))
                    self.assertTrue(ready.acquire(timeout=1))
                    remove(queue)
                    thread.join(timeout=1)
                self.assertEqual(queue.get_nowait(), 2)

    def test_bulk_drain_wakes_multiple_producers(self):
        queue = FastQueue(3)
        for value in range(3):
            queue.put(value)
        ready = threading.Semaphore(0)
        with self.observe_wait(queue._not_full, ready):
            threads = [self.spawn(lambda item=item: queue.put(item, timeout=2)) for item in range(3, 6)]
            for _ in threads:
                self.assertTrue(ready.acquire(timeout=1))
            self.assertEqual(queue.getall(), [0, 1, 2])
            for thread in threads:
                thread.join(timeout=1)
        self.assertEqual(sorted(queue.getall()), [3, 4, 5])

    def test_multiple_consumers_receive_all_inserted_items(self):
        queue = FastQueue()
        ready = threading.Semaphore(0)
        results = []
        with self.observe_wait(queue._condition, ready):
            threads = [self.spawn(lambda: results.append(queue.get(timeout=2))) for _ in range(5)]
            for _ in threads:
                self.assertTrue(ready.acquire(timeout=1))
            for value in range(5):
                queue.put(value)
            for thread in threads:
                thread.join(timeout=1)
        self.assertEqual(sorted(results), list(range(5)))

    def test_spurious_wake_does_not_return_empty_data(self):
        queue = FastQueue()
        ready = threading.Semaphore(0)
        results = []
        with self.observe_wait(queue._condition, ready):
            thread = self.spawn(lambda: results.append(queue.get(timeout=2)))
            self.assertTrue(ready.acquire(timeout=1))
            with queue._condition:
                queue._condition.notify_all()
            self.assertTrue(ready.acquire(timeout=1))
            self.assertEqual(results, [])
            queue.put(1)
            thread.join(timeout=1)
        self.assertEqual(results, [1])

    def test_wait_timeouts_leave_queue_usable(self):
        queue = FastQueue(1)
        with self.assertRaises(FastQueue.Empty):
            queue.get(timeout=0.01)
        queue.put(1)
        with self.assertRaises(FastQueue.Full):
            queue.put(2, timeout=0.01)
        self.assertEqual(queue.get(), 1)
        queue.put(3)
        self.assertEqual(queue.get(), 3)

    def test_multiple_producers_and_consumers_lose_no_items(self):
        for maxsize in (0, 7):
            with self.subTest(maxsize=maxsize):
                queue = FastQueue(maxsize)
                start = threading.Barrier(6)
                results = []

                def produce(producer):
                    start.wait(timeout=2)
                    for index in range(500):
                        queue.put((producer, index), timeout=2)

                def consume():
                    start.wait(timeout=2)
                    while True:
                        item = queue.get(timeout=2)
                        if item is None:
                            return
                        results.append(item)

                consumers = [self.spawn(consume) for _ in range(2)]
                producers = [self.spawn(lambda producer=producer: produce(producer)) for producer in range(4)]
                for thread in producers:
                    thread.join(timeout=3)
                    self.assertFalse(thread.is_alive())
                queue.put(None, timeout=2)
                queue.put(None, timeout=2)
                for thread in consumers:
                    thread.join(timeout=3)
                self.assertEqual(len(results), 2000)
                self.assertEqual(set(results), {(producer, index) for producer in range(4) for index in range(500)})
                self.assertTrue(queue.empty())


if __name__ == "__main__":
    unittest.main()
