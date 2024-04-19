# -*- coding: utf-8; -*-

# Based on original concept / code by Lionel Ott - Copyright (C) 2015 - 2019 Lionel Ott  
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


import logging
import threading
import time
import math
from xml.etree import ElementTree

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import Qt


from gremlin.base_classes import InputActionCondition
from gremlin.common import InputType, MouseButton, get_guid
from gremlin import input_devices, joystick_handling, util
from gremlin.util import rad2deg
from gremlin.error import ProfileError
from gremlin.profile import safe_format, safe_read, read_bool, Profile, parse_guid, write_guid
import gremlin.ui.common
import gremlin.ui.input_item
import os

from gremlin.input_devices import VjoyAction, remote_state
from gremlin.base_classes import AbstractAction, AbstractFunctor
from gremlin.input_devices import ButtonReleaseActions
from action_plugins.map_to_keyboard import *
from action_plugins.map_to_mouse import *

syslog = logging.getLogger("system")


class RangeContainerWidget(gremlin.ui.input_item.AbstractContainerWidget):
    ''' Range container for a ranged action '''

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(profile_data, parent)


    def _create_action_ui(self):
        ''' creates the UI for the container '''


        # get container parent widget

        toolbar_widget = QtWidgets.QWidget()
        toolbar_container = QtWidgets.QVBoxLayout()
        toolbar_widget.setLayout(toolbar_container)

        toolbar1_widget = QtWidgets.QWidget()
        toolbar1 = QtWidgets.QHBoxLayout()
        toolbar1_widget.setLayout(toolbar1)

        toolbar2_widget = QtWidgets.QWidget()
        toolbar2 = QtWidgets.QHBoxLayout()
        toolbar2_widget.setLayout(toolbar2)


        toolbar_container.addWidget(toolbar1_widget)
        toolbar_container.addWidget(toolbar2_widget)

        self.widget_layout = QtWidgets.QVBoxLayout()

        # self.profile_data.create_or_delete_virtual_button()
        self.action_selector = gremlin.ui.common.ActionSelector(
            self.profile_data.get_input_type()
        )

        profile: RangeContainer
        profile = self.profile_data

        # attach this UI widget to the container data
        profile._widget = self

        # min range box
        min_box = gremlin.ui.common.DynamicDoubleSpinBox()
        min_box.setMinimum(-1.0)
        min_box.setMaximum(1.0)
        min_box.setDecimals(3)
        min_box.setValue(profile.range_min)

        min_box_included = QtWidgets.QCheckBox("[")
        min_box_included.setChecked(profile.range_min_included)

        max_box_included = QtWidgets.QCheckBox("]")
        max_box_included.setChecked(profile.range_max_included)

        add_button_top_90 = QtWidgets.QPushButton("Top 90%")
        add_button_top_90.clicked.connect(self._add_top_90)

        action_label = QtWidgets.QLabel("Actions")
        self.ui_action_dropdown = QtWidgets.QComboBox()

        for entry in gremlin.plugin_manager.ActionPlugins().repository.values():
            self.ui_action_dropdown.addItem(entry.name, entry)

        cfg = gremlin.config.Configuration()
        self.ui_action_dropdown.setCurrentText(cfg.default_action)
        self.add_button = QtWidgets.QPushButton("Add")
        self.add_button.clicked.connect(self._add_action)

        range_count_label = QtWidgets.QLabel("Add Count")
        self.ui_range_count = QtWidgets.QSpinBox()
        self.ui_range_count.minimum = 1
        self.ui_range_count.maximum = 20
        self.ui_range_count.setValue(5)


        add_range = QtWidgets.QPushButton("Add Ranges")
        add_range.clicked.connect(self._add_range)

        
        replace_range = QtWidgets.QPushButton("Replace Ranges")
        replace_range.clicked.connect(self._replace_range)
        
        # max range box
        max_box = gremlin.ui.common.DynamicDoubleSpinBox()
        max_box.setMinimum(-1.0)
        max_box.setMaximum(1.0)
        max_box.setDecimals(3)
        max_box.setValue(profile.range_max)

        symmetrical_box = QtWidgets.QCheckBox("Symmetrical")
        symmetrical_box.setChecked(profile.symmetrical)
        
        toolbar1.addWidget(QtWidgets.QLabel("Start:"))
        toolbar1.addWidget(min_box_included)
        toolbar1.addWidget(min_box)
        toolbar1.addWidget(QtWidgets.QLabel("End:"))
        toolbar1.addWidget(max_box)
        toolbar1.addWidget(max_box_included)
        toolbar1.addWidget(symmetrical_box)
        toolbar1.addStretch(1)

        toolbar2.addWidget(add_button_top_90)
        toolbar2.addWidget(action_label)
        toolbar2.addWidget(self.ui_action_dropdown)
        toolbar2.addWidget(range_count_label)
        toolbar2.addWidget(self.ui_range_count)
        toolbar2.addWidget(add_range)
        toolbar2.addWidget(replace_range)
        toolbar2.addStretch(1)
        
        self.widget_layout.addWidget(toolbar_widget)        
        self.widget_layout.addWidget(self.action_selector)
        
        self.ui_min_box = min_box
        self.ui_min_box_included = min_box_included
        self.ui_max_box = max_box
        self.ui_max_box_included = min_box_included
        self.ui_symmetrical = symmetrical_box

        self.action_selector.action_added.connect(self._add_action)

        min_box.valueChanged.connect(self._range_min_changed)
        min_box_included.clicked.connect(self._range_min_included_changed)
        max_box.valueChanged.connect(self._range_max_changed)
        max_box_included.clicked.connect(self._range_max_included_changed)
        symmetrical_box.clicked.connect(self._symmetrical_changed)

        self.action_layout.addLayout(self.widget_layout)

        # Insert action widgets
        for i, action in enumerate(self.profile_data.action_sets):
            widget = self._create_action_set_widget(
                self.profile_data.action_sets[i],
                f"Action {i:d}",
                gremlin.ui.common.ContainerViewTypes.Action
            )
            self.action_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)


    def _create_condition_ui(self):
        if self.profile_data.activation_condition_type == "action":
            for i, action in enumerate(self.profile_data.action_sets):
                widget = self._create_action_set_widget(
                    self.profile_data.action_sets[i],
                    f"Action {i:d}",
                    gremlin.ui.common.ContainerViewTypes.Condition
                )
                self.activation_condition_layout.addWidget(widget)
                widget.redraw()
                widget.model.data_changed.connect(self.container_modified.emit)

    def _add_action(self, action_name):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        self.profile_data.add_action(action_item)
        self.container_modified.emit()      



    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        # Find the index of the widget that gets modified
        index = self._get_widget_index(widget)

        if index == -1:
            logging.getLogger("system").warning(
                "Unable to find widget specified for interaction, not doing "
                "anything."
            )
            return

        # Perform action
        if action == gremlin.ui.input_item.ActionSetView.Interactions.Up:
            if index > 0:
                self.profile_data.action_sets[index],\
                    self.profile_data.action_sets[index-1] = \
                    self.profile_data.action_sets[index-1],\
                    self.profile_data.action_sets[index]
        if action == gremlin.ui.input_item.ActionSetView.Interactions.Down:
            if index < len(self.profile_data.action_sets) - 1:
                self.profile_data.action_sets[index], \
                    self.profile_data.action_sets[index + 1] = \
                    self.profile_data.action_sets[index + 1], \
                    self.profile_data.action_sets[index]
        if action == gremlin.ui.input_item.ActionSetView.Interactions.Delete:
            del self.profile_data.action_sets[index]

        self.container_modified.emit()

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        return f"Range: {" -> ".join([", ".join([a.name for a in actions]) for actions in self.profile_data.action_sets])}"
    
    ''' event handlers for the UI elements in this action '''
    def _range_min_changed(self):
        self.profile_data.range_min = self.ui_min_box.value()

    def _range_max_changed(self):
        self.profile_data.range_max = self.ui_max_box.value()
        
    def _range_min_included_changed(self):
        self.profile_data.range_min_included = self.ui_min_box_included.isChecked()

    def _range_max_included_changed(self):
        self.profile_data.range_max_included = self.ui_max_box_included.isChecked()

    def _symmetrical_changed(self):
        self.profile_data.symmetrical = self.ui_symmetrical.isChecked()       

    def _add_top_90(self):
        self.ui_min_box.setValue(0.90)
        self.ui_max_box.setValue(1.00)
        
    def _add_range(self):
        ''' adds containers '''
        count = self.ui_range_count.value()
        action = self.ui_action_dropdown.currentText()
        self._add_containers(count, action)

    def _replace_range(self):
        ''' replaces current containers with new containers '''
        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        # the profile_data member is a RangeContainer object
        widget = container_plugins.get_parent_widget(self.profile_data)
        for container in widget.action_model._containers:
            if isinstance(container, RangeContainer):
                widget._remove_container(container)
        self._add_range()


    def _add_containers(self, count, action_name = None):
        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        # the profile_data member is a RangeContainer object
        widget = container_plugins.get_parent_widget(self.profile_data)
        if widget:
            # add five containers via the parent widget
            value = -1.0
            offset = 2.0 / count
            for _ in range(count):
                container : RangeContainer
                container = widget._add_container(RangeContainer.name)
                container.range_min = value
                container.range_min_included  = value == -1.0
                value += offset
                container.range_max = value

                # add the default action if one is provided
                if action_name:
                    container._widget._add_action(action_name)

                


class RangeContainerFunctor(gremlin.base_classes.AbstractFunctor):

    """Executes the contents of the associated basic container."""


    def __init__(self, container):
        container: RangeContainer
        super().__init__(container)
        
        self.action_sets = []
        for action_set in container.action_sets:
            self.action_sets.append(
                gremlin.execution_graph.ActionSetExecutionGraph(action_set)
            )
        self.container = container
        self.reset_range()

        # latch all the range containers
        self.latched_functors = []
        self.latched_loaded = False


    def reset_range(self):
        ''' resets the range trigger '''
        self.last_range_min = -2.0
        self.last_range_max = -2.0

    def process_event(self, event, value):
        """Executes the content with the provided data.

        :param event the event to process
        :param value the value received with the event
        :return True if execution was successful, False otherwise
        """

        if event.event_type != InputType.JoystickAxis:
            return

        target = value.current


        # verify the event is in the correct range
        container : RangeContainer
        container = self.container

        range_min = container.range_min
        range_max = container.range_max

        # latch all other functors
        if not self.latched_loaded:
            container_plugins = gremlin.plugin_manager.ContainerPlugins()
            for functor in container_plugins.functors:
                if isinstance(functor, RangeContainerFunctor) and functor != self:
                    self.latched_functors.append(functor)

            self.latched_loaded = True

        ranges = [(range_min, range_max)]

        if container.symmetrical:
            # duplicate the ranges for symmetrical
            sym_min = -range_min
            sym_max = -range_max
            if sim_max < sim_min:
                tmp = sim_max
                sim_max = sim_min
                sim_min = tmp

            ranges.append((sym_min, sym_max))

        in_range = False
        
        for (range_min, range_max) in ranges:
            if target < range_min or target > range_max: 
                continue
            if not container.range_min_included:
                if target == range_min:
                    continue
            if not container.range_max_included:
                if target == range_max:
                    continue

            #syslog.info(f"{target:0.3f} range {range_min:0.3f} {range_max:0.3f} bracket {self.last_range_min:0.3f} {self.last_range_max:0.3f}")    
            in_range = True
                
            break

        if in_range:
            # axis value is in a bracket range - make sure it hasn't been processed already
            range_changed = self.last_range_min != range_min and self.last_range_max != range_max
            if range_changed:
                #syslog.info("trigger!")
                for action in self.action_sets:
                    action.process_event(event, value)
                self.last_range_min = range_min
                self.last_range_max = range_max


            if self.latched_functors:
                # reset the other latched functors of their range trigger to indicate we got our own range
                for functor in self.latched_functors:
                    functor.reset_range()

   
                

            return True

        return False

class RangeContainer(gremlin.base_classes.AbstractContainer):
    ''' action data for the map to Range action '''

    
    name = "Range"
    tag = "range"

    # this container only works with axis inputs
    input_types = [gremlin.common.InputType.JoystickAxis]

    # allowed interactions with this container
    interaction_types = [
        gremlin.ui.input_item.ActionSetView.Interactions.Up,
        gremlin.ui.input_item.ActionSetView.Interactions.Down,
        gremlin.ui.input_item.ActionSetView.Interactions.Delete,
    ]


    functor = RangeContainerFunctor
    widget = RangeContainerWidget

    def __init__(self, parent):
        '''' creates a new instance 
        :parent the InputItem which is the parent to this action
        '''

        super().__init__(parent)
        self.id = get_guid() # unique id of this item
        self._index = 0 # index # of this item
        self.range_min = -1.0 # lower bound of the range
        self.range_min_included = False # true if the lower range is excluded from the range
        self.range_max = 1.0 # upper bound of the range
        self.range_max_included = False # true if the higher range is excluded from the range
        self.symmetrical = False # true if the range is symmetrical about the center of the axis 
        self.range_min_included = True # true if the boundary is included in the range
        self.range_max_included = True # true if the boundery is included in the range
        self.action_model = None # set at creation by the parent of this container
        self._widget = None # will be populated by the widget attached to this container
        self._functor = None # will be populated when the functor is created for this container

        self.condition_enabled = False
        self.virtual_button_enabled = False



    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"        


    def _parse_xml(self, node):
        ''' reads configuration '''
        try:
            if "min" in node.attrib:
                self.range_min = safe_read(node, "min", float)
            if "max" in node.attrib:
                self.range_max = safe_read(node, "max", float)
            if "min_inc" in node.attrib:
                self.range_min_included = safe_read(node, "min_inc", bool)
            if "max_inc" in node.attrib:
                self.range_min_included = safe_read(node, "max_inc", bool)
            if "sym" in node.attrib:
                self.symmetrical = safe_read(node, "sym",bool)
            
        except:
            pass
        pass

    def _generate_xml(self):
        
        ''' returns an xml node encoding this action's data '''
        node = ElementTree.Element("container")
        node.set("type", RangeContainer.tag)
        node.set("min", safe_format(self.range_min, float))
        node.set("max", safe_format(self.range_max, float))
        node.set("min_inc", safe_format(self.range_min_included, bool))
        node.set("max_inc", safe_format(self.range_max_included, bool))
        node.set("sym", safe_format(self.symmetrical, bool))

        # write children out
        as_node = ElementTree.Element("action-set")
        for action in self.action_sets[0]:
            as_node.append(action.to_xml())
        node.append(as_node)

        return node


    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return len(self.action_sets) > 0



version = 1
name = "Range"
create = RangeContainer


