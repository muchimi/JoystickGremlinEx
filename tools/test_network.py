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
"""Network scan checks with mocks and loopback UDP: python tools/test_network.py."""

import ast
from collections import deque
import importlib.util
import ipaddress
from pathlib import Path
import socket
import struct
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("network_checks", ROOT / "gremlin/network.py")
NETWORK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NETWORK)

# Use the production OSC codec without importing device or UI services.
OSC = dict(struct=struct)
exec(compile(ast.Module(body=[node for node in ast.parse((ROOT / "gremlin/maestro.py").read_bytes()).body
    if getattr(node, "name", None) in {"_osc_string", "_encode_message", "_decode_message"}],
    type_ignores=[]), "maestro-osc-codec", "exec"), OSC)


class RemoteControlFirewallChecks(unittest.TestCase):
    status = NETWORK.RemoteControlFirewallStatus
    group = NETWORK.REMOTE_CONTROL_MULTICAST_GROUP
    server = "192.0.2.12"

    def rule(self, **changes):
        fields = dict(
            Enabled=True, Direction=1, Protocol=socket.IPPROTO_UDP, Action=1, Profiles=6,
            LocalPorts="6012", RemotePorts="*", LocalAddresses=self.group, RemoteAddresses=self.server,
            ApplicationName="", ServiceName="", Interfaces=None, InterfaceTypes="All",
            LocalAppPackageId="", LocalUserOwner="", LocalUserAuthorizedList="",
            RemoteUserAuthorizedList="", RemoteMachineAuthorizedList="", SecureFlags=0,
        )
        fields.update(changes)
        return SimpleNamespace(**fields)

    def check(self, *rules, host=server, include_unicast=False, modify_state=0):
        policy = SimpleNamespace(CurrentProfileTypes=6, LocalPolicyModifyState=modify_state, Rules=rules)
        source = ipaddress.IPv4Address(host) if host else None
        return NETWORK._multicast_firewall_status(policy, 6012, source, include_unicast)

    def test_checks_destination_source_and_rule_scope(self):
        self.assertIs(self.check(self.rule()), self.status.FOUND)
        self.assertIs(self.check(self.rule(), host=None), self.status.MISSING)
        self.assertIs(self.check(self.rule(RemoteAddresses="*"), host=None), self.status.FOUND)
        self.assertIs(self.check(self.rule(LocalAddresses="*", RemoteAddresses="*")), self.status.FOUND)
        self.assertIs(
            self.check(self.rule(LocalAddresses="224.0.0.0/4", RemoteAddresses="192.0.2.1-192.0.2.20")),
            self.status.FOUND,
        )
        for changes in (
            {"LocalAddresses": "192.0.2.1"}, {"RemoteAddresses": self.group}, {"LocalPorts": "6013"},
            {"RemotePorts": "6012"}, {"Enabled": False}, {"Direction": 2}, {"Protocol": socket.IPPROTO_TCP},
            {"ApplicationName": r"C:\OtherApp\other.exe"}, {"ServiceName": "OtherService"},
            {"LocalUserOwner": "S-1-5-21-1"}, {"SecureFlags": 1},
        ):
            with self.subTest(changes=changes):
                self.assertIs(self.check(self.rule(**changes)), self.status.MISSING)

    def test_applies_active_profiles_and_reports_blocking_policy(self):
        self.assertIs(self.check(self.rule(Profiles=2)), self.status.MISSING)
        self.assertIs(self.check(self.rule(Profiles=2), self.rule(Profiles=4)), self.status.FOUND)
        self.assertIs(self.check(self.rule(), self.rule(Action=0, Profiles=4)), self.status.BLOCKED)
        self.assertIs(self.check(self.rule(), self.rule(Action=0, Profiles=1)), self.status.FOUND)
        self.assertIs(self.check(self.rule(), modify_state=2), self.status.BLOCKED)
        self.assertIs(self.check(modify_state=1), self.status.MANAGED)

    def test_symbolic_addresses_are_skipped_before_ip_parsing(self):
        with patch.object(NETWORK.ipaddress, "ip_address", wraps=ipaddress.ip_address) as parse_address:
            symbolic = self.rule(LocalAddresses="LocalSubnet", RemoteAddresses="LocalSubnet4,DNS")
            self.assertIs(self.check(symbolic), self.status.MISSING)
            parse_address.assert_not_called()

            mixed = self.rule(
                LocalAddresses=f"LocalSubnet, {self.group}",
                RemoteAddresses=f"DNS, LocalSubnet4, {self.server}",
            )
            self.assertIs(self.check(mixed), self.status.FOUND)
            self.assertEqual([call.args[0] for call in parse_address.call_args_list], [self.group, self.server])

    def test_broadcast_server_rule_also_covers_unicast_probe_requests(self):
        self.assertIs(self.check(self.rule(), include_unicast=True), self.status.MISSING)
        self.assertIs(self.check(self.rule(LocalAddresses="*"), include_unicast=True), self.status.FOUND)
        with patch.object(NETWORK, "_run_netsh_elevated", return_value=True) as launch:
            self.assertTrue(NETWORK.addInboundRemoteControlFirewallRule(6012, include_unicast=True))
        command = launch.call_args.args[0]
        self.assertNotIn("localip=", command)
        self.assertNotIn("remoteip=", command)

    def test_creation_places_multicast_group_and_server_in_correct_fields(self):
        with patch.object(NETWORK, "_run_netsh_elevated", return_value=True) as launch:
            self.assertTrue(NETWORK.addInboundRemoteControlFirewallRule(6108, self.server))
            with self.assertRaisesRegex(ValueError, "unicast"):
                NETWORK.addInboundRemoteControlFirewallRule(6108, self.group)
        launch.assert_called_once()
        command = launch.call_args.args[0]
        for field in (
            "dir=in", "action=allow", "enable=yes", "profile=any", "protocol=UDP",
            "localport=6108", f"localip={self.group}", f"remoteip={self.server}",
        ):
            self.assertIn(field, command)
        self.assertNotIn("remoteport=", command)

    def test_reuses_existing_rule_and_confirms_new_rule(self):
        with patch.object(NETWORK, "checkInboundRemoteControlFirewallRule") as read, \
                patch.object(NETWORK, "addInboundRemoteControlFirewallRule", return_value=True) as add:
            for status in (self.status.FOUND, self.status.BLOCKED, self.status.MANAGED):
                read.return_value = status
                self.assertIs(NETWORK.ensureInboundRemoteControlFirewallRule(6012, self.server), status)
            add.assert_not_called()

            read.reset_mock()
            read.side_effect = [self.status.MISSING, self.status.FOUND]
            self.assertIs(NETWORK.ensureInboundRemoteControlFirewallRule(6012, self.server), self.status.FOUND)
            add.assert_called_once_with(6012, self.server, include_unicast=False)
            self.assertEqual(read.call_count, 2)

            read.side_effect = [self.status.MISSING, self.status.MISSING]
            with self.assertRaisesRegex(RuntimeError, "did not report a matching rule"):
                NETWORK.ensureInboundRemoteControlFirewallRule(6012, self.server)

            read.reset_mock()
            read.side_effect = [self.status.MISSING]
            add.return_value = False
            with self.assertRaisesRegex(RuntimeError, "Windows did not add the firewall rule"):
                NETWORK.ensureInboundRemoteControlFirewallRule(6012, self.server)
            self.assertEqual(read.call_count, 1)


class WindowsDiscoveryChecks(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Uses the Windows Shell")
    def test_uses_explorer_computer_paths_and_skips_other_entries(self):
        import pythoncom

        items = [
            SimpleNamespace(IsFolder=True, Path=r"\\Server"),
            SimpleNamespace(IsFolder=True, Path=r"\\server"),
            SimpleNamespace(IsFolder=True, Path=r"\\LocalPC"),
            SimpleNamespace(IsFolder=True, Path=r"\\Server\Share"),
            SimpleNamespace(IsFolder=False, Path="provider://printer"),
        ]
        folder = SimpleNamespace(Items=lambda: items)
        shell = SimpleNamespace(NameSpace=Mock(return_value=folder))
        with (
            patch("win32com.client.Dispatch", return_value=shell) as dispatch,
            patch.object(pythoncom, "CoInitialize") as initialize,
            patch.object(pythoncom, "CoUninitialize") as uninitialize,
            patch.object(NETWORK.socket, "gethostname", return_value="localpc"),
        ):
            self.assertEqual(NETWORK._windows_network_computer_names(), ["Server"])
        dispatch.assert_called_once_with("Shell.Application")
        shell.NameSpace.assert_called_once_with(18)
        initialize.assert_called_once()
        uninitialize.assert_called_once()

    def test_resolves_ipv4_only_for_discovered_computers(self):
        def resolve(name, port, family, kind):
            if name == "Offline":
                raise socket.gaierror("Name unavailable")
            return [(family, kind, 0, "", (ip, 0)) for ip in ("192.0.2.108", "192.0.2.95", "192.0.2.95", "127.0.0.1")]

        with (
            patch.object(NETWORK, "_windows_network_computer_names", return_value=["Offline", "Server"]),
            patch.object(NETWORK.socket, "getaddrinfo", side_effect=resolve) as getaddrinfo,
        ):
            self.assertEqual(NETWORK.discover_windows_computers(), [("Server", "192.0.2.95"), ("Server", "192.0.2.108")])
            self.assertEqual(getaddrinfo.call_count, 2)
            getaddrinfo.assert_called_with("Server", None, socket.AF_INET, socket.SOCK_DGRAM)


class NetworkPortChecks(unittest.TestCase):
    def setUp(self):
        logger = patch.object(NETWORK, "syslog", Mock())
        logger.start()
        self.addCleanup(logger.stop)

    def test_invalid_port_is_rejected_before_socket_creation(self):
        with patch.object(NETWORK.socket, "socket") as factory:
            for port in (None, 0, -1, 65536, "8010", True, 8010.5):
                with self.subTest(port=port), self.assertRaisesRegex(ValueError, "Port must be an integer"):
                    NETWORK.check_port("127.0.0.1", port)
            factory.assert_not_called()

    def test_invalid_port_does_not_create_scan_workers_or_detect_subnet(self):
        with (patch.object(NETWORK.concurrent.futures, "ThreadPoolExecutor") as executor,
              patch.object(NETWORK, "get_local_subnet") as subnet):
            for port in (None, 0, 65536, "8010", True):
                self.assertEqual(NETWORK.scan_network("127.0.0.0/30", port), [])
                self.assertEqual(NETWORK.scan_local_network(port), [])
            executor.assert_not_called()
            subnet.assert_not_called()

    def test_valid_port_is_passed_to_connect_ex(self):
        with patch.object(NETWORK.socket, "socket") as factory:
            connection = factory.return_value.__enter__.return_value
            connection.connect_ex.return_value = 0
            self.assertEqual(NETWORK.check_port("127.0.0.1", 8010), "127.0.0.1")
            connection.settimeout.assert_called_once_with(0.5)
            connection.connect_ex.assert_called_once_with(("127.0.0.1", 8010))

    def test_refused_connection_is_not_reported_as_open(self):
        with patch.object(NETWORK.socket, "socket") as factory:
            factory.return_value.__enter__.return_value.connect_ex.return_value = 10061
            self.assertIsNone(NETWORK.check_port("127.0.0.1", 8010))

    def test_workers_receive_the_validated_port(self):
        with patch.object(NETWORK, "check_port", side_effect=lambda ip, port: str(ip)) as check:
            self.assertEqual(sorted(NETWORK.scan_network("192.0.2.0/30", 9123, 2)), ["192.0.2.1", "192.0.2.2"])
            self.assertEqual(check.call_count, 2)
            self.assertTrue(all(call.args[1] == 9123 for call in check.call_args_list))


class MaestroDiscoveryChecks(unittest.TestCase):
    def setUp(self):
        self.receiver, self.sender = MagicMock(), MagicMock()
        for connection in (self.receiver, self.sender):
            connection.__enter__.return_value = connection
        self.packets = deque()
        self.receiver.recvfrom.side_effect = self.receive
        self.sender.sendto.side_effect = self.reply
        self.deliver = True
        self.service_version = None
        self.requests = []
        self.addCleanup(patch.stopall)
        patch.object(NETWORK, "syslog", Mock()).start()
        patch.object(NETWORK, "get_local_subnet", return_value=("192.168.1.0/24", "192.168.1.95")).start()
        self.tcp = patch.object(NETWORK, "scan_network", return_value=[]).start()
        patch.object(NETWORK.socket, "socket", side_effect=[self.receiver, self.sender]).start()

    def receive(self, size):
        if self.packets:
            return self.packets.popleft()
        raise socket.timeout()

    def reply(self, packet, destination):
        address, args = OSC["_decode_message"](packet)
        self.assertEqual(address, "/maestro_ping")
        if destination == ("192.168.1.111", 8010):
            self.requests.append(args[0])
            if self.deliver:
                values = [args[0], "MaestroOscService", 1]
                if self.service_version is not None:
                    values.append(self.service_version)
                pong = OSC["_encode_message"]("/maestro_pong", values)
                self.packets.append((pong, ("192.168.1.111", 63975)))

    def test_udp_only_maestro_at_expected_host_is_discovered(self):
        self.assertEqual(NETWORK.scan_local_network(8010), ["192.168.1.111"])
        self.receiver.bind.assert_called_once_with(("0.0.0.0", 8011))
        self.tcp.assert_called_once_with("192.168.1.0/24", 8010, 100)
        self.receiver.__exit__.assert_called_once()
        self.sender.__exit__.assert_called_once()

    def test_sending_udp_without_a_pong_does_not_report_an_open_host(self):
        self.deliver = False
        self.assertEqual(NETWORK.scan_local_network(), [])
        self.assertEqual(len(self.requests), 2)  # one retry for a lost datagram
        self.assertEqual(self.requests[0], self.requests[1])

    def test_pong_with_service_version_is_discovered(self):
        for version in ("0.1.3", "12.34.5678"):
            with (self.subTest(version=version),
                  patch.object(NETWORK.socket, "socket", side_effect=[self.receiver, self.sender])):
                self.service_version = version
                self.assertEqual(NETWORK.scan_local_network(), ["192.168.1.111"])

    def test_malformed_versioned_pongs_are_ignored(self):
        def reply(packet, destination):
            if destination[0] != "192.168.1.111":
                return
            request_id = OSC["_decode_message"](packet)[1][0]
            valid = OSC["_encode_message"]("/maestro_pong", [request_id, "MaestroOscService", 1, "0.1.3"])
            invalid = (
                valid[:-1], valid + b"\0\0\0\0", valid[:-8] + b"\xff.1.3\0\0\0",
                OSC["_encode_message"]("/maestro_pong", [request_id, "MaestroOscService", 1, 3]),
                OSC["_encode_message"]("/maestro_pong", [request_id, "MaestroOscService", 2, "0.1.3"]),
            )
            self.packets.extend((data, ("192.168.1.111", 49152)) for data in invalid)

        self.sender.sendto.side_effect = reply
        self.assertEqual(NETWORK.scan_local_network(), [])

    def test_mismatched_requests_and_unrelated_services_are_ignored(self):
        self.deliver = False

        def reply(packet, destination):
            if destination[0] != "192.168.1.111":
                return
            request_id = OSC["_decode_message"](packet)[1][0]
            for args, host in (([request_id ^ 1, "MaestroOscService", 1], "192.168.1.111"),
                               ([request_id, "OtherService", 1], "192.168.1.111"),
                               ([request_id, "MaestroOscService", 1], "203.0.113.1")):
                self.packets.append((OSC["_encode_message"]("/maestro_pong", args), (host, 49152)))
            self.packets.append((b"not OSC", ("192.168.1.111", 49152)))

        self.sender.sendto.side_effect = reply
        self.assertEqual(NETWORK.scan_local_network(), [])

    def test_tcp_and_udp_results_are_deduplicated_and_sorted_numerically(self):
        self.tcp.return_value = ["192.168.1.111", "192.168.1.9"]
        self.assertEqual(NETWORK.scan_local_network(), ["192.168.1.9", "192.168.1.111"])

    def test_custom_reply_port_is_used(self):
        self.assertEqual(NETWORK.scan_local_network(reply_port=9124), ["192.168.1.111"])
        self.receiver.bind.assert_called_once_with(("0.0.0.0", 9124))

    def test_busy_reply_port_is_reported_without_sharing_an_active_client(self):
        self.receiver.bind.side_effect = OSError("reply port already in use")
        self.assertEqual(NETWORK.scan_local_network(), [])
        NETWORK.syslog.warning.assert_called_once()
        self.sender.sendto.assert_not_called()


class LoopbackDiscoveryChecks(unittest.TestCase):
    def test_real_udp_pong_arrives_on_fixed_reply_port_from_an_ephemeral_source(self):
        with (socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as service,
              socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as replies,
              socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation):
            service.bind(("127.0.0.1", 0))
            service.settimeout(0.05)
            port = service.getsockname()[1]
            reservation.bind(("127.0.0.1", 0))
            reply_port = reservation.getsockname()[1]
            reservation.close()
            stopped = threading.Event()
            errors = []

            def respond():
                while not stopped.is_set():
                    try:
                        data, source = service.recvfrom(4096)
                    except socket.timeout:
                        continue
                    try:
                        address, args = OSC["_decode_message"](data)
                        if address == "/maestro_ping":
                            pong = OSC["_encode_message"]("/maestro_pong", [args[0], "MaestroOscService", 1])
                            replies.sendto(pong, (source[0], reply_port))
                    except Exception as error:
                        errors.append(error)
                        return

            worker = threading.Thread(target=respond, daemon=True)
            worker.start()
            try:
                with patch.object(NETWORK, "get_local_subnet", return_value=("127.0.0.0/30", "127.0.0.1")):
                    self.assertEqual(NETWORK.scan_local_network(port, 2, reply_port=reply_port, timeout=0.1),
                                     ["127.0.0.1"])
                self.assertEqual(errors, [])
                self.assertNotEqual(replies.getsockname()[1], port)
            finally:
                stopped.set()
                worker.join(1)
            self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
