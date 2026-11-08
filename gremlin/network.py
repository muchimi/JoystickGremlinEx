# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.



import socket
import concurrent.futures
import ipaddress
import logging
import secrets
import struct
import time

syslog = logging.getLogger("system")

def get_local_subnet():
    """Dynamically find the local machine's IP address and return its /24 subnet."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to an external public IP (no traffic is actually sent)
        # to force the OS to choose the correct active local network interface.
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()

    # Assume a standard home/office /24 subnet based on the local IP
    # (e.g., '192.168.1.5' becomes '192.168.1.0/24')
    interface = ipaddress.ip_interface(f"{local_ip}/24")
    return str(interface.network), local_ip

def check_port(ip, port, timeout=0.5):
    """Check a TCP port; reject invalid ports before opening a socket."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError(f"Port must be an integer from 1 to 65535, got {port!r}")
    try:
        # Create a standard TCP socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            # connect_ex returns 0 if the connection was successful
            result = s.connect_ex((str(ip), port))
            if result == 0:
                return str(ip)
    except (socket.timeout, socket.error):
        pass
    return None

def scan_network(network_str, port, max_threads=100):
    """Scan an entire subnet (e.g., '192.168.1.0/24') for an open port."""
    if type(port) is not int or not 1 <= port <= 65535:
        syslog.error("NET: Invalid scan port %r; expected an integer from 1 to 65535", port)
        return []
    try:
        network = ipaddress.ip_network(network_str, strict=False)
    except ValueError as e:
        syslog.error(f"NET:Invalid network format: {e}")
        return []

    open_hosts = []
    syslog.info(f"NET: Scanning {network_str} on TCP port {port} using {max_threads} threads...")

    # Use ThreadPoolExecutor to run connection attempts concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        # Map futures to each host in the subnet (excluding network/broadcast addresses)
        futures = {executor.submit(check_port, ip, port): ip for ip in network.hosts()}

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                syslog.info(f"NET: [+] Active TCP service found on: {result}:{port}")
                open_hosts.append(result)

    syslog.info("NET: TCP scan complete. Found %s active host(s) on port %s.", len(open_hosts), port)
    return open_hosts

def _osc_string(value):
    data = value.encode("utf-8") + b"\0"
    return data + b"\0" * (-len(data) % 4)


def _scan_maestro_network(network_str, port, reply_port, timeout):
    """Confirm UDP listeners with Maestro's read-only OSC ping/pong exchange."""
    targets = {str(ip) for ip in ipaddress.ip_network(network_str, strict=False).hosts()}
    hosts = set()
    request_id = struct.pack(">i", secrets.randbits(31))
    ping = _osc_string("/maestro_ping") + _osc_string(",i") + request_id
    pong = (_osc_string("/maestro_pong") + _osc_string(",isi") + request_id
            + _osc_string("MaestroOscService") + struct.pack(">i", 1))
    try:
        with (socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver,
              socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender):
            # Maestro replies to a fixed port, from an ephemeral source port.
            # Do not share a live client's reply socket or consume its replies.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                receiver.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            receiver.bind(("0.0.0.0", reply_port))
            for _ in range(2):
                pending = targets - hosts
                if not pending:
                    break
                for host in pending:
                    try:
                        sender.sendto(ping, (host, port))
                    except OSError:
                        continue
                deadline = time.monotonic() + timeout
                while (remaining := deadline - time.monotonic()) > 0:
                    receiver.settimeout(remaining)
                    try:
                        data, source = receiver.recvfrom(4096) # @IgnoreException
                    except socket.timeout:
                        break
                    except ConnectionResetError:
                        continue
                    if source[0] in targets and data == pong:
                        if source[0] not in hosts:
                            syslog.info("NET: Active Maestro UDP service found on %s:%s", source[0], port)
                        hosts.add(source[0])
    except OSError as error:
        syslog.warning("NET: Maestro UDP discovery on reply port %s failed: %s", reply_port, error)
    return hosts


def scan_local_network(port=8010, max_threads=100, *, reply_port=8011, timeout=1.0):
    """Return local /24 hosts with a TCP listener or confirmed Maestro UDP service.

    Maestro listens on UDP 8010 and replies to UDP 8011 by default. A UDP send
    alone cannot establish availability, so only matching pong replies count.
    ``reply_port`` must match the service's configured OSC send port and be free.
    """
    if type(port) is not int or not 1 <= port <= 65535:
        syslog.error("NET: Invalid scan port %r; expected an integer from 1 to 65535", port)
        return []
    if type(reply_port) is not int or not 1 <= reply_port <= 65535:
        raise ValueError("Reply port must be an integer from 1 to 65535")
    if timeout <= 0:
        raise ValueError("Scan timeout must be positive")
    network_str, local_ip = get_local_subnet()
    hosts = _scan_maestro_network(network_str, port, reply_port, timeout)
    hosts.update(scan_network(network_str, port, max_threads))
    syslog.info("NET: Local scan complete. Found %s active host(s) on port %s.", len(hosts), port)
    return sorted(hosts, key=ipaddress.ip_address)
