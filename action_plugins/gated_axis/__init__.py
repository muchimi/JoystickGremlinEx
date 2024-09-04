# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
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


import os
from PySide6 import QtWidgets
from lxml import etree as ElementTree

import gremlin.base_profile
from gremlin.input_types import InputType
import gremlin.ui.input_item
import gremlin.gated_handler
import gremlin.shared_state


class GatedAxisWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget associated with the action of switching to the previous mode."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, GatedAxis))

    def _create_ui(self):

        self.container_widget = QtWidgets.QWidget()
        self.container_layout = QtWidgets.QVBoxLayout(self.container_widget)
        self.container_widget.setContentsMargins(0,0,0,0)

        
        self.gate_widget = gremlin.gated_handler.GatedAxisWidget(action_data = self.action_data,
                                                            show_configuration=False
                                                            )

        self.main_layout.addWidget(self.gate_widget)


    def _populate_ui(self):
        pass


class GatedAxisFunctor(gremlin.base_profile.AbstractContainerActionFunctor):

    def __init__(self, action):
        super().__init__(action)

    def process_event(self, event, value):
        # all the work happens in the gate widget - nothing to do
        return True


class GatedAxis(gremlin.base_profile.AbstractAction):

    """ action data for the GatedAxis action """

    name = "Gated Axis"
    tag = "gated-axis"

    default_button_activation = (True, False)
    # override default allowed input types here if not all
    input_types = [
        InputType.JoystickAxis,
    ]

    functor = GatedAxisFunctor
    widget = GatedAxisWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        # gate data
        gate_data = gremlin.gated_handler.GateData(profile_mode = gremlin.shared_state.current_mode, action_data=self)
        self.gate_data = gate_data
        self.gates = [gate_data]

    def icon(self):
        return "fa.sliders"

    def requires_virtual_button(self):
        return False

    def _parse_xml(self, node):
        # load gate data
        gates = []
        gate_node = gremlin.util.get_xml_child(node,"gates")
        if not gate_node is None:
            for child in gate_node:
                gate_data = gremlin.gated_handler.GateData(self, action_data = self)
                gate_data.from_xml(child)
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
