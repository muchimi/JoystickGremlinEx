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


import concurrent.futures
import ctypes
import ipaddress
import logging
import os
import secrets
import socket
import struct
import sys
import time
from ctypes import wintypes
from enum import Enum

syslog = logging.getLogger("system")

REMOTE_CONTROL_MULTICAST_GROUP = "224.3.29.72"


def get_local_subnet():
    """Dynamically find the local machine's IP address and return its /24 subnet."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to an external public IP (no traffic is actually sent)
        # to force the OS to choose the correct active local network interface.
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except Exception:  # noqa: BLE001
        local_ip = "127.0.0.1"
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
    except socket.timeout, socket.error:  # noqa: UP024, UP041
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
    pong = (
        _osc_string("/maestro_pong")
        + _osc_string(",isi")
        + request_id
        + _osc_string("MaestroOscService")
        + struct.pack(">i", 1)
    )
    versioned_pong = (
        _osc_string("/maestro_pong")
        + _osc_string(",isis")
        + request_id
        + _osc_string("MaestroOscService")
        + struct.pack(">i", 1)
    )
    try:
        with (
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver,
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender,
        ):
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
                        data, source = receiver.recvfrom(4096)  # @IgnoreException
                    except socket.timeout:  # noqa: UP041
                        break
                    except ConnectionResetError:
                        continue
                    if source[0] not in targets:
                        continue
                    valid_pong = data == pong
                    if data.startswith(versioned_pong):
                        try:
                            version = data[len(versioned_pong) :].split(b"\0", 1)[0].decode("utf-8")
                        except UnicodeDecodeError:
                            continue
                        valid_pong = data == versioned_pong + _osc_string(version)
                    if valid_pong:
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
    network_str, _ = get_local_subnet()
    hosts = _scan_maestro_network(network_str, port, reply_port, timeout)
    hosts.update(scan_network(network_str, port, max_threads))
    syslog.info("NET: Local scan complete. Found %s active host(s) on port %s.", len(hosts), port)
    return sorted(hosts, key=ipaddress.ip_address)


def _windows_network_computer_names():
    import pythoncom
    from win32com.client import Dispatch
    from win32com.shell import shellcon  # type: ignore

    names = {}
    local_name = socket.gethostname().casefold()
    pythoncom.CoInitialize()
    try:
        network = Dispatch("Shell.Application").NameSpace(shellcon.CSIDL_NETWORK)
        if network is not None:
            for item in network.Items():
                if not item.IsFolder:
                    continue
                path = item.Path
                # Explorer's Network folder also lists devices and shares. Computers have a bare UNC path.
                if isinstance(path, str) and path.startswith("\\\\"):
                    name = path[2:].rstrip("\\")
                    if name and "\\" not in name and name.casefold() != local_name:
                        names.setdefault(name.casefold(), name)
    except pythoncom.com_error as err:
        raise OSError("Could not read Windows Network Discovery.") from err
    finally:
        pythoncom.CoUninitialize()
    return sorted(names.values(), key=str.casefold)


def _resolve_discovered_computer(name):
    try:
        records = socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_DGRAM)  # @IgnoreException
    except socket.gaierror:
        return []

    addresses = {ipaddress.IPv4Address(record[4][0]) for record in records}
    return [
        (name, str(address))
        for address in sorted(addresses)
        if not (address.is_loopback or address.is_unspecified or address.is_multicast or int(address) == 0xFFFFFFFF)
    ]


def discover_windows_computers() -> list[tuple[str, str]]:
    """Return other computers from Explorer's Network folder with their resolved IPv4 addresses."""
    names = _windows_network_computer_names()
    if not names:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(names))) as executor:
        return [entry for computer in executor.map(_resolve_discovered_computer, names) for entry in computer]


SEE_MASK_NOCLOSEPROCESS = 0x00000040
INFINITE = 0xFFFFFFFF
SW_HIDE = 0  # Hides the netsh console flash after UAC is accepted


class SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _run_netsh_elevated(params):
    """Executes netsh.exe prompting for UAC elevation (admin rights) if needed, and returns True on success"""
    import win32api

    sei = SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = os.path.join(win32api.GetSystemDirectory(), "netsh.exe")
    sei.lpParameters = params
    sei.nShow = SW_HIDE

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        error = ctypes.get_last_error()
        if error == 1223:  # ERROR_CANCELLED
            return False
        raise ctypes.WinError(error)

    if not sei.hProcess:
        raise RuntimeError("Windows did not return a handle for the firewall command.")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process = wintypes.HANDLE(sei.hProcess)
    exit_code = wintypes.DWORD()
    try:
        if kernel32.WaitForSingleObject(process, wintypes.DWORD(INFINITE)) != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(process)
    return exit_code.value == 0


def addFirewallRule(
    rule_name: str,
    direction: str = "in",
    action: str = "allow",
    protocol: str = "UDP",  # or "TCP"
    local_port: int | None = None,
    program_path: str | None = None,
    *,
    local_address: str | None = None,
    remote_host: str | None = None,
):
    """add a firewall rule"""
    args = [
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f'name="{rule_name}"',
        f"dir={direction}",
        f"action={action}",
        "enable=yes",
        "profile=any",
    ]

    if program_path:
        args.append(f'program="{program_path}"')

    if local_port:
        args.append(f"protocol={protocol}")
        args.append(f"localport={local_port}")

    if local_address is not None:
        args.append(f"localip={ipaddress.ip_address(local_address)}")
    if remote_host is not None:
        args.append(f"remoteip={ipaddress.ip_address(remote_host)}")

    return _run_netsh_elevated(" ".join(args))


def removeFirewallRule(
    rule_name: str,
    direction: str | None = None,
    protocol: str | None = None,  # "UDP" or "TCP"
    local_port: int | None = None,
    program_path: str | None = None,
):
    """Removes all firewall rules matching the given name and optional filters."""
    args = [
        "advfirewall",
        "firewall",
        "delete",
        "rule",
        f'name="{rule_name}"',
    ]

    # Optional filters to narrow down which rule gets deleted if names are shared
    if direction:
        args.append(f"dir={direction}")
    if program_path:
        args.append(f'program="{program_path}"')
    if protocol:
        args.append(f"protocol={protocol}")
    if local_port:
        args.append(f"localport={local_port}")

    return _run_netsh_elevated(" ".join(args))


def _unrestricted(field):
    return (field or "").strip().casefold() in ("", "*", "any")


def _host_matches(target_ip, addresses):
    """Checks whether a firewall address list covers the requested address or scope."""
    if _unrestricted(addresses):
        return True
    if target_ip is None:
        return False

    for entry in addresses.split(","):
        entry = entry.strip()
        # Windows can return symbolic scopes such as LocalSubnet alongside literal addresses.
        # Leave those dynamic scopes to Windows and keep matching the explicit entries.
        if "." not in entry and ":" not in entry:
            continue
        try:
            # Handles single IPs (192.168.1.50) and CIDR blocks (192.168.1.0/24 or 192.168.1.50/32)
            if "/" in entry:
                if target_ip in ipaddress.ip_network(entry, strict=False):
                    return True
            # Handles explicit IP ranges (192.168.1.10-192.168.1.50)
            elif "-" in entry:
                start_str, end_str = entry.split("-", 1)
                start_ip = ipaddress.ip_address(start_str.strip())
                end_ip = ipaddress.ip_address(end_str.strip())
                if type(target_ip) is type(start_ip) and start_ip <= target_ip <= end_ip:
                    return True
            else:
                if target_ip == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            continue

    return False


def _port_matches(target_port, port_field):
    """Checks whether a firewall port list includes the requested port."""
    if _unrestricted(port_field):
        return True
    for part in port_field.split(","):
        part = part.strip()
        if part.isdigit() and int(part) == target_port:
            return True
        if "-" in part:
            start, end = part.split("-", 1)
            if start.isdigit() and end.isdigit() and int(start) <= target_port <= int(end):
                return True

    return False


class RemoteControlFirewallStatus(Enum):
    FOUND = "found"
    MISSING = "missing"
    BLOCKED = "blocked"
    MANAGED = "managed"


def _remote_control_source(port, host):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid UDP port.")
    if host is None:
        return None
    source = ipaddress.IPv4Address(host)
    if source.is_multicast or source.is_unspecified or int(source) == 0xFFFFFFFF:
        raise ValueError("Enter the server's unicast IPv4 address.")
    return source


def addInboundRemoteControlFirewallRule(port: int, host: str | None = None, *, include_unicast=False):
    """Adds an inbound UDP rule for the selected source on the configured port."""
    source = _remote_control_source(port, host)
    traffic = "UDP" if include_unicast else "Multicast UDP"
    return addFirewallRule(
        f"GremlinEx Remote Control {traffic} {port} ({source or 'Any host'})",
        local_port=port,
        local_address=None if include_unicast else REMOTE_CONTROL_MULTICAST_GROUP,
        remote_host=str(source) if source is not None else None,
    )


def _multicast_firewall_status(policy, port, source, include_unicast):
    active_profiles = policy.CurrentProfileTypes or 7  # Domain, Private and Public when offline
    modify_state = policy.LocalPolicyModifyState
    if modify_state == 2:  # NET_FW_MODIFY_STATE_INBOUND_BLOCKED
        return RemoteControlFirewallStatus.BLOCKED

    group = ipaddress.IPv4Address(REMOTE_CONTROL_MULTICAST_GROUP)
    executable = os.path.normcase(os.path.normpath(sys.executable))
    allowed_profiles = 0
    for rule in policy.Rules:
        if not rule.Enabled or rule.Direction != 1 or rule.Protocol not in (socket.IPPROTO_UDP, 256):
            continue  # NET_FW_RULE_DIR_IN and the Windows protocol value for Any
        profiles = rule.Profiles & active_profiles
        if not profiles or not _port_matches(port, rule.LocalPorts) or not _unrestricted(rule.RemotePorts):
            continue
        if not _host_matches(group, rule.LocalAddresses) or not _host_matches(source, rule.RemoteAddresses):
            continue
        program = rule.ApplicationName
        if program and os.path.normcase(os.path.normpath(os.path.expandvars(program))) != executable:
            continue
        if (
            rule.ServiceName
            or rule.LocalAppPackageId
            or rule.LocalUserOwner
            or rule.LocalUserAuthorizedList
            or rule.RemoteUserAuthorizedList
            or rule.RemoteMachineAuthorizedList
            or rule.SecureFlags
        ):
            continue
        if rule.Interfaces or (rule.InterfaceTypes or "").casefold() not in ("", "all"):
            continue
        if rule.Action == 0:  # NET_FW_ACTION_BLOCK
            return RemoteControlFirewallStatus.BLOCKED
        if rule.Action == 1 and (not include_unicast or _unrestricted(rule.LocalAddresses)):
            allowed_profiles |= profiles

    if allowed_profiles == active_profiles:
        return RemoteControlFirewallStatus.FOUND
    if modify_state == 1:  # NET_FW_MODIFY_STATE_GP_OVERRIDE
        return RemoteControlFirewallStatus.MANAGED
    return RemoteControlFirewallStatus.MISSING


def checkInboundRemoteControlFirewallRule(port: int, host: str | None = None, *, include_unicast=False):
    """Reads Windows Firewall rules without requiring elevation."""
    import pythoncom
    from win32com.client import Dispatch

    source = _remote_control_source(port, host)
    pythoncom.CoInitialize()
    try:
        return _multicast_firewall_status(Dispatch("HNetCfg.FwPolicy2"), port, source, include_unicast)
    except pythoncom.com_error as err:
        raise OSError("Could not read the Windows Firewall rules.") from err
    finally:
        pythoncom.CoUninitialize()


def ensureInboundRemoteControlFirewallRule(port: int, host: str | None = None, *, include_unicast=False):
    """Creates a rule only when missing and confirms Windows can see it."""
    status = checkInboundRemoteControlFirewallRule(port, host, include_unicast=include_unicast)
    if status is not RemoteControlFirewallStatus.MISSING:
        return status
    if not addInboundRemoteControlFirewallRule(port, host, include_unicast=include_unicast):
        raise RuntimeError(
            "Windows did not add the firewall rule. The administrator prompt may have been declined or the command may have failed."
        )

    status = checkInboundRemoteControlFirewallRule(port, host, include_unicast=include_unicast)
    if status is RemoteControlFirewallStatus.MISSING:
        raise RuntimeError("Windows did not report a matching rule after the add command.")
    return status
