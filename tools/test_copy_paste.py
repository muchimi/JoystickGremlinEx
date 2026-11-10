"""Copy/paste regressions with production readers/models and real offscreen Qt.

Run: python tools/test_copy_paste.py
Hardware, profile services and the Windows clipboard are isolated fixtures.
"""

import ast
import base64
import collections
import collections.abc as _collections_abc
import copy
from enum import IntEnum
import html
import inspect
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback
from types import ModuleType, SimpleNamespace as NS
from typing import Callable
import unittest
from unittest.mock import Mock, patch
import uuid

import dill
import lxml.etree
from PySide6 import QtCore, QtWidgets
from psygnal import Signal
from shiboken6 import Shiboken

from test_qt_marshalling import APP, UTIL, flush_deletes, invoke, pump_until


ROOT = Path(__file__).resolve().parents[1]
syslog = logging.getLogger("copy-paste-checks")
get_guid = lambda **kwargs: str(uuid.uuid4())
with_wait_cursor = lambda method: method
_trace = lambda message: None


def load(path, name, methods=None, base=None):
    node = next(node for node in ast.parse((ROOT / path).read_bytes()).body
                if getattr(node, "name", None) == name)
    if isinstance(node, ast.ClassDef):
        node.decorator_list = []
        if methods is not None:
            node.body = [m for m in node.body if isinstance(m, ast.FunctionDef) and m.name in methods]
            assert {m.name for m in node.body} == methods
        if base:
            node.bases = [ast.parse(base, mode="eval").body]
            node.keywords = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROOT / path), "exec"), globals())
    return globals()[name]


def module(name, **attributes):
    result = ModuleType(name)
    result.__path__ = []
    result.__dict__.update(attributes)
    MODULES[name] = result
    if "." in name:
        parent, child = name.rsplit(".", 1)
        setattr(MODULES[parent], child, result)
    return result


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()


def safe_read(node, key, kind, default=None):
    value = node.get(key)
    if value is None:
        return default
    return value.casefold() in ("true", "1") if kind is bool else kind(value)


def safe_format(value, kind):
    return str(value).lower() if kind is bool else str(value)


def read_guid(node, key):
    return uuid.UUID(node.attrib[key].strip("{}"))


class ActivationRule(IntEnum):
    All = 1
    Any = 2


class DeviceType(IntEnum):
    Joystick = 1
    VJoy = 2


SendType = IntEnum("SendType", {"Default": 0, "Remote": 1})
CONFIG = NS(verbose_mode_ui_level=lambda level: False, verbose_mode_condition=False,
            verbose=False, persist_clipboard=False, convert_response_curve=False, convert_vjoy_remap=False)
EVENTS = NS(**{name: Mock() for name in (
    "shutdown", "profile_unloaded", "paste_condition", "copy_condition", "condition_changed",
    "condition_added", "condition_removed", "condition_state_changed", "action_crud",
)})
MODULES = {}
gremlin = module("gremlin")
module("gremlin.util", InvokeUiMethod=invoke, is_ui_thread=UTIL["is_ui_thread"],
       assert_ui_thread=lambda: None, get_guid=get_guid, clear_layout=clear_layout,
       clamp=lambda value, low, high: max(low, min(high, value)), userprofile_path=tempfile.gettempdir,
       get_xml_child=lambda node, tag: node.find(tag))
module("gremlin.config", Configuration=lambda: CONFIG)
module("gremlin.shared_state", is_running=False, edit_mode="Default", master_mode="Master",
       current_profile=NS(get_mode_object=lambda mode: mode), is_redraw_suspended=lambda: False)
module("gremlin.event_handler", EventListener=lambda: EVENTS)
module("gremlin.base_profile", ProfileImportData=lambda: NS(used_ids={}))
module("gremlin.base_classes", BaseCallbacks=object)
module("gremlin.input_item")
module("gremlin.ui")
for name, attribute in (("keyboard_device", "BaseKeyboardCondition"),
                        ("joystick_device", "BaseJoystickCondition"), ("state_device", "BaseStateCondition")):
    module(f"gremlin.ui.{name}", **{attribute: Mock()})
module("container_plugins")
module("container_plugins.basic")

load("gremlin/util.py", "TriggerDict")
load("gremlin/base_classes.py", "AbstractModel")
load("gremlin/base_classes.py", "AbstractCallbackModel")


class ProfileData:
    def from_xml(self, node, data=None, extra_data=None):
        self._parse_xml(node, data, extra_data)


class InputItem:
    def __init__(self):
        self.containers = AbstractCallbackModel(model_description="containers")
        self.device_name, self.display_name = "Fixture joystick", "Axis 2"
        self.profile_mode = "Default"

    def get_valid_container_list(self):
        return ["Basic"]

    def get_device_type(self):
        return DeviceType.Joystick


class AbstractCondition:
    pass


class ConditionContainer:
    pass


load("gremlin/input_item.py", "AbstractAction", {"from_xml", "get_container"}, "ProfileData")
load("gremlin/input_item.py", "AbstractContainer", {
    "from_xml", "_parse_action_set_xml", "_parse_action_xml", "_parse_activation_condition_xml", "add_action",
}, "ProfileData")
for name in ("BaseAbstractCondition", "BaseModeCondition", "ConditionTrackerData", "ConditionModel",
             "ActionSet", "ActionSets", "ConditionTracker", "BaseActivationCondition"):
    load("gremlin/input_item.py", name)
BaseVJoyCondition = BaseInputActionCondition = BaseModeCondition
TrackerClass = ConditionTracker
ConditionTracker = lambda: TRACKER
gremlin.input_item.ConditionTracker = ConditionTracker
for name in ("AbstractAction", "AbstractContainer", "InputItem", "BaseActivationCondition"):
    setattr(gremlin.input_item, name, globals()[name])
gremlin.base_profile.AbstractAction = AbstractAction


class FixtureAction(AbstractAction):
    name = "Fixture action"
    parse_count = 0

    def __init__(self, parent):
        self.parent = self.parent_container = parent
        self.input_item = parent.input_item
        self.conditions = ConditionModel(self)
        self.activation_condition = BaseActivationCondition(self, ActivationRule.All)
        self.id = get_guid()
        self.remote_config = NS(from_xml=Mock())
        self.comment = ""
        self.value = None

    def _parse_xml(self, node, data=None, extra_data=None):
        type(self).parse_count += 1
        self.context, self.options = data, dict(extra_data or {})
        self.value = float(node.get("value"))
        self.payload = copy.deepcopy(node)

    def to_xml(self):
        node = copy.deepcopy(self.payload)
        node.set("action_id", self.id)
        for child in node.findall("activation-condition"):
            node.remove(child)
        node.append(self.activation_condition.to_xml())
        return node

    def setId(self, value):
        self.id = value

    def update_inputs(self, item):
        self.updated_input = item


class FixtureContainer(AbstractContainer):
    name = "Basic"
    custom_action_sets = False
    actionsetParseCallback = actionsetCustomParseCallback = None
    debug_name = "fixture container"

    def __init__(self, item):
        self.parent = self.input_item = item
        self.conditions = ConditionModel(self)
        self.activation_condition = BaseActivationCondition(self, ActivationRule.All)
        self.action_sets = ActionSets(self)
        self.id = self._id = get_guid()
        self.comment = ""
        self.create_or_delete_virtual_button = Mock()
        self._fireChangeCallbacks = Mock()

    def _parse_xml(self, node, data=None, extra_data=None):
        self.id = node.get("container_id")
        self.xml = copy.deepcopy(node)

    def _parse_virtual_button_xml(self, *args):
        pass

    def to_xml(self):
        return copy.deepcopy(self.xml)


gremlin.__dict__["base_classes"].AbstractCallbackModel = AbstractCallbackModel
gremlin.ui.keyboard_device.BaseKeyboardCondition = BaseModeCondition
gremlin.ui.joystick_device.BaseJoystickCondition = BaseModeCondition
gremlin.ui.state_device.BaseStateCondition = BaseModeCondition
MODULES["container_plugins.basic"].BasicContainer = FixtureContainer

load("gremlin/clipboard.py", "EncoderType")
load("gremlin/clipboard.py", "ObjectEncoder")
win32clipboard = NS(CF_TEXT=1, CF_UNICODETEXT=13)
load("gremlin/clipboard.py", "Clipboard")
ClipboardClass = Clipboard
module("gremlin.clipboard", Clipboard=lambda: CLIPBOARD, ObjectEncoder=ObjectEncoder, EncoderType=EncoderType)
ObjectEncoder.__module__ = EncoderType.__module__ = "gremlin.clipboard"
load("gremlin/plugin_manager.py", "clone_xml_for_paste")
load("gremlin/plugin_manager.py", "discard_pasted_conditions")
load("gremlin/plugin_manager.py", "ActionPlugins", {"duplicate", "duplicate_for_paste", "fromClipboard"})
ActionPluginsClass = ActionPlugins
load("gremlin/plugin_manager.py", "ContainerPlugins", {"duplicate"})
ContainerPluginsClass = ContainerPlugins
module("gremlin.plugin_manager", ActionPlugins=lambda: ACTIONS, ContainerPlugins=lambda: CONTAINERS,
       clone_xml_for_paste=clone_xml_for_paste, discard_pasted_conditions=discard_pasted_conditions)

load("gremlin/input_item.py", "ConditionHelper")
HelperClass = ConditionHelper
ConditionHelper = lambda: HELPER
for name, methods in (
    ("ConditionView", {"_copy_condition", "_paste_condition", "_handle_model_changed", "_create_ui",
                       "_update_count_ui", "redraw", "_redraw_ui"}),
    ("AbstractConditionWidget", {"_copy_condition", "_paste_condition"}),
    ("ActionSetView", {"_paste_action"}),
    ("ActionSetsView", {"_paste_action", "_paste_action_worker"}),
    ("InputItemMappingWidget", {"_paste_action", "_paste_container", "_add_containers_batched"}),
):
    load("gremlin/input_item.py", name, methods, "QtWidgets.QWidget")


ACTION_XML = b'''<fixture-action action_id="action-source" value="0.625" comment="Preserve me" priority="17" send-mode="1">
  <vjoy device="2" axis="3" value="0.8"/><remote-config host="192.0.2.1"/>
  <activation-condition rule="any" condition_id="activation-source">
    <condition condition_id="condition-source" condition-type="mode" mode="Flight" comparison="is" delay="0.25" description="In flight"/>
  </activation-condition>
</fixture-action>'''
SET_GUID = "fb185ec7-4e01-472d-8a1a-7454d39445ba"
ACTION_SET_GUID = "b334c097-51df-43ec-bee1-4603424ae7f1"
CONTAINER_XML = (b'<container type="basic" container_id="container-source" comment="Container note">'
                 + f'<action-set guid="{ACTION_SET_GUID}" description="Row title" set-guid="{SET_GUID}" set-description="Pilot &amp;amp; copilot">'.encode()
                 + ACTION_XML + b'</action-set></container>')


def encoded(xml, kind=EncoderType.Action):
    return ObjectEncoder(object(), xml, "stale name", kind)


class ConditionRow(QtWidgets.QLabel):
    def __init__(self, condition, **kwargs):
        super().__init__(condition.mode)


class CopyPasteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = patch.dict(sys.modules, MODULES)
        cls.modules.start()

    @classmethod
    def tearDownClass(cls):
        cls.modules.stop()

    def setUp(self):
        global TRACKER, CLIPBOARD, ACTIONS, CONTAINERS, HELPER, ActionPlugins
        TRACKER = TrackerClass()
        CLIPBOARD = ClipboardClass()
        ACTIONS = ActionPluginsClass()
        ACTIONS.tag_map = {"fixture-action": FixtureAction}
        ActionPlugins = lambda: ACTIONS
        CONTAINERS = ContainerPluginsClass()
        CONTAINERS.tag_map = {"basic": FixtureContainer}
        CONTAINERS.set_container_data = Mock()
        HELPER = HelperClass()
        self.item = InputItem()
        self.target = FixtureContainer(self.item)
        FixtureAction.parse_count = 0
        for event in vars(EVENTS).values():
            event.reset_mock()
        self.native = {
            "OpenClipboard": Mock(), "CloseClipboard": Mock(), "EmptyClipboard": Mock(),
            "SetClipboardText": Mock(), "IsClipboardFormatAvailable": Mock(return_value=True),
            "GetClipboardData": Mock(),
        }
        self.clipboard_patch = patch.multiple(win32clipboard, create=True, **self.native)
        self.clipboard_patch.start()
        self.widgets = []

    def tearDown(self):
        self.clipboard_patch.stop()
        for widget in self.widgets:
            widget.deleteLater()
        flush_deletes()

    def mapping(self):
        widget = InputItemMappingWidget()
        self.widgets.append(widget)
        widget._input_item = self.item
        widget._container_model = self.item.containers
        widget._container_model.addContainer = widget._container_model.add
        widget._container_view = None
        widget.redraw, widget.notify_changed = Mock(), Mock()
        return widget

    def condition_view(self, target):
        view = ConditionView()
        self.widgets.append(view)
        view._model, view._container = target.conditions, target
        view._model_callback_cleaned = False
        view._title = "Conditions"
        view.title_widget = QtWidgets.QLabel(view)
        view.conditions_layout = QtWidgets.QVBoxLayout(view)
        view.condition_map = {"Mode": (BaseModeCondition, ConditionRow)}
        view._handle_remove = Mock()
        view._hash_key, view._draw_once = None, False
        ConditionView.model = property(lambda obj: obj._model)
        ConditionView.input_item = property(lambda obj: obj._container.input_item)
        target.conditions.addCallback(view._handle_model_changed)
        view.redraw()
        return view

    def action(self):
        return ACTIONS.duplicate(encoded(ACTION_XML), self.target)

    def assert_action_data(self, action):
        self.assertEqual(action.value, 0.625)
        self.assertEqual(action.comment, "Preserve me")
        self.assertEqual(action._priority, 17)
        self.assertEqual(action._send_mode, SendType.Remote)
        self.assertEqual(action.payload.find("vjoy").attrib, {"device": "2", "axis": "3", "value": "0.8"})
        self.assertEqual(action.context, (self.item, self.target) if action.parent is self.target else (self.item, action.parent))
        condition = action.conditions[0]
        self.assertEqual((condition.mode, condition.delay, condition.description), ("Flight", 0.25, "In flight"))
        self.assertIs(condition.target, action)
        self.assertIs(TRACKER.getData(condition).container, action)

    def test_encoded_action_preserves_data_and_uses_destination_context(self):
        action = self.action()
        self.assert_action_data(action)
        self.assertTrue(action.options["paste"])
        self.assertIs(action.updated_input, self.item)
        self.assertNotEqual(action.id, "action-source")

    def test_repeated_live_action_paste_preserves_source_tracker(self):
        source = self.action()
        source_condition = source.conditions[0]
        first = ACTIONS.duplicate(source, self.target)
        second = ACTIONS.duplicate(source, self.target)
        self.assertEqual(len({source.id, first.id, second.id}), 3)
        self.assertEqual(len({source_condition.id, first.conditions[0].id, second.conditions[0].id}), 3)
        self.assertIs(TRACKER.getData(source_condition).condition, source_condition)
        self.assert_action_data(first)

    def test_mapping_action_paste_refreshes_and_keeps_values(self):
        widget = self.mapping()
        widget._paste_action(encoded(ACTION_XML), None)
        self.assertEqual(len(self.item.containers), 1)
        self.assert_action_data(self.item.containers[0].action_sets[0][0])
        widget.redraw.assert_called_once_with(force=True)
        widget.notify_changed.assert_called_once_with()

    def test_action_set_paste_adds_a_visible_action_and_refreshes(self):
        view = ActionSetView()
        self.widgets.append(view)
        view.container, view.model = self.target, self.target.action_sets[0]
        view.redraw = Mock()
        view._paste_action(encoded(ACTION_XML), self.target)
        self.assert_action_data(view.model[0])
        view.redraw.assert_called_once_with(force=True)
        self.target.create_or_delete_virtual_button.assert_called_once()

    def test_action_sets_paste_from_worker_updates_on_gui(self):
        view = ActionSetsView()
        self.widgets.append(view)
        view.container = self.target
        calls = []
        view.redraw = lambda **kwargs: calls.append(QtCore.QThread.isMainThread())
        thread = threading.Thread(target=lambda: view._paste_action(encoded(ACTION_XML), self.target))
        thread.start()
        thread.join()
        pump_until(lambda: bool(calls))
        self.assertEqual(calls, [True])
        self.assert_action_data(self.target.action_sets[0][0])

    def test_clipboard_selector_defers_deserialization(self):
        CLIPBOARD._data = encoded(ACTION_XML)
        actions = ACTIONS.fromClipboard(self.target, self.item, decode=False)
        self.assertEqual(FixtureAction.parse_count, 0)
        self.assertEqual(TRACKER._data_map, {})
        self.assertEqual(actions[0].name, FixtureAction.name)
        self.assert_action_data(ACTIONS.duplicate(actions[0], self.target))
        self.assertEqual(FixtureAction.parse_count, 1)

    def test_clipboard_decoder_keeps_valid_actions_when_another_is_bad(self):
        payload = CONTAINER_XML.replace(b"</action-set>", b'<fixture-action value="bad"/></action-set>')
        CLIPBOARD._data = encoded(payload, EncoderType.Container)
        with self.assertLogs(syslog, level="ERROR"):
            actions = ACTIONS.fromClipboard(self.target, self.item)
        self.assertEqual(len(actions), 1)
        self.assert_action_data(actions[0])
        self.assertEqual(len(TRACKER._data_map), 1)

    def test_clipboard_rejects_unknown_plugins_before_deserialization(self):
        payload = CONTAINER_XML.replace(b"</action-set>", b"<missing-plugin/></action-set>")
        CLIPBOARD._data = encoded(payload, EncoderType.Container)
        with self.assertLogs(syslog, level="ERROR"):
            self.assertEqual(ACTIONS.fromClipboard(self.target, self.item), [])
        self.assertEqual(FixtureAction.parse_count, 0)
        self.assertEqual(TRACKER._data_map, {})
        with self.assertLogs(syslog, level="WARNING"):
            self.assertEqual(ACTIONS.fromClipboard(None, None), [])

    def test_container_paste_preserves_set_metadata_and_unique_ids(self):
        widget = self.mapping()
        options = {"custom": "preserved"}
        first = widget._paste_container(encoded(CONTAINER_XML, EncoderType.Container), options)[0]
        second = widget._paste_container(first)[0]
        self.assertEqual(options, {"custom": "preserved"})
        self.assertEqual(first.action_sets.description, "Pilot & copilot")
        self.assertEqual(first.action_sets[0].description, "Row title")
        self.assertNotEqual(first.action_sets[0].id, uuid.UUID(ACTION_SET_GUID))
        self.assertNotEqual(first.action_sets[0].id, first.action_sets.id)
        self.assertNotEqual(first._id, second._id)
        self.assertNotEqual(first.action_sets[0][0].conditions[0].id, second.action_sets[0][0].conditions[0].id)
        self.assert_action_data(first.action_sets[0][0])
        self.assertEqual(widget.redraw.call_count, 2)

    def test_multicontainer_paste_rebuilds_once(self):
        widget = self.mapping()
        payload = b"<multi_containers>" + CONTAINER_XML * 2 + b"</multi_containers>"
        pasted = widget._paste_container(encoded(payload, EncoderType.MultiContainer))
        self.assertEqual(len(pasted), 2)
        self.assertEqual(len(self.item.containers), 2)
        self.assertNotEqual(pasted[0]._id, pasted[1]._id)
        widget.redraw.assert_called_once_with(force=True)

    def test_container_duplicate_defaults_to_owning_input(self):
        source = self.mapping()._paste_container(encoded(CONTAINER_XML, EncoderType.Container))[0]
        self.assertIs(CONTAINERS.duplicate(source).input_item, self.item)

    def test_condition_group_paste_from_model_refreshes_real_rows(self):
        source = self.action()
        HELPER.copy_condition(source.conditions)
        self.assertEqual(CLIPBOARD.data.encoder_type, EncoderType.ActivationCondition)
        view = self.condition_view(self.target)
        self.assertTrue(HELPER.paste_condition(self.target.conditions, CLIPBOARD.data))
        self.assertEqual(view.title_widget.text(), "Conditions (1)")
        self.assertEqual(view.conditions_layout.count(), 1)
        self.assertEqual(view.conditions_layout.itemAt(0).widget().text(), "Flight")
        self.assertEqual(self.target.activation_condition.rule, ActivationRule.All)

    def test_individual_condition_widget_pastes_to_action_owner(self):
        action = self.action()
        source_condition = action.conditions[0]
        HELPER.copy_condition(source_condition)
        view = self.condition_view(action)
        row = AbstractConditionWidget()
        self.widgets.append(row)
        row.condition = source_condition
        row._paste_condition()
        self.assertEqual(view.title_widget.text(), "Conditions (2)")
        self.assertEqual(view.conditions_layout.count(), 2)
        self.assertIs(action.conditions[1].target, action)
        self.assertEqual(len(self.target.conditions), 0)
        self.assertIs(TRACKER.getData(source_condition).condition, source_condition)
        EVENTS.condition_changed.emit.assert_called_with(self.target)

    def test_condition_view_copy_and_paste_callbacks(self):
        action = self.action()
        view = self.condition_view(action)
        view._copy_condition()
        view._paste_condition()
        self.assertEqual(len(action.conditions), 2)
        self.assertEqual(view.conditions_layout.count(), 2)

    def test_condition_paste_from_worker_refreshes_on_gui(self):
        action = self.action()
        HELPER.copy_condition(action.conditions[0])
        view = self.condition_view(self.target)
        thread = threading.Thread(target=lambda: HELPER.paste_condition(self.target, CLIPBOARD.data))
        thread.start()
        thread.join()
        self.assertEqual(len(self.target.conditions), 0)
        pump_until(lambda: view.conditions_layout.count() == 1)
        self.assertEqual(view.title_widget.text(), "Conditions (1)")

    def test_bad_condition_group_does_not_partially_modify_destination(self):
        source = self.action()
        node = source.activation_condition.to_xml()
        node.append(lxml.etree.Element("condition", {"condition-type": "missing"}))
        data = encoded(lxml.etree.tostring(node), EncoderType.ActivationCondition)
        before = dict(TRACKER._data_map)
        with self.assertLogs(syslog, level="ERROR"):
            self.assertFalse(HELPER.paste_condition(self.target, data))
        self.assertEqual(len(self.target.conditions), 0)
        self.assertEqual(TRACKER._data_map, before)

    def test_invalid_destination_is_safe_with_assertions_disabled(self):
        namespace = dict(HELPER.paste_condition.__func__.__globals__)
        node = ast.parse((ROOT / "gremlin/input_item.py").read_bytes())
        cls = next(c for c in node.body if isinstance(c, ast.ClassDef) and c.name == "ConditionHelper")
        cls.decorator_list = []
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "optimized-condition-helper", "exec", optimize=1), namespace)
        helper = namespace["ConditionHelper"]()
        with self.assertLogs(syslog, level="WARNING"):
            self.assertFalse(helper.paste_condition(object(), encoded(b"<condition/>", EncoderType.Condition)))

    def test_malformed_or_unknown_action_does_not_attach_or_refresh(self):
        widget = self.mapping()
        for payload in (b"broken xml", b"<missing-plugin/>", b'<fixture-action value="bad"/>'):
            with self.assertLogs(syslog, level="ERROR"):
                widget._paste_action(encoded(payload), None)
        self.assertEqual(len(self.item.containers), 0)
        widget.redraw.assert_not_called()

    def test_bad_container_is_safe(self):
        widget = self.mapping()
        with self.assertLogs(syslog, level="ERROR"):
            self.assertEqual(widget._paste_container(encoded(b"broken", EncoderType.Container)), [])
        widget.redraw.assert_not_called()

    def test_failed_container_batch_removes_partial_condition_records(self):
        widget = self.mapping()
        bad_container = CONTAINER_XML.replace(b"</action-set>", b'<fixture-action value="bad"/></action-set>')
        data = encoded(b"<multi_containers>" + CONTAINER_XML + bad_container + b"</multi_containers>", EncoderType.MultiContainer)
        with self.assertLogs(syslog, level="ERROR"):
            self.assertEqual(widget._paste_container(data), [])
        self.assertEqual(len(self.item.containers), 0)
        self.assertEqual(TRACKER._data_map, {})
        self.assertEqual(TRACKER._owner_map, {})
        self.assertTrue(all(not cache for cache in TRACKER._cache.values()))
        widget.redraw.assert_not_called()

    def test_failed_action_conditions_do_not_leave_tracker_entries(self):
        payload = ACTION_XML.replace(b"</activation-condition>", b'<condition condition-type="missing"/></activation-condition>')
        with self.assertLogs(syslog, level="ERROR"):
            self.assertIsNone(ACTIONS.duplicate_for_paste(encoded(payload), self.target))
        self.assertEqual(TRACKER._data_map, {})
        self.assertEqual(TRACKER._owner_map, {})

    def test_each_container_paste_handler_accepts_encoded_actions_and_bad_data(self):
        for path in sorted((ROOT / "container_plugins").glob("*/__init__.py")):
            tree = ast.parse(path.read_bytes())
            for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
                methods = [method for method in cls.body if isinstance(method, ast.FunctionDef)
                           and method.name.startswith("_paste_") and method.name.endswith("action")]
                if not methods:
                    continue
                widget_type = load(path.relative_to(ROOT), cls.name, {m.name for m in methods}, "QtWidgets.QWidget")
                for method in methods:
                    with self.subTest(container=path.parent.name, method=method.name):
                        widget = widget_type()
                        self.widgets.append(widget)
                        widget.container = widget.profile_data = FixtureContainer(self.item)
                        widget.container_modified = Mock()
                        widget._update_actions = widget._update_action_sets = Mock()
                        widget.short_layout_widget_list = widget.double_layout_widget_list = []
                        target_set = widget.container.action_sets[0]
                        for name in ("single_action_set", "double_action_set", "short_action_set", "long_action_set"):
                            setattr(widget.container, name, target_set)
                        widget.container.getActionSet = lambda direction: target_set
                        args = [encoded(ACTION_XML), widget.container]
                        if method.args.args[1].arg in ("index", "direction"):
                            args = [0, encoded(ACTION_XML)]
                        getattr(widget, method.name)(*args)
                        self.assertEqual(len(target_set), 1)
                        self.assert_action_data(target_set[0])
                        # Semantic errors reach the final handler after selector validation.
                        args[0 if method.args.args[1].arg == "action" else 1] = encoded(b'<fixture-action value="bad"/>')
                        with self.assertLogs(syslog, level="ERROR"):
                            getattr(widget, method.name)(*args)
                        self.assertEqual(len(target_set), 1)

    def test_windows_clipboard_text_round_trip(self):
        data = encoded(ACTION_XML)
        CLIPBOARD.data = data
        text, format_id = self.native["SetClipboardText"].call_args.args
        self.assertEqual(format_id, win32clipboard.CF_UNICODETEXT)
        self.native["GetClipboardData"].return_value = text
        CLIPBOARD._data = None
        decoded = CLIPBOARD.data
        self.assertEqual(decoded.data, data.data)
        self.assertEqual(decoded.encoder_type, data.encoder_type)
        self.assertEqual(self.native["CloseClipboard"].call_count, 2)

    def test_nontext_or_failed_clipboard_read_always_closes(self):
        self.native["IsClipboardFormatAvailable"].return_value = False
        self.assertIsNone(CLIPBOARD.get_windows_clipboard_text())
        self.native["CloseClipboard"].assert_called_once()
        self.native["IsClipboardFormatAvailable"].return_value = True
        self.native["GetClipboardData"].side_effect = RuntimeError("busy")
        with self.assertLogs(syslog, level="ERROR"):
            self.assertIsNone(CLIPBOARD.get_windows_clipboard_text())
        self.assertEqual(self.native["CloseClipboard"].call_count, 2)

    def test_persisted_clipboard_permission_errors_are_handled(self):
        CLIPBOARD._persist_to_file = True
        with patch("builtins.open", side_effect=PermissionError("fixture denied")):
            with self.assertLogs(syslog, level="ERROR"):
                CLIPBOARD.data = encoded(ACTION_XML)
            self.assertEqual(CLIPBOARD.data.data, ACTION_XML)
            CLIPBOARD._data = None
            with patch("os.path.isfile", return_value=True), self.assertLogs(syslog, level="ERROR"):
                self.assertIsNone(CLIPBOARD.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
