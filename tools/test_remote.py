"""Remoting regression checks without device output.

Run with: python tools/test_remote.py
Actual packet builders, MessagePack, receive handlers, and worker queues are
used with in-memory sockets, loopback UDP, and device doubles.
"""

import ast
import enum
import ipaddress
import json
import logging
import os
import queue
import re
import socket
import socketserver
import struct
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import msgpack
from lxml import etree
from psygnal import Signal
from PySide6 import QtCore, QtWidgets

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.types import DeviceType, GamePadOutput, MouseButton, VjoyAction  # noqa: E402
from gremlin.error import VJoyError  # noqa: E402
from gremlin.input_types import InputType  # noqa: E402
from gremlin.network import REMOTE_CONTROL_MULTICAST_GROUP  # noqa: E402


def load_remote(source=None):
    names = {
        "_unpack_remote_packet", "_hat_direction", "_open_remote_output", "GremlinServer", "GremlinSocketHandler",
        "RPCGremlin", "RemoteBroadcastTest", "RemoteClient", "BaseData", "ButtonData", "AxisData", "HatData", "KeyData",
        "MouseData", "BlockData", "ClientData", "PacketState", "PacketData",
        "RemoteClientData", "RemoteConfig", "_VIRTUAL_OUTPUT_ACTIONS",
        "RemoteControl", "RemoteClientSelectionWidget", "_client_address_key", "normalize_client_address",
        "ClientOperation", "OutputMode", "SelectionBehavior", "_OUTPUT_MODES",
        "read_client_selection", "write_client_selection",
    }
    tree = ast.parse(source if source is not None else (ROOT / "gremlin/remote.py").read_bytes())
    nodes = [
        node
        for node in tree.body
        if getattr(node, "name", None) in names
        or isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and (target.id.startswith("_PROBE_") or target.id in names) for target in node.targets)
    ]
    output_api = ast.parse((ROOT / "gremlin/joystick_handling.py").read_bytes())
    nodes.extend(node for node in output_api.body if getattr(node, "name", None) in {
        "parse_virtual_device_key", "maestro_output_identity", "match_maestro_output",
    })
    services = NS(singleton_decorator=NS(SingletonDecorator=lambda cls: cls))
    namespace = dict(
        gremlin=services, socket=socket, socketserver=socketserver, queue=queue,
        threading=threading, struct=struct, time=time, uuid=uuid, enum=enum,
        msgpack=msgpack, DeviceType=DeviceType, GamePadOutput=GamePadOutput, MouseButton=MouseButton, VJoyError=VJoyError,
        QtCore=QtCore, QtWidgets=QtWidgets, Signal=Signal, VjoyAction=VjoyAction,
        ipaddress=ipaddress, json=json, re=re, Path=Path, tempfile=tempfile, ElementTree=etree,
        safe_read=lambda node, attr, kind, default: (
            (node.get(attr).casefold() == "true" if kind is bool else kind(node.get(attr)))
            if attr in node.attrib else default
        ),
        get_guid=lambda: str(uuid.uuid4()), syslog=logging.getLogger("remote-checks"),
        REMOTE_CONTROL_MULTICAST_GROUP=REMOTE_CONTROL_MULTICAST_GROUP,
        remote_server=Mock(startup_ready=True),
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
        self.destinations = []
        self.closed = False

    def sendto(self, data, address):
        if self.closed:
            raise OSError("closed socket")
        self.packets.append(data)
        self.destinations.append(address)
        return len(data)

    def getsockname(self):
        return "0.0.0.0", 49832

    def getsockopt(self, level, option, size):
        return socket.inet_aton("192.0.2.1")

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
        self.services.joystick_handling = NS(
            VJoyProxy=lambda: {1: self.device},
            vjoy_id_from_guid=lambda *_: 1,
            get_output_device=lambda *_: None,
            get_output_target=lambda *_: None,
            get_virtual_device=lambda *_: None,
            parse_virtual_device_key=self.ns["parse_virtual_device_key"],
            maestro_output_identity=self.ns["maestro_output_identity"],
            match_maestro_output=self.ns["match_maestro_output"],
        )
        self.ns["maestro_devices"] = lambda: []
        self.services.shared_state = NS(is_running=True, application_version="test", application_start_time=1)
        self.services.util = NS(get_guid=lambda: str(uuid.uuid4()), clamp=lambda value: max(-1, min(1, value)))
        self.services.sendinput = Mock()
        self.services.process = NS(ProcessHelper=Mock(return_value=NS(findProcessHwnd=lambda *_: 99)))
        self.services.keyboard = NS(getInnerWindows=lambda hwnd: [hwnd])
        self.services.types = NS(MouseButton=MouseButton)
        self.gamepad = Mock()
        self.services.gamepad_handling = NS(getGamepad=lambda index: self.gamepad)
        self.config = NS(
            enable_remote_control=True, remote_video_enabled=False, client_name="test", verbose_mode_remote=False,
            vjoy_installed=True, virtual_output_failover=True, verbose_mode_maestro=False,
        )
        self.services.config = NS(Configuration=lambda: self.config)
        self.sender = self.make_client(10)
        self.receiver = self.make_client(20)
        self.ns["remote_client"] = self.receiver

    def make_client(self, identifier):
        client = object.__new__(self.ns["RemoteClient"])
        client._sock = MemorySocket()
        client._socket_lock = threading.RLock()
        client._socket_settings = (6012, "127.0.0.1", True)
        client._callbacks_lock = threading.Lock()
        client._address = ("224.3.29.72", 6012)
        client._started = False
        client._id = f"session-{identifier}"
        client._callbacks = {}
        client._verbose_remote = client._verbose_remote_extra = client._verbose_outputs = False
        client.remote_control = NS(
            clientId=identifier, clientName=f"client-{identifier}", customName="",
            registerClient=Mock(), unregisterClient=Mock(),
            filterClientTargets=lambda targets: (0,) if 0 in targets else targets,
        )
        return client

    def transfer(self, sender=None, receiver=None):
        sender = sender or self.sender
        receiver = receiver or self.receiver
        packet = msgpack.unpackb(sender._sock.packets[-1])
        receiver.handle(packet, peer_ip="192.0.2.1")
        return packet

    def make_routing(self):
        self.ns["remote_control"] = NS(getClients=lambda: {})
        self.services.event_handler = NS(EventListener=lambda: NS(remote_control_client_change=Mock()))
        return self.ns["RemoteConfig"]()

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

    def test_legacy_axis_uses_configured_maestro_when_native_vjoy_is_unavailable(self):
        routing = self.services.joystick_handling
        maestro = NS(device_guid=uuid.uuid4(), name="Pedals", is_gamepad=False, virtual_id=27,
                     connected=True, disabled=False, data={"maestro_key": "maestro://client:8010/gex-1"})
        self.ns["maestro_devices"] = lambda: [maestro]
        routing.get_output_device = Mock(side_effect={maestro.device_guid: self.device}.get)
        routing.VJoyProxy = Mock(side_effect=VJoyError("driver unavailable"))

        self.config.vjoy_installed = False
        self.sender.send_axis(1, 6, 0.6)
        self.transfer()
        self.assertEqual(self.axes[6].value, 0.6)
        routing.VJoyProxy.assert_not_called()
        routing.get_output_device.assert_called_once_with(maestro.device_guid)

        self.config.vjoy_installed = True
        self.sender.send_axis(1, 6, 0.9)
        self.transfer()
        self.assertEqual(self.axes[6].value, 0.9)
        routing.VJoyProxy.assert_called_once_with()

        self.config.virtual_output_failover = False
        routing.get_output_device.reset_mock()
        self.sender.send_axis(1, 6, -0.25)
        self.transfer()
        self.assertEqual(self.axes[6].value, 0.9)
        routing.get_output_device.assert_not_called()

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

    def test_maestro_command_uses_service_index_or_unique_name_across_hosts(self):
        master = NS(device_type=DeviceType.Maestro, name="Pedals", is_gamepad=False, virtual_id=6,
                    data={"maestro_key": "maestro://master:8010/gex-2"})
        target = NS(device_guid=uuid.uuid4(), name="Renamed pedals", is_gamepad=False, virtual_id=12,
                    connected=True, disabled=False, data={"maestro_key": "maestro://client:8010/gex-2"})
        decoy = NS(device_guid=uuid.uuid4(), name="Yoke", is_gamepad=False, virtual_id=6,
                   connected=True, disabled=False, data={"maestro_key": "maestro://client:8010/gex-5"})
        routing = self.services.joystick_handling
        key = str(uuid.uuid4())
        routing.get_virtual_device = {key: master}.get
        routing.get_output_device = Mock(side_effect={target.device_guid: self.device}.get)
        self.ns["maestro_devices"] = lambda: [decoy, target]

        self.sender.send_button(key, 1, True)
        self.transfer()
        self.assertTrue(self.button.is_pressed)
        routing.get_output_device.assert_called_once_with(target.device_guid)

        target.data["maestro_key"] = "maestro://client:8010/gex-8"
        target.name = " PEDALS "
        self.sender.send_button(key, 1, False)
        self.transfer()
        self.assertFalse(self.button.is_pressed)
        routing.get_output_device.assert_called_with(target.device_guid)

        decoy.name = "Pedals"
        routing.get_output_device.reset_mock()
        self.sender.send_button(key, 1, True)
        self.transfer()
        self.assertFalse(self.button.is_pressed)
        routing.get_output_device.assert_not_called()

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

    def test_all_kvm_packet_types_use_the_current_master_client_filter(self):
        control = self.make_master()
        self.register_peer(20, "left-pc", "192.0.2.20")
        self.register_peer(30, "right-pc", "192.0.2.30")
        sends = (
            (self.sender.send_kvm_mouse_motion_start, (), "start"),
            (self.sender.send_kvm_keyboard, (0x41, 0x1E, 0), "key"),
            (self.sender.send_kvm_keyboard, (0x41, 0x1E, 2), "key"),
            (self.sender.send_kvm_mouse_motion, (0, 0, 3, -2), "motion"),
            (self.sender.send_kvm_mouse_button, (1, True), "button"),
            (self.sender.send_kvm_mouse_button, (1, False), "button"),
            (self.sender.send_kvm_mouse_wheel, (120, False), "wheel"),
            (self.sender.send_kvm_mouse_wheel, (-120, True), "hwheel"),
            (self.sender.send_kvm_mouse_motion_stop, (), "stop"),
        )
        for selection, targets, expected in (
            (frozenset({"left-pc"}), [0], [20]),
            (frozenset({"192.0.2.30"}), [20, 30], [30]),
            (frozenset({"192.0.2.30"}), [20], []),
            (frozenset({"offline-pc"}), [0], []),
            (None, [0], [0]),
        ):
            with self.subTest(selection=selection, targets=targets):
                control.setActiveClients(selection)
                self.sender._sock.packets.clear()
                for send, args, _ in sends:
                    send(*args, client_list=targets)
                packets = [msgpack.unpackb(packet) for packet in self.sender._sock.packets]
                self.assertEqual(
                    [(packet["action"], packet["subtype"], packet["to"]) for packet in packets],
                    [("kvm", subtype, client_id) for _, _, subtype in sends for client_id in expected],
                )

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

    def make_master(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.config.enable_remote_broadcast = True
        self.config.master = True
        self.config.custom_host_name = ""
        self.config.data_path = lambda: folder
        self.services.util.safeReplace = os.replace
        self.services.util.is_ui_thread = lambda: True
        self.services.event_handler = NS(EventListener=Mock())
        control = self.ns["RemoteControl"]()
        self.sender.remote_control = control
        return control

    def register_peer(self, client_id, name, address):
        client = self.ns["ClientData"].fromData(client_id, "GEX Client", "")
        client.host_name = name
        self.sender.handle(
            {"action": "register_client", "sender_id": client_id, "data": client.toPayload()},
            peer_ip=address,
        )

    def test_master_catalog_remembers_manual_and_discovered_clients_after_disconnect(self):
        control = self.make_master()
        control.addKnownClient("  Spare-Client. ")
        self.register_peer(20, "Left-PC", "192.0.2.20")
        control.unregisterClient(20)
        self.assertIsNone(control.getClient(20))
        self.assertEqual(control.getKnownClients(), {"left-pc": "GEX Client, 192.0.2.20", "spare-client": ""})

        restarted = self.ns["RemoteControl"]()
        self.assertEqual(restarted.getKnownClients(), control.getKnownClients())
        restarted.removeKnownClient("spare-client")
        self.assertEqual(self.ns["RemoteControl"]().getKnownClients(), {"left-pc": "GEX Client, 192.0.2.20"})

    def test_registered_client_updates_a_manually_entered_ip(self):
        control = self.make_master()
        control.addKnownClient("192.0.2.20")
        self.register_peer(20, "left-pc", "192.0.2.20")
        self.assertEqual(control.getKnownClients(), {"192.0.2.20": "left-pc, GEX Client"})

    def test_network_discovery_merges_hosts_in_one_save_and_keeps_existing_addresses(self):
        control = self.make_master()
        control.addKnownClient("192.0.2.20")
        computers = [
            ("Right-PC", "192.0.2.30"),
            ("RIGHT-PC", "192.0.2.9"),
            ("Left-PC", "192.0.2.20"),
        ]
        with patch.object(control, "_save_known_clients", wraps=control._save_known_clients) as save:
            self.assertEqual(control.addDiscoveredClients(computers), 1)
            self.assertEqual(control.addDiscoveredClients(computers), 0)
            save.assert_called_once()
        self.assertEqual(
            self.ns["RemoteControl"]().getKnownClients(),
            {"192.0.2.20": "", "right-pc": "192.0.2.9, 192.0.2.30"},
        )

    def test_master_filter_matches_name_or_ip_and_intersects_explicit_targets(self):
        control = self.make_master()
        control.setActiveClients(frozenset({"left-pc", "192.0.2.30"}))
        self.sender.send_button(1, 1, True, client_list=[0])
        self.assertEqual(self.sender._sock.packets, [])
        self.register_peer(20, "LEFT-PC", "192.0.2.20")
        self.register_peer(30, "right-pc", "192.0.2.30")
        self.register_peer(40, "middle-pc", "192.0.2.40")

        self.assertEqual(control.getActiveClients(), {20, 30})
        self.sender.send_button(1, 1, True, client_list={0: True})
        self.assertCountEqual([msgpack.unpackb(packet)["to"] for packet in self.sender._sock.packets], [20, 30])
        self.sender._sock.packets.clear()
        self.sender.send_button(1, 1, True, client_list=["30", "40", "30"])
        self.sender.send_button(1, 1, True, client_list=[])
        self.assertEqual([msgpack.unpackb(packet)["to"] for packet in self.sender._sock.packets], [30])

        for selection in (None, frozenset()):
            with self.subTest(selection=selection):
                control.setActiveClients(selection)
                self.assertFalse(control.clientFiltered)
                self.sender.send_button(1, 1, True)
                self.assertEqual(msgpack.unpackb(self.sender._sock.packets[-1])["to"], 0)

    def test_solo_takes_precedence_temporarily_and_restores_the_latest_regular_selection(self):
        control = self.make_master()
        self.register_peer(20, "left-pc", "192.0.2.20")
        self.register_peer(30, "right-pc", "192.0.2.30")
        control.setActiveClients(frozenset({"left-pc"}))
        first, second = object(), object()

        control.beginClientSolo(first, "192.0.2.30")
        self.assertEqual(control.getActiveClients(), {30})
        self.assertEqual(control.filterClientTargets((20, 30)), (30,))
        control.endClientSolo(first)
        self.assertEqual(control.getActiveClients(), {20})

        control.beginClientSolo(first, "192.0.2.30")
        control.beginClientSolo(second, "LEFT-PC")
        self.assertEqual(control.getActiveClients(), {20})

        control.setActiveClients(None)
        control.endClientSolo(second)
        self.assertEqual(control.filterClientTargets((0,)), {30})
        control.endClientSolo(first)
        self.assertEqual(control.filterClientTargets((0,)), (0,))

    def test_solo_tracks_live_registration_and_handles_out_of_order_release(self):
        control = self.make_master()
        self.register_peer(20, "left-pc", "192.0.2.20")
        first, second = object(), object()
        control.beginClientSolo(first, "left-pc")
        control.beginClientSolo(second, "right-pc")
        self.assertFalse(control.filterClientTargets((0,)))

        self.register_peer(30, "right-pc", "192.0.2.30")
        control.endClientSolo(first)
        self.assertEqual(control.getActiveClients(), {30})
        control.unregisterClient(30)
        self.assertFalse(control.filterClientTargets((0,)))
        control.endClientSolo(second)
        self.assertFalse(control.clientFiltered)

    def test_temporary_client_selection_matches_multiple_live_clients(self):
        control = self.make_master()
        self.register_peer(20, "left-pc", "192.0.2.20")
        self.register_peer(30, "right-pc", "192.0.2.30")
        control.setActiveClients(frozenset({"left-pc"}))
        hold = object()
        control.beginClientOverride(hold, frozenset({"right-pc", "192.0.2.40"}))
        self.assertEqual(control.getActiveClients(), {30})

        self.register_peer(40, "panel-pc", "192.0.2.40")
        self.assertEqual(control.getActiveClients(), {30, 40})
        control.endClientOverride(hold)
        self.assertEqual(control.getActiveClients(), {20})

    def test_all_client_overrides_include_or_block_undiscovered_clients(self):
        control = self.make_master()
        self.register_peer(20, "left-pc", "192.0.2.20")
        control.setActiveClients(frozenset({"left-pc"}))
        enable, disable = object(), object()

        control.beginClientOverride(enable, None)
        self.assertFalse(control.clientFiltered)
        self.assertTrue(control.clientActive(30))
        self.sender.send_kvm_keyboard(0x41, 0x1E, 0, client_list=[0])
        self.assertEqual(self.transfer(receiver=self.make_client(30))["to"], 0)
        self.services.sendinput.send_key.assert_called_once_with(0x41, 0x1E, 0)
        self.assertEqual(control.filterClientTargets((30,)), (30,))

        control.beginClientOverride(disable, frozenset())
        self.assertTrue(control.clientFiltered)
        self.assertFalse(control.clientActive(30))
        self.assertFalse(control.getActiveClients())
        self.sender._sock.packets.clear()
        self.sender.send_kvm_keyboard(0x41, 0x1E, 0, client_list=[0])
        self.sender.send_kvm_keyboard(0x41, 0x1E, 0, client_list=[30])
        self.assertEqual(self.sender._sock.packets, [])

        control.endClientOverride(disable)
        self.assertEqual(control.filterClientTargets((0,)), (0,))
        control.endClientOverride(enable)
        self.assertEqual(control.getActiveClients(), {20})
        self.assertEqual(control.filterClientTargets((30,)), ())

    def test_regular_all_client_mute_survives_registration_and_temporary_overrides(self):
        control = self.make_master()
        control.setAllClientsActive(False)
        self.register_peer(20, "left-pc", "192.0.2.20")
        self.assertTrue(control.clientFiltered)
        self.assertEqual(control.filterClientTargets((0, 20, 30)), frozenset())
        self.assertEqual(control.filterClientTargets((20, 30)), ())

        hold = object()
        control.beginClientOverride(hold, None)
        self.assertEqual(control.filterClientTargets((0,)), (0,))
        control.endClientOverride(hold)
        self.assertEqual(control.filterClientTargets((0,)), frozenset())

        control.setAllClientsActive(True)
        self.assertEqual(control.filterClientTargets((0,)), (0,))
        self.assertEqual(control.filterClientTargets((20, 30)), (20, 30))

    def test_startup_client_operation_and_routing_apply_independently(self):
        control = self.make_master()
        operations = self.ns["ClientOperation"]
        modes = self.ns["OutputMode"]
        self.register_peer(20, "panel", "192.0.2.20")
        control.applyClientOperation(operations.Select, frozenset({"panel"}))
        control.applyOutputMode(modes.RemoteOnly)
        self.assertEqual(control.getActiveClients(), {20})
        self.assertEqual((control.is_local, control.is_remote), (False, True))
        control.applyClientOperation(operations.Unchanged, None)
        control.applyOutputMode(modes.LocalAndRemote)
        self.assertEqual(control.getActiveClients(), {20})
        self.assertEqual((control.is_local, control.is_remote), (True, True))
        control.applyClientOperation(operations.DisableAll, None)
        control.applyOutputMode(modes.Unchanged)
        self.assertEqual(control.filterClientTargets((0,)), frozenset())
        self.assertEqual((control.is_local, control.is_remote), (True, True))
        control.applyClientOperation(operations.EnableAll, None)
        control.applyOutputMode(modes.LocalOnly)
        self.assertEqual(control.filterClientTargets((0,)), (0,))
        self.assertEqual((control.is_local, control.is_remote), (True, False))

    def test_default_mapping_multicasts_once_without_discovery(self):
        routing = self.make_routing()
        self.assertEqual(routing.getClientList(), [0])
        self.sender.send_axis(1, 6, 0.75, client_list=routing.getClientList())
        self.assertEqual(self.sender._sock.destinations, [(REMOTE_CONTROL_MULTICAST_GROUP, 6012)])
        self.assertEqual(self.transfer()["to"], 0)
        self.assertEqual(self.axes[6].value, 0.75)

        other = self.make_client(30)
        self.axes[6].value = 0.0
        self.transfer(receiver=other)
        self.assertEqual(self.axes[6].value, 0.75)

    def test_saved_specific_mapping_uses_multicast_and_filters_non_targets(self):
        routing = self.make_routing()
        routing.from_xml(etree.fromstring(
            '<remote-config custom="true"><client client-id="20" selected="true"/></remote-config>'
        ))
        self.assertEqual(routing.getClientList(), [20])
        self.sender.send_button(1, 1, True, client_list=routing.getClientList())
        self.assertEqual(self.sender._sock.destinations, [(REMOTE_CONTROL_MULTICAST_GROUP, 6012)])
        self.transfer(receiver=self.make_client(30))
        self.assertFalse(self.button.is_pressed)
        packet = self.transfer()
        self.assertEqual(packet["to"], 20)
        self.assertTrue(self.button.is_pressed)

        routing.isCustom = False
        self.assertEqual(routing.getClientList(), [0])

    def test_virtual_output_requires_a_recipient_field(self):
        self.sender.send_button(1, 1, True)
        packet = msgpack.unpackb(self.sender._sock.packets[-1])
        del packet["to"]
        self.receiver.handle(packet)
        self.assertFalse(self.button.is_pressed)

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

    def test_broadcast_role_ignores_received_control_but_still_discovers_clients(self):
        self.services.config.Configuration = lambda: NS(enable_remote_control=False, client_name="test")
        self.sender.send_button(1, 1, True)
        self.transfer()
        self.assertFalse(self.button.is_pressed)

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

    def test_connection_probe_replies_to_sender_and_only_multicasts_when_requested(self):
        handler = object.__new__(self.ns["GremlinSocketHandler"])
        handler.client_address = ("192.0.2.1", 1234)
        connection = Mock()
        remote = Mock()
        nonce = uuid.uuid4().bytes

        with patch.dict(self.ns, remote_client=remote):
            for multicast in (False, True):
                request = {"action": "connection_test", "nonce": nonce, "multicast": multicast}
                handler.request = (msgpack.packb(request), connection)
                handler.handle()
                packet, address = connection.sendto.call_args.args
                self.assertEqual(address, handler.client_address)
                self.assertEqual(msgpack.unpackb(packet), {"action": "connection_test_reply", "nonce": nonce})
                if not multicast:
                    remote.send.assert_not_called()

        remote.send.assert_called_once_with({"action": "connection_test_multicast", "nonce": nonce})
        remote.handle.assert_not_called()

    def test_multicast_probe_notifies_diagnostic_listener_without_replying(self):
        handler = object.__new__(self.ns["GremlinSocketHandler"])
        handler.server = NS(server_address=("0.0.0.0", 6012))
        connection = Mock()
        listener = Mock()
        nonce = uuid.uuid4().bytes

        with patch.dict(self.ns, remote_server=listener):
            for candidate in ("invalid", b"short", nonce):
                packet = {"action": "connection_test_multicast", "nonce": candidate}
                handler.request = (msgpack.packb(packet), connection)
                handler.handle()

        listener.connection_test_multicast.emit.assert_called_once_with(nonce, 6012)
        connection.sendto.assert_not_called()

    def test_broadcast_ping_replies_from_enabled_client_without_running_profile(self):
        handler = object.__new__(self.ns["GremlinSocketHandler"])
        handler.server = NS(server_address=("0.0.0.0", 6012))
        handler.client_address = ("192.0.2.1", 49832)
        connection = Mock()
        nonce = uuid.uuid4().bytes
        self.services.shared_state.is_running = False
        config = self.services.config.Configuration()
        self.services.config.Configuration = lambda: config

        def ping(sender, token=nonce):
            request = {"action": "broadcast_test_ping", "nonce": token, "sender_id": sender}
            handler.request = (msgpack.packb(request), connection)
            handler.handle()

        ping(self.receiver.clientId)  # Its own multicast packet.
        ping(self.sender.clientId, b"short")
        config.enable_remote_control = False
        with self.assertLogs("remote-checks") as logs:
            ping(self.sender.clientId)
        self.assertIn("skipped pong because client remote control is disabled", logs.output[-1])
        connection.sendto.assert_not_called()

        config.enable_remote_control = True
        with self.assertLogs("remote-checks") as logs:
            ping(self.sender.clientId)
        self.assertIn(f"[{nonce.hex()}] received ping from 192.0.2.1:49832 on UDP port 6012", logs.output[0])
        self.assertIn(f"[{nonce.hex()}] sent unicast pong to 192.0.2.1:6012", logs.output[1])
        connection.sendto.assert_called_once()
        packet, destination = connection.sendto.call_args.args
        self.assertEqual(destination, ("192.0.2.1", 6012))
        self.assertEqual(
            msgpack.unpackb(packet),
            {"action": "broadcast_test_pong", "nonce": nonce, "sender_id": 20, "sender_name": "test", "to": 10},
        )

        connection.sendto.side_effect = OSError("test error")
        with self.assertLogs("remote-checks", level="WARNING") as logs:
            ping(self.sender.clientId)
        self.assertIn(f"[{nonce.hex()}] could not send pong to 192.0.2.1:6012: test error", logs.output[0])

    def test_broadcast_pong_is_delivered_only_to_the_addressed_server(self):
        handler = object.__new__(self.ns["GremlinSocketHandler"])
        handler.server = NS(server_address=("0.0.0.0", 6012))
        handler.client_address = ("192.0.2.12", 6012)
        listener = Mock()
        nonce = uuid.uuid4().bytes
        client_id = 0xABCDEF012345
        packet = {
            "action": "broadcast_test_pong", "nonce": nonce, "sender_id": client_id,
            "sender_name": "  Test\nClient  ", "to": self.sender.clientId,
        }

        with patch.dict(self.ns, remote_server=listener):
            handler.request = (msgpack.packb(packet), None)
            handler.handle()
            listener.broadcast_test_reply.emit.assert_not_called()
            packet["to"] = self.receiver.clientId
            handler.request = (msgpack.packb(packet), None)
            with self.assertLogs("remote-checks") as logs:
                handler.handle()

        listener.broadcast_test_reply.emit.assert_called_once_with(nonce, 6012, client_id, "Test Client", "192.0.2.12")
        self.assertIn(f"[{nonce.hex()}] received pong from 192.0.2.12:6012 on UDP port 6012", logs.output[0])

    def test_client_refreshes_outbound_socket_only_when_endpoint_changes(self):
        config = self.services.config.Configuration()
        config.server_port, config.broadcast_host_ip, config.broadcast_bind_all_ips = self.sender._socket_settings
        config.verbose_mode_remote_extra = config.verbose_mode_remote = config.verbose_mode_outputs = False
        self.services.config.Configuration = lambda: config
        self.sender.remote_control.remoteEnabled = lambda: True
        self.sender._started = True
        self.sender.requestIdentify = Mock()

        outbound = self.sender._sock
        self.sender._handle_config_options_changed()
        self.assertIs(self.sender._sock, outbound)
        self.sender.requestIdentify.assert_not_called()

        config.server_port += 1
        self.sender._handle_config_options_changed()
        self.assertTrue(outbound.closed)
        self.assertIsNone(self.sender._sock)
        self.sender.requestIdentify.assert_called_once()

    def test_client_waits_for_application_startup(self):
        server = Mock(startup_ready=False)
        self.sender.remote_control.remoteEnabled = lambda: True
        self.sender.ensure_socket = Mock()
        with patch.dict(self.ns, remote_server=server):
            self.sender.start()
            self.assertFalse(self.sender.send({"action": "identify"}))

        self.sender.ensure_socket.assert_not_called()
        server.start.assert_not_called()
        self.assertEqual(self.sender._sock.packets, [])

    def test_broadcast_test_multicasts_and_collects_unique_current_replies(self):
        class ReplyListener(QtCore.QObject):
            broadcast_test_reply = QtCore.Signal(bytes, int, object, str, str)

        app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
        listener = ReplyListener()
        listener.listening_port = 6012
        listener.startup_ready = True
        listener.start = Mock()
        send = Mock(wraps=self.sender._sock.sendto)
        self.sender._sock.sendto = send
        test = self.ns["RemoteBroadcastTest"](6012)
        finished = Mock()
        test.finished.connect(finished)

        with patch.dict(self.ns, remote_client=self.sender, remote_server=listener):
            try:
                with self.assertLogs("remote-checks") as logs:
                    test.start()
                send.assert_called_once()
                raw, target = send.call_args.args
                self.assertEqual(target, (REMOTE_CONTROL_MULTICAST_GROUP, 6012))
                ping = msgpack.unpackb(raw)
                self.assertEqual(ping["action"], "broadcast_test_ping")
                nonce = ping["nonce"]
                self.assertIn(
                    f"[{nonce.hex()}] sent multicast ping to {REMOTE_CONTROL_MULTICAST_GROUP}:6012 using 192.0.2.1, "
                    "source UDP port 49832, expecting unicast replies on UDP port 6012",
                    logs.output[0],
                )

                listener.broadcast_test_reply.emit(nonce, 6012, 0xABCDEF012345, "Zeta", "192.0.2.12")
                listener.broadcast_test_reply.emit(nonce, 6012, 0xABCDEF012345, "Duplicate", "192.0.2.13")
                listener.broadcast_test_reply.emit(nonce, 6012, 31, "Alpha", "192.0.2.14")
                listener.broadcast_test_reply.emit(nonce, 6013, 32, "Other port", "192.0.2.15")
                listener.broadcast_test_reply.emit(uuid.uuid4().bytes, 6012, 33, "Old test", "192.0.2.16")
                app.processEvents()
                with self.assertLogs("remote-checks") as logs:
                    test._finish()
                self.assertIn(f"[{nonce.hex()}] completed with 2 unique client replies", logs.output[0])
                finished.assert_called_once_with(
                    "2 clients replied to the multicast ping.", [("Alpha", "192.0.2.14"), ("Zeta", "192.0.2.12")]
                )
            finally:
                test.cancel()


class RemoteClientTriggerChecks(unittest.TestCase):
    def setUp(self):
        class ActionBase:
            def __init__(self, parent, extra_data=None):
                pass

            def setPriority(self, priority):
                pass

        class FunctorBase:
            def __init__(self, action, parent=None):
                self.action_data = action

        namespace = load_remote()
        self.control = Mock()
        self.callbacks = Mock()
        namespace["gremlin"].input_item = NS(AbstractAction=ActionBase)
        namespace["gremlin"].base_profile = NS(AbstractFunctor=FunctorBase)
        namespace.update(
            InputType=InputType, RemoteClientWidget=object, remote_control=self.control,
            CallbackActions=lambda: self.callbacks, etree=etree, safe_format=lambda value, kind: str(value),
        )
        source = ROOT / "action_plugins/remote_client/__init__.py"
        nodes = [node for node in ast.parse(source.read_bytes()).body
                 if isinstance(node, ast.ClassDef) and node.name in ("RemoteClientAction", "RemoteClientFunctor")]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
        self.operations = namespace["ClientOperation"]
        self.behaviors = namespace["SelectionBehavior"]
        self.routing = namespace["OutputMode"]
        self.action = namespace["RemoteClientAction"](None)
        self.functor = namespace["RemoteClientFunctor"](self.action)

    def send(self, pressed, *, event_type=InputType.JoystickButton, value=None):
        event = NS(is_pressed=pressed, event_type=event_type, value=value, extra_data=None, is_virtual_button=False)
        self.assertTrue(self.functor.process_event(event, None))

    def test_legacy_default_and_release_round_trip(self):
        self.action._parse_xml(etree.Element("remote-client"))
        self.assertTrue(self.action.exec_on_press)
        self.assertFalse(self.action.exec_on_release)
        self.action.exec_on_press = False
        self.action.exec_on_release = True
        self.action._parse_xml(self.action._generate_xml())
        self.assertFalse(self.action.exec_on_press)
        self.assertTrue(self.action.exec_on_release)

    def test_release_only_applies_client_filter_and_routing(self):
        self.action.exec_on_press = False
        self.action.exec_on_release = True
        self.action.operation = self.operations.DisableAll
        self.action.output_mode = self.routing.LocalOnly
        self.send(True)
        self.control.applyClientOperation.assert_not_called()
        self.control.applyOutputMode.assert_not_called()
        self.send(False)
        self.control.applyClientOperation.assert_called_once_with(self.operations.DisableAll, None)
        self.control.applyOutputMode.assert_called_once_with(self.routing.LocalOnly)
        self.action.exec_on_release = False
        self.assertFalse(self.action.hasOutput())

    def test_toggle_on_both_edges_ignores_hat_center_events(self):
        self.action.behavior = self.behaviors.Toggle
        self.action.exec_on_release = True
        self.action.selection = frozenset({"panel-pc"})
        self.send(False, event_type=InputType.JoystickHat, value=(0, 0))
        self.send(True, event_type=InputType.JoystickHat, value=(1, 0))
        self.control.beginClientOverride.assert_called_once()
        hold, addresses = self.control.beginClientOverride.call_args.args
        self.assertEqual(addresses, self.action.selection)
        self.send(False, event_type=InputType.JoystickHat, value=(1, 0))
        self.send(True, event_type=InputType.JoystickHat, value=(0, 0))
        self.control.endClientOverride.assert_called_once_with(hold)

    def test_release_only_toggle_uses_each_release(self):
        self.action.behavior = self.behaviors.Toggle
        self.action.exec_on_press = False
        self.action.exec_on_release = True
        self.send(True)
        self.control.beginClientOverride.assert_not_called()
        self.send(False)
        self.control.beginClientOverride.assert_called_once()
        hold, _ = self.control.beginClientOverride.call_args.args
        self.send(True)
        self.control.endClientOverride.assert_not_called()
        self.send(False)
        self.control.endClientOverride.assert_called_once_with(hold)

    def test_hold_uses_press_and_release_regardless_of_trigger_settings(self):
        self.action.behavior = self.behaviors.Temporary
        self.action.operation = self.operations.EnableAll
        self.action.exec_on_press = False
        self.action.exec_on_release = True
        self.assertTrue(self.action.hasOutput())
        self.send(True)
        self.control.beginClientOverride.assert_called_once()
        hold, addresses = self.control.beginClientOverride.call_args.args
        self.assertIsNone(addresses)
        release_callback, _ = self.callbacks.register_callback.call_args.args
        release_callback()
        self.send(False)
        self.control.endClientOverride.assert_called_once_with(hold)
        self.control.applyOutputMode.assert_called_once()


class ListenerChecks(unittest.TestCase):
    def test_only_endpoint_changes_replace_listener_and_close_old_socket_first(self):
        ns = load_remote()
        services = ns["gremlin"]
        with socket.socket(type=socket.SOCK_DGRAM) as first, socket.socket(type=socket.SOCK_DGRAM) as second:
            first.bind(("0.0.0.0", 0))
            second.bind(("0.0.0.0", 0))
            port, next_port = first.getsockname()[1], second.getsockname()[1]

        config = NS(server_port=port, broadcast_host_ip="127.0.0.1", remoteEnabled=lambda: True)
        services.config = NS(Configuration=lambda: config)
        services.joystick_handling = NS(vjoy_id_list=lambda **_: [], VJoyProxy=Mock())
        rpc = ns["RPCGremlin"]()
        self.addCleanup(rpc.stop)
        with patch.dict(ns, GremlinServer=Mock()) as bindings:
            rpc.start()
            rpc.reconfigure()
            bindings["GremlinServer"].assert_not_called()
            self.assertIsNone(rpc.listening_port)

        rpc.enable_startup()
        rpc.start()
        self.assertEqual(rpc.listening_port, port)
        initial_listener = rpc._listener
        rpc.reconfigure()
        self.assertIs(rpc._listener, initial_listener)

        for host, expected_port in (("127.0.0.2", port), ("127.0.0.2", next_port)):
            previous_server, previous_thread = rpc._listener
            config.broadcast_host_ip = host
            config.server_port = expected_port
            real_factory = ns["GremlinServer"]

            def bind_after_close(*args):
                self.assertEqual(previous_server.socket.fileno(), -1)
                self.assertFalse(previous_thread.is_alive())
                return real_factory(*args)

            with patch.dict(ns, GremlinServer=bind_after_close):
                rpc.reconfigure()
            self.assertEqual(rpc.listening_port, expected_port)
            self.assertIsNot(rpc._listener[0], previous_server)

        rpc.stop()
        self.assertIsNone(rpc.listening_port)
        with socket.socket(type=socket.SOCK_DGRAM) as released:
            released.bind(("0.0.0.0", next_port))


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
