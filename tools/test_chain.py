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
"""Chain, Pause and step-model regressions without device or profile services.

Run: python -m pytest tools/test_chain.py tools/test_sequence.py -q
Production definitions run with real models, XML and offscreen Qt widgets.
"""

import ast
import collections
import collections.abc as _collections_abc
from enum import IntEnum
import html
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Callable
import unittest
from unittest.mock import Mock, call
import uuid

import lxml.etree
from PySide6 import QtCore, QtWidgets
from psygnal import Signal
from shiboken6 import Shiboken

from test_qt_marshalling import APP, flush_deletes
from test_sequence import InputType, Interactions, Value, load_sequence

ROOT = Path(__file__).resolve().parents[1]


class ServiceImports(ast.NodeTransformer):
    def visit_Import(self, node):
        return None if all(alias.name.startswith("gremlin") for alias in node.names) else node


def load(namespace, path, name, methods=None, base=None):
    node = next(node for node in ast.parse((ROOT / path).read_bytes()).body
                if getattr(node, "name", None) == name)
    if isinstance(node, ast.ClassDef):
        node.decorator_list = []
        if methods is not None:
            node.body = [method for method in node.body if getattr(method, "name", None) in methods]
        if base is not None:
            node.bases = [ast.Name(id=base, ctx=ast.Load())]
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node,
    ], type_ignores=[])
    exec(compile(ast.fix_missing_locations(ServiceImports().visit(module)), path, "exec"), namespace)
    return namespace[name]


class StubAction:
    def __init__(self, parent=None, extra_data=None):
        self.parent = parent
        self.name = self.tag = "test-action"

    def from_xml(self, node, data=None, extra_data=None):
        self.tag = node.tag

    def to_xml(self):
        return lxml.etree.Element(self.tag)


class StubFunctor:
    def __init__(self, action_data, parent=None):
        self.action_data = action_data
        self.functor_complete = Mock()

    def profile_started(self):
        pass


class WidgetBase(QtWidgets.QWidget):
    container_modified = QtCore.Signal()

    def _create_action_set_widget(self, model, label, view_type, **kwargs):
        row = QtWidgets.QLabel(label, self)
        row.model = model
        row.index = kwargs["index"]
        row.redraw = Mock()
        return row


def environment():
    config = NS(verbose_mode_ui_level=lambda level: False, verbose_mode_container=False,
                verbose_mode_execution=False, convert_response_curve=False, convert_vjoy_remap=False,
                pause_action_default_pause_value=.25)
    plugins = NS(get_class=lambda name: StubAction,
                 duplicate_for_paste=lambda action, container: StubAction(container), tag_map={})
    services = NS(
        config=NS(Configuration=lambda: config),
        shared_state=NS(is_running=False),
        event_handler=NS(EventListener=lambda: NS(action_crud=Mock())),
        plugin_manager=NS(ActionPlugins=lambda: plugins),
        util=NS(delete_widget=lambda widget: widget.deleteLater()),
        input_item=NS(BaseInputActionCondition=type("InputCondition", (), {})),
        base_profile=NS(AbstractFunctor=StubFunctor),
        actions=NS(Value=Value), control_action=NS(pause=Mock()),
    )
    ns = dict(
        gremlin=services, QtCore=QtCore, QtWidgets=QtWidgets, Shiboken=Shiboken, Signal=Signal,
        Callable=Callable, uuid=uuid, collections=collections, _collections_abc=_collections_abc,
        logging=logging, syslog=logging.getLogger("chain-checks"), html=html,
        lxml=lxml, ElementTree=lxml.etree, AbstractAction=StubAction, InputItem=type("InputItem", (), {}),
        StubFunctor=StubFunctor, WidgetBase=WidgetBase, InputType=InputType, Interactions=Interactions,
        ContainerViewTypes=NS(Action=0), IntEnum=IntEnum, PauseActionWidget=object,
        ActionPlugins=lambda: plugins, time=NS(monotonic=Mock(return_value=1), sleep=Mock()),
        isNumeric=lambda value: value.replace(".", "", 1).isdigit(), write_guid=str,
    )
    for name in ("TriggerDict", "safe_read", "read_guid"):
        load(ns, "gremlin/util.py", name)
    for name in ("AbstractModel", "AbstractCallbackModel", "_is_curve_tag"):
        load(ns, "gremlin/base_classes.py", name)
    services.base_classes = NS(_is_curve_tag=ns["_is_curve_tag"])
    load(ns, "gremlin/input_item.py", "AbstractContainer", {"add_action", "ensureActionSet"}, base="object")
    for name in ("ActionSet", "ActionSets"):
        load(ns, "gremlin/input_item.py", name)
    load(ns, "gremlin/base_profile.py", "AbstractSelfTriggerFunctor", base="StubFunctor")
    services.base_profile.AbstractSelfTriggerFunctor = ns["AbstractSelfTriggerFunctor"]
    for name in ("PauseMode", "PauseActionFunctor", "PauseAction"):
        if name == "PauseAction":
            ns["AbstractAction"] = StubAction
            services.input_item.AbstractAction = StubAction
        load(ns, "action_plugins/pause/__init__.py", name)
    load(ns, "container_plugins/chain/__init__.py", "ChainContainerWidget", {
        "_create", "_add_action", "_paste_action", "_new_step_index", "_handle_interaction", "_update_action_sets",
    }, base="WidgetBase")
    load(ns, "container_plugins/chain/__init__.py", "ChainContainerFunctor")
    load(ns, "container_plugins/chain/__init__.py", "ChainContainer")
    load(ns, "container_plugins/sequence/__init__.py", "SequenceContainer", {"_parse_steps_xml"}, base="object")
    return ns, services, config, plugins


class ChainChecks(unittest.TestCase):
    def setUp(self):
        self.ns, self.services, self.config, self.plugins = environment()
        self.container = self.ns["AbstractContainer"]()
        self.container.input_item = self.ns["InputItem"]()
        self.container.debug_name = "test chain"
        self.container.timeout = 0
        self.container.activation_condition = NS(conditions=[])
        self.container.create_or_delete_virtual_button = Mock()
        self.container._fireChangeCallbacks = Mock()
        self.container.action_sets = self.ns["ActionSets"](self.container)
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.deleteLater()
        flush_deletes()

    def widget(self):
        widget = self.ns["ChainContainerWidget"]()
        self.widgets.append(widget)
        widget.container = self.container
        widget.container.interaction_types = list(Interactions)
        widget._action_set_widgets = {}
        widget.action_set_layout = QtWidgets.QVBoxLayout(widget)
        return widget

    def add_steps(self, *names):
        self.container.action_sets.clear()
        for name in names:
            step = self.ns["ActionSet"]()
            if name is not None:
                action = StubAction(self.container)
                action.name = name
                step.add(action)
            self.container.action_sets.add(step)

    def step_names(self):
        return [step[0].name for step in self.container.action_sets if step]

    def functor(self, nodes=None):
        functor = self.ns["ChainContainerFunctor"](self.container)
        functor._valid = True
        functor.action_set_nodes = [NS(id=index) for index in range(2)] if nodes is None else nodes
        functor._ec = NS(execute_node=Mock())
        return functor

    def send(self, functor, pressed, now, event_type=InputType.JoystickButton):
        self.ns["time"].monotonic.return_value = now
        return functor.process_event(NS(event_type=event_type), Value(pressed))

    def test_add_and_paste_create_separate_visible_steps_and_reuse_initial_set(self):
        widget = self.widget()
        initial = self.container.action_sets[0]
        widget._add_action("A")
        widget._add_action("B")
        widget._paste_action(object(), None)
        self.assertIs(self.container.action_sets[0], initial)
        self.assertEqual([len(step) for step in self.container.action_sets], [1, 1, 1])
        self.assertEqual([row.text() for row in widget._action_set_widgets.values()], ["Step 1", "Step 2", "Step 3"])
        self.plugins.duplicate_for_paste = lambda *args: None
        widget._paste_action(object(), None)
        self.assertEqual(len(self.container.action_sets), 3)

    def test_move_and_delete_act_once_and_use_real_indices_across_empty_steps(self):
        self.add_steps("A", None, "B", "C")
        widget = self.widget()
        widget._update_action_sets()
        self.assertEqual(list(widget._action_set_widgets), [0, 2, 3])
        widget._handle_interaction(Interactions.Up, 2, None)
        self.assertEqual(self.step_names(), ["B", "A", "C"])
        widget._handle_interaction(Interactions.Down, 0, None)
        self.assertEqual(self.step_names(), ["A", "B", "C"])
        widget._handle_interaction(Interactions.Top, 3, None)
        self.assertEqual(self.step_names(), ["C", "B", "A"])
        widget._handle_interaction(Interactions.Bottom, 0, None)
        self.assertEqual(self.step_names(), ["A", "B", "C"])
        widget._handle_interaction(Interactions.Delete, 2, None)
        self.assertEqual(self.step_names(), ["A", "C"])
        self.assertEqual(list(widget._action_set_widgets), [0, 2])
        widget._handle_interaction(Interactions.Delete, 99, None)
        self.assertEqual(self.step_names(), ["A", "C"])

    def test_last_step_can_be_deleted_and_replaced(self):
        self.add_steps("A")
        widget = self.widget()
        widget._update_action_sets()
        widget._handle_interaction(Interactions.Delete, 0, None)
        self.assertEqual(len(self.container.action_sets), 1)
        self.assertFalse(self.container.action_sets[0])
        self.assertEqual(widget._action_set_widgets, {})
        widget._add_action("B")
        self.assertEqual([len(step) for step in self.container.action_sets], [1])

    def test_opening_a_saved_empty_chain_creates_an_editable_initial_set(self):
        container = self.ns["ChainContainer"].__new__(self.ns["ChainContainer"])
        container.__dict__.update(self.container.__dict__)
        container.action_sets.clear()
        widget = self.widget()
        widget._create(container)
        widget._update_action_sets()
        widget._add_action("A")
        self.assertEqual([len(step) for step in container.action_sets], [1])

    def test_redraw_does_not_accumulate_model_change_connections(self):
        self.add_steps("A")
        widget = self.widget()
        modified = Mock()
        widget.container_modified.connect(modified)
        for _ in range(4):
            widget._update_action_sets()
        self.container.action_sets[0].data_changed.emit()
        modified.assert_called_once_with()

    def test_cycle_uses_executable_steps_and_keeps_press_release_pairs(self):
        self.add_steps(None, "A", None, "B", None)
        functor = self.functor()
        for now, pressed in enumerate([True, False] * 3, 1):
            self.assertFalse(self.send(functor, pressed, now))
        calls = functor._ec.execute_node.call_args_list
        self.assertEqual([call.args[0].id for call in calls], [0, 0, 1, 1, 0, 0])

    def test_empty_or_uninitialized_chain_is_a_noop(self):
        functor = self.functor([])
        self.send(functor, True, 1)
        functor._valid = False
        del functor.action_set_nodes
        self.send(functor, True, 2)
        functor._ec.execute_node.assert_not_called()

    def test_timeout_resets_after_idle_but_releases_held_step(self):
        self.container.timeout = 5
        functor = self.functor()
        for now, pressed in [(1, True), (2, False), (3, True), (30, False), (31, True), (32, False), (40, True)]:
            self.send(functor, pressed, now)
        self.assertEqual([call.args[0].id for call in functor._ec.execute_node.call_args_list], [0, 0, 1, 1, 0, 0, 0])

    def test_press_only_and_release_only_containers_cycle(self):
        for press_only in (True, False):
            with self.subTest(press_only=press_only):
                functor = self.functor()
                functor.switch_on_press = press_only
                for now in range(3):
                    self.send(functor, press_only, now)
                self.assertEqual([call.args[0].id for call in functor._ec.execute_node.call_args_list], [0, 1, 0])

    def test_timeout_resets_press_only_and_release_only_chains(self):
        self.container.timeout = 5
        for press_only in (True, False):
            with self.subTest(press_only=press_only):
                functor = self.functor()
                functor.switch_on_press = press_only
                for now in (1, 2, 20):
                    self.send(functor, press_only, now)
                self.assertEqual([call.args[0].id for call in functor._ec.execute_node.call_args_list], [0, 1, 0])

    def test_profile_restart_rebuilds_filtered_nodes_and_resets_position(self):
        graph_types = NS(Container="container", ActionSet="action-set")
        nodes = [NS(nodeType="action-set", action_set=step, has_actions=bool(step))
                 for step in [[], ["A"], [], ["B"]]]
        context = NS(find=lambda *args: NS(nodeType="container", children=[NS(children=nodes)]), execute_node=Mock())
        self.services.execution_graph = NS(ExecutionContext=lambda: context, ExecutionGraphNodeType=graph_types)
        functor = self.functor()
        functor.index, functor.last_execution, functor.last_value = 1, 50, True
        functor.profile_started()
        self.assertEqual(functor.action_set_nodes, [nodes[1], nodes[3]])
        self.assertEqual((functor.index, functor.last_execution, functor.last_value), (0, 0, None))
        for pressed in (True, False, True, False, True):
            self.send(functor, pressed, 51)
        self.assertEqual([call.args[0] for call in context.execute_node.call_args_list], [nodes[1], nodes[1], nodes[3], nodes[3], nodes[1]])

    def test_step_remains_a_valid_model_and_widget_map_key_after_editing(self):
        step = self.container.action_sets[0]
        original_hash = hash(step)
        views = {step: "step view"}
        step.add(StubAction())
        step.add(StubAction())
        step.removeAt(0)
        self.assertEqual(hash(step), original_hash)
        self.assertEqual(views[step], "step view")
        self.container.action_sets.removeAt(0)
        self.assertEqual(len(self.container.action_sets), 0)

    def test_model_change_tracking_uses_contents_separately_from_identity(self):
        model = self.ns["AbstractCallbackModel"](model_description="test model")
        model._fireChanged()
        self.assertFalse(model.modelChanged())
        original_hash = hash(model)
        model.pushSuspend()
        model.add(StubAction())
        self.assertTrue(model.modelChanged())
        model.popSuspend()
        self.assertEqual(hash(model), original_hash)
        self.assertFalse(model.modelChanged())

    def test_parent_change_tracking_still_detects_nested_action_edits(self):
        parent = self.container.action_sets
        parent._fireChanged()
        self.assertFalse(parent.modelChanged())
        original_hash = parent.hashKey()
        parent[0].add(StubAction())
        self.assertNotEqual(parent.hashKey(), original_hash)
        self.assertTrue(parent.modelChanged())
        parent._fireChanged()
        self.assertFalse(parent.modelChanged())

    def test_remap_conversion_loads_all_sequence_steps_and_sibling_tags(self):
        self.config.convert_vjoy_remap = True
        self.config.convert_response_curve = True
        self.plugins.tag_map = {tag: type(f"Plugin_{tag}", (StubAction,), {"plugin_tag": tag})
                               for tag in ("pause", "remap", "vjoyremap", "response-curve", "response-curve-ex")}
        xml = lxml.etree.fromstring(b'''<container>
          <action-set><pause/><remap/><pause/><response-curve/><remap/></action-set>
          <action-set><pause/></action-set>
        </container>''')
        self.ns["SequenceContainer"]._parse_steps_xml(self.container, xml)
        self.assertEqual([len(step) for step in self.container.action_sets], [5, 1])
        self.assertEqual([action.plugin_tag for action in self.container.action_sets[0]],
                         ["pause", "vjoyremap", "pause", "response-curve-ex", "vjoyremap"])
        saved = lxml.etree.Element("container")
        for step in self.container.action_sets:
            saved.append(step.to_xml())
        self.assertEqual([len(step) for step in saved], [5, 1])

    def test_legacy_conversion_falls_back_when_replacement_plugins_are_missing(self):
        self.config.convert_vjoy_remap = True
        self.config.convert_response_curve = True
        self.plugins.tag_map = {tag: StubAction for tag in ("pause", "remap", "response-curve")}
        step = self.ns["ActionSet"]()
        step.from_xml(lxml.etree.fromstring(b'<action-set><remap/><pause/><response-curve/></action-set>'), self.container)
        self.assertEqual([action.tag for action in step], ["remap", "pause", "response-curve"])

    def test_saved_pause_modes_round_trip_and_legacy_pause_still_pauses(self):
        for mode in self.ns["PauseMode"]:
            with self.subTest(mode=mode):
                action = self.ns["PauseAction"](self.container)
                action.mode = mode
                action.delay = 750
                loaded = self.ns["PauseAction"](self.container)
                loaded._parse_xml(action._generate_xml())
                self.assertEqual(loaded.mode, mode)
                if mode == self.ns["PauseMode"].Delay:
                    self.assertEqual(loaded.delay, 750)
        loaded._parse_xml(lxml.etree.Element("pause"))
        self.assertEqual(loaded.mode, self.ns["PauseMode"].PauseAction)

    def test_sequence_continues_after_pause_in_each_runner_with_fresh_values(self):
        for runner in ("_normal_runner", "_stepped_runner", "_wiggle_runner"):
            with self.subTest(runner=runner):
                ns, _, _ = load_sequence()
                container = ns["SequenceContainer"]()
                container.wiggle_count_enabled = True
                container.wiggle_count_min = container.wiggle_count_max = 2
                container.normal_autorelease_delay = container.wiggle_exec_delay = container.wiggle_step_delay = 0
                container.wiggle_min_delay = container.wiggle_max_delay = 0
                functor = ns["SequenceContainerFunctor"](container)
                functor.action_set_nodes = [NS(id=0), NS(id=1)]
                pause = self.ns["PauseActionFunctor"](NS(mode=self.ns["PauseMode"].Delay, delay=1000))
                events, values = [], []

                def execute(node, event, value, extra):
                    self.assertIsInstance(value, Value)
                    self.assertEqual(value.current, event.is_pressed)
                    values.append(value)
                    if node.id == 0:
                        pause.process_event(event, value, extra)
                    elif value.is_pressed:
                        events.append("after pause")
                    # An action may mutate the value; the next event must start fresh.
                    value.current = "modified"

                functor._ec = NS(execute_node=execute)
                for _ in range(2 if runner == "_stepped_runner" else 1):
                    container._is_running = True
                    getattr(functor, runner)()
                self.assertEqual(events, ["after pause"])
                self.assertEqual(len({id(value) for value in values}), len(values))
        self.assertEqual(self.ns["time"].sleep.call_args_list, [call(1)] * 3)


if __name__ == "__main__":
    unittest.main()
