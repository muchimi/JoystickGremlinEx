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

from __future__ import annotations
import os
from PySide6 import QtWidgets, QtCore
from lxml import etree as ElementTree

import gremlin.base_profile
from gremlin.input_types import InputType
import gremlin.shared_state
import gremlin.ui.input_item
import gremlin.gated_handler
import gremlin.shared_state
import logging

syslog = logging.getLogger("system")

class GatedAxisWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget associated with the action of switching to the previous mode."""

    def __init__(self, action_data, parent=None):
        self.action_data = action_data
        self.gate_widget = None
        super().__init__(action_data, parent=parent)
  



    def _create_ui(self):

        self.container_widget = QtWidgets.QWidget()
        self.container_layout = QtWidgets.QVBoxLayout(self.container_widget)
        self.container_widget.setContentsMargins(0,0,0,0)

        self.gate_widget  = gremlin.gated_handler.GatedAxisWidget(action_data = self.action_data,
                                                                show_configuration=False,
                                                                parent=self
                                                                )
        #cache.register(self.action_data, widget)
        self.main_layout.addWidget(self.gate_widget)
        

    def _populate_ui(self):
        pass

    def _cleanup_ui(self):
        ''' cleanup the UI and widget hooks '''

        if self.gate_widget:
            self.gate_widget.unhook()
            self.main_layout.removeWidget(self.gate_widget)
            self.gate_widget.deleteLater()
            self.gate_widget = None

    


class GatedAxisFunctor(gremlin.base_profile.AbstractContainerActionFunctor):

    def __init__(self, action_data, parent = None):
        super().__init__(action_data, parent)
        self.manual_callback = True # indicate this functor only uses manual callbacks

    # def profile_start(self):
    #     ''' register the gated functor'''
    #     #self.action_data.gate_data.setActionId(self.action_data.id)
    #     pass

    def process_event(self, event, value, extra_data = None):
        # all the work happens in the gate widget hook function - nothing to do
        #self.action_data.gate_data.process_event(event, value)
        #syslog.info("Gated Axis: trigger")
        #return self.action_data.gate_data.process_event(event, value, extra_data)
        #return True # prevent child from executing
        return True

class GatedAxis(gremlin.base_profile.AbstractAction):

    """ action data for the GatedAxis action """

    name = "Gated Axis"
    tag = "gated-axis"

    default_button_activation = (True, False)
    # override default allowed input types here if not all
    input_types = [
        InputType.JoystickAxis,
        InputType.OpenSoundControl,
        InputType.Midi
    ]

    functor = GatedAxisFunctor
    widget = GatedAxisWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.singleton = True # this action can only appear once per input

        # gate data
        gate_data = gremlin.gated_handler.GateData(profile_mode = gremlin.shared_state.current_mode, action_data=self)
        self.gate_data = gate_data
        self.gates = [gate_data]

    def _cleanup(self):
        ''' clean ourselves up '''
        super()._cleanup()
        if self.gates:
            self.gates.clear()
        if self.gate_data:
            self.gate_data.unhook()
            self.gate_data = None


    def icon(self):
        return "ph.sliders"

    def requires_virtual_button(self):
        return False

    def _parse_xml(self, node, data = None):
        # load gate data
        import gremlin.util
        
        gates = []
        gate_node = gremlin.util.get_xml_child(node,"gates")
        profile_mode = gremlin.util.get_xml_mode(node)
        if not profile_mode:
            # paste operation
            profile_mode = gremlin.shared_state.current_mode
        if not gate_node is None:
            for child in gate_node:
                gate_data = gremlin.gated_handler.GateData(profile_mode, action_data = self)
                
                gate_data.from_xml(child, data)
                gates.append(gate_data)

        if gates:
            self.gates = gates
            self.gate_data = gates[0]

    def _generate_xml(self):
         # save gate data
        node = ElementTree.Element(GatedAxis.tag)
        if self.gates:
            node_gate = ElementTree.SubElement(node, "gates")
            for gate_data in self.gates:
                child = gate_data.to_xml()
                node_gate.append(child)
        return node

    def _is_valid(self):
        return True


version = 1
name = "gated-axis"
create = GatedAxis
