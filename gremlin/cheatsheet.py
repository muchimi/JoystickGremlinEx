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

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.platypus import BaseDocTemplate, Paragraph, \
    Spacer, Frame, PageTemplate, Table, Flowable, PageBreak

import gremlin
import gremlin.base_profile
import gremlin.clipboard
from gremlin.keyboard import key_from_code
from gremlin.input_types import InputType
import os
import gremlin.shared_state
import gremlin.util
from PySide6 import QtWidgets, QtCore, QtGui
from enum import Enum, auto


hat_direction_abbrev = {
    "center": "C",
    "north": "N",
    "north-east": "NE",
    "east": "E",
    "south-east": "SE",
    "south": "S",
    "south-west": "SW",
    "west": "W",
    "north-west": "NW"
}


class InputItemData:

    """Represents the the data about a single InputItem entry."""

    style = getSampleStyleSheet()["Normal"]

    def __init__(self, input_item, inherited_from):
        """Creates a new instance.

        :param input_item the InputItem instance this represents
        :param inherited_from mode from which this InputItem was inherited
        """
        self.input_item : gremlin.base_profile.InputItem = input_item
        self.inherited_from = inherited_from
    

    def table_data(self):
        """Returns the data necessary to create the data table.

        :return table data entries
        """
        containers = self.input_item.containers

        # Extract information about the input item's data
        # container_count = len(containers)
        # actionset_count = [len(c.action_sets) for c in containers]
        global_desc = self.input_item.description
        container_desc = [self.extract_description_actions(c) for c in containers]

        # Basic information
        input_name = format_input_name(
            self.input_item.input_type,
            self.input_item.input_id
        )
        inherited = Paragraph(
            f"<span color='#c0c0c0'><i>{"" if self.inherited_from is None else self.inherited_from}</i></span>",
            InputItemData.style
        )

        output = []

        # If it's not a hat we have one input name and each description element
        # on a line of its own
        if self.input_item.input_type != InputType.JoystickHat:
            additional_desc = ""
            for c_descs in container_desc:
                for a_desc in c_descs:
                    additional_desc += f"\n{a_desc}"

            description = global_desc
            if len(additional_desc) > 0:
                description += additional_desc

            output.append((input_name, description, inherited))

        # In the case of a hat we have multiple lines based on virtual button
        # settings or container
        else:
            hat_outputs = []
            standard_desc = [global_desc]

            for container in containers:
                # Hat to Buttons container
                if container.tag == "hat_buttons":
                    direction_lookup = []
                    if container.button_count == 4:
                        direction_lookup = ["N", "E", "S", "W"]
                    elif container.button_count == 8:
                        direction_lookup = [
                            "N", "NE", "E", "SE", "S", "SW", "W", "NW"
                        ]

                    for i, action_set in enumerate(container.action_sets):
                        if len(action_set) > 0:
                            hat_outputs.append((
                                f"{input_name} {direction_lookup[i]}",
                                self.extract_action_set_descriptions(action_set),
                                inherited
                            ))

                # Virtual button
                elif container.virtual_button is not None:
                    c_dirs = []
                    for direction in container.virtual_button.directions:
                        c_dirs.append(f"{input_name} {hat_direction_abbrev[direction]}")
                    c_input_name = "\n".join(c_dirs)

                    hat_outputs.append((
                        c_input_name,
                        "\n".join(self.extract_description_actions(container)),
                        inherited
                    ))

                # Standard hat
                else:
                    standard_desc.append(
                        "\n".join(self.extract_description_actions(container))
                    )

            # Insert standard hat entry before the specialized ones
            output.append((input_name, "\n".join(standard_desc), inherited))
            output.extend(hat_outputs)

        return output

    def extract_description_actions(self, container):
        """Returns all description contents from Description actions.

        :param container the container instance to process
        :return description contents of all Description actions stored within
            the container
        """
        descriptions = []
        for action_set in container.action_sets:
            for action in [a for a in action_set if a.tag == "description"]:
                descriptions.append(action.description)
        return descriptions

    def extract_action_set_descriptions(self, action_set):
        """Returns a string representing the action set descriptions.

        :param action_set action set to process for descriptions
        :return string of descriptions contained in the action set
        """
        descriptions = []
        for action in [a for a in action_set if a.tag == "description"]:
            descriptions.append(action.description)
        return "\n".join(descriptions)


def recursive(device, tree, storage):
    """Recursively parses a profile and stores the contents in
    the required form.

    :param device the device of interest
    :param tree the subtree currently being processed
    :param storage the storage for the extracted data
    """
    for parent, children in tree.items():
        # Ensure the storage structure is correctly initialized
        if parent not in storage:
            storage[parent] = {}
        for child in children:
            if child not in storage:
                storage[child] = {}

        # In case the parent mode doesn't exist skip this recursion level
        if parent not in device.modes:
            continue

        # Insert actions of parent into parent
        mode = device.modes[parent]

        # Aggregate all input items into a single list
        for items in mode.config.values():
            for item in items.values():
                if len(item.containers) > 0:
                    storage[parent][(item.input_type, item.input_id)] = \
                        InputItemData(item, None)

                    for child in children:
                        storage[child][(item.input_type, item.input_id)] = \
                            InputItemData(item, parent)

        # Recursively process the remainder of the inheritance tree
        recursive(device, children, storage)


def sort_data(data):
    """Returns a new list sorted by input type.

    :param data the data to sort
    :return the sorted data
    """
    sorted_data = []

    for input_type in InputType:
        for key, value in sorted(data.items(), key=lambda x: x[0][1]):
            if input_type == key[0]:
                sorted_data.append(
                    [format_input_name(key[0], key[1]), value[0], value[1]]
                )

    return sorted_data


class DeviceFloat(Flowable):

    """Creates a device header element."""

    def __init__(self, device_name):
        """Creates a new instance.

        :param device_name name of the device
        """
        super().__init__()
        self._device_name = device_name

    def draw(self):
        self.canv.setFillColor(HexColor("#364151"))
        self.canv.rect(-1.25*cm, 0.0, A4[0]+0.1*cm, cm, stroke=False, fill=True)
        self.canv.setFillColor(HexColor("#ffffff"))
        self.canv.drawCentredString(
            A4[0]/2.0,
            0.35*cm,
            self._device_name
        )

    def wrap(self, availWidth, availHeight):
        return (A4[0]-2*cm, cm)

    def split(self, availWidth, availheight):
        return []


class ModeFloat(Flowable):

    """Creates a mode header element."""

    def __init__(self, mode_name):
        """Creates a new instance.

        :param mode_name name of the mode
        """
        super().__init__()
        self._mode_name = mode_name

        self._bar_offset = 0.1*cm
        self._bar_width = 0.25*cm
        self._bar_height = 0.75*cm

    def _draw_bar(self, path, offset):
        """Draws a single angle bar element.

        :param path the path element to which to add instructions
        :param offset the
        """
        path.moveTo(offset + self._bar_offset, 0)
        path.lineTo(offset + self._bar_offset + self._bar_width, 0)
        path.lineTo(
            offset + self._bar_height + self._bar_offset + self._bar_width,
            self._bar_height
        )
        path.lineTo(
            offset + self._bar_height + self._bar_offset,
            self._bar_height
        )
        path.lineTo(offset + self._bar_offset, 0)

        return offset + self._bar_width + self._bar_offset

    def draw(self):
        self.canv.setFillColor(HexColor("#798593"))

        offset = 7*cm

        path = self.canv.beginPath()
        path.moveTo(-1.25*cm, 0)
        path.lineTo(offset, 0)
        path.lineTo(offset+self._bar_height, self._bar_height)
        path.lineTo(-1.25*cm, self._bar_height)
        path.lineTo(-1.25*cm, 0)

        offset = self._draw_bar(path, offset)
        offset = self._draw_bar(path, offset)
        offset = self._draw_bar(path, offset)

        self.canv.drawPath(path, stroke=False, fill=True)
        self.canv.setFillColor(HexColor("#000000"))
        self.canv.setFillColor(HexColor("#ffffff"))
        self.canv.drawString(
            0,
            0.25*cm,
            self._mode_name
        )

    def wrap(self, availWidth, availHeight):
        return (A4[0]-2*cm, 0.75*cm)

    def split(self, availWidth, availheight):
        return []


def generate_cheatsheet(fname, profile):
    """Generates a cheatsheet of the provided profile.

    :param fname the file to store the cheatsheet in
    :param profile the profile to process
    """

    width, height = A4

    styles = getSampleStyleSheet()
    main_frame = Frame(cm, cm, width-2*cm, height-2*cm, showBoundary=False)
    main_template = PageTemplate(id="main", frames=[main_frame])
    doc = BaseDocTemplate(fname, pageTemplates=[main_template])

    story = []
    style = styles["Normal"]

    # Build device actions considering inheritance
    inheritance_tree = profile.build_inheritance_tree()
    device_storage = {}
    for key, device in profile.devices.items():
        device_storage[device] = {}
        recursive(device, inheritance_tree, device_storage[device])

    for dev, dev_data in device_storage.items():
        dev_float_added = False
        for mode_name, mode_data in dev_data.items():
            # Only proceed if we actually have input items available
            if len(mode_data.values()) == 0:
                continue

            if not dev_float_added:
                story.append(DeviceFloat(dev.name))
                story.append(Spacer(1, 0.25 * cm))
                dev_float_added = True

            # Add heading for device and mode combination
            story.append(ModeFloat(mode_name))
            table_data = []
            for entry in mode_data.values():
                table_data.extend(entry.table_data())

            table_style = style = [
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, HexColor("#c0c0c0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP")
            ]
            if len(table_data) == 1:
                table_style = []
            story.append(Table(
                table_data,
                colWidths=[
                    0.15 * (width - 2 * cm),
                    0.30 * (width - 2 * cm),
                    0.55 * (width - 2 * cm)
                ],
                rowHeights=[None] * len(table_data),
                style=table_style
            ))
            story.append(Spacer(1, 0.50 * cm))

        if dev_float_added:
            del story[-1]
            story.append(PageBreak())

    doc.build(story)

    # open in the default editor

    if os.path.isfile(fname):
        gremlin.util.display_file(fname)


def format_input_name(input_type, identifier):
    """Returns a formatted name of the provided input.

    :param input_type the type of the input
    :param identifier the identifier of the input
    :return formatted string of the provided input
    """
    if input_type == InputType.Keyboard:
        return key_from_code(identifier[0], identifier[1]).name
    else:
        return f"{InputType.to_display_name(input_type)} {identifier}"

class ViewInputMode(Enum):
    Device = auto()
    Mode = auto()

class ViewInput(QtWidgets.QDialog):
    ''' displays a dialog that lets the user pick from a list of mapped inputs '''

    def __init__(self, parent=None):
        super().__init__(parent)        
        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setMinimumWidth(600)

        profile = gremlin.shared_state.current_profile

        # get a list of mapped objects
         # Build device actions considering inheritance
        inheritance_tree = profile.build_inheritance_tree()
        map_data = {}
        for _, device in profile.devices.items():
            map_data[device] = {}
            recursive(device, inheritance_tree, map_data[device])

        self._display_mode = ViewInputMode.Mode

        self.option_container_widget = QtWidgets.QWidget()
        self.option_container_layout = QtWidgets.QHBoxLayout(self.option_container_widget)

        self.cb_display_by_device_widget = QtWidgets.QRadioButton("By device")
        self.cb_display_by_mode_widget = QtWidgets.QRadioButton("By mode")

        if self._display_mode ==ViewInputMode.Device:
            self.cb_display_by_device_widget.setChecked(True)
        else:
            self.cb_display_by_mode_widget.setChecked(True)
        
        self.cb_display_by_device_widget.clicked.connect(self._mode_by_device_cb)
        self.cb_display_by_mode_widget.clicked.connect(self._mode_by_mode_cb)
        self.to_clipboard_widget = QtWidgets.QPushButton()
        self.to_clipboard_widget.setIcon(gremlin.util.load_icon("button_copy.svg"))
        self.to_clipboard_widget.setToolTip("Copies the data to the clipboard")
        self.to_clipboard_widget.clicked.connect(self._to_clipboard_cb)
        self.option_container_layout.addWidget(QtWidgets.QLabel("Display Mode:"))
        self.option_container_layout.addWidget(self.cb_display_by_device_widget)
        self.option_container_layout.addWidget(self.cb_display_by_mode_widget)
        self.option_container_layout.addWidget(self.cb_display_by_mode_widget)
        self.option_container_layout.addWidget(self.to_clipboard_widget)
        self.option_container_layout.addStretch()


        self._map_data = map_data
        self._tree_widget = QtWidgets.QTreeWidget()
        self._tree_widget.setColumnCount(2)
        self._tree_widget.setHeaderLabels(["Mapping", "Value"])
        header = self._tree_widget.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(self.option_container_widget)
        self.main_layout.addWidget(self._tree_widget)

        self._update()

    QtCore.Slot()
    def _mode_by_device_cb(self):
        if self.cb_display_by_device_widget.isChecked():
            self._display_mode = ViewInputMode.Device
            self._update()

    QtCore.Slot()
    def _mode_by_mode_cb(self):
        if self.cb_display_by_device_widget.isChecked():
            self._display_mode = ViewInputMode.Mode
            self._update()

    QtCore.Slot()
    def _to_clipboard_cb(self):
        ''' copies the data to the clipboard '''
        lines = []

        it = QtWidgets.QTreeWidgetItemIterator(self._tree_widget)
        item : QtWidgets.QTreeWidgetItem
        while it.value():
            item = it.value()
            depth = 0
            parent = item.parent()
            while parent:
                depth +=1
                parent = parent.parent()
            text = f"{'\t'*depth if depth else ''}{item.text(0)} {item.text(1)}\n"
            lines.append(text)
            it+=1
    
        text = "".join(lines)
        gremlin.clipboard.Clipboard().set_windows_clipboard_text(text)
            
            



    def _update(self):
        
        nodes = []
        
        is_mode = self._display_mode == ViewInputMode.Mode

        if is_mode:
            # display data by mode
            mode_nodes = {}
            for dev, dev_data in  self._map_data.items():
                for mode_name, mode_data in dev_data.items():
                    # Only proceed if we actually have input items available
                    if len(mode_data.values()) == 0:
                        continue
                    if is_mode:
                        if not mode_name in mode_nodes.keys():
                            mode_node = QtWidgets.QTreeWidgetItem([f"Mode: [{mode_name}]"])
                            mode_nodes[mode_name] = mode_node 
                        else:
                            mode_node = mode_nodes[mode_name]
                    else:
                        mode_node = QtWidgets.QTreeWidgetItem([mode_name])

                    device_node = QtWidgets.QTreeWidgetItem([f"Device: '{dev.name}'"])

                    has_containers = False
                    for entry in mode_data.values():
                        if entry.input_item.containers:
                            for container in entry.input_item.containers:
                                for action_set in container.action_sets:
                                    for action in action_set:
                                        action_node = QtWidgets.QTreeWidgetItem([action.name, action.display_name()])
                                        device_node.addChild(action_node)
                            has_containers = True

                    if has_containers:
                        # has data
                        mode_node.addChild(device_node)
                        if not mode_node in nodes:
                            nodes.append(mode_node)
            
        else:
            # display data by device                
            for dev, dev_data in  self._map_data.items():
                device_node = QtWidgets.QTreeWidgetItem([f"Device: '{dev.name}'"])
                nodes.append(device_node)
                
                for mode_name, mode_data in dev_data.items():
                    # Only proceed if we actually have input items available
                    if len(mode_data.values()) == 0:
                        continue
                    mode_node = QtWidgets.QTreeWidgetItem([f"Mode: [{mode_name}]"])
                    
                    has_containers = False
                    for entry in mode_data.values():
                        if entry.input_item.containers:
                            for container in entry.input_item.containers:
                                for action_set in container.action_sets:
                                    for action in action_set:
                                        action_node = QtWidgets.QTreeWidgetItem([action.name, action.display_name()])
                                        mode_node.addChild(action_node)
                            has_containers = True

                    if has_containers:
                        # has data
                        device_node.addChild(mode_node)
                        if not device_node in nodes:
                            nodes.append(device_node)

        self._tree_widget.clear()     
        self._tree_widget.insertTopLevelItems(0, nodes)
        self._tree_widget.expandAll()


