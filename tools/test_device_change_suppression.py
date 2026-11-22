# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Hardware-free DirectInput change batching checks.

Run: python tools/test_device_change_suppression.py
"""

import ast
from pathlib import Path
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock


class ControlledTimer:
    def __init__(self, interval, callback, args=()):
        self.callback, self.args = callback, args
        self.cancelled = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        # Also exercise an expired callback racing with cancel().
        self.callback(*self.args)


def listener_fixture():
    source = Path(__file__).resolve().parents[1] / "gremlin/event_handler.py"
    tree = ast.parse(source.read_bytes())
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EventListener")
    names = {"pushDeviceChangeSuppression", "popDeviceChangeSuppression", "deferDeviceChanges",
             "_queue_device_change_locked", "_dinput_device_change_handler", "_run_device_list_update",
             "_process_device_change_cb"}
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in names]
    cls = ast.ClassDef(name="Listener", bases=[], keywords=[], body=methods, decorator_list=[])
    reset = Mock()
    namespace = dict(threading=threading, Timer=ControlledTimer,
                     gremlin=NS(shared_state=NS(is_running=False, has_device_changes=False),
                                joystick_handling=NS(reset_devices=reset)))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(source), "exec"), namespace)
    listener = namespace["Listener"]()
    listener._device_update_timer = None
    listener._device_change_suppressed = 0
    listener._device_change_pending = False
    listener._device_change_generation = 0
    listener._device_change_state_lock = threading.Lock()
    listener._process_device_change_lock = threading.Lock()
    listener.device_change_event = NS(emit=Mock())
    listener._process_device_change = NS(emit=listener._process_device_change_cb)
    reset.side_effect = lambda **kwargs: listener.device_change_event.emit()
    listener.reset_devices = reset
    return listener


class DeviceChangeSuppressionChecks(unittest.TestCase):
    def setUp(self):
        self.listener = listener_fixture()
        self.device = NS(vendor_id=1, product_id=1, button_count=128, name=b"gex-1")

    def changed(self):
        self.listener._dinput_device_change_handler(self.device, 1)

    def test_four_creations_produce_one_update_after_the_outer_request(self):
        self.listener.pushDeviceChangeSuppression()
        for _ in range(4):
            self.changed()
        self.assertIsNone(self.listener._device_update_timer)
        self.listener.reset_devices.assert_not_called()
        self.listener.device_change_event.emit.assert_not_called()
        self.listener.popDeviceChangeSuppression()
        self.listener._device_update_timer.fire()
        self.listener.reset_devices.assert_called_once_with(force=False)
        self.listener.device_change_event.emit.assert_called_once_with()

    def test_nested_requests_do_not_resume_changes_early(self):
        self.listener.pushDeviceChangeSuppression()
        self.listener.pushDeviceChangeSuppression()
        self.changed()
        self.listener.popDeviceChangeSuppression()
        self.assertIsNone(self.listener._device_update_timer)
        self.listener.popDeviceChangeSuppression()
        self.listener._device_update_timer.fire()
        self.listener.reset_devices.assert_called_once()

    def test_suppression_cancels_and_replays_a_previously_scheduled_update(self):
        self.changed()
        stale = self.listener._device_update_timer
        self.listener.pushDeviceChangeSuppression()
        self.assertTrue(stale.cancelled)
        stale.fire()
        self.listener.reset_devices.assert_not_called()
        self.listener.popDeviceChangeSuppression()
        stale.fire()
        self.listener.reset_devices.assert_not_called()
        self.listener._device_update_timer.fire()
        self.listener.reset_devices.assert_called_once()

    def test_already_queued_processing_is_deferred(self):
        self.listener.pushDeviceChangeSuppression()
        self.listener._process_device_change_cb()
        self.listener._run_device_list_update()
        self.listener.reset_devices.assert_not_called()
        self.listener.popDeviceChangeSuppression()
        self.listener._device_update_timer.fire()
        self.listener.reset_devices.assert_called_once()

    def test_native_callback_does_not_wait_for_registry_consumers(self):
        registry_lock = threading.Lock()
        finished = threading.Event()

        def consumer():
            with registry_lock:
                pass

        self.listener.device_change_event.emit.side_effect = consumer

        def native_callback():
            try:
                self.changed()
            finally:
                finished.set()

        with registry_lock:
            worker = threading.Thread(target=native_callback)
            worker.start()
            returned = finished.wait(0.5)
        worker.join(timeout=1)
        self.assertTrue(returned, "Native device callback waited for the registry lock")
        self.listener.device_change_event.emit.assert_not_called()
        self.listener._device_update_timer.fire()
        self.listener.reset_devices.assert_called_once()

    def test_changes_during_a_rebuild_are_retried_after_it_finishes(self):
        with self.listener._process_device_change_lock:
            self.listener._process_device_change_cb()
        self.listener.reset_devices.assert_not_called()
        self.listener._device_update_timer.fire()
        self.listener.reset_devices.assert_called_once()

    def test_unrelated_hotplug_changes_are_still_debounced(self):
        self.changed()
        previous = self.listener._device_update_timer
        self.changed()
        self.assertTrue(previous.cancelled)
        previous.fire()
        self.listener.reset_devices.assert_not_called()
        self.listener._device_update_timer.fire()
        self.listener.reset_devices.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
