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
"""Exercise the installer PowerShell OSC probe against a fake localhost bridge.

Run: python tools/test_installer_bridge_ping.py
No installed bridge, vJoy, external network or installer execution is required.
"""

import base64
import json
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")


def osc_string(value):
    data = value.encode("utf-8") + b"\0"
    return data + b"\0" * (-len(data) % 4)


def pong(request_id, name="MaestroOscService", version=1, service_version=None):
    tags = ",isi" if service_version is None else ",isis"
    return (osc_string("/maestro_pong") + osc_string(tags) + struct.pack(">i", request_id)
            + osc_string(name) + struct.pack(">i", version)
            + (b"" if service_version is None else osc_string(service_version)))


@unittest.skipUnless(POWERSHELL, "Requires Windows PowerShell")
class InstallerBridgePingTests(unittest.TestCase):
    def probe(self, mode="connected", through_connection=False):
        bridge = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bridge.bind(("127.0.0.1", 0))
        bridge.settimeout(0.05)
        self.addCleanup(bridge.close)
        reply_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            reply_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        reply_socket.bind(("127.0.0.1", 0))
        reply_port = reply_socket.getsockname()[1]
        self.addCleanup(reply_socket.close)
        if mode != "port_unavailable":
            reply_socket.close()

        stop = threading.Event()
        packets, errors = [], []

        def serve():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.bind(("127.0.0.1", 0))  # Service replies also have an ephemeral source port.
                while not stop.is_set():
                    try:
                        packet, _ = bridge.recvfrom(4096)
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                    packets.append(packet)
                    try:
                        self.assertEqual(packet[:20], osc_string("/maestro_ping") + osc_string(",i"))
                        self.assertEqual(len(packet), 24)
                        request_id = struct.unpack(">i", packet[20:])[0]
                        self.assertGreater(request_id, 0)
                        if mode == "timeout":
                            continue
                        # Lifecycle notifications and unrelated packets must not count as a pong.
                        sender.sendto(osc_string("/maestro_start") + osc_string(","), ("127.0.0.1", reply_port))
                        if mode == "wrong_request":
                            response = pong(request_id + 1)
                        elif mode == "wrong_service":
                            response = pong(request_id, name="AnotherService")
                        elif mode == "wrong_protocol":
                            response = pong(request_id, version=2)
                        elif mode == "truncated":
                            response = pong(request_id)[:-1]
                        elif mode == "versioned":
                            response = pong(request_id, service_version="0.1.3")
                        elif mode == "truncated_version":
                            response = pong(request_id, service_version="0.1.3")[:-1]
                        elif mode == "wrong_protocol_versioned":
                            response = pong(request_id, version=2, service_version="0.1.3")
                        else:
                            response = pong(request_id)
                        sender.sendto(response, ("127.0.0.1", reply_port))
                    except Exception as error:
                        errors.append(error)
                        return

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        helper = str(ROOT / "installer" / "dependencies.ps1").replace("'", "''")
        script = f". '{helper}' -Component bridge\n"
        if through_connection:
            # Even unexpected remote metadata must not redirect the installer probe.
            script += ("function Get-BridgeProbeSettings($Installation) { [pscustomobject]@{"
                       f"Address = '192.0.2.210'; ReceivePort = {bridge.getsockname()[1]}; SendPort = {reply_port}"
                       "} }\nTest-BridgeConnection ([pscustomobject]@{Installed = $true}) | ConvertTo-Json -Compress")
        else:
            script += (f"Test-BridgeOscPing -ReceivePort {bridge.getsockname()[1]} "
                       f"-SendPort {reply_port} -TimeoutMilliseconds 200 | ConvertTo-Json -Compress")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        try:
            result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                     "-EncodedCommand", encoded],
                                    capture_output=True, text=True, timeout=12)
        finally:
            stop.set()
            worker.join(timeout=1)
        self.assertEqual(errors, [])
        self.assertEqual(result.returncode, 0, result.stderr)
        outcome = json.loads(result.stdout)
        if mode != "port_unavailable":
            self.assertEqual(len(packets), 1)
        return outcome

    def test_valid_pong_checks_identity_protocol_and_configured_ports(self):
        result = self.probe()
        self.assertEqual(result["State"], "connected")
        self.assertIn("OSC protocol 1", result["Message"])
        self.assertIn("localhost", result["Message"])

    def test_installer_connection_always_pings_localhost(self):
        result = self.probe(through_connection=True)
        self.assertEqual(result["State"], "connected")
        self.assertIn("127.0.0.1", result["Message"])

    def test_versioned_pong_is_accepted(self):
        self.assertEqual(self.probe("versioned")["State"], "connected")

    def test_invalid_versioned_pongs_are_rejected(self):
        for mode in ("truncated_version", "wrong_protocol_versioned"):
            with self.subTest(mode=mode):
                self.assertEqual(self.probe(mode)["State"], "failed")

    def test_wrong_request_id_is_rejected(self):
        self.assertEqual(self.probe("wrong_request")["State"], "failed")

    def test_wrong_service_is_rejected(self):
        self.assertEqual(self.probe("wrong_service")["State"], "failed")

    def test_wrong_protocol_is_rejected(self):
        self.assertEqual(self.probe("wrong_protocol")["State"], "failed")

    def test_truncated_packet_is_rejected(self):
        self.assertEqual(self.probe("truncated")["State"], "failed")

    def test_no_reply_times_out(self):
        result = self.probe("timeout")
        self.assertEqual(result["State"], "failed")
        self.assertIn("localhost", result["Message"])

    def test_busy_reply_port_is_reported_without_sharing_it(self):
        result = self.probe("port_unavailable")
        self.assertEqual(result["State"], "port_unavailable")
        self.assertIn("Close GEX", result["Message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
