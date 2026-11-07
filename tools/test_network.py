"""Socket-free network scan regressions: python tools/test_network.py."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("network_checks", ROOT / "gremlin/network.py")
NETWORK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NETWORK)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
