"""Hardware-free startup checks: python tools/test_virtual_output_startup.py."""

import ast
from contextlib import nullcontext
import importlib.util
import logging
from pathlib import Path
import socket
import sys
import threading
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from shiboken6 import Shiboken

from test_maestro_startup import Maestro, NAMESPACE as MAESTRO_NAMESPACE

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STARTUP = load_module('virtual_output_startup_checks', 'gremlin/virtual_output_startup.py')


class OptionalVJoyChecks(unittest.TestCase):
    def setUp(self):
        self.module = load_module('optional_vjoy_checks', 'vjoy/vjoy_interface.py')
        self.interface = self.module.VJoyInterface
        self.util = ModuleType('gremlin.util')
        self.util.get_dll_version = Mock(return_value='2.2.1.0')
        self.util.version_valid = Mock(return_value=True)
        services = ModuleType('gremlin')
        services.util = self.util
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {'gremlin': services, 'gremlin.util': self.util}).start()
        self.module.syslog = Mock()
        patch.object(self.interface, '_is_ui_thread', return_value=True).start()
        self.exists = patch.object(self.module.os.path, 'isfile', return_value=True).start()
        self.dll = NS(**{name: Mock(return_value=0) for name in self.interface.api_functions})
        self.load = patch.object(self.module.ctypes.cdll, 'LoadLibrary', return_value=self.dll).start()
        self.exit = patch.object(self.module.os, '_exit', side_effect=AssertionError('Startup must not exit.')).start()

    def assert_unavailable(self):
        self.assertFalse(self.interface.valid)
        self.assertTrue(self.interface.initialization_error)
        self.assertFalse(self.interface.vJoyEnabled())
        self.assertEqual(self.interface.GetVJDStatus(1), self.module.VJoyState.Missing.value)
        self.assertFalse(self.interface.AcquireVJD(1))
        self.assertEqual(self.interface.GetVJDButtonNumber(1), 0)
        self.interface.RelinquishVJD(1)
        self.exit.assert_not_called()

    def test_missing_dll_is_optional(self):
        self.exists.return_value = False
        self.assertFalse(self.interface.initialize())
        self.assert_unavailable()
        self.load.assert_not_called()

    def test_outdated_or_unreadable_dll_is_optional(self):
        self.util.version_valid.return_value = False
        self.assertFalse(self.interface.initialize())
        self.assert_unavailable()
        self.util.get_dll_version.side_effect = OSError('No version resource')
        self.assertFalse(self.interface.initialize())
        self.assert_unavailable()

    def test_dll_load_failure_is_optional(self):
        self.load.side_effect = OSError('Driver dependency missing')
        self.assertFalse(self.interface.initialize())
        self.assert_unavailable()

    def test_missing_export_disables_all_api_calls(self):
        del self.dll.GetVJDButtonNumber
        self.assertFalse(self.interface.initialize())
        self.assert_unavailable()
        self.dll.GetVJDStatus.assert_not_called()

    def test_available_dll_can_be_used_after_missing_dll(self):
        self.exists.return_value = False
        self.assertFalse(self.interface.initialize())
        self.exists.return_value = True
        self.dll.vJoyEnabled.return_value = True
        self.assertTrue(self.interface.initialize())
        self.assertTrue(self.interface.valid)
        self.assertIsNone(self.interface.initialization_error)
        self.assertTrue(self.interface.vJoyEnabled())
        self.dll.vJoyEnabled.assert_called_once_with()

    def test_shutdown_without_dll_keeps_queries_safe(self):
        self.interface.shutdown()
        self.assertFalse(self.interface.valid)
        self.assertFalse(self.interface.vJoyEnabled())
        self.assertEqual(self.interface.GetVJDStatus(1), self.module.VJoyState.Missing.value)


class VJoyInstallationChecks(unittest.TestCase):
    def setUp(self):
        self.config = NS(vjoy_installed=False)
        self.interface = NS(valid=True, vJoyEnabled=Mock(return_value=False), GetVJDStatus=Mock(return_value=1))
        self.addCleanup(patch.stopall)
        patch.object(STARTUP, 'VJoyInterface', self.interface).start()
        self.registry = patch.object(STARTUP, '_machine_key_exists', return_value=False).start()
        patch.object(STARTUP, 'syslog', Mock()).start()

    def test_stale_registry_does_not_count_as_an_installed_driver(self):
        self.registry.return_value = True
        self.assertFalse(STARTUP.vjoy_installed(self.config))
        self.interface.vJoyEnabled.assert_called_once_with()
        self.interface.GetVJDStatus.assert_not_called()

    def test_cached_installed_flag_does_not_override_the_dll(self):
        self.config.vjoy_installed = True
        self.assertFalse(STARTUP.vjoy_installed(self.config))
        self.interface.vJoyEnabled.assert_called_once_with()

    def test_a_loaded_dll_without_a_responding_driver_is_not_an_installation(self):
        self.assertFalse(STARTUP.vjoy_installed(self.config))
        self.interface.vJoyEnabled.assert_called_once_with()

    def test_a_responding_driver_is_detected_with_or_without_registry_data(self):
        self.interface.vJoyEnabled.return_value = True
        for registered in (False, True):
            with self.subTest(registered=registered):
                self.registry.return_value = registered
                self.assertTrue(STARTUP.vjoy_installed(self.config))

    def test_missing_or_invalid_dll_does_not_count_as_an_installed_driver(self):
        self.registry.return_value = True
        self.config.vjoy_installed = True
        self.interface.valid = False
        self.assertFalse(STARTUP.vjoy_installed(self.config))
        self.interface.vJoyEnabled.assert_not_called()

    def test_dll_query_errors_do_not_claim_an_installed_driver(self):
        self.registry.return_value = True
        self.config.vjoy_installed = True
        for error in (OSError('Driver unavailable'), RuntimeError('DLL query failed')):
            with self.subTest(error=error):
                self.interface.vJoyEnabled.side_effect = error
                self.assertFalse(STARTUP.vjoy_installed(self.config))

    def test_responding_driver_with_no_defined_device_is_not_installed(self):
        self.config.vjoy_installed = self.registry.return_value = True
        self.interface.vJoyEnabled.return_value = True
        for status in (3, 4, -1, 99):
            with self.subTest(status=status):
                self.interface.GetVJDStatus.reset_mock()
                self.interface.GetVJDStatus.return_value = status
                self.assertFalse(STARTUP.vjoy_installed(self.config))
                self.assertEqual([call.args[0] for call in self.interface.GetVJDStatus.call_args_list],
                                 list(range(1, 17)))

    def test_a_defined_device_in_slot_16_counts_even_when_owned_or_busy(self):
        self.interface.vJoyEnabled.return_value = True
        for status in (0, 1, 2):
            with self.subTest(status=status):
                self.interface.GetVJDStatus.reset_mock()
                self.interface.GetVJDStatus.side_effect = lambda device_id: status if device_id == 16 else 3
                self.assertTrue(STARTUP.vjoy_installed(self.config))
                self.assertEqual([call.args[0] for call in self.interface.GetVJDStatus.call_args_list],
                                 list(range(1, 17)))

    def test_device_status_query_error_does_not_claim_an_installation(self):
        self.interface.vJoyEnabled.return_value = True
        self.interface.GetVJDStatus.side_effect = OSError('Device query failed')
        self.assertFalse(STARTUP.vjoy_installed(self.config))


class BridgeInstallationChecks(unittest.TestCase):
    def setUp(self):
        self.registry = {}
        self.files = set()
        self.addCleanup(patch.stopall)
        self.lookup = patch.object(STARTUP.psutil, 'win_service_get',
            side_effect=STARTUP.psutil.NoSuchProcess(pid=None, name='GEXMaestroBridgeService')).start()
        patch.object(STARTUP.winreg, 'OpenKey', side_effect=self.open_key).start()
        patch.object(STARTUP.winreg, 'QueryValueEx', side_effect=self.query_value).start()
        self.exists = patch.object(STARTUP.Path, 'is_file', autospec=True,
                                   side_effect=lambda path: str(path) in self.files).start()

    def open_key(self, root, path, reserved, access):
        view = access & (STARTUP.winreg.KEY_WOW64_64KEY | STARTUP.winreg.KEY_WOW64_32KEY)
        key = (path, view)
        if key not in self.registry:
            raise FileNotFoundError(path)
        return nullcontext(key)

    def query_value(self, key, name):
        if name not in self.registry[key]:
            raise FileNotFoundError(name)
        value = self.registry[key][name]
        return (value, STARTUP.winreg.REG_SZ) if isinstance(value, str) else value

    def register(self, path, values, view=None):
        self.registry[(path, view or STARTUP.winreg.KEY_WOW64_64KEY)] = values

    def service(self, status):
        self.lookup.side_effect = None
        service = self.lookup.return_value = Mock()
        service.status.return_value = status
        return service

    def test_running_service_is_detected_without_assuming_a_directory(self):
        service = self.service('running')
        self.assertTrue(STARTUP.bridge_installed())
        self.assertTrue(STARTUP.bridge_installed(require_running=True))
        self.lookup.assert_called_with('GEXMaestroBridgeService')
        service.status.assert_called_once_with()
        self.exists.assert_not_called()

    def test_stopped_paused_or_pending_service_is_installed_but_not_running(self):
        for status in ('stopped', 'paused', 'start_pending', 'stop_pending'):
            with self.subTest(status=status):
                self.service(status)
                self.assertTrue(STARTUP.bridge_installed())
                self.assertFalse(STARTUP.bridge_installed(require_running=True))

    def test_custom_service_image_path_with_arguments(self):
        executable = r'D:\Custom Bridge Folder\GEXMaestroBridgeService.exe'
        self.register(STARTUP._BRIDGE_SERVICE_KEY, {'ImagePath': f'"{executable}" --receive-port 9123'})
        self.files.add(executable)
        self.assertTrue(STARTUP.bridge_installed())
        self.assertFalse(STARTUP.bridge_installed(require_running=True))

    def test_unquoted_service_path_and_environment_variables(self):
        executable = r'E:\Bridge Folder\GEXMaestroBridgeService.exe'
        self.files.add(executable)
        for command in (f'{executable} --mock', r'"%GEX_TEST_BRIDGE%\GEXMaestroBridgeService.exe" --mock'):
            with self.subTest(command=command), patch.dict(STARTUP.os.environ, GEX_TEST_BRIDGE=r'E:\Bridge Folder'):
                self.register(STARTUP._BRIDGE_SERVICE_KEY,
                              {'ImagePath': (command, STARTUP.winreg.REG_EXPAND_SZ)})
                self.assertTrue(STARTUP.bridge_installed())

    def test_console_install_location_in_either_registry_view(self):
        location = r'D:\Apps\Bridge Console'
        for view in (STARTUP.winreg.KEY_WOW64_64KEY, STARTUP.winreg.KEY_WOW64_32KEY):
            with self.subTest(view=view):
                self.registry.clear()
                self.register(STARTUP._BRIDGE_UNINSTALL_KEY, {'InstallLocation': location}, view)
                self.files.add(str(Path(location) / 'GEXMaestroBridgeService.exe'))
                self.assertTrue(STARTUP.bridge_installed())
                self.assertFalse(STARTUP.bridge_installed(require_running=True))

    def test_stale_registration_without_an_executable_is_not_an_installation(self):
        self.register(STARTUP._BRIDGE_UNINSTALL_KEY, {'InstallLocation': r'D:\Removed Bridge'})
        self.assertFalse(STARTUP.bridge_installed())
        self.assertFalse(STARTUP.bridge_installed(require_running=True))

    def test_program_files_is_not_used_as_an_unregistered_fallback(self):
        self.files.add(r'C:\Program Files\GEXMaestroBridge\GEXMaestroBridgeService.exe')
        self.assertFalse(STARTUP.bridge_installed())
        self.exists.assert_not_called()

    def test_service_status_errors_do_not_claim_a_running_service(self):
        for error in (STARTUP.psutil.AccessDenied(name='GEXMaestroBridgeService'), OSError('Service query failed')):
            with self.subTest(error=error):
                self.lookup.side_effect = error
                self.assertFalse(STARTUP.bridge_installed(require_running=True))


class StartupProviderChecks(unittest.TestCase):
    def setUp(self):
        self.config = NS(vjoy_installed=False, maestro_enabled=False, maestro_use_localhost=True)
        self.maestro = NS(enabled=False, service_running=False, connect=Mock(return_value=None), refreshDevices=Mock())
        self.addCleanup(patch.stopall)
        self.interface = NS(valid=True, vJoyEnabled=Mock(return_value=False), GetVJDStatus=Mock(return_value=1))
        patch.object(STARTUP, 'VJoyInterface', self.interface).start()
        self.registry = patch.object(STARTUP, '_machine_key_exists', return_value=False).start()
        self.installed = patch.object(STARTUP, 'bridge_installed', return_value=False).start()
        self.install = patch.object(STARTUP, 'install_bridge', return_value=0).start()
        buttons = STARTUP.QtWidgets.QMessageBox.StandardButton
        self.box = patch.object(STARTUP.QtWidgets, 'QMessageBox').start()
        self.box.StandardButton = buttons
        patch.object(STARTUP, 'syslog', Mock()).start()
        self.box.question.return_value = self.box.StandardButton.No

    def check(self, vjoy=False):
        return STARTUP.check_virtual_output(self.config, self.maestro, vjoy)

    def test_vjoy_only_and_maestro_only_start_without_dialogs(self):
        self.assertTrue(self.check(vjoy=True))
        self.maestro.enabled = self.maestro.service_running = True
        self.assertTrue(self.check())
        self.box.question.assert_not_called()
        self.box.warning.assert_not_called()
        self.install.assert_not_called()

    def test_neither_provider_offers_setup_and_decline_continues(self):
        self.assertFalse(self.check())
        self.box.question.assert_called_once()
        self.install.assert_not_called()
        self.box.warning.assert_not_called()

    def test_installed_but_unavailable_bridge_is_not_reinstalled(self):
        self.installed.return_value = True
        self.assertFalse(self.check())
        self.box.question.assert_not_called()
        self.box.warning.assert_called_once()
        self.install.assert_not_called()

    def test_stopped_local_service_explains_how_to_start_it_without_reinstalling(self):
        self.installed.side_effect = lambda require_running=False: not require_running
        self.assertFalse(self.check())
        self.box.question.assert_not_called()
        self.install.assert_not_called()
        self.assertIn('Start GEXMaestroBridgeService', self.box.warning.call_args.args[2])
        self.installed.assert_called_with(require_running=True)

    def test_running_local_service_with_no_connection_points_to_osc_settings(self):
        self.installed.return_value = True
        self.config.maestro_enabled = True
        self.assertFalse(self.check())
        self.assertIn('Windows service is running', self.box.warning.call_args.args[2])
        self.assertIn('service/reply ports', self.box.warning.call_args.args[2])
        self.box.question.assert_not_called()
        self.install.assert_not_called()

    def test_remote_configuration_does_not_check_local_service_health(self):
        self.config.maestro_use_localhost = False
        self.installed.return_value = True
        self.assertFalse(self.check())
        self.installed.assert_called_once_with()

    def test_installed_but_unconfigured_vjoy_warns_without_setup(self):
        self.config.vjoy_installed = True
        self.interface.vJoyEnabled.return_value = True
        self.assertFalse(self.check())
        self.box.question.assert_not_called()
        self.box.warning.assert_called_once()
        self.maestro.connect.assert_not_called()
        self.installed.assert_not_called()
        self.assertFalse(self.config.maestro_enabled)

    def test_stale_vjoy_registration_does_not_block_working_maestro(self):
        self.registry.return_value = True
        self.maestro.enabled = self.maestro.service_running = True
        self.assertTrue(self.check())
        self.box.question.assert_not_called()
        self.box.warning.assert_not_called()
        self.install.assert_not_called()
        self.maestro.connect.assert_not_called()
        self.installed.assert_not_called()

    def test_vjoy_with_no_defined_devices_does_not_block_working_maestro(self):
        self.registry.return_value = True
        self.interface.vJoyEnabled.return_value = True
        self.interface.GetVJDStatus.return_value = 3
        self.maestro.enabled = self.maestro.service_running = True
        self.assertTrue(self.check())
        self.box.warning.assert_not_called()
        self.install.assert_not_called()

    def test_working_vjoy_skips_every_maestro_check(self):
        self.maestro = object()  # Accessing any Maestro state would fail.
        self.assertTrue(self.check(vjoy=True))
        self.installed.assert_not_called()
        self.registry.assert_not_called()
        self.assertFalse(self.config.maestro_enabled)

    def test_installed_vjoy_skips_even_cached_maestro_state(self):
        self.config.vjoy_installed = True
        self.interface.vJoyEnabled.return_value = True
        self.maestro = object()
        self.assertFalse(self.check())
        self.installed.assert_not_called()
        self.install.assert_not_called()
        self.assertNotIn('Maestro', self.box.warning.call_args.args[2])

    def test_accepted_setup_enables_and_reconnects_maestro(self):
        self.box.question.return_value = self.box.StandardButton.Yes

        def connect(**kwargs):
            if not self.install.called:
                return None
            self.maestro.enabled = self.maestro.service_running = True
            return object()

        self.maestro.connect.side_effect = connect
        self.assertTrue(self.check())
        self.install.assert_called_once()
        self.assertTrue(self.config.maestro_enabled)
        self.maestro.refreshDevices.assert_called_once()
        self.box.warning.assert_not_called()

    def test_setup_failure_cancellation_and_restart_allow_startup(self):
        self.box.question.return_value = self.box.StandardButton.Yes
        for code in (1, 1602, 3010, 1641):
            with self.subTest(code=code):
                self.config.maestro_enabled = False
                self.install.return_value = code
                self.assertFalse(self.check())
                self.assertEqual(self.config.maestro_enabled, code in (3010, 1641))
        self.assertEqual(self.box.information.call_count, 2)
        self.assertEqual(self.box.warning.call_count, 2)
        self.assertEqual(self.maestro.connect.call_count, 4)  # Probe before offering each installation.
        self.maestro.refreshDevices.assert_not_called()

    def test_successful_setup_with_stopped_service_warns(self):
        self.box.question.return_value = self.box.StandardButton.Yes
        self.assertFalse(self.check())
        self.box.warning.assert_called_once()

    def test_setup_launch_error_warns_and_continues(self):
        self.box.question.return_value = self.box.StandardButton.Yes
        self.install.side_effect = OSError('UAC cancelled')
        self.assertFalse(self.check())
        self.box.warning.assert_called_once()


class LocalhostMaestroChecks(unittest.TestCase):
    """Run the production connection and startup checks with no driver or service."""

    def setUp(self):
        self.config = NS(vjoy_installed=False, maestro_enabled=True, maestro_configured=True,
                         maestro_use_localhost=True, maestro_osc_host='127.0.0.1', maestro_osc_port=8010,
                         maestro_osc_reply_host='127.0.0.1', maestro_osc_reply_port=8011,
                         maestro_device_map=None)
        self.services = ModuleType('gremlin')
        self.services.config = NS(Configuration=lambda: self.config)
        self.services.event_handler = ModuleType('gremlin.event_handler')
        self.services.event_handler.EventListener = Mock(return_value=NS(shutdown=Mock()))
        self.psutil = Mock()
        self.psutil.win_service_get.return_value.status.return_value = 'running'
        self.client_factory = Mock()
        self.addCleanup(patch.stopall)
        patch.object(STARTUP, 'VJoyInterface', NS(
            valid=True, vJoyEnabled=Mock(side_effect=lambda: self.config.vjoy_installed),
            GetVJDStatus=Mock(return_value=1),
        )).start()
        patch.dict(MAESTRO_NAMESPACE, gremlin=self.services, socket=socket, psutil=self.psutil,
                   MaestroOscClient=self.client_factory, syslog=Mock()).start()
        patch.dict(sys.modules, {'gremlin': self.services, 'gremlin.event_handler': self.services.event_handler}).start()
        self.publish = patch.object(Maestro, 'populateDeviceList').start()
        patch.object(Maestro, 'sync').start()
        patch.object(STARTUP, '_machine_key_exists', return_value=False).start()
        patch.object(STARTUP, 'bridge_installed', return_value=True).start()
        self.install = patch.object(STARTUP, 'install_bridge').start()
        self.box = patch.object(STARTUP.QtWidgets, 'QMessageBox').start()
        patch.object(STARTUP, 'syslog', Mock()).start()

    def client(self, error=None, protocol=('MaestroOscService', 1)):
        result = Mock(args=protocol)
        result.raise_for_error.return_value = result
        client = Mock(destination=('127.0.0.1', 8010))
        client.request.side_effect = error
        client.request.return_value = result
        client.list.return_value = []
        return client

    def assert_no_prompt(self):
        self.box.question.assert_not_called()
        self.box.warning.assert_not_called()
        self.install.assert_not_called()

    def test_running_localhost_bridge_with_successful_initial_handshake(self):
        self.client_factory.return_value = self.client()
        maestro = Maestro()
        self.assertTrue(maestro.isServiceRunning())
        self.assertTrue(STARTUP.check_virtual_output(self.config, maestro, False))
        self.assert_no_prompt()

    def test_running_localhost_bridge_recovers_after_initial_ping_timeout(self):
        initial_client, ready_client = self.client(TimeoutError('No reply during startup')), self.client()
        self.client_factory.side_effect = [initial_client, ready_client]
        maestro = Maestro()
        self.assertTrue(maestro.isServiceRunning())
        self.assertFalse(maestro.enabled)
        self.assertFalse(maestro.service_running)
        self.assertTrue(STARTUP.check_virtual_output(self.config, maestro, False))
        self.assertTrue(maestro.enabled)
        self.assertTrue(maestro.service_running)
        self.assertEqual(self.client_factory.call_count, 2)
        self.client_factory.assert_called_with('127.0.0.1', 8010, '127.0.0.1', 8011)
        ready_client.request.assert_called_with('/maestro_ping', timeout=1.0, attempts=2)
        ready_client.list.assert_any_call('/maestro_devices')
        self.assert_no_prompt()

    def test_deferred_startup_recheck_recovers_without_a_warning(self):
        self.client_factory.side_effect = [self.client(TimeoutError('Startup timeout')), self.client()]
        maestro = Maestro()
        self.config.startup_start_minimized = False
        window = STARTUP.QtWidgets.QMainWindow()
        window.apply_user_settings = Mock()
        try:
            STARTUP.show_startup_ui(window, self.config, maestro, False)
            self.assertFalse(maestro.enabled)
            STARTUP.QtWidgets.QApplication.instance().processEvents()
            self.assertTrue(maestro.enabled)
            self.assertTrue(window.isVisible())
            self.assert_no_prompt()
        finally:
            Shiboken.delete(window)

    def test_running_service_without_osc_reply_still_warns(self):
        self.client_factory.side_effect = lambda *args: self.client(TimeoutError('OSC blocked'))
        maestro = Maestro()
        self.assertTrue(maestro.isServiceRunning())
        self.assertFalse(STARTUP.check_virtual_output(self.config, maestro, False))
        self.box.warning.assert_called_once()
        self.install.assert_not_called()

    def test_running_localhost_bridge_recovers_after_inventory_error(self):
        initial_client, ready_client = self.client(), self.client()
        initial_client.list.side_effect = TimeoutError('Inventory was not ready')
        self.client_factory.side_effect = [initial_client, ready_client]
        maestro = Maestro()
        self.assertTrue(maestro.isServiceRunning())
        self.assertFalse(maestro.enabled)
        self.assertTrue(STARTUP.check_virtual_output(self.config, maestro, False))
        ready_client.list.assert_any_call('/maestro_definitions')
        ready_client.list.assert_any_call('/maestro_devices')
        self.assert_no_prompt()

    def test_running_service_with_wrong_protocol_still_warns(self):
        self.client_factory.side_effect = lambda *args: self.client(protocol=('OtherService', 2))
        maestro = Maestro()
        self.assertFalse(STARTUP.check_virtual_output(self.config, maestro, False))
        self.box.warning.assert_called_once()
        self.install.assert_not_called()

    def test_detected_bridge_automatically_enables_disabled_maestro(self):
        self.config.maestro_enabled = False
        self.client_factory.return_value = self.client()
        maestro = Maestro()
        self.client_factory.assert_not_called()
        self.assertTrue(STARTUP.check_virtual_output(self.config, maestro, False))
        self.assertTrue(self.config.maestro_enabled)
        self.assertTrue(maestro.enabled)
        self.publish.assert_called_once()
        self.client_factory.return_value.list.assert_any_call('/maestro_devices')
        self.assert_no_prompt()

    def test_failed_detection_keeps_maestro_disabled(self):
        self.config.maestro_enabled = False
        self.client_factory.return_value = self.client(TimeoutError('No bridge reply'))
        maestro = Maestro()
        self.assertFalse(STARTUP.check_virtual_output(self.config, maestro, False))
        self.assertFalse(self.config.maestro_enabled)
        self.publish.assert_not_called()

    def test_deferred_startup_automatically_enables_a_detected_bridge(self):
        self.config.maestro_enabled = False
        self.config.startup_start_minimized = False
        self.client_factory.return_value = self.client()
        maestro = Maestro()
        window = STARTUP.QtWidgets.QMainWindow()
        window.apply_user_settings = Mock()
        try:
            STARTUP.show_startup_ui(window, self.config, maestro, False)
            self.assertFalse(self.config.maestro_enabled)
            STARTUP.QtWidgets.QApplication.instance().processEvents()
            self.assertTrue(self.config.maestro_enabled)
            self.assertTrue(maestro.enabled)
            self.assert_no_prompt()
        finally:
            Shiboken.delete(window)

    def test_vjoy_suppresses_constructor_and_default_device_probes(self):
        self.config.vjoy_installed = True
        self.client_factory.side_effect = AssertionError('Maestro must not be probed when vJoy is installed')
        maestro = Maestro()
        self.assertFalse(maestro.initialized)
        self.assertFalse(maestro.offerDefaultJoysticks())
        self.assertFalse(STARTUP.check_virtual_output(self.config, maestro, False))
        self.client_factory.assert_not_called()
        self.publish.assert_not_called()
        self.install.assert_not_called()

    def test_reply_port_bind_error_warns_and_keeps_startup_usable(self):
        self.config.maestro_enabled = False
        maestro = Maestro()
        self.config.maestro_enabled = True
        self.client_factory.side_effect = OSError('Reply port 8011 is already in use')
        self.assertFalse(STARTUP.check_virtual_output(self.config, maestro, False))
        self.box.warning.assert_called_once()
        self.install.assert_not_called()


class StartupWindowChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = STARTUP.QtWidgets.QApplication.instance() or STARTUP.QtWidgets.QApplication([
            'startup-window-checks', '-platform', 'offscreen'])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.config = NS(vjoy_installed=False, maestro_enabled=False, maestro_use_localhost=True,
                         startup_start_minimized=False)
        self.maestro = NS(enabled=False, service_running=False, connect=Mock(return_value=None), refreshDevices=Mock())
        interface_patch = patch.object(STARTUP, 'VJoyInterface', NS(
            valid=True, vJoyEnabled=Mock(side_effect=lambda: self.config.vjoy_installed),
            GetVJDStatus=Mock(return_value=1),
        ))
        interface_patch.start()
        self.addCleanup(interface_patch.stop)
        self.registry_patch = patch.object(STARTUP, '_machine_key_exists', return_value=False)
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)
        self.applied_settings = []

        class Window(STARTUP.QtWidgets.QMainWindow):
            def apply_user_settings(window, ignore_minimize=False):
                self.applied_settings.append(ignore_minimize)
                if self.config.startup_start_minimized and not ignore_minimize:
                    window.hide()

        self.window = Window()
        self.window.showMinimized()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        if Shiboken.isValid(self.window):
            self.window.close()
            self.window.deleteLater()
        STARTUP.QtCore.QCoreApplication.sendPostedEvents(None, STARTUP.QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def dismiss_startup_dialog(self, installed):
        observed = []
        timer = STARTUP.QtCore.QTimer()

        def dismiss():
            dialog = self.app.activeModalWidget()
            if isinstance(dialog, STARTUP.QtWidgets.QMessageBox):
                observed.append((dialog.parentWidget(), self.window.isVisible(), self.window.isMinimized()))
                buttons = STARTUP.QtWidgets.QMessageBox.StandardButton
                dialog.done(buttons.Ok if installed else buttons.No)

        timer.timeout.connect(dismiss)
        with (
            patch.object(STARTUP, '_machine_key_exists', return_value=False),
            patch.object(STARTUP, 'bridge_installed', return_value=installed),
            patch.object(STARTUP, 'install_bridge') as install,
            patch.object(STARTUP, 'syslog', Mock()),
        ):
            STARTUP.show_startup_ui(self.window, self.config, self.maestro, False)
            self.assertEqual(observed, [])  # the prompt waits for the event loop
            self.assertTrue(self.window.isVisible())
            timer.start(0)
            self.app.processEvents()
            timer.stop()
            install.assert_not_called()
        self.assertEqual(observed, [(self.window, True, False)])
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.isMinimized())
        self.assertEqual(self.applied_settings, [True])

    def test_missing_vjoy_warning_leaves_editor_visible_after_dismissal(self):
        self.dismiss_startup_dialog(installed=True)

    def test_declining_bridge_setup_leaves_editor_visible(self):
        self.dismiss_startup_dialog(installed=False)

    def test_unavailable_output_overrides_saved_start_minimized(self):
        self.config.startup_start_minimized = True
        self.dismiss_startup_dialog(installed=True)

    def test_working_provider_preserves_saved_minimized_preference(self):
        self.config.startup_start_minimized = True
        with patch.object(STARTUP, 'check_virtual_output') as check:
            STARTUP.show_startup_ui(self.window, self.config, self.maestro, True)
            self.app.processEvents()
            check.assert_not_called()
        self.assertFalse(self.window.isVisible())
        self.assertEqual(self.applied_settings, [False])

    def test_installed_but_unusable_vjoy_does_not_read_maestro_state(self):
        self.config.vjoy_installed = True
        self.maestro = object()
        with patch.object(STARTUP, 'check_virtual_output') as check:
            STARTUP.show_startup_ui(self.window, self.config, self.maestro, False)
            self.app.processEvents()
            check.assert_called_once_with(self.config, self.maestro, False, parent=self.window)
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.applied_settings, [True])

    def test_working_maestro_shows_editor_normally_without_warning(self):
        self.maestro.enabled = self.maestro.service_running = True
        with patch.object(STARTUP, 'check_virtual_output') as check:
            STARTUP.show_startup_ui(self.window, self.config, self.maestro, False)
            self.app.processEvents()
            check.assert_not_called()
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.isMinimized())
        self.assertEqual(self.applied_settings, [False])

    def test_destroying_window_cancels_pending_provider_prompt(self):
        with patch.object(STARTUP, 'check_virtual_output') as check:
            STARTUP.show_startup_ui(self.window, self.config, self.maestro, False)
            self.window.deleteLater()
            STARTUP.QtCore.QCoreApplication.sendPostedEvents(None, STARTUP.QtCore.QEvent.Type.DeferredDelete)
            self.app.processEvents()
            check.assert_not_called()


class EnumerationChecks(unittest.TestCase):
    def test_no_vjoy_or_physical_devices_does_not_exit_or_query_vjoy(self):
        tree = ast.parse((ROOT / 'gremlin/joystick_handling.py').read_bytes())
        node = next(node for node in tree.body if getattr(node, 'name', None) == 'joystick_devices_initialization')
        config = NS(verbose_mode_inputs=False, verbose_mode_vjoy=False, verbose_mode_extra=False,
                    hid_list_enabled=False, vjoy_installed=False)
        services = ModuleType('gremlin')
        services.util = ModuleType('gremlin.util')
        services.util.InvokeUiMethod = Mock()
        services.util.normalize_guid = lambda value: value
        services.config = NS(Configuration=lambda: config)
        monitor = NS(start=Mock(), stop=Mock())
        driver = NS(valid=False, vJoyEnabled=Mock())
        vjoy = NS(VJoyMonitor=lambda: monitor, device_available=Mock())
        listener = NS(device_initialized=Mock())
        services.event_handler = NS(EventListener=lambda: listener)
        services.ui = NS(axis_calibration=NS(CalibrationManager=lambda: NS(reload=Mock())))
        services.hid = NS(Hid=Mock())
        namespace = dict(gremlin=services, dinput=NS(DILL=NS(init=Mock(), get_device_count=lambda: 0),
            AxisMap=lambda: NS(getName=lambda: '')), vjoy=vjoy, vjoy_installed=STARTUP.vjoy_installed,
            syslog=logging.getLogger('startup-checks'), VJoyProxy=lambda: NS(reset=Mock()),
            _joystick_initialized=False, _last_device_signature=None,
            _joystick_init_lock=threading.Lock(), _device_registry_lock=threading.RLock(),
            _joystick_devices=[], _all_joystick_devices=[], _disconnected_devices=[], _special_devices=[],
            _joystick_device_guid_map={}, _all_vjoy_devices_map={}, _vjoy_devices_map={},
            _all_devices_map={}, _maestro_devices_map={}, _maestro_devices=[], _vjoy_devices=[],
            _apply_maestro_service_devices=Mock(), _update_joystick_device_maps=Mock(),
            registerSpecialDevices=Mock(), _update_virtual_map=Mock(), _device_list_signature=lambda: ())
        namespace['_create_vjoy_device'] = lambda vid: NS(device_guid=f'vjoy-{vid}', button_count=128,
            axis_count=8, hat_count=4, axismap_list=[], axis_names={})
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'joystick_handling.py', 'exec'), namespace)
        with (patch.dict(sys.modules, {'gremlin': services, 'gremlin.util': services.util}),
              patch.object(STARTUP, 'VJoyInterface', driver),
              patch.object(STARTUP, '_machine_key_exists', return_value=False)):
            self.assertTrue(namespace['joystick_devices_initialization']())
        self.assertFalse(config.vjoy_installed)
        self.assertTrue(namespace['_joystick_initialized'])
        self.assertEqual(len(namespace['_all_vjoy_devices_map']), 16)
        vjoy.device_available.assert_not_called()
        monitor.start.assert_not_called()
        listener.device_initialized.emit.assert_called_once()


class InstallerProcessChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = STARTUP.QtWidgets.QApplication.instance() or STARTUP.QtWidgets.QApplication([
            'bridge-installer-checks', '-platform', 'offscreen'])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_helper_uses_qt_process_and_preserves_restart_exit_code(self):
        self.check_process(False)

    def test_helper_start_failure_returns_an_error_without_hanging(self):
        self.check_process(True)

    def check_process(self, fail):
        qt_process = STARTUP.QtCore.QProcess

        class Signal:
            def connect(self, callback):
                self.callback = callback

        class Process:
            ProcessChannelMode = qt_process.ProcessChannelMode
            ExitStatus = qt_process.ExitStatus
            ProcessError = qt_process.ProcessError

            def __init__(self, parent):
                self.finished, self.errorOccurred = Signal(), Signal()

            def setProcessChannelMode(self, mode):
                pass

            def start(self, executable, arguments):
                self.executable, self.arguments = executable, arguments
                if fail:
                    callback = lambda: self.errorOccurred.callback(self.ProcessError.FailedToStart)
                else:
                    callback = lambda: self.finished.callback(3010, self.ExitStatus.NormalExit)
                STARTUP.QtCore.QTimer.singleShot(0, callback)

            def error(self):
                return self.ProcessError.FailedToStart if fail else self.ProcessError.UnknownError

            def errorString(self):
                return 'PowerShell unavailable'

            def readAllStandardOutput(self):
                return b''

        process = Process(None)
        with patch.object(STARTUP.QtCore, 'QProcess', Process), patch.object(Process, '__new__', return_value=process):
            if fail:
                with self.assertRaisesRegex(OSError, 'PowerShell unavailable'):
                    STARTUP.install_bridge()
            else:
                self.assertEqual(STARTUP.install_bridge(), 3010)
        self.assertTrue(process.executable.lower().endswith('powershell.exe'))
        self.assertEqual(process.arguments[-2:], ['-Component', 'bridge'])
        script = Path(process.arguments[process.arguments.index('-File') + 1])
        self.assertEqual(script, ROOT / 'installer' / 'dependencies.ps1')


if __name__ == '__main__':
    unittest.main()
