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
import gremlin.ui.ui_common
from gremlin.input_types import InputType
from gremlin.ui.input_item import AbstractContainerWidget
from gremlin.base_profile import AbstractContainer
from gremlin.base_conditions import AbstractTriggerFunctor
import gremlin.base_classes
import gremlin.execution_graph
import gremlin.config
from gremlin.util import safe_format, safe_read
import logging
from shiboken6 import Shiboken
import vjoy.vjoy
from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia

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

        warning_widget = gremlin.ui.ui_common.QWarningWidget("Experimental container.  Not all features may function as expected.")
        self.action_layout.addWidget(warning_widget)

        
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

        self.sticky_widget = QtWidgets.QCheckBox("Sticky buttons")
        self.sticky_widget.setToolTip("When on, a release event does not occur unless the hat is returned to the center position.\nWhen off, any hat change results in a release of the prior position.")
        self.sticky_widget.setChecked(self.profile_data.sticky)
        self.sticky_widget.clicked.connect(self._change_sticky)
        

        widgets = [
            "<b>Button mode</b>",
            self.four_way,
            self.eight_way,
            self.sticky_widget
                   ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)
        self.action_layout.addWidget(widget)
        action_sets = self.profile_data.getActionSets()
        for action_set in action_sets:
            self.action_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
            self._create_action_widget(
                action_set,
                self.action_layout,
                gremlin.ui.ui_common.ContainerViewTypes.Action
            )
            #self._add_action_selector(lambda x: self._add_action(direction, x), name, lambda x: self._paste_action(direction, x))
        
        self.action_layout.addStretch()

    def _ensureActionSet(self, position):
        return self.profile_data.getActionSet(position)

    # def _add_action_selector(self, add_action_cb, label, paste_action_cb = None):
    #     """Adds an action selection UI widget.

    #     :param add_action_cb function to call when an action is added
    #     :param label the description of the action selector
    #     """
    #     input_item = self.profile_data.input_item
    #     action_selector = gremlin.ui.ui_common.ActionSelector(InputType.JoystickButton, input_item)
    #     action_selector.action_added.connect(add_action_cb)
    #     if paste_action_cb:
    #         action_selector.action_paste.connect(paste_action_cb)

    #     group_layout = QtWidgets.QVBoxLayout()
    #     group_layout.addWidget(action_selector)
    #     group_layout.addStretch(1)
    #     group_box = QtWidgets.QGroupBox(label)
    #     group_box.setLayout(group_layout)

    #     self.action_layout.addWidget(group_box)        

    def _create_condition_ui(self):
        action_sets = self.profile_data.getActionSets()
        if not action_sets:
            return
        
        for action_set in action_sets:
            direction = action_set.data
            widget = self._create_action_set_widget(
                action_set,
                vjoy.vjoy.Hat.getName(direction),
                gremlin.ui.ui_common.ContainerViewTypes.Conditions
            )
            self.activation_condition_layout.addWidget(widget)
            widget.redraw()
            widget.model.data_changed.connect(self.container_modified.emit)

    

    def _create_action_widget(self, action_set, layout, view_type):
        """Creates a new action widget.

        :param index the index at which to store the created action
        :param label the name of the action to create
        :param layout the layout widget to populate
        :param view_type the visualization type being used
        """
        direction = action_set.data
        icon = vjoy.vjoy.Hat.getIcon(direction)
        widget = self._create_action_set_widget(
            action_set,
            vjoy.vjoy.Hat.getName(direction),
            view_type,
            icon,
            icon_size = 48

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
            
            #self.container_modified.emit()
        finally:
            gremlin.util.popCursor()


    def _paste_action(self, direction, action):
        ''' paste action'''

        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.duplicate(action, self.profile_data)
            action_set = self.profile_data.getActionSet(direction)
            action_set.append(action_item)
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

    @QtCore.Slot(bool)
    def _change_sticky(self, checked : bool):
        self.profile_data.sticky = checked


class HatButtonsContainerFunctor(AbstractTriggerFunctor):

    """Executes the contents of the associated basic container.

    This functor does nothing when called (should never happen) as the
    callbacks generated by this container are several basic containers.
    """

    def __init__(self, container, parent = None):
        super().__init__(container, parent)
        self.container = container
        self.release_events = [] # release events (node, event)
        self.action_set_lookup = {}
        self.action_nodes = {}

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

        self.action_nodes.clear() # list of nodes arranged by button index
        action_sets = self.container.getActionSets() # define action sets
        

        group_node = self.container_node.children[0] # group node is the only child of the container node
        self.action_set_nodes = [node for node in group_node.children if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.ActionSet]
        self.action_set_lookup = {} # lookup of action set button position to list of nodes to execute
        for action_set in action_sets:
            #nodes = [node for node in self.action_nodes if node.id ]
            direction = action_set.data
            if not direction in self.action_set_lookup:
                self.action_set_lookup[direction] = []
            for action in action_set:
                action_node = [node for node in self.action_set_nodes if node.containsActionId(action.id)]
                self.action_set_lookup[direction].append(action_node)
            



        # group_node = self.container_node.children[0] # group node is the only child of the container node
        # self.action_set_nodes = [node for node in group_node.children if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.ActionSet]
        # self.action_set_lookup = {}

        # for index in self.lookup.values():
        #     # index of each data set
        #     if index in action_sets:
        #         if not index in self.action_set_lookup:
        #             self.action_set_lookup[index] = []
        #         action_set = action_sets[index]
        #         if action_set is not None:

        #             for action in action_set:
        #                 action_node = [node for node in self.action_set_nodes if node.containsActionId(action.id)]
        #                 self.action_set_lookup[index].append(action_node)

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

        direction = value.current
        sticky = self.container.sticky
        if direction == (0,0) or not sticky: # release prior position
            # hat released = issue release events
            value.is_pressed = False
            for node, event_release in self.release_events:
                ec.execute_node(node, event_release, value, extra_data)
            # clear for next use
            self.release_events.clear()

        if event.is_pressed and direction in self.action_set_lookup:
            nodes = self.action_set_lookup[direction] # graph nodes to execute
            for action_set_nodes in nodes:
                value.is_pressed = True                    

                event_press = event.fake_button(True, True) # fake button event for press
                event_release = event.fake_button(False, True) # fake button event for release
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
        self.sticky = True # true if hat only releases in the center position
        
        self.actionsetParseCallback = self._parse_xml_actionset # callback when the action set node is being read

        # make actions think we're attached to a button
        self.override_input_id = 1
        self.override_input_type = InputType.JoystickButton
        self.action_set_position_map = {} # used positions
        self.custom_action_sets = True # indicate we use custom action sets
        


    def getActionSet(self, position):
        ''' gets an action set for a specific position 
        
        :param position: position tuple or name

        '''
        if isinstance(position, str):
            position = vjoy.vjoy.Hat.getDirection(position) # name -> tuple
            if not position:
                syslog.error(f"HATBUTTONCONTAINER: invalid position: {position} found.")
                return None
        if not position in self.action_set_position_map:
            self.action_set_position_map[position] = gremlin.base_classes.DataList(position)
        return self.action_set_position_map[position]
    
    def getActionSets(self):
        ''' all action sets for this input hat  '''
        positions = []
        if self.button_count == 4:
            positions = vjoy.vjoy.Hat.getFourDirections()
        elif self.button_count == 8:
            positions = vjoy.vjoy.Hat.getEightDirections()
        return [self.getActionSet(position) for position in positions]

   
    @property
    def action_sets(self):
        ''' override action set property '''
        return self.getActionSets()
    
    @action_sets.setter
    def action_sets(self, value):
        pass

    def get_input_type(self):
        ''' override input type for action selectors '''
        return self.override_input_type


    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        self.button_count = safe_read(node, "button-count", int, 8)
        self.sticky = safe_read(node, "sticky", bool, True)

    def _parse_xml_actionset(self, node):
        ''' special handler for custom action set parsing as the action set node has custom entries '''
        if "position" in node.attrib:
            name = node.get("position")
            position = vjoy.vjoy.Hat.getDirection(name) # convert from ID to position tuple
            action_set = gremlin.base_classes.DataList(position)
            self.action_set_position_map[position] = action_set
            return action_set
        return None
       

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", HatButtonsContainer.tag)
        node.set("button-count", str(self.button_count))
        node.set("sticky", safe_format(self.sticky, bool))

        for action_set in self.action_sets:
            if len(action_set) > 0:
                # only save used positions
                as_node = ElementTree.Element("action-set")
                position = action_set.data
                name = vjoy.vjoy.Hat.getName(position) 
                if name:
                    as_node.set("position", name)
                for action in action_set:
                    as_node.append(action.to_xml())
                node.append(as_node)
        return node

    def _is_container_valid(self):
        return True
    
    def get_action_sets(self):
        """ override method: returns action sets - override because we have custom sets """
        return self.getActionSets()


# Plugin definitions
version = 1
name = "hat_buttons"
create = HatButtonsContainer
