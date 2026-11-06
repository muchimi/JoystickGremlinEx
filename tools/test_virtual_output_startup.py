"""Hardware-free startup checks: python tools/test_virtual_output_startup.py."""

import ast
import importlib.util
import logging
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


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


class StartupProviderChecks(unittest.TestCase):
    def setUp(self):
        self.config = NS(vjoy_installed=False, maestro_enabled=False)
        self.maestro = NS(enabled=False, service_running=False, connect=Mock(return_value=None), refreshDevices=Mock())
        self.addCleanup(patch.stopall)
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

    def test_installed_but_unconfigured_vjoy_warns_without_setup(self):
        self.config.vjoy_installed = True
        self.assertFalse(self.check())
        self.box.question.assert_not_called()
        self.box.warning.assert_called_once()

    def test_installed_but_disabled_vjoy_warns_without_setup(self):
        self.registry.return_value = True
        self.assertFalse(self.check())
        self.box.question.assert_not_called()
        self.install.assert_not_called()

    def test_accepted_setup_enables_and_reconnects_maestro(self):
        self.box.question.return_value = self.box.StandardButton.Yes

        def connect():
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
        self.maestro.connect.assert_not_called()

    def test_successful_setup_with_stopped_service_warns(self):
        self.box.question.return_value = self.box.StandardButton.Yes
        self.assertFalse(self.check())
        self.box.warning.assert_called_once()

    def test_setup_launch_error_warns_and_continues(self):
        self.box.question.return_value = self.box.StandardButton.Yes
        self.install.side_effect = OSError('UAC cancelled')
        self.assertFalse(self.check())
        self.box.warning.assert_called_once()


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
            AxisMap=lambda: NS(getName=lambda: '')), vjoy=vjoy, VJoyInterface=driver,
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
        with patch.dict(sys.modules, {'gremlin': services, 'gremlin.util': services.util}):
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
