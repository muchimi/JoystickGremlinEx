"""Mapping-template IO and real Qt UI regressions without device services.

Run: python tools/test_mapping_templates.py
"""

import copy
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from lxml import etree
from PySide6 import QtWidgets
from shiboken6 import Shiboken

import test_copy_paste as cp
import test_gated_axis as gated
import test_ui_refresh as ui


# Reuse the hardware-free fixtures, loading the actual template entry points.
FixtureInputItem = cp.InputItem
methods = cp.load("gremlin/input_item.py", "InputItem", {
    "save_container_to_template", "load_container_from_template",
}, "object")
for name in ("save_container_to_template", "load_container_from_template"):
    setattr(FixtureInputItem, name, getattr(methods, name))
cp.InputItem = FixtureInputItem
cp.ContainerPluginsClass = cp.load("gremlin/plugin_manager.py", "ContainerPlugins", {
    "duplicate", "save_template", "load_template",
})
cp.load("gremlin/input_item.py", "InputItemMappingWidget", {
    "_paste_action", "_paste_container", "_add_containers_batched",
    "_save_container_to_template", "_load_container_from_template",
}, "QtWidgets.QWidget")
ContainerWidget = cp.load("gremlin/input_item.py", "AbstractContainerWidget", {
    "_open_template", "_save_template",
}, "QtWidgets.QWidget")
Selector = cp.load("gremlin/input_item.py", "ContainerSelector", base="QtWidgets.QWidget")


def button(callback=None, **kwargs):
    result = QtWidgets.QPushButton()
    if callback:
        result.clicked.connect(callback)
    return result


def horizontal_container(widgets, **kwargs):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(widget)
    for child in widgets:
        layout.addWidget(child)
    return widget


cp.module("gremlin.ui.ui_common", MessageBox=Mock(), QDataComboBox=QtWidgets.QComboBox,
          getHContainer=horizontal_container,
          Buttons=NS(**{f"get{name}Widget": button for name in ("Add", "Save", "Folder", "Copy", "Paste", "Delete")}))
cp.gremlin.event_handler.EventHandler = lambda: NS(last_container_changed=Mock())
cp.CONFIG.last_container = "Basic"
cp.CONFIG.sync_last_selection = False
cp.gremlin.shared_state.data_path = tempfile.gettempdir()
cp.module("gremlin.ui.octavi_device")
FixtureInputItem.toExtraData = lambda item: {"device_guid": "destination-device", "input_id": 2, "mode": item.profile_mode}
FixtureInputItem.locked = False
cp.FixtureContainer.widget = lambda container, item, data: ui.Editor(container)


class MappingTemplateTests(unittest.TestCase):
    setUpClass = classmethod(cp.CopyPasteTests.setUpClass.__func__)
    tearDownClass = classmethod(cp.CopyPasteTests.tearDownClass.__func__)
    mapping = cp.CopyPasteTests.mapping
    assert_action_data = cp.CopyPasteTests.assert_action_data

    def setUp(self):
        cp.CopyPasteTests.setUp(self)
        self.item.containers.addContainer = self.item.containers.add
        self.item.input_type = 1
        self.item.lockedChanged = Mock()
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "mapping.xml"
        self.path.write_bytes(b"<container_template>" + cp.CONTAINER_XML + b"</container_template>")
        cp.gremlin.ui.ui_common.MessageBox.reset_mock()

    def tearDown(self):
        cp.CopyPasteTests.tearDown(self)
        self.directory.cleanup()

    def selector(self, mapping=None):
        selector = Selector(self.item.input_type, data=self.item, parent=mapping)
        self.widgets.append(selector)
        if mapping:
            selector.container_to_template.connect(mapping._save_container_to_template)
            selector.container_from_template.connect(mapping._load_container_from_template)
        return selector

    def source(self):
        return cp.CONTAINERS.load_template(self.path, self.item)[0]

    def test_roundtrip_preserves_values_and_registers_new_condition_ids(self):
        source = self.source()
        condition = source.action_sets[0][0].conditions[0]
        saved = Path(self.directory.name) / "saved.xml"
        self.assertTrue(cp.CONTAINERS.save_template(saved, [source]))
        first = cp.CONTAINERS.load_template(saved, self.item)[0]
        second = cp.CONTAINERS.load_template(saved, self.item)[0]
        self.assert_action_data(first.action_sets[0][0])
        self.assertEqual(first.comment, source.comment)
        self.assertEqual(first.action_sets[0].description, "Row title")
        self.assertEqual(len({source._id, first._id, second._id}), 3)
        conditions = [container.action_sets[0][0].conditions[0] for container in (source, first, second)]
        self.assertEqual(len({condition.id for condition in conditions}), 3)
        for current in conditions:
            self.assertIs(cp.TRACKER.getData(current).condition, current)
        self.assertIs(cp.TRACKER.getData(condition).container, source.action_sets[0][0])
        self.assertEqual(len(cp.TRACKER._data_map), 3)

    def test_internal_references_follow_new_ids_and_external_inputs_stay(self):
        xml = cp.CONTAINER_XML.replace(b'<vjoy ', b'<vjoy action-ref="action-source" condition-ref="condition-source" device-guid="physical-device" input-id="11" ')
        self.path.write_bytes(b"<container_template>" + xml + b"</container_template>")
        action = self.source().action_sets[0][0]
        reference = action.payload.find("vjoy")
        self.assertEqual(reference.get("action-ref"), action.id)
        self.assertEqual(reference.get("condition-ref"), action.conditions[0].id)
        self.assertEqual(reference.get("device-guid"), "physical-device")
        self.assertEqual(reference.get("input-id"), "11")
        self.assertIn(b'condition-ref="condition-source"', self.path.read_bytes())

    def test_loader_uses_destination_context_and_does_not_mutate_options(self):
        options = {"device_guid": "source-device", "input_id": 99, "custom": "kept"}
        original = dict(options)
        action = cp.CONTAINERS.load_template(self.path, self.item, options)[0].action_sets[0][0]
        self.assertEqual(options, original)
        self.assertEqual(action.options["device_guid"], "destination-device")
        self.assertEqual(action.options["input_id"], 2)
        self.assertEqual(action.options["custom"], "kept")
        self.assertTrue(action.options["paste"])
        self.assertTrue(action.options["ids_regenerated"])
        self.assertEqual(action.id, action.payload.get("action_id"))

    def test_invalid_or_incompatible_templates_leave_no_partial_records(self):
        for payload in (b"broken", b"<profile/>", b'<container_template><container type="missing"/></container_template>',
                        b"<container_template>" + cp.CONTAINER_XML.replace(b'value="0.625"', b'value="bad"') + b"</container_template>"):
            with self.subTest(payload=payload):
                self.path.write_bytes(payload)
                with self.assertRaises(Exception):
                    cp.CONTAINERS.load_template(self.path, self.item)
                self.assertEqual(cp.TRACKER._data_map, {})
        self.path.write_bytes(b"<container_template>" + cp.CONTAINER_XML + b"</container_template>")
        with patch.object(self.item, "get_valid_container_list", return_value=[]), self.assertRaises(ValueError):
            cp.CONTAINERS.load_template(self.path, self.item)

    def test_failed_batch_rolls_back_valid_conditions_from_earlier_containers(self):
        bad = cp.CONTAINER_XML.replace(b"</action-set>", b'<fixture-action value="bad"/></action-set>')
        self.path.write_bytes(b"<container_template>" + cp.CONTAINER_XML + bad + b"</container_template>")
        with self.assertRaises(ValueError):
            cp.CONTAINERS.load_template(self.path, self.item)
        self.assertEqual(cp.TRACKER._data_map, {})
        self.assertEqual(len(self.item.containers), 0)

    def test_failed_replace_preserves_previous_file_and_cleans_temp_file(self):
        source = self.source()
        original = self.path.read_bytes()
        with patch("os.replace", side_effect=PermissionError("fixture denied")), self.assertRaises(PermissionError):
            cp.CONTAINERS.save_template(self.path, [source])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path])

    def test_serialization_error_preserves_previous_file(self):
        original = self.path.read_bytes()
        source = self.source()
        with patch.object(source, "to_xml", side_effect=ValueError("bad mapping")), self.assertRaises(ValueError):
            cp.CONTAINERS.save_template(self.path, [source])
        self.assertEqual(self.path.read_bytes(), original)

    def test_programmatic_load_appends_and_notifies_once(self):
        changed = Mock()
        self.item.containers.addCallback(changed)
        containers = self.item.load_container_from_template(self.path)
        self.assertEqual(list(self.item.containers), containers)
        cp.CONTAINERS.set_container_data.assert_called_once_with(self.item, containers[0])
        changed.assert_called_once()
        self.assert_action_data(containers[0].action_sets[0][0])

    def test_programmatic_io_handles_errors_and_cancel(self):
        self.assertFalse(self.item.save_container_to_template(None))
        self.assertEqual(self.item.load_container_from_template(None), [])
        with self.assertLogs(cp.syslog, level="ERROR"):
            self.assertEqual(self.item.load_container_from_template(self.path.with_name("missing.xml")), [])
        with patch.object(cp.CONTAINERS, "save_template", side_effect=PermissionError("fixture denied")), self.assertLogs(cp.syslog, level="ERROR"):
            self.assertFalse(self.item.save_container_to_template(self.path))

    def test_selector_load_updates_real_container_rows_and_save_button(self):
        mapping = self.mapping()
        selector = self.selector(mapping)
        view = ui.ContainerView(mapping)
        self.widgets.append(view)
        view._main_layout = QtWidgets.QVBoxLayout(view)
        view._input_item, view._model = self.item, self.item.containers
        view._redraw_lock, view._last_hash = False, None
        view._create_ui()
        view._redraw_ui()
        view.pushSuspended, view.popSuspended = Mock(), Mock()
        mapping._container_view = view
        self.assertFalse(selector.save_template_widget.isEnabled())
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(self.path), "XML")):
            selector.load_template_widget.click()
        self.assertEqual(len(self.item.containers), 1)
        self.assertEqual(len(view._widget_map), 1)
        self.assertEqual(view._scroll_layout.count(), 2)  # container row and stretch
        self.assertTrue(selector.save_template_widget.isEnabled())
        self.assertIs(mapping._container_view, view)
        mapping.redraw.assert_not_called()
        mapping.notify_changed.assert_called_once()
        self.item.containers.clear()
        self.assertFalse(selector.save_template_widget.isEnabled())

    def test_selector_save_button_calls_shared_writer(self):
        self.item.load_container_from_template(self.path)
        mapping = self.mapping()
        selector = self.selector(mapping)
        saved = self.path.with_name("from-button.xml")
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(saved), "XML")):
            selector.save_template_widget.click()
        self.assertEqual(etree.parse(saved).getroot().tag, "container_template")
        self.assertEqual(len(etree.parse(saved).findall("container")), 1)

    def test_ui_failures_are_reported_and_do_not_change_model(self):
        mapping = self.mapping()
        self.path.write_bytes(b"<wrong-root/>")
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(self.path), "XML")), self.assertLogs(cp.syslog, level="ERROR"):
            self.assertEqual(mapping._load_container_from_template(), [])
        cp.gremlin.ui.ui_common.MessageBox.assert_called_once()
        self.assertIn("not a mapping template", cp.gremlin.ui.ui_common.MessageBox.call_args.kwargs["prompt"])
        mapping.redraw.assert_not_called()
        self.assertEqual(len(self.item.containers), 0)
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(self.path), "XML")), patch.object(cp.CONTAINERS, "save_template", side_effect=PermissionError("fixture denied")), self.assertLogs(cp.syslog, level="ERROR"):
            self.assertFalse(mapping._save_container_to_template(self.item))
        self.assertEqual(cp.gremlin.ui.ui_common.MessageBox.call_count, 2)

    def test_locked_input_and_cancel_do_not_load_or_refresh(self):
        mapping = self.mapping()
        selector = self.selector(mapping)
        self.item.locked = True
        selector._handle_lock_changed_ui(self.item)
        self.assertFalse(selector.load_template_widget.isEnabled())
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName") as dialog:
            self.assertEqual(mapping._load_container_from_template(), [])
            dialog.assert_not_called()
        self.item.locked = False
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=("", "")):
            self.assertEqual(mapping._load_container_from_template(), [])
        mapping.redraw.assert_not_called()
        cp.gremlin.ui.ui_common.MessageBox.assert_not_called()

    def test_destroyed_selector_removes_model_callback(self):
        selector = self.selector()
        callback = selector._containers_changed
        self.assertIn(callback, self.item.containers._data_changed_callbacks)
        self.widgets.remove(selector)
        selector.deleteLater()
        cp.flush_deletes()
        self.assertFalse(Shiboken.isValid(selector))
        self.assertNotIn(callback, self.item.containers._data_changed_callbacks)
        self.item.load_container_from_template(self.path)

    def test_worker_load_dispatches_dialog_and_refresh_to_gui(self):
        mapping = self.mapping()
        dialog_threads = []
        def choose(*args):
            dialog_threads.append(cp.QtCore.QThread.isMainThread())
            return str(self.path), "XML"
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", side_effect=choose):
            thread = threading.Thread(target=mapping._load_container_from_template)
            thread.start()
            thread.join()
            cp.pump_until(lambda: mapping.notify_changed.called)
        self.assertEqual(dialog_threads, [True])
        self.assert_action_data(self.item.containers[0].action_sets[0][0])

    def test_container_save_and_recall_updates_the_model(self):
        container = self.source()
        widget = ContainerWidget()
        self.widgets.append(widget)
        widget.container = container
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(self.path), "XML")):
            self.assertTrue(widget._save_template())
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(self.path), "XML")):
            loaded = widget._open_template()
        self.assertEqual(list(self.item.containers), loaded)
        self.assertIs(widget.container, container)
        self.assertNotEqual(loaded[0]._id, container._id)

    def test_container_recall_uses_parent_mapping_batch(self):
        mapping = self.mapping()
        widget = ContainerWidget(mapping)
        self.widgets.append(widget)
        widget.container = self.target
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(self.path), "XML")):
            loaded = widget._open_template()
        self.assertEqual(list(self.item.containers), loaded)
        mapping.notify_changed.assert_called_once()

    def test_gated_axis_uses_remapped_gate_ids_and_range_references(self):
        data = gated.GateDataFixture((-1, 0, 1), NS(get_input_item=lambda: gated.InputItem()))
        xml = data.to_xml()
        old_gate_ids = {node.get("id") for node in xml.findall("gate")}
        cloned = cp.clone_xml_for_paste(xml)
        expected_gate_ids = {node.get("id") for node in cloned.findall("gate")}
        self.assertTrue(old_gate_ids.isdisjoint(expected_gate_ids))
        for node in cloned.findall("range"):
            self.assertIn(node.get("min_id"), expected_gate_ids)
            self.assertIn(node.get("max_id"), expected_gate_ids)
        restored = gated.GateDataFixture((-1, 1), data._action_data)
        restored.from_xml(copy.deepcopy(cloned), gated.InputItem(), {"paste": True, "ids_regenerated": True})
        self.assertEqual({gate.id for gate in restored.getUsedGates()}, expected_gate_ids)
        self.assertEqual(len(restored.getUsedRanges()), 2)

    def test_legacy_gate_paste_remaps_range_endpoints(self):
        data = gated.GateDataFixture((-1, 0, 1), NS(get_input_item=lambda: gated.InputItem()))
        old_ids = {gate.id for gate in data.getUsedGates()}
        restored = gated.GateDataFixture((-1, 1), data._action_data)
        restored.from_xml(data.to_xml(), gated.InputItem(), {"paste": True})
        self.assertTrue(old_ids.isdisjoint({gate.id for gate in restored.getUsedGates()}))
        self.assertEqual(len(restored.getUsedRanges()), 2)

    def test_nested_input_reader_tracks_conditions_under_nested_owner(self):
        reader = cp.load("gremlin/input_item.py", "InputItem", {"from_xml"}, "object").from_xml
        cp.InputItem = FixtureInputItem
        self.item._containers = self.item.containers
        self.item.setInputType = Mock()
        self.item._handle_content_changed = lambda data=None, force=False, operation=None: None
        root = etree.Element("gate")
        nested = etree.SubElement(root, "axis")
        node = etree.fromstring(cp.CONTAINER_XML)
        condition = copy.deepcopy(node.find("./action-set/fixture-action/activation-condition"))
        condition.set("condition_id", "container-activation-source")
        condition.find("condition").set("condition_id", "container-condition-source")
        node.append(condition)
        nested.append(cp.clone_xml_for_paste(node))
        outer_owner = object()
        options = {"input_item": outer_owner, "paste": True, "ids_regenerated": True}
        class NestedContainer(cp.FixtureContainer):
            def __init__(self, parent, extra_data=None):
                super().__init__(parent)
        with patch.dict(cp.CONTAINERS.tag_map, {"basic": NestedContainer}), patch.dict(reader.__globals__, {
            "ContainerPlugins": lambda: cp.CONTAINERS, "InputType": NS(to_enum=lambda tag: 1),
            "_is_curve_tag": lambda tag: False,
        }), patch.object(cp.gremlin.base_profile, "get_mode_object", return_value=None, create=True):
            reader(self.item, nested, (outer_owner, self.target), options, skip_root=True)
        self.assertIs(options["input_item"], outer_owner)
        container = self.item.containers[0]
        for condition in (container.conditions[0], container.action_sets[0][0].conditions[0]):
            self.assertIs(cp.TRACKER.getData(condition).input_item, self.item)

    def test_device_copy_does_not_recall_a_failed_or_empty_save(self):
        profile_type = cp.load("gremlin/base_profile.py", "Profile", {"copy_devices"}, "object")
        source_guid, target_guid = object(), object()
        source = NS(containers=[object()], save_container_to_template=Mock())
        target = NS(load_container_from_template=Mock())
        profile = profile_type()
        profile.devices = {
            source_guid: NS(modes={"Default": NS(config={1: {1: source}})}),
            target_guid: NS(modes={"Default": NS(config={1: {1: target}})}),
        }
        with patch.object(cp.gremlin, "joystick_handling", NS(getDevice=lambda guid: object()), create=True), patch.object(
            cp.gremlin.util, "getTemporaryFile", return_value=str(self.path), create=True
        ), patch.object(cp.EVENTS, "request_reload", Mock(), create=True):
            for saved, recalled in ((False, [object()]), (True, []), (True, [object()])):
                with self.subTest(saved=saved, recalled=bool(recalled)):
                    source.save_container_to_template.return_value = saved
                    target.load_container_from_template.return_value = recalled
                    target.load_container_from_template.reset_mock()
                    cp.EVENTS.request_reload.reset_mock()
                    profile.copy_devices(source_guid, target_guid)
                    self.assertEqual(target.load_container_from_template.called, saved)
                    self.assertEqual(cp.EVENTS.request_reload.emit.called, saved and bool(recalled))


if __name__ == "__main__":
    unittest.main(verbosity=2)
