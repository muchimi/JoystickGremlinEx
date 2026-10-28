"""Remoting regression checks without live network or device output.

Run with: python tools/test_remote.py
Actual packet builders, MessagePack, receive handlers, and worker queues are
used with in-memory sockets and device doubles.
"""

import ast
import enum
import logging
import queue
import socket
import socketserver
import struct
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import msgpack

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.types import GamePadOutput, MouseButton  # noqa: E402
from gremlin.input_types import InputType  # noqa: E402


def load_remote(source=None):
    names = {
        "_hat_direction", "_open_remote_vjoy", "GremlinServer", "GremlinSocketHandler",
        "RemoteClient", "BaseData", "ButtonData", "AxisData", "HatData", "KeyData",
        "MouseData", "BlockData", "ClientData", "PacketState", "PacketData",
    }
    tree = ast.parse(source if source is not None else (ROOT / "gremlin/remote.py").read_bytes())
    nodes = [node for node in tree.body if getattr(node, "name", None) in names]
    services = NS(singleton_decorator=NS(SingletonDecorator=lambda cls: cls))
    namespace = dict(
        gremlin=services, socket=socket, socketserver=socketserver, queue=queue,
        threading=threading, struct=struct, time=time, uuid=uuid, enum=enum,
        msgpack=msgpack, GamePadOutput=GamePadOutput, MouseButton=MouseButton,
        get_guid=lambda: str(uuid.uuid4()), syslog=logging.getLogger("remote-checks"),
        RPCGremlin=NS(MULTICAST_GROUP="224.3.29.72", MULTICAST_TTL=2),
        remote_server=Mock(),
    )
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *nodes,
    ], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROOT / "gremlin/remote.py"), "exec"), namespace)
    return namespace


class MemorySocket:
    def __init__(self):
        self.packets = []
        self.closed = False

    def sendto(self, data, address):
        if self.closed:
            raise OSError("closed socket")
        self.packets.append(data)
        return len(data)

    def close(self):
        self.closed = True


class Hat:
    directions = {(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1)}

    def __init__(self):
        self._direction = (0, 0)

    @property
    def direction(self):
        return self._direction

    @direction.setter
    def direction(self, value):
        # Like vJoy, require a hashable supported direction.
        if value not in self.directions:
            raise ValueError(value)
        self._direction = value


class FakeTimer:
    def __init__(self, interval, callback):
        self.callback = callback
        self.cancelled = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


class RemoteChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.namespace = load_remote()

    def setUp(self):
        self.ns = self.namespace
        self.services = self.ns["gremlin"]
        self.hat = Hat()
        self.axes = {1: NS(value=0.0), 6: NS(value=0.0)}
        self.button = NS(is_pressed=False)
        self.device = NS(
            hat_count=1, button_count=1, axis_count=2,
            hat=lambda target: self.hat, button=lambda target: self.button,
            axis=lambda target: self.axes[target], is_axis_valid=lambda axis_id: axis_id in self.axes,
        )
        self.services.joystick_handling = NS(VJoyProxy=lambda: {1: self.device}, vjoy_id_from_guid=lambda *_: 1)
        self.services.shared_state = NS(is_running=True, application_version="test", application_start_time=1)
        self.services.util = NS(get_guid=lambda: str(uuid.uuid4()), clamp=lambda value: max(-1, min(1, value)))
        self.services.sendinput = Mock()
        self.services.process = NS(ProcessHelper=Mock(return_value=NS(findProcessHwnd=lambda *_: 99)))
        self.services.keyboard = NS(getInnerWindows=lambda hwnd: [hwnd])
        self.services.types = NS(MouseButton=MouseButton)
        self.gamepad = Mock()
        self.services.gamepad_handling = NS(getGamepad=lambda index: self.gamepad)
        self.services.config = NS(Configuration=lambda: NS(enable_remote_control=True, remote_video_enabled=False))
        self.sender = self.make_client(10)
        self.receiver = self.make_client(20)
        self.ns["remote_client"] = self.receiver

    def make_client(self, identifier):
        client = object.__new__(self.ns["RemoteClient"])
        client._sock = MemorySocket()
        client._socket_lock = threading.RLock()
        client._callbacks_lock = threading.Lock()
        client._address = ("224.3.29.72", 6012)
        client._started = False
        client._id = f"session-{identifier}"
        client._callbacks = {}
        client._verbose_remote = client._verbose_remote_extra = client._verbose_outputs = False
        client.remote_control = NS(
            clientId=identifier, clientName=f"client-{identifier}", customName="",
            registerClient=Mock(), unregisterClient=Mock(),
        )
        return client

    def transfer(self, sender=None, receiver=None):
        sender = sender or self.sender
        receiver = receiver or self.receiver
        packet = msgpack.unpackb(sender._sock.packets[-1])
        receiver.handle(packet, peer_ip="192.0.2.1")
        return packet

    def test_all_hat_directions_survive_messagepack(self):
        for position in sorted(Hat.directions):
            with self.subTest(position=position):
                self.sender.send_hat(1, 1, position)
                self.transfer()
                self.assertEqual(self.hat.direction, position)
                self.assertIsInstance(self.hat.direction, tuple)

    def test_legacy_axis_payload_for_hats(self):
        payload = self.ns["AxisData"].create(1, 1, (1, -1), action="value").toPayload()
        self.sender.send(self.sender.getDatablock("hat", key="axis", data=payload))
        self.transfer()
        self.assertEqual(self.hat.direction, (1, -1))

    def test_hat_payload_normalizes_center_and_rejects_invalid_positions(self):
        for value in (None, False, [0, 0]):
            self.assertEqual(self.ns["HatData"].create(1, 1, value).direction, (0, 0))
        for value in ([2, 0], [1], [1, 2, 3], [[0], 1], "north"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.ns["HatData"].create(1, 1, value)

    def test_sparse_axis_ids_and_relative_clamping(self):
        self.sender.send_axis(1, 6, 0.8)
        self.transfer()
        self.assertEqual(self.axes[6].value, 0.8)
        self.sender.send_relative_axis(1, 6, 0.4)
        self.transfer()
        self.assertEqual(self.axes[6].value, 1)

    def test_invalid_axis_is_ignored_before_reading_current_value(self):
        self.sender.send_relative_axis(1, 99, 0.1)
        self.transfer()
        self.assertEqual(self.axes[1].value, 0)

    def test_button_and_toggle_roundtrip(self):
        self.sender.send_button(1, 1, True)
        self.transfer()
        self.assertTrue(self.button.is_pressed)
        self.sender.toggle_button(1, 1)
        self.transfer()
        self.assertFalse(self.button.is_pressed)

    def test_keyboard_without_target_process_is_sent(self):
        self.sender.send_key(0x41, 0x1E, 2)
        with patch.dict(sys.modules, {"win32gui": NS(PostMessage=Mock())}):
            self.transfer()
        self.services.sendinput.send_key.assert_called_once_with(0x41, 0x1E, 2)

    def test_keyboard_process_metadata_survives_decode(self):
        post = Mock()
        self.sender.send_key(0x41, 0x1E, 2, extra_data={"process_name": "target.exe", "partial_match": True})
        with patch.dict(sys.modules, {"win32gui": NS(PostMessage=post)}):
            self.transfer()
        self.services.process.ProcessHelper.assert_called_once()
        self.assertEqual(post.call_args.args[:3], (99, 0x101, 0x41))
        self.services.sendinput.send_key.assert_not_called()

    def test_mouse_helpers_roundtrip(self):
        for method, args, output, expected in (
            ("send_mouse_button", (1, True), "mouse_press", (MouseButton.Left,)),
            ("send_mouse_button", (1, False), "mouse_release", (MouseButton.Left,)),
            ("send_mouse_wheel", (-3,), "mouse_wheel", (-3,)),
            ("send_mouse_h_wheel", (2,), "mouse_h_wheel", (2,)),
        ):
            with self.subTest(method=method, args=args):
                getattr(self.sender, method)(*args)
                self.transfer()
                getattr(self.services.sendinput, output).assert_called_with(*expected)

    def test_accelerated_mouse_alias_roundtrip(self):
        self.sender.send_mouse_acceleration(45, 5, 20, 1)
        self.transfer()
        self.services.sendinput.MouseController().set_accelerated_motion.assert_called_once_with(45, 5, 20, 1)

    def test_gamepad_axis_enum_roundtrip(self):
        for mode, output in (
            (GamePadOutput.LeftStickX, "left_joystick_float_x"),
            (GamePadOutput.LeftStickY, "left_joystick_float_y"),
            (GamePadOutput.RightStickX, "right_joystick_float_x"),
            (GamePadOutput.RightStickY, "right_joystick_float_y"),
            (GamePadOutput.LeftTrigger, "left_trigger_float"),
            (GamePadOutput.RightTrigger, "right_trigger_float"),
        ):
            with self.subTest(mode=mode):
                self.sender.send_gamepad_axis(0, mode, -0.5)
                self.transfer()
                getattr(self.gamepad, output).assert_called_once_with(-0.5)
        self.assertEqual(self.gamepad.update.call_count, 6)

    def test_joystick_packets_keep_existing_wire_format(self):
        for method, args, action, key, payload in (
            ("send_button", (1, 1, True), "button", "button", self.ns["ButtonData"].create(1, 1, True, action="button").toPayload()),
            ("toggle_button", (1, 1), "toggle", "button", self.ns["ButtonData"].create(1, 1, action="toggle").toPayload()),
            ("send_axis", (1, 6, 0.4), "axis", "axis", self.ns["AxisData"].create(1, 6, 0.4, action="value").toPayload()),
            ("send_relative_axis", (1, 6, 0.2), "axis", "axis", self.ns["AxisData"].create(1, 6, relative_value=0.2, action="relative").toPayload()),
            ("send_hat", (1, 1, (1, 0)), "hat", "hat", self.ns["HatData"].create(1, 1, (1, 0), action="value").toPayload()),
        ):
            with self.subTest(method=method):
                getattr(self.sender, method)(*args)
                actual = msgpack.unpackb(self.sender._sock.packets[-1], use_list=False)
                expected = dict(action=action, key=key, data=payload, sender_id=10, sender_name="client-10", to=0)
                self.assertEqual(actual, expected)

    def test_kvm_mouse_keyboard_and_wheel_packets_roundtrip(self):
        for method, args, output, expected in (
            ("send_kvm_mouse_motion", (0, 0, 3, -2), "send_mouse_motion", (3, -2)),
            ("send_kvm_mouse_button", (1, True), "mouse_press", (1,)),
            ("send_kvm_mouse_button", (1, False), "mouse_release", (1,)),
            ("send_kvm_mouse_button", (MouseButton.WheelDown, True), "mouse_wheel", (-1,)),
            ("send_kvm_mouse_wheel", (-120, True), "mouse_h_wheel", (-1,)),
            ("send_kvm_keyboard", (0x41, 0x1E, 2), "send_key", (0x41, 0x1E, 2)),
        ):
            with self.subTest(method=method, args=args):
                getattr(self.sender, method)(*args)
                self.transfer()
                getattr(self.services.sendinput, output).assert_called_with(*expected)

    def test_gamepad_button_roundtrip(self):
        self.sender.send_gamepad_button(0, 0x1000, True)
        self.transfer()
        self.gamepad.press_button.assert_called_once_with(0x1000)
        self.sender.send_gamepad_button(0, 0x1000, False)
        self.transfer()
        self.gamepad.release_button.assert_called_once_with(0x1000)

    def test_string_target_is_one_client_and_duplicates_are_removed(self):
        self.sender.send_hat(1, 1, (0, 1), client_list="20")
        self.assertEqual(len(self.sender._sock.packets), 1)
        self.assertEqual(self.transfer()["to"], 20)
        self.sender._sock.packets.clear()
        self.sender.toggle_button(1, 1, client_list=[20, 20])
        self.assertEqual(len(self.sender._sock.packets), 1)

    def test_broadcast_supersedes_individual_targets_and_empty_list_sends_nothing(self):
        self.sender.send_hat(1, 1, (0, 1), client_list=[20, 0])
        self.assertEqual(len(self.sender._sock.packets), 1)
        self.assertEqual(self.transfer()["to"], 0)
        self.sender.send_hat(1, 1, (0, 1), client_list=[])
        self.assertEqual(len(self.sender._sock.packets), 1)

    def test_send_does_not_mutate_callers_packet(self):
        packet = {"action": "hb", "data": {"example": 1}}
        self.assertTrue(self.sender.send(packet, 20))
        self.assertEqual(packet, {"action": "hb", "data": {"example": 1}})

    def test_empty_payload_is_retained(self):
        self.assertEqual(self.sender.getDatablock("request", data={}), {"action": "request", "data": {}})

    def test_input_routing_ignores_self_other_targets_and_stopped_profiles(self):
        self.sender.send_button(1, 1, True, client_list=99)
        self.transfer()
        self.assertFalse(self.button.is_pressed)
        self.transfer(receiver=self.sender)
        self.assertFalse(self.button.is_pressed)
        self.services.shared_state.is_running = False
        self.sender.send_button(1, 1, True)
        self.transfer()
        self.assertFalse(self.button.is_pressed)

    def test_register_client_is_dispatched_without_running_profile(self):
        self.services.shared_state.is_running = False
        payload = dict(client_id=10, client_name="peer", client_custom="", client_version="test", client_timestamp=1)
        self.sender.send({"action": "register_client", "data": payload})
        self.transfer()
        self.receiver.remote_control.registerClient.assert_called_once()

    def test_targeted_request_and_reply_without_running_profile(self):
        self.services.shared_state.is_running = False
        callback = Mock()
        with patch.object(threading, "Timer", FakeTimer):
            self.sender.sendRequest(callback, {"action": "alive", "response": None}, client_id=20)
            packet = next(iter(self.sender._callbacks.values()))
            self.transfer()
            self.assertEqual(msgpack.unpackb(self.sender._sock.packets[-1])["reply_id"], 10)
            self.transfer(sender=self.receiver, receiver=self.sender)
        callback.assert_called_once_with(packet)
        self.assertEqual(packet.status, self.ns["PacketState"].Received)
        self.assertIsNotNone(packet.received)
        self.assertEqual(packet.response["client_id"], 20)
        self.assertEqual(self.sender._callbacks, {})
        self.assertIsNone(packet.timer)

    def test_broadcast_collects_multiple_replies_and_expires_without_false_timeout(self):
        callback = Mock()
        with patch.object(threading, "Timer", FakeTimer):
            self.sender.requestClients(callback)
            packet = next(iter(self.sender._callbacks.values()))
            self.sender.handleResponse(packet.id, {"client_id": 20})
            self.sender.handleResponse(packet.id, {"client_id": 30})
            packet._handle_timeout()
        self.assertEqual(callback.call_count, 2)
        self.assertEqual(packet.status, self.ns["PacketState"].Received)
        self.assertEqual(self.sender._callbacks, {})

    def test_timeout_cleans_up_and_fires_once(self):
        callback = Mock()
        with patch.object(threading, "Timer", FakeTimer):
            self.sender.requestAlive(callback)
            packet = next(iter(self.sender._callbacks.values()))
            packet._handle_timeout()
            packet._handle_timeout()
            self.sender.handleResponse(packet.id, {})
        callback.assert_called_once_with(packet)
        self.assertEqual(packet.status, self.ns["PacketState"].TimedOut)
        self.assertEqual(self.sender._callbacks, {})

    def test_failed_request_send_expires_immediately(self):
        callback = Mock()
        with patch.object(threading, "Timer", FakeTimer), patch.object(self.sender, "send", return_value=False):
            self.sender.requestAlive(callback)
        callback.assert_called_once()
        self.assertEqual(callback.call_args.args[0].status, self.ns["PacketState"].TimedOut)
        self.assertEqual(self.sender._callbacks, {})

    def test_immediate_reply_does_not_restart_request_timer(self):
        callback = Mock()

        def reply_immediately(data, client_id):
            self.sender.handleResponse(data["request_id"], {"client_id": client_id})
            return True

        with patch.object(threading, "Timer", FakeTimer), patch.object(self.sender, "send", side_effect=reply_immediately):
            self.sender.sendRequest(callback, {"action": "alive"}, client_id=20)
        callback.assert_called_once()
        packet = callback.call_args.args[0]
        self.assertIsNone(packet.timer)
        self.assertEqual(packet.status, self.ns["PacketState"].Received)
        self.assertEqual(self.sender._callbacks, {})

    def test_socket_creation_is_serialized_and_failed_socket_is_closed(self):
        self.sender._sock = None
        self.services.config = NS(Configuration=lambda: NS(
            broadcast_host_ip="0.0.0.0", server_port=6012, broadcast_bind_all_ips=True,
        ))
        created = Mock()
        with patch.object(socket, "socket", return_value=created) as factory:
            threads = [threading.Thread(target=self.sender.ensure_socket) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=1)
        factory.assert_called_once()
        self.sender._sock = None
        created.setsockopt.side_effect = OSError("invalid socket option")
        with patch.object(socket, "socket", return_value=created):
            self.assertFalse(self.sender.ensure_socket())
        created.close.assert_called_once()
        self.assertIsNone(self.sender._sock)

    def test_stopping_closes_lazy_socket_and_cancels_requests(self):
        original = self.sender._sock
        callback = Mock()
        with patch.object(threading, "Timer", FakeTimer):
            self.sender.requestAlive(callback)
            packet = next(iter(self.sender._callbacks.values()))
            timer = packet.timer
            self.sender.stop()
            packet._handle_timeout()  # Simulate a timer that raced cancellation.
        self.assertTrue(original.closed)
        self.assertIsNone(self.sender._sock)
        self.assertTrue(timer.cancelled)
        self.assertEqual(self.sender._callbacks, {})
        callback.assert_not_called()

    def test_socket_handler_preserves_binary_tail_and_ignores_bad_packets(self):
        handler = object.__new__(self.ns["GremlinSocketHandler"])
        handler.client_address = ("192.0.2.1", 1234)
        received = Mock()
        with patch.dict(self.ns, remote_client=NS(handle=received)):
            for value in (9, 10, 13, 32):
                handler.request = (msgpack.packb({"value": value}), None)
                handler.handle()
                self.assertEqual(received.call_args.args[0], {"value": value})
            for raw in (b"\xc1", b"\x81", msgpack.packb([1, 2]), msgpack.packb("string")):
                handler.request = (raw, None)
                handler.handle()
        self.assertEqual(received.call_count, 4)

    def test_socket_handler_discards_bad_payload_without_socket_error(self):
        handler = object.__new__(self.ns["GremlinSocketHandler"])
        handler.client_address = ("192.0.2.1", 1234)
        handler.request = (msgpack.packb({"sender_id": 10, "action": "hat", "to": 20, "data": {}}), None)
        handler.handle()


class WorkerChecks(unittest.TestCase):
    def test_failed_worker_does_not_discard_following_packets(self):
        ns = load_remote()
        server = ns["GremlinServer"](("127.0.0.1", 0), ns["GremlinSocketHandler"], bind_and_activate=False)
        done = threading.Event()

        def process(request, address):
            if request == "bad":
                raise RuntimeError("handler error")
            done.set()

        server.process_request_thread = process
        try:
            server.process_request("bad", ("192.0.2.1", 1000))
            server.process_request("good", ("192.0.2.1", 1000))
            self.assertTrue(done.wait(timeout=1))
        finally:
            server.server_close()
            for worker in server._request_workers:
                worker.join(timeout=2)

    def test_partial_worker_start_keeps_sender_on_existing_worker(self):
        ns = load_remote()
        server = ns["GremlinServer"](("127.0.0.1", 0), ns["GremlinSocketHandler"], bind_and_activate=False)
        entered, release = threading.Event(), threading.Event()
        completed = []
        original_start = threading.Thread.start
        starts = 0

        def start(thread):
            nonlocal starts
            starts += 1
            if starts == 2:
                raise RuntimeError("cannot create another thread")
            original_start(thread)

        def process(request, address):
            if request == "first":
                entered.set()
                release.wait(timeout=2)
            completed.append(request)

        server.process_request_thread = process
        try:
            with patch.object(threading.Thread, "start", start):
                server.process_request("first", ("192.0.2.1", 1000))
                self.assertTrue(entered.wait(timeout=1))
                server.process_request("second", ("192.0.2.1", 1000))
                self.assertEqual(completed, [])
                self.assertEqual(starts, 2)
        finally:
            release.set()
            server.server_close()
            for worker in server._request_workers:
                worker.join(timeout=2)
        self.assertEqual(completed, ["first", "second"])

    def test_sender_order_is_preserved_while_other_senders_can_progress(self):
        ns = load_remote()
        server = ns["GremlinServer"](("127.0.0.1", 0), ns["GremlinSocketHandler"], bind_and_activate=False)
        entered, release, other_done = threading.Event(), threading.Event(), threading.Event()
        completed = []
        first_peer = ("192.0.2.1", 1000)
        second_peer = next(("192.0.2.2", port) for port in range(1000, 1010) if hash(("192.0.2.2", port)) % 4 != hash(first_peer) % 4)

        def process(request, address):
            if request == "press":
                entered.set()
                release.wait(timeout=2)
            completed.append(request)
            if request == "other":
                other_done.set()

        server.process_request_thread = process
        try:
            server.process_request("press", first_peer)
            self.assertTrue(entered.wait(timeout=1))
            server.process_request("release", first_peer)
            server.process_request("other", second_peer)
            self.assertTrue(other_done.wait(timeout=1))
            self.assertNotIn("release", completed)
        finally:
            release.set()
            server.server_close()
            for worker in server._request_workers:
                worker.join(timeout=2)
        self.assertLess(completed.index("press"), completed.index("release"))
        self.assertTrue(all(not worker.is_alive() for worker in server._request_workers))


class GamepadMapperChecks(unittest.TestCase):
    def setUp(self):
        self.pad, self.remote, self.callbacks = Mock(), Mock(), Mock()
        services = NS(
            base_profile=NS(AbstractFunctor=object),
            config=NS(Configuration=lambda: NS(verbose_mode_outputs=False)),
            gamepad_handling=NS(getGamepad=Mock(return_value=self.pad)),
            util=NS(scale_to_range=lambda value, **kwargs: (value + 1) / 2),
            remote=NS(remote_client=self.remote),
        )
        namespace = dict(
            gremlin=services, GamePadOutput=GamePadOutput, InputType=InputType,
            vc=NS(XUSB_BUTTON=NS(XUSB_GAMEPAD_A=0x1000)),
            CallbackActions=lambda: self.callbacks,
            syslog=logging.getLogger("gamepad-checks"),
        )
        source = ROOT / "action_plugins/map_to_gamepad/__init__.py"
        node = next(node for node in ast.parse(source.read_bytes()).body if isinstance(node, ast.ClassDef) and node.name == "MapToGamepadFunctor")
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
        self.functor = object.__new__(namespace["MapToGamepadFunctor"])
        self.local, self.remote_enabled = False, True
        self.functor.action_data = NS(
            device_index=0, output_mode=GamePadOutput.LeftStickX,
            sendFlags=lambda: (self.local, self.remote_enabled),
        )
        self.services = services

    def test_axis_routes_for_all_local_and_remote_combinations(self):
        for local, remote in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(local=local, remote=remote):
                self.pad.reset_mock()
                self.remote.reset_mock()
                self.local, self.remote_enabled = local, remote
                self.functor.process_event(NS(is_axis=True, force_remote=False), NS(current=0.4))
                self.assertEqual(self.pad.left_joystick_float_x.call_count, int(local))
                self.assertEqual(self.pad.update.call_count, int(local))
                self.assertEqual(self.remote.send_gamepad_axis.call_count, int(remote))
                if remote:
                    self.remote.send_gamepad_axis.assert_called_once_with(0, GamePadOutput.LeftStickX, 0.4)

    def test_remote_triggers_are_scaled_before_sending(self):
        for mode in (GamePadOutput.LeftTrigger, GamePadOutput.RightTrigger):
            self.functor.action_data.output_mode = mode
            for value, expected in ((-1, 0), (0, 0.5), (1, 1)):
                with self.subTest(mode=mode, value=value):
                    self.functor.process_event(NS(is_axis=True, force_remote=False), NS(current=value))
                    self.remote.send_gamepad_axis.assert_called_with(0, mode, expected)

    def test_forced_remote_does_not_write_locally(self):
        self.local, self.remote_enabled = True, False
        self.functor.process_event(NS(is_axis=True, force_remote=True), NS(current=0.5))
        self.remote.send_gamepad_axis.assert_called_once_with(0, GamePadOutput.LeftStickX, 0.5)
        self.pad.update.assert_not_called()

    def test_remote_release_uses_event_state_after_autorelease(self):
        self.functor.action_data.output_mode = GamePadOutput.ButtonA
        event = NS(is_axis=False, force_remote=False, event_type=InputType.JoystickButton, is_pressed=False)
        self.functor.process_event(event, NS(is_pressed=True))
        self.remote.send_gamepad_button.assert_called_once_with(0, 0x1000, False)

    def test_button_routes_to_local_and_remote(self):
        self.local = True
        self.functor.action_data.output_mode = GamePadOutput.ButtonA
        event = NS(is_axis=False, force_remote=False, event_type=InputType.JoystickButton, is_pressed=True)
        self.functor.process_event(event, NS(is_pressed=True))
        self.pad.press_button.assert_called_once_with(0x1000)
        self.remote.send_gamepad_button.assert_called_once_with(0, 0x1000, True)

    def test_missing_local_gamepad_keeps_remote_output_working(self):
        self.local = True
        self.services.gamepad_handling.getGamepad.return_value = None
        self.functor.process_event(NS(is_axis=True, force_remote=False), NS(current=0.4))
        self.remote.send_gamepad_axis.assert_called_once_with(0, GamePadOutput.LeftStickX, 0.4)


if __name__ == "__main__":
    unittest.main()
