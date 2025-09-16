# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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

from lxml import etree as ElementTree

from PySide6 import QtWidgets

import dinput

import gremlin
import gremlin.actions
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.input_types import InputType
from gremlin.base_buttons import VirtualHatButton
from container_plugins.basic import BasicContainer
from gremlin.ui.input_item import AbstractContainerWidget
from gremlin.base_profile import AbstractContainer
import gremlin.execution_graph
import gremlin.config
from gremlin.util import safe_format, safe_read
import logging
from shiboken6 import Shiboken

syslog = logging.getLogger("system")

# Lookup for direction to index with 4 way hat usage
_four_lookup = {
    (0, 1): 0,
    (1, 0): 1,
    (0, -1): 2,
    (-1, 0): 3
}

# Lookup for direction to indices with 8 way hat usage
_eight_lookup = {
    (0, 1): 0,
    (1, 1): 1,
    (1, 0): 2,
    (1, -1): 3,
    (0, -1): 4,
    (-1, -1): 5,
    (-1, 0): 6,
    (-1, 1): 7
}

# Names for the indices in a 4 way hat case
_four_names = ["North", "East", "South", "West"]

# Names for the indices in a 8 way hat case
_eight_names = [
    "North", "North East", "East", "South East", "South",
    "South West", "West", "North West"
]


class HatButtonsContainerWidget(AbstractContainerWidget):

    """Basic container which holds a single action."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent)

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        
        gremlin.ui.ui_common.clear_layout(self.action_layout)

        self.options_layout = QtWidgets.QHBoxLayout()
        self.four_way = QtWidgets.QRadioButton("4 Way")
        self.eight_way = QtWidgets.QRadioButton("8 Way")
        if self.profile_data.button_count == 4:
            self.four_way.setChecked(True)
            self.eight_way.setChecked(False)
        else:
            self.four_way.setChecked(False)
            self.eight_way.setChecked(True)
        self.four_way.clicked.connect(self._change_button_type)
        self.eight_way.clicked.connect(self._change_button_type)
        self.options_layout.addWidget(QtWidgets.QLabel("<b>Button mode</b>"))
        self.options_layout.addWidget(self.four_way)
        self.options_layout.addWidget(self.eight_way)
        self.options_layout.addStretch()

        self.action_layout.addLayout(self.options_layout)

        # Create hat direction action sets
        self._ensureActionSet(self.profile_data.button_count)
        if self.profile_data.button_count == 4:
            for i, direction in enumerate(_four_names):
                self.action_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
                self._create_action_widget(
                    i,
                    direction,
                    self.action_layout,
                    gremlin.ui.ui_common.ContainerViewTypes.Action
                )
            self._add_action_selector(lambda x: self._add_action(i, x),direction, lambda x: self._paste_action(i, x)
                                          )
        elif self.profile_data.button_count == 8:
            for i, direction in enumerate(_eight_names):
                self.action_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
                self._create_action_widget(
                    i,
                    direction,
                    self.action_layout,
                    gremlin.ui.ui_common.ContainerViewTypes.Action
                )
            self._add_action_selector(lambda x: self._add_action(i, x), direction, lambda x: self._paste_action(i, x))
        else:
            pass

        self.action_layout.addStretch()

    def _ensureActionSet(self, index):
        while index > len(self.profile_data.action_sets):
            self.profile_data.action_sets.append([])

    def _add_action_selector(self, add_action_cb, label, paste_action_cb = None):
        """Adds an action selection UI widget.

        :param add_action_cb function to call when an action is added
        :param label the description of the action selector
        """
        input_item = self.profile_data.input_item
        action_selector = gremlin.ui.ui_common.ActionSelector(InputType.JoystickButton, input_item)
        action_selector.action_added.connect(add_action_cb)
        if paste_action_cb:
            action_selector.action_paste.connect(paste_action_cb)

        group_layout = QtWidgets.QVBoxLayout()
        group_layout.addWidget(action_selector)
        group_layout.addStretch(1)
        group_box = QtWidgets.QGroupBox(label)
        group_box.setLayout(group_layout)

        self.action_layout.addWidget(group_box)        

    def _create_condition_ui(self):
        if not self.profile_data.action_sets:
            return

        lookup = _four_lookup
        if self.profile_data.button_count == 8:
            lookup = _eight_lookup
        id_to_direction = {}
        for k, v in lookup.items():
            id_to_direction[v] = k

        names = _four_names
        if self.profile_data.button_count == 8:
            names = _eight_names
        for i, action_set in enumerate(self.profile_data.action_sets):
            widget = self._create_action_set_widget(
                action_set,
                names[i],
                gremlin.ui.ui_common.ContainerViewTypes.Conditions
            )
            self.activation_condition_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

    

    def _create_action_widget(self, index, label, layout, view_type):
        """Creates a new action widget.

        :param index the index at which to store the created action
        :param label the name of the action to create
        :param layout the layout widget to populate
        :param view_type the visualization type being used
        """
        self._ensureActionSet(index)
        widget = self._create_action_set_widget(
            self.profile_data.action_sets[index],
            label,
            view_type,

        )
        layout.addWidget(widget)
        widget.redraw()
        widget.model.data_changed.connect(self.container_modified.emit)

    def _add_action(self, index, action):
        """Adds a new action to the container action set.
        :param index: the action set to add the action to
        :param action - action or action
        """
        from gremlin.clipboard import Clipboard
        if action is None:
            return
        
        gremlin.util.pushCursor()

        try:

            if isinstance(action, str):
                action_name = action
                plugin_manager = gremlin.plugin_manager.ActionPlugins()
                action_item = plugin_manager.get_class(action_name)(self.profile_data)
            elif isinstance(action, Clipboard):
                # paste operation
                if action.is_action:
                    # verify the action in the clipboard is appropriate for this input

                    action_item = plugin_manager.duplicate(action.data, self.profile_data)

            self.profile_data.add_action(action_item, index)
            self.container_modified.emit()
        finally:
            gremlin.util.popCursor()


    def _paste_action(self, index, action):
        ''' paste action'''

        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.duplicate(action, self.profile_data)
            if self.profile_data.action_sets[index] is None:
                self.profile_data.action_sets[index] = []
            self.profile_data.action_sets[index].append(action_item)
            self.profile_data.create_or_delete_virtual_button()
        finally:
            gremlin.util.popCursor()



    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        pass

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        title = "Hat Buttons: "
        if len(self.profile_data.action_sets) > 0:
            title += ", ".join(a.name for a in self.profile_data.action_sets[0])
        return title

    def _change_button_type(self, state):
        """Handles changing the number of buttons being used.

        :param state radio button state - not used
        """
        button_count = 4 if self.four_way.isChecked() else 8
        if button_count != self.profile_data.button_count:
            self.profile_data.button_count = button_count
            if button_count == 4 and len(self.profile_data.action_sets) == 8:
                del self.profile_data.action_sets[7]
                del self.profile_data.action_sets[5]
                del self.profile_data.action_sets[3]
                del self.profile_data.action_sets[1]
            elif button_count == 8 and len(self.profile_data.action_sets) == 4:
                self.profile_data.action_sets.insert(1, [])
                self.profile_data.action_sets.insert(3, [])
                self.profile_data.action_sets.insert(5, [])
                self.profile_data.action_sets.insert(7, [])
            self._create_action_ui()


class HatButtonsContainerFunctor(gremlin.base_conditions.AbstractTriggerFunctor):

    """Executes the contents of the associated basic container.

    This functor does nothing when called (should never happen) as the
    callbacks generated by this container are several basic containers.
    """

    def __init__(self, container, parent = None):
        super().__init__(container, parent)
        self.container = container

    def profile_start(self):
        ec = gremlin.execution_graph.ExecutionContext()
        container_node = ec.find(self.container, gremlin.execution_graph.ExecutionGraphNodeType.Container)

        if not container_node:
            # if we get here it usually means an instance of the functor is still in memory and hooked to the execution graph which should not happen
            syslog.error(f"Unable to find this action in the execution tree: {str(self.action_data)}")
            self.valid = False
            return

        self.container_node = container_node

        self.button_count = self.container.button_count
        self.lookup = _four_lookup
        if self.button_count == 8:
            self.lookup = _eight_lookup

        self.action_nodes = {} # list of nodes arranged by button index
        action_sets = {}
        for index, action_set in enumerate(self.container.action_sets):
            action_sets[index] = action_set

        group_node = self.container_node.children[0] # group node is the only child of the container node
        self.action_set_nodes = [node for node in group_node.children if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.ActionSet]
        self.action_set_lookup = {}

        for index in self.lookup.values():
            # index of each data set
            if index in action_sets:
                if not index in self.action_set_lookup:
                    self.action_set_lookup[index] = []
                action_set = action_sets[index]
                if action_set is not None:

                    for action in action_set:
                        action_node = [node for node in self.action_set_nodes if node.containsActionId(action.id)]
                        self.action_set_lookup[index].append(action_node)

        self.release_events = [] # release events (node, event)

            


    def process_event(self, event, value, extra_data = None):
        """Executes the content with the provided data.

        :param event the event to process
        :param value the value received with the event
        :return True if execution was successful, False otherwise
        """
        
        

        ec = gremlin.execution_graph.ExecutionContext()
        
        # self.button_count = 4
        # #self.action_sets = [[], [], [], []]

        hat_value = value.current
        if hat_value == (0,0):
            # hat released = issue release events
            value.is_pressed = False
            for node, event_release in self.release_events:
                ec.execute_node(node, event_release, value, extra_data)
            # clear for next use
            self.release_events.clear()
        elif hat_value in self.lookup:
            index = self.lookup[hat_value]
            if index in self.action_set_lookup:
                nodes = self.action_set_lookup[index]
                for action_set_nodes in nodes:
                    value.is_pressed = True                    
                    event_press = event.fake_button(True, True)
                    event_release = event.fake_button(False, True)
                    for node in action_set_nodes:
                        self.release_events.append((node, event_release))
                        ec.execute_node(node, event_press, value, extra_data)



       # self._execute(event, value, extra_data)
        return True
        


class HatButtonsContainer(AbstractContainer):

    """Represents a container which holds exactly one action."""

    name = "Hat Buttons"
    tag = "hat_buttons"
    functor = HatButtonsContainerFunctor
    widget = HatButtonsContainerWidget
    # override default allowed inputs here
    input_types = [InputType.JoystickHat]
    interaction_types = []

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.button_count = 8
        self.action_sets = []
        for _ in range(self.button_count):
            self.action_sets.append([])

        # make actions think we're attached to a button
        self.override_input_id = 1
        self.override_input_type = InputType.JoystickButton


    def get_input_type(self):
        ''' override input type for action selectors '''
        return self.override_input_type


    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        self.button_count = gremlin.profile.safe_read(node, "button-count", int, 8)
       

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", HatButtonsContainer.tag)
        node.set("button-count", str(self.button_count))

        for action_set in self.action_sets:
            as_node = ElementTree.Element("action-set")
            for action in action_set:
                as_node.append(action.to_xml())
            node.append(as_node)
        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        count = 0
        for action_set in self.action_sets:
            count += len(action_set)
        return count > 0


# Plugin definitions
version = 1
name = "hat_buttons"
create = HatButtonsContainer
