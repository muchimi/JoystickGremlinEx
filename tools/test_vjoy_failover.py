"""Hardware-free profile failover checks: python tools/test_vjoy_failover.py."""

import ast
from pathlib import Path
import re
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
from uuid import UUID

from lxml import etree
from PySide6 import QtCore, QtWidgets
from shiboken6 import Shiboken
from test_qt_marshalling import flush_deletes


ROOT = Path(__file__).resolve().parents[1]


def load_class(path, name, namespace, methods=None):
    tree = ast.parse((ROOT / path).read_bytes())
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    node.decorator_list = []
    if methods is not None:
        node.bases = []
        node.body = [item for item in node.body if isinstance(item, ast.FunctionDef) and item.name in methods]
        assert {item.name for item in node.body} == methods
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), path, "exec"), namespace)
    return namespace[name]


class Events(QtCore.QObject):
    config_option_changed = QtCore.Signal()
    profile_loaded = QtCore.Signal()


class IconLabel(QtWidgets.QLabel):
    def __init__(self, icon, *, text, parent=None, **kwargs):
        super().__init__(text, parent)


class VJoyFailoverChecks(unittest.TestCase):
    def setUp(self):
        self.config = NS(vjoy_installed=False, vjoy_failover=True, virtual_output_failover=True)
        self.events = Events()
        self.devices = NS(clearVjoyDevices=Mock(), configure_vjoy_failover=Mock())
        self.services = NS(
            config=NS(Configuration=lambda: self.config),
            joystick_handling=self.devices,
            event_handler=NS(EventListener=lambda: self.events),
        )
        namespace = dict(
            gremlin=self.services, re=re, parse_guid=UUID, syslog=Mock(),
            safe_read=lambda node, key, cast, default: cast(node.get(key)) if key in node.attrib else default,
        )
        self.profile = load_class(
            "gremlin/base_profile.py", "Profile", namespace, {"_configure_vjoy_failover"}
        )()
        self.widget_class = load_class(
            "gremlin/ui/ui_common.py", "QFailoverWidget",
            dict(gremlin=self.services, QIconLabel=IconLabel, Shiboken=Shiboken),
        )

    def configure(self, content):
        self.profile._configure_vjoy_failover(etree.fromstring(f"<profile>{content}</profile>"))

    def test_installed_driver_never_creates_failover_devices(self):
        self.config.vjoy_installed = True
        self.configure('<devices><device type="vjoy" name="VJoy (1)"/></devices>')
        self.assertFalse(self.config.vjoy_failover)
        self.devices.clearVjoyDevices.assert_not_called()
        self.devices.configure_vjoy_failover.assert_not_called()

    def test_empty_physical_and_maestro_profiles_disable_failover(self):
        for content in (
            '',
            '<devices><device type="joystick" name="Stick"/></devices>',
            '<devices><device type="maestro" name="Maestro (1)">'
            '<vjoyremap device-type="Maestro" virtual-id="1"/></device></devices>'
            '<settings><maestro-input id="1"/></settings>',
            '<devices><device type="maestro" name="VJoy (1)"/></devices>',
            '<vjoyremap virtual-id="0"/><remap vjoy="17"/>',
        ):
            with self.subTest(content=content):
                self.config.vjoy_failover = True
                self.configure(content)
                self.assertFalse(self.config.vjoy_failover)
        self.devices.configure_vjoy_failover.assert_not_called()

    def test_vjoy_references_enable_failover_without_output_mappings(self):
        for content in (
            '<devices><device type="vjoy" name="VJoy (2)"/></devices>',
            '<devices><vjoy-device name="Custom name" vjoy-id="2"/></devices>',
            '<settings><input-filter><device name="VJoy 8/128/4 (2)"/></input-filter></settings>',
            '<settings><vjoy-input id="2"/></settings>',
            '<settings><vjoy id="2"/></settings>',
            '<merge-axis><vjoy vjoy-id="2"/></merge-axis>',
            '<vjoyremap device-type="VJoy" virtual-id="2"/>',
            '<vjoyremap vjoy="2"/>',
            '<remap vjoy="2"/>',
        ):
            with self.subTest(content=content):
                self.devices.configure_vjoy_failover.reset_mock()
                self.configure(content)
                self.assertTrue(self.config.vjoy_failover)
                self.devices.configure_vjoy_failover.assert_called_once_with(2, None)

    def test_profile_switch_clears_prior_devices_and_state(self):
        guid = "00000000-0000-0000-0000-000000000002"
        self.configure(f'<devices><device type="vjoy" name="VJoy (2)" device-guid="{guid}"/></devices>'
                       '<vjoyremap virtual-id="2"/>')
        self.devices.configure_vjoy_failover.assert_called_once_with(2, UUID(guid))
        self.assertTrue(self.config.vjoy_failover)
        self.configure('')
        self.assertFalse(self.config.vjoy_failover)
        self.assertEqual(self.devices.clearVjoyDevices.call_count, 2)

    def widget(self):
        widget = self.widget_class()
        self.addCleanup(flush_deletes)
        self.addCleanup(widget.deleteLater)
        self.addCleanup(widget._cleanup_ui)
        return widget

    def test_indicator_requires_profile_references_missing_driver_and_preference(self):
        widget = self.widget()
        for installed in (False, True):
            for references in (False, True):
                for enabled in (False, True):
                    with self.subTest(installed=installed, references=references, enabled=enabled):
                        self.config.vjoy_installed = installed
                        self.config.vjoy_failover = references
                        self.config.virtual_output_failover = enabled
                        self.events.config_option_changed.emit()
                        self.assertEqual(not widget.isHidden(), references and not installed and enabled)

    def test_existing_indicator_updates_when_profile_changes(self):
        self.configure('')
        widget = self.widget()
        self.assertTrue(widget.isHidden())
        self.configure('<vjoyremap virtual-id="2"/>')
        self.events.profile_loaded.emit()
        self.assertFalse(widget.isHidden())
        self.configure('')
        self.events.profile_loaded.emit()
        self.assertTrue(widget.isHidden())

    def test_new_profile_resets_failover_before_creating_profile(self):
        listener, profile = Mock(), Mock()
        profile.devices = {}
        self.services.event_handler = Mock(EventListener=Mock(return_value=listener))
        self.services.execution_graph = Mock()
        self.services.shared_state = NS(
            current_profile=Mock(), current_mode="Default", resetState=Mock(),
        )
        self.devices.physical_devices = Mock(return_value=[])
        self.services.base_profile = NS(Profile=Mock(return_value=profile))
        worker = load_class(
            "gremlinEx.py", "GremlinUi", dict(gremlin=self.services), {"_new_profile_worker"}
        )
        ui = Mock(getTabCount=Mock(return_value=0))
        worker._new_profile_worker(ui, None)
        self.assertFalse(self.config.vjoy_failover)
        self.devices.clearVjoyDevices.assert_called_once()
        self.assertIs(self.services.shared_state.current_profile, profile)
        listener.profile_loaded.emit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
