"""Regression tests for the Star Citizen telemetry input transitions."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gremlin.input_types import InputType
from gremlin.ui.star_citizen import protocol, telemetry


class StarCitizenTelemetryTests(unittest.TestCase):
    def make_vehicle(self, gear=1):
        frame = protocol.TelemetryFrame()
        state = frame.vehicle.state
        state.class_name = "test-ship"
        state.flight.state.gear = gear
        state.power.main = True
        state.power.engines = True
        return frame

    def test_gear_changes_emit_both_the_change_and_destination_address(self):
        tracker = telemetry.StateChanges()
        frame = self.make_vehicle()
        self.assertEqual(tracker.update(frame, 0), [])
        frame.vehicle.state.flight.state.gear = 3

        transitions = tracker.update(frame, 0.1)
        self.assertEqual(
            [(item.button, item.address, before, after) for item, before, after in transitions],
            [
                (1, "/star-citizen/gear/changed", "retracted", "deployed"),
                (4, "/star-citizen/gear/deployed", "retracted", "deployed"),
            ],
        )
        self.assertEqual(tracker.update(frame, 0.2), [])

    def test_optional_data_does_not_fabricate_state_changes(self):
        tracker = telemetry.StateChanges()
        frame = self.make_vehicle()
        frame.vehicle.state.flight.state.transformation = 3
        tracker.update(frame, 0)
        frame.vehicle.state.flight.state.ClearField("transformation")
        self.assertEqual(tracker.update(frame, 0.1), [])
        frame.vehicle.state.flight.state.transformation = 1
        self.assertEqual(
            [item.address for item, _, _ in tracker.update(frame, 0.2)],
            ["/star-citizen/wings/changed", "/star-citizen/wings/retracted"],
        )

    def test_vehicle_loss_and_switch_baseline_without_pulsing(self):
        tracker = telemetry.StateChanges()
        self.assertIsNone(tracker.snapshot())
        self.assertEqual(tracker.update(self.make_vehicle(), 0), [])
        first_snapshot = tracker.snapshot()
        self.assertEqual(first_snapshot[1]["gear"], "retracted")
        self.assertEqual(tracker.update(protocol.TelemetryFrame(), 3), [])
        self.assertIsNone(tracker.snapshot())
        frame = self.make_vehicle(gear=3)
        self.assertEqual(tracker.update(frame, 3.1), [])
        self.assertEqual(tracker.snapshot()[1]["gear"], "deployed")
        self.assertEqual(first_snapshot[1]["gear"], "retracted")
        frame.vehicle.state.class_name = "next-ship"
        frame.vehicle.state.flight.state.gear = 1
        self.assertEqual(tracker.update(frame, 3.2), [])
        self.assertEqual(tracker.snapshot()[0][1], "next-ship")

    def test_engine_loss_changes_derived_flight_ready(self):
        tracker = telemetry.StateChanges()
        frame = self.make_vehicle()
        tracker.update(frame, 0)
        frame.vehicle.state.power.engines = False
        addresses = {item.address for item, _, _ in tracker.update(frame, 0.1)}
        self.assertIn("/star-citizen/engines/off", addresses)
        self.assertIn("/star-citizen/flight-ready/off", addresses)

    def test_held_inputs_follow_stable_values_and_clear_after_vehicle_loss(self):
        tracker = telemetry.StateChanges()
        frame = self.make_vehicle(gear=3)
        flight = frame.vehicle.state.flight.state
        flight.vtol = 1
        gear, vtol, engines = (telemetry.HELD_INPUTS[key].button for key in ("gear", "vtol", "engines"))
        self.assertEqual(gear, 61)  # Keep the original held gear mapping ID.
        self.assertEqual(tracker.update(frame, 0), [])
        self.assertEqual(tracker.held_buttons & {gear, vtol, engines}, {gear, engines})

        flight.gear = 4
        flight.vtol = 2
        tracker.update(frame, 0.1)
        self.assertEqual(tracker.held_buttons & {gear, vtol, engines}, {gear, engines})

        flight.gear = 1
        flight.vtol = 3
        frame.vehicle.state.power.engines = False
        tracker.update(frame, 0.2)
        self.assertEqual(tracker.held_buttons & {gear, vtol, engines}, {vtol})
        tracker.update(protocol.TelemetryFrame(), 3)
        self.assertFalse(tracker.held_buttons)

    def test_additional_power_fields_supply_held_inputs_and_transition_pulses(self):
        tracker = telemetry.StateChanges()
        frame = self.make_vehicle()
        power = frame.vehicle.state.power
        fields = ("shields", "coolers", "life-support", "gravity-generators", "sensors")
        button_ids = {telemetry.HELD_INPUTS[field].button for field in fields}
        power.shield_generators = True
        tracker.update(frame, 0)
        self.assertFalse(tracker.held_buttons & button_ids)

        power.shield_emitters = True
        for field in fields[1:]:
            setattr(power, field.replace("-", "_"), True)
        transitions = tracker.update(frame, 0.1)
        self.assertEqual(tracker.held_buttons & button_ids, button_ids)
        self.assertTrue({telemetry.INPUTS[field, "on"] for field in fields}.issubset(
            {item for item, _, _ in transitions}
        ))
        self.assertEqual(tracker.update(frame, 0.2), [])

        power.shield_generators = False
        for field in fields[1:]:
            setattr(power, field.replace("-", "_"), False)
        transitions = tracker.update(frame, 0.3)
        self.assertFalse(tracker.held_buttons & button_ids)
        self.assertTrue({telemetry.INPUTS[field, "off"] for field in fields}.issubset(
            {item for item, _, _ in transitions}
        ))

    def test_deployment_transitions_have_individual_mappable_inputs(self):
        tracker = telemetry.StateChanges()
        frame = self.make_vehicle()
        flight = frame.vehicle.state.flight.state
        flight.vtol = 1
        self.assertEqual(tracker.update(frame, 0), [])

        flight.gear = 2
        flight.vtol = 2
        transitions = tracker.update(frame, 0.1)
        self.assertEqual(
            [item.address for item, _, _ in transitions],
            ["/star-citizen/gear/changed", "/star-citizen/gear/deploying",
             "/star-citizen/vtol/changed", "/star-citizen/vtol/deploying"],
        )

        flight.gear = 3
        flight.vtol = 3
        frame.vehicle.state.power.engines = False
        transitions = tracker.update(frame, 0.2)
        self.assertEqual(
            [item for item, _, _ in transitions if item.field in ("gear", "vtol", "engines")],
            [telemetry.INPUTS[key] for key in (
                ("gear", "changed"), ("gear", "deployed"), ("vtol", "changed"),
                ("vtol", "deployed"), ("engines", "changed"), ("engines", "off"),
            )],
        )


class StarCitizenInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from gremlin import base_profile, joystick_handling, shared_state

        cls.app = QApplication.instance() or QApplication([])
        with patch("gremlin.config.STAR_CITIZEN_ENABLED", True):
            joystick_handling.registerSpecialDevices()
        joystick_handling._joystick_initialized = True
        cls.device = joystick_handling.getDevice(shared_state.star_citizen_tab_guid)

    def setUp(self):
        from gremlin import base_profile, shared_state
        from gremlin.ui.star_citizen.tab import prepare_inputs

        self.profile = base_profile.Profile()
        self.mode = self.profile.get_default_mode()
        self.guid = self.device.device_guid
        current_profile = patch.object(shared_state, "current_profile", self.profile)
        current_profile.start()
        self.addCleanup(current_profile.stop)
        prepare_inputs(self.device, self.profile, self.mode)
        self.item = self.profile.devices[self.guid].modes[self.mode].getInputItem(InputType.StarCitizen, 1)

    def test_profile_round_trip_preserves_the_action_and_input_type(self):
        from lxml import etree

        from action_plugins.map_to_star_citizen import MapToStarCitizen
        from container_plugins.basic import BasicContainer
        from gremlin import base_profile, shared_state
        from gremlin.ui.star_citizen.tab import StarCitizenInputItemModel

        self.assertEqual(InputType.from_string(InputType.to_string(InputType.StarCitizen)), InputType.StarCitizen)
        self.assertEqual(InputType.to_display_name(InputType.StarCitizen), "Star Citizen")
        self.assertEqual(self.item.getInputType(), InputType.JoystickButton)
        model = StarCitizenInputItemModel(self.profile, self.guid, self.mode)
        model.refresh()
        self.assertEqual(model.rows(), len(telemetry.BUTTONS))
        self.assertEqual(model.getInputItemAt(0).input_id, telemetry.HELD_INPUTS["gear"].button)
        settings = self.profile.settings
        settings.setInputTypeVisibleDevice(self.device, InputType.StarCitizen, False)
        model.refresh()
        self.assertEqual(model.rowCount(), 0)
        settings.setDeviceDefault(self.device)
        model.refresh()
        self.assertEqual(model.rowCount(), len(telemetry.BUTTONS))

        container = BasicContainer(self.item)
        action = MapToStarCitizen(container)
        action.action_name = "test_action"
        container.add_action(action)
        self.item.containers.append(container)
        self.assertFalse(self.profile.empty())

        xml = self.profile.to_xml()
        self.assertIsNotNone(etree.fromstring(xml).find(".//mode/star-citizen[@id='1']"))
        loaded = base_profile.Profile()
        with patch.object(shared_state, "current_profile", loaded):
            loaded.from_xml(xml, fname_is_xml=True)
        item = loaded.devices[self.guid].modes[self.mode].getInputItem(InputType.StarCitizen, 1)
        self.assertEqual(item.containers[0].action_sets[0][0].action_name, "test_action")

    def test_last_input_selection_uses_the_numbered_telemetry_input(self):
        from gremlin import shared_state
        from gremlin.config import Configuration
        from gremlin.types import DeviceType

        config = Configuration()
        with patch.dict(shared_state.device_type_map, {self.guid: DeviceType.StarCitizen}):
            self.assertEqual(config._get_input_id(self.guid, None), (InputType.StarCitizen, 1, 1))
            self.assertEqual(config._get_input_id(self.guid, "4"), (InputType.StarCitizen, 4, 4))

        saved = {"last_input": {self.device.device_id: ["star-citizen", "4"]}}
        with patch.object(config, "_profile_data", saved):
            self.assertEqual(config.get_last_input(self.guid), (self.device.device_id, InputType.StarCitizen, 4))

    def test_telemetry_pulse_reaches_a_registered_button_callback(self):
        from gremlin import shared_state
        from gremlin.event_handler import Event, EventHandler
        from gremlin.ui.star_citizen.telemetry import StarCitizenClient

        with patch("gremlin.ui.star_citizen.telemetry.telemetry_enabled", return_value=False):
            service = StarCitizenClient.klass()
        self.addCleanup(service.close)
        handler = EventHandler()
        self.addCleanup(handler.clear)
        event = Event(event_type=InputType.StarCitizen, device_guid=self.guid, identifier=1)
        handler.registerInputItem(self.mode, self.item)
        received = []
        handler.addCallback(self.guid, self.mode, event, received.append)
        service._listener.joystick_event.connect(handler.execute_event)
        self.addCleanup(service._listener.joystick_event.disconnect, handler.execute_event)

        service._profile_started()
        with patch.object(shared_state, "is_running", True), patch.object(shared_state, "runtime_mode", self.mode):
            service._emit_inputs(service._activation, [(telemetry.BUTTONS[1], "retracted", "deployed")], frozenset())
        self.assertEqual(
            [(event.event_type, event.getInputType(), event.identifier, event.is_pressed) for event in received],
            [
                (InputType.StarCitizen, InputType.JoystickButton, 1, True),
                (InputType.StarCitizen, InputType.JoystickButton, 1, False),
            ],
        )


    def test_held_inputs_emit_only_edges_and_report_their_pressed_state(self):
        from gremlin import joystick_handling, shared_state
        from gremlin.ui.star_citizen.telemetry import StarCitizenClient

        with patch("gremlin.ui.star_citizen.telemetry.telemetry_enabled", return_value=False):
            service = StarCitizenClient.klass()
        self.addCleanup(service.close)
        gear, engines = (telemetry.HELD_INPUTS[key].button for key in ("gear", "engines"))
        received = []

        def record(event):
            pressed = joystick_handling.get_button(self.guid, event.identifier)
            received.append((event.identifier, event.is_pressed, pressed))

        service._listener.joystick_event.connect(record)
        self.addCleanup(service._listener.joystick_event.disconnect, record)
        service._profile_started()
        activation = service._activation
        with patch.object(shared_state, "is_running", True), patch.object(StarCitizenClient, "instance", service):
            service._emit_inputs(activation, [], {gear, engines})
            self.assertTrue(joystick_handling.get_button(self.guid, gear))
            self.assertTrue(joystick_handling.get_button(self.guid, engines))
            service._emit_inputs(activation, [], {gear, engines})
            service._emit_inputs(activation, [], {gear})
            service._emit_inputs(activation, [], set())
            self.assertFalse(joystick_handling.get_button(self.guid, gear))
        self.assertEqual(received, [(gear, True, True), (engines, True, True), (engines, False, False), (gear, False, False)])


    def test_gear_rows_show_live_input_state_with_profile_stopped(self):
        from gremlin import shared_state
        from gremlin.config import Configuration
        from gremlin.types import VerboseMode
        from gremlin.ui.star_citizen.telemetry import StarCitizenClient
        from gremlin.ui.star_citizen.tab import StarCitizenInputItemWidget
        from gremlin.ui.ui_common import QButtonStateWidget

        with patch("gremlin.ui.star_citizen.telemetry.telemetry_enabled", return_value=False):
            service = StarCitizenClient.klass()
        self.addCleanup(service.close)
        held = telemetry.HELD_INPUTS["gear"].button
        held_item = self.profile.devices[self.guid].modes[self.mode].getInputItem(InputType.StarCitizen, held)

        def is_lit(row):
            return row.button_repeater_widget._last_state_value

        with patch.dict(Configuration()._data, {"verbose_mode": VerboseMode.NotSet, "show_input_axis": True}):
            changed_row = StarCitizenInputItemWidget(self.item, 0, service)
            held_row = StarCitizenInputItemWidget(held_item, 1, service)
        self.addCleanup(changed_row.deleteLater)
        self.addCleanup(held_row.deleteLater)
        self.assertTrue(changed_row._current.isHidden())
        self.assertIsInstance(changed_row.button_repeater_widget, QButtonStateWidget)
        self.assertIs(changed_row._repeater_container_widget.widget(), changed_row.button_repeater_widget)

        frames = []
        for gear in (1, 3, 1):
            frame = protocol.TelemetryFrame()
            frame.vehicle.state.class_name = "test-ship"
            frame.vehicle.state.flight.state.gear = gear
            frames.append(frame)

        observed = []

        def stream(_request):
            for frame in frames:
                yield frame
                self.app.processEvents()
                observed.append((is_lit(changed_row), is_lit(held_row)))
                if changed_row._pulse_timer.isActive():
                    changed_row._pulse_timer.stop()
                    changed_row._pulse_timer.timeout.emit()
                    self.assertFalse(is_lit(changed_row))

        channel = Mock()
        channel.unary_unary.return_value.return_value = protocol.ActionList()
        channel.unary_stream.return_value.side_effect = stream
        runtime_callback = Mock()
        service._listener.joystick_event.connect(runtime_callback)
        self.addCleanup(service._listener.joystick_event.disconnect, runtime_callback)
        with (
            patch.object(shared_state, "is_running", False),
            patch("grpc.insecure_channel", return_value=channel),
            patch("grpc.channel_ready_future"),
            patch.object(service._closed, "wait", side_effect=lambda delay: service._closed.set()),
        ):
            service._read_telemetry()
            self.app.processEvents()

        self.assertEqual(observed, [(False, False), (True, True), (True, False)])
        runtime_callback.assert_not_called()

    def test_removed_row_ignores_telemetry_and_config_changes(self):
        from gremlin import util
        from gremlin.config import Configuration
        from gremlin.types import VerboseMode
        from gremlin.ui.star_citizen.telemetry import StarCitizenClient
        from gremlin.ui.star_citizen.tab import StarCitizenInputItemWidget

        with patch("gremlin.ui.star_citizen.telemetry.telemetry_enabled", return_value=False):
            service = StarCitizenClient.klass()
        self.addCleanup(service.close)
        config = Configuration()

        with patch.dict(config._data, {"verbose": True, "verbose_mode": VerboseMode.StarCitizen}):
            row = StarCitizenInputItemWidget(self.item, 0, service)
            field = row.definition.field
            service._set_snapshot((("test-ship", ""), {field: "test-value"}))
            self.assertEqual(row._current.text(), "Current value  test value")
            service.input_preview_changed.emit({row.definition.button}, set())
            self.assertTrue(row._pulse_timer.isActive())

            util.delete_widget(row)
            with patch("sys.excepthook") as excepthook:
                service._set_snapshot((("test-ship", ""), {field: "new-value"}))
                config.changed.emit("verbose_mode", VerboseMode.StarCitizen)
            excepthook.assert_not_called()
            self.assertFalse(row._pulse_timer.isActive())
            service.input_preview_changed.emit({row.definition.button}, set())
            self.assertFalse(row._pulse_timer.isActive())

    def test_telemetry_highlights_one_visible_input_only_when_enabled(self):
        from gremlin import shared_state
        from gremlin.config import Configuration
        from gremlin.ui.star_citizen.telemetry import StarCitizenClient

        with patch("gremlin.ui.star_citizen.telemetry.telemetry_enabled", return_value=False):
            service = StarCitizenClient.klass()
        self.addCleanup(service.close)

        selected = Mock()
        service._listener.button_state_change.connect(selected)
        self.addCleanup(service._listener.button_state_change.disconnect, selected)
        changed = telemetry.INPUTS["gear", "changed"]
        destination = telemetry.INPUTS["gear", "deployed"]
        held = telemetry.HELD_INPUTS["gear"]
        transitions = [(item, "deploying", "deployed") for item in (changed, destination)]
        config = Configuration()
        with (
            patch.object(shared_state, "is_running", False),
            patch.object(shared_state, "is_highlighting_suspended", return_value=False),
            patch.dict(config._data, {"highlight_device": True, "highlight_input_buttons": True}),
        ):
            service._handle_telemetry_inputs(None, [], frozenset({held.button}))
            selected.assert_not_called()

            service._handle_telemetry_inputs(None, transitions, frozenset({held.button}))
            selected.assert_called_once()
            event = selected.call_args.args[0]
            self.assertEqual((event.event_type, event.identifier, event.is_pressed), (InputType.StarCitizen, destination.button, True))

            selected.reset_mock()
            self.profile.settings.setInputVisible(self.guid, InputType.StarCitizen, destination.button, False)
            service._handle_telemetry_inputs(None, [], frozenset())
            service._handle_telemetry_inputs(None, transitions, frozenset({held.button}))
            selected.assert_called_once()
            self.assertEqual(selected.call_args.args[0].identifier, held.button)

            selected.reset_mock()
            with patch.dict(config._data, {"highlight_input_buttons": False}):
                service._handle_telemetry_inputs(None, transitions, frozenset({held.button}))
            with patch.object(shared_state, "is_running", True):
                service._handle_telemetry_inputs(None, transitions, frozenset({held.button}))
            selected.assert_not_called()

    def test_verbose_telemetry_logs_state_changes_without_repeating_frames(self):
        from gremlin.config import Configuration
        from gremlin.types import VerboseMode
        from gremlin.ui.star_citizen.telemetry import StarCitizenClient

        config = Configuration()
        for verbose in (True, False):
            with self.subTest(verbose=verbose):
                with patch("gremlin.ui.star_citizen.telemetry.telemetry_enabled", return_value=False):
                    service = StarCitizenClient.klass()
                self.addCleanup(service.close)

                frames = []
                for gear in (1, 1, 2, 2, 3, 3):
                    frame = protocol.TelemetryFrame()
                    frame.vehicle.state.class_name = "test-ship"
                    frame.vehicle.state.flight.state.gear = gear
                    frames.append(frame)

                channel = Mock()
                channel.unary_unary.return_value.return_value = protocol.ActionList()
                channel.unary_stream.return_value.return_value = iter(frames)
                verbose_mode = VerboseMode.StarCitizen if verbose else VerboseMode.NotSet
                with (
                    patch.dict(config._data, {"verbose": True, "verbose_mode": verbose_mode}),
                    patch("grpc.insecure_channel", return_value=channel),
                    patch("grpc.channel_ready_future"),
                    patch.object(service._closed, "wait", side_effect=lambda delay: service._closed.set()),
                    patch("gremlin.ui.star_citizen.telemetry.syslog.info") as log,
                ):
                    service._read_telemetry()

                messages = [entry.args[0] % entry.args[1:] for entry in log.call_args_list]
                if verbose:
                    self.assertEqual(
                        messages,
                        [
                            "STAR CITIZEN: receiving telemetry frames",
                            "STAR CITIZEN: test-ship initial state: gear=retracted, landed=off, lights=off",
                            "STAR CITIZEN: test-ship gear: retracted -> deploying",
                            "STAR CITIZEN: test-ship gear: deploying -> deployed",
                            "STAR CITIZEN: telemetry stream ended",
                        ],
                    )
                else:
                    self.assertEqual(messages, [])

    def test_shared_client_publishes_distinct_frames_on_the_application_thread(self):
        from concurrent.futures import ThreadPoolExecutor

        from PySide6.QtCore import QThread

        from gremlin.ui.star_citizen import get_device

        with (
            patch.object(telemetry.StarCitizenClient, "instance", None),
            patch.object(telemetry, "telemetry_enabled", return_value=False),
        ):
            self.assertFalse(telemetry.is_button_pressed(self.item.input_id))
            self.assertIsNone(telemetry.StarCitizenClient.instance)
            client = telemetry.get_client()
            self.assertIs(telemetry.StarCitizenClient(), client)
            self.assertIs(telemetry.get_client(), client)
            self.assertIs(get_device(), client)
        self.addCleanup(client.close)

        initial = protocol.TelemetryFrame()
        initial.vehicle.state.class_name = "test-ship"
        duplicate = protocol.TelemetryFrame.FromString(initial.SerializeToString())
        changed = protocol.TelemetryFrame.FromString(initial.SerializeToString())
        changed.vehicle.state.lights = False
        self.assertEqual(telemetry.vehicle_snapshot(initial), telemetry.vehicle_snapshot(changed))

        channel = Mock()
        channel.unary_unary.return_value.return_value = protocol.ActionList()
        channel.unary_stream.return_value.return_value = iter((initial, duplicate, changed, changed, initial))
        received = []

        def record(frame):
            received.append((QThread.currentThread(), frame))

        client.frame_changed.connect(record)
        self.addCleanup(client.frame_changed.disconnect, record)
        with (
            patch("grpc.insecure_channel", return_value=channel),
            patch("grpc.channel_ready_future"),
            patch.object(client._closed, "wait", side_effect=lambda delay: client._closed.set()),
            ThreadPoolExecutor(max_workers=1) as worker,
        ):
            worker.submit(client._read_telemetry).result(timeout=5)
            self.assertEqual(received, [])
            self.app.processEvents()

        app_thread = self.app.thread()
        self.assertEqual(received, [(app_thread, initial), (app_thread, changed), (app_thread, initial)])

    def test_client_connects_after_service_starts_and_reconnects_after_restart(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import ExitStack
        import socket
        import threading
        import time

        import grpc
        from PySide6.QtTest import QTest

        def wait_for(predicate, description):
            deadline = time.monotonic() + 8
            while not predicate():
                if time.monotonic() >= deadline:
                    self.fail(f"Timed out waiting for {description}. Client status: {client.status}")
                QTest.qWait(10)

        def start_service(ship_name):
            frame = protocol.TelemetryFrame()
            frame.vehicle.state.class_name = ship_name

            def stream(_request, context):
                finished = threading.Event()
                if context.add_callback(finished.set):
                    yield frame
                    finished.wait()

            server = grpc.server(executor, options=(("grpc.so_reuseport", 0),))
            cleanup.callback(lambda: server.stop(0).wait(5))
            server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(
                protocol.SERVICE.strip("/"),
                {"TelemetryStream": grpc.unary_stream_rpc_method_handler(
                    stream, response_serializer=protocol.TelemetryFrame.SerializeToString
                )},
            ),))
            self.assertEqual(server.add_insecure_port(address), port)
            server.start()
            return server

        with ExitStack() as cleanup:
            reservation = cleanup.enter_context(socket.socket())
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
            address = f"127.0.0.1:{port}"
            executor = cleanup.enter_context(ThreadPoolExecutor(max_workers=2))
            cleanup.enter_context(patch.object(telemetry, "ADDRESS", address))
            cleanup.enter_context(patch.dict(os.environ, {telemetry.ENVIRONMENT_FLAG: "true"}))
            cleanup.enter_context(patch.object(telemetry.StarCitizenClient, "instance", None))
            client = telemetry.get_client()
            cleanup.callback(client.close)
            snapshots = []
            client.snapshot_changed.connect(snapshots.append)

            wait_for(lambda: client._channel is not None, "the first connection attempt")
            wait_for(lambda: client._channel is None, "the first attempt to fail without a server")
            self.assertEqual(snapshots, [])

            reservation.close()
            first_server = start_service("first-ship")
            wait_for(lambda: len(snapshots) >= 1, "the first live snapshot")
            self.assertTrue(client.status.startswith("Connected to Star Citizen"))

            self.assertTrue(first_server.stop(0).wait(5))
            wait_for(lambda: len(snapshots) >= 2, "the snapshot to clear after shutdown")

            start_service("restarted-ship")
            wait_for(lambda: len(snapshots) >= 3, "a snapshot from the restarted service")
            self.assertIs(telemetry.get_client(), client)
            self.assertTrue(client.status.startswith("Connected to Star Citizen"))
            self.assertEqual(
                snapshots,
                [
                    (("", "first-ship"), {"lights": "off"}),
                    None,
                    (("", "restarted-ship"), {"lights": "off"}),
                ],
            )

    def test_telemetry_stream_releases_held_inputs_on_disconnect(self):
        from gremlin import shared_state
        from gremlin.ui.star_citizen.telemetry import StarCitizenClient

        with patch("gremlin.ui.star_citizen.telemetry.telemetry_enabled", return_value=False):
            service = StarCitizenClient.klass()
        self.addCleanup(service.close)

        frame = protocol.TelemetryFrame()
        frame.vehicle.state.class_name = "test-ship"
        frame.vehicle.state.power.engines = True
        channel = Mock()
        channel.unary_unary.return_value.return_value = protocol.ActionList()
        channel.unary_stream.return_value.return_value = iter((frame, frame))

        engine = telemetry.HELD_INPUTS["engines"].button
        edges = []

        def record(event):
            if event.identifier == engine:
                edges.append(event.is_pressed)

        service._listener.joystick_event.connect(record)
        self.addCleanup(service._listener.joystick_event.disconnect, record)
        service._profile_started()

        with (
            patch.object(shared_state, "is_running", True),
            patch("grpc.insecure_channel", return_value=channel),
            patch("grpc.channel_ready_future"),
            patch.object(service._closed, "wait", side_effect=lambda delay: service._closed.set()),
        ):
            service._read_telemetry()
            self.app.processEvents()

        self.assertEqual(edges, [True, False])
        self.assertFalse(service.is_pressed(engine))


if __name__ == "__main__":
    unittest.main()
