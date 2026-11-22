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
import threading
import time

import gremlin.event_handler
import gremlin.shared_state
from gremlin.event_handler import Event, EventHandler
from gremlin.input_types import InputType
from gremlin.ui.octavi_device import OctaviButton, OctaviInterface


class DummyProfile:
    def get_parent_mode(self, mode):
        return {"Child": "Base", "Base": "Root"}.get(mode)


def test_matching_callbacks_walks_parent_mode_chain():
    handler = EventHandler()
    handler.process_callbacks = True
    device_guid = "test-device"
    event = Event(
        event_type=InputType.JoystickButton,
        identifier=1,
        device_guid=device_guid,
        is_pressed=True,
        value=True,
    )
    event.mode = "Child"

    callback = lambda e: None
    handler.callbacks[device_guid] = {"Root": {}, "Base": {}, "Child": {}}  # type: ignore[index]
    handler.callbacks[device_guid]["Base"][event.callbackKey] = [(callback, True)]

    previous_profile = gremlin.shared_state.current_profile
    gremlin.shared_state.current_profile = DummyProfile()
    try:
        assert handler._matching_callbacks(event, None) == [callback]
    finally:
        gremlin.shared_state.current_profile = previous_profile


def test_octavi_run_yields_after_read_failures():
    class FailingDevice:
        def __init__(self):
            self.calls = 0

        def read(self, size):
            self.calls += 1
            raise OSError("simulated HID failure")

    interface = object.__new__(OctaviInterface)
    interface._device = FailingDevice()
    interface._buttons = {button: False for button in OctaviButton}
    interface._last_buttons = {button: False for button in OctaviButton}
    interface._core_buttons = [button for button in OctaviButton if button < OctaviButton.INNER]
    interface._timers = {}
    interface._autorelease_delay = 0.01
    interface._device_guid = "octavi-test"
    interface._process_input = lambda data: None

    stop_event = threading.Event()
    thread = threading.Thread(target=interface._run, args=(stop_event,), daemon=True)
    thread.start()

    time.sleep(0.08)
    stop_event.set()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert interface._device.calls < 25


def test_blank_keyboard_input_xml_serializes_without_key():
    from gremlin.base_profile import ProfileModeNode
    from gremlin.ui.keyboard_device import KeyboardInputItem

    mode = ProfileModeNode(name="Default")
    item = KeyboardInputItem(mode)

    node = item.to_xml()

    assert node is not None
    assert node.tag == "keyboard"
