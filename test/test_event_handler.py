import gremlin.event_handler
import gremlin.shared_state
from gremlin.event_handler import Event, EventHandler
from gremlin.input_types import InputType


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
