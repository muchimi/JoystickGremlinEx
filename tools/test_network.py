"""Network scan checks with mocks and loopback UDP: python tools/test_network.py."""

import ast
from collections import deque
import importlib.util
from pathlib import Path
import socket
import struct
import threading
import unittest
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
                pong = OSC["_encode_message"]("/maestro_pong", [args[0], "MaestroOscService", 1])
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
