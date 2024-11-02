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


import logging

from PySide6 import QtWidgets, QtCore


import gremlin
import gremlin.base_profile
import gremlin.config
import gremlin.config
import gremlin.event_handler
import gremlin.event_handler
import gremlin.joystick_handling
import gremlin.profile
import gremlin.shared_state
import gremlin.types
from gremlin.types import DeviceType
from gremlin.input_types import InputType
import gremlin.util
import gremlin.ui.input_item as input_item
import gremlin.ui.ui_common
from  gremlin.clipboard import Clipboard, ObjectEncoder, EncoderType
import lxml

class InputItemConfiguration(QtWidgets.QFrame):

    """ mapping viewer for a selected input item (this is the right side of the device tab) """

    # Signal emitted when the description changes
    description_changed = QtCore.Signal(str) # indicates the description was changed
    description_clear = QtCore.Signal() # clear the description field

    def __init__(self, item_data = None, input_type = None, parent=None):
        """Creates a new object instance.

        :params:
         
        item_data =profile data associated with the item, can be none to display an empty box
        input_type = override input type if the input type is not that of the item_data (InputItem) - controls what containers/actions are available
        parent = the parent of this widget

        """
        super().__init__(parent)

        self.id = gremlin.util.get_guid()
        self.item_data : gremlin.base_profile.InputItem = item_data
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.button_layout = QtWidgets.QHBoxLayout()
        self.widget_layout = QtWidgets.QVBoxLayout()
        self._input_type = InputType.NotSet
        if input_type is not None:
            # override input type
            self._input_type = input_type
        else:
            if item_data is not None:
                self._input_type = item_data.input_type

        if item_data is None:
            parent = self.parent()
            while parent and not isinstance(parent, JoystickDeviceTabWidget):
                parent = self.parent()
            parent :JoystickDeviceTabWidget
            if parent is not None:
                item_data = parent.last_item_data_key
        
            label = QtWidgets.QLabel("Please select an input to configure")
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
            self.main_layout.addWidget(label)
            return

        # verbose = gremlin.config.Configuration().verbose
        # if verbose:
        #     syslog = logging.getLogger("system")
        #     syslog.info(f"Create InputItemConfiguration for {item_data.debug_display}")

        
        if not item_data.is_action:
            # only draw description if not a sub action item
            self._create_description()
        
        if self.item_data.device_type == DeviceType.VJoy:
            self._create_vjoy_dropdowns()
        else:
            self._create_dropdowns()

        self.action_model = ActionContainerModel(self.item_data.containers, self.item_data, self._input_type)
        self.action_view = ActionContainerView()
        self.action_view.setContentsMargins(0,0,0,0)
        self.action_view.set_model(self.action_model)
        self.action_view.redraw()

        self.main_layout.addWidget(self.action_view)

        # setup the container widget reference
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        plugin_manager.set_widget(self.item_data, self)


    def _add_action(self, action_name):
        """Adds a new action to the input item.

        :param action_name name of the action to be added
        """
        import container_plugins.basic
        import gremlin.plugin_manager
        # If this is a vJoy item then do not permit adding an action if
        # there is already one present, as only response curves can be added
        # and only one of them makes sense to exist
        if self.item_data.get_device_type() == DeviceType.VJoy:
            if len(self.item_data.containers) > 0:
                return

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        container = container_plugins.basic.BasicContainer(self.item_data)
        action = plugin_manager.get_class(action_name)(container)
        container.add_action(action)
      
        if len(container.action_sets) > 0:
            self.action_model.add_container(container)
        
        self.action_model.data_changed.emit()

        el = gremlin.event_handler.EventListener()
        el.mapping_changed.emit(self.item_data)
        

    def _paste_action(self, action):
        """ paste action to the input item """
        import container_plugins.basic
        import gremlin.plugin_manager
        if self.item_data.get_device_type() == DeviceType.VJoy:
            if len(self.item_data.containers) > 0:
                return

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        container = container_plugins.basic.BasicContainer(self.item_data)
        action_item = plugin_manager.duplicate(action, container )
        
        # remap inputs
        action_item.update_inputs(self.item_data)
        container.add_action(action_item)
        
        if len(container.action_sets) > 0:
            self.action_model.add_container(container)
        self.action_model.data_changed.emit()

        eh = gremlin.event_handler.EventListener()
        eh.mapping_changed.emit(self.item_data)

    def _add_container(self, container_name):
        """Adds a new container to the input item.

        :param container_name name of the container to be added
        """
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        container = plugin_manager.get_class(container_name)(self.item_data)
        if hasattr(container, "action_model"):
            container.action_model = self.action_model
        self.action_model.add_container(container)
        plugin_manager.set_container_data(self.item_data, container)

        eh = gremlin.event_handler.EventListener()
        eh.mapping_changed.emit(self.item_data)

        return container
    

    def _paste_container(self, container):
        """Adds a new container to the input item.

        :param container container to be added
        """
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()

        if isinstance(container, ObjectEncoder):
            oc = container
            if oc.encoder_type == EncoderType.Container:
                xml = oc.data
                node = lxml.etree.fromstring(xml)
                container_type = node.get("type")
                container_tag_map = plugin_manager.tag_map
                new_container = container_tag_map[container_type](self.item_data)
                new_container.from_xml(node)

                #new_container = copy.deepcopy(container)

                for action_set in new_container.get_action_sets():
                    for action in action_set:
                        action.action_id = gremlin.util.get_guid()
        else:
            new_container = plugin_manager.duplicate(container, self.item_data)

        if hasattr(new_container, "action_model"):
            new_container.action_model = self.action_model

        
        self.action_model.add_container(new_container)
        plugin_manager.set_container_data(self.item_data, new_container)

        eh = gremlin.event_handler.EventListener()
        eh.mapping_changed.emit(self.item_data)

        return new_container

    def _remove_container(self, container):
        """Removes an existing container from the InputItem.

        :param container the container instance to be removed
        """

        self.action_model.remove_container(container)

        eh = gremlin.event_handler.EventListener()
        eh.mapping_changed.emit(self.item_data)

                

    def _create_description(self):
        """Creates the description input for the input item."""
        self.description_layout = QtWidgets.QHBoxLayout()
        self.description_layout.addWidget(
            QtWidgets.QLabel("<b>Action Description</b>")
        )
        self.description_field = QtWidgets.QLineEdit()
        self.description_field.setText(self.item_data.description)
        self.description_field.textChanged.connect(self._edit_description_cb)
        self.description_layout.addWidget(self.description_field)
        del_icon = gremlin.util.load_icon("mdi.delete")
        self.description_clear_button = QtWidgets.QPushButton()
        self.description_clear_button.setIcon(del_icon)
        self.description_clear_button.clicked.connect(self._delete_description_cb)
        self.description_clear_button.setMaximumWidth(20)
        self.description_clear_button.setToolTip("Reset description to default")
        self.description_layout.addWidget(self.description_clear_button)

        self.main_layout.addLayout(self.description_layout)


    def _create_dropdowns(self):
        """Creates a drop down selection with actions that can be
        added to the current input item.
        """
        import gremlin.ui.input_item as input_item
        import gremlin.ui.ui_common as ui_common
        self.action_layout = QtWidgets.QHBoxLayout()

        # repeat the current active mode for editing
        # mode_widget = QtWidgets.QLineEdit(text=gremlin.shared_state.current_mode)
        # mode_widget.setReadOnly(True)

        # self.action_layout.addWidget(QtWidgets.QLabel("Mode:"))
        # self.action_layout.addWidget(mode_widget)

        self.action_selector = ui_common.ActionSelector(
            self._input_type
        )
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.action_paste.connect(self._paste_action)

        self.container_selector = input_item.ContainerSelector(
            self._input_type
        )
        self.container_selector.container_added.connect(self._add_container)
        self.container_selector.container_paste.connect(self._paste_container)
        self.always_execute = QtWidgets.QCheckBox("Always execute")
        self.always_execute.setChecked(self.item_data.always_execute)
        self.always_execute.stateChanged.connect(self._always_execute_cb)

        self.action_layout.addWidget(self.action_selector)
        self.action_layout.addStretch()
        self.action_layout.addWidget(self.container_selector)
        self.action_layout.addWidget(self.always_execute)
        self.main_layout.addLayout(self.action_layout)

    def _create_vjoy_dropdowns(self):
        """Creates the action drop down selection for vJoy devices."""
        self.action_layout = QtWidgets.QHBoxLayout()

        self.action_selector = gremlin.ui.ui_common.ActionSelector(
            gremlin.types.DeviceType.VJoy
        )
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.action_paste.connect(self._paste_action)
        self.action_layout.addWidget(self.action_selector)
        self.main_layout.addLayout(self.action_layout)

    @QtCore.Slot()
    def _edit_description_cb(self, text):
        """Handles changes to the description text field.

        :param text the new contents of the text field
        """
        self.item_data.description = text
        self.description_changed.emit(text)

    @QtCore.Slot()
    def _delete_description_cb(self):
        """ deletes the description text.

        :param text the new contents of the text field
        """
        self.item_data.description = None
        self.description_clear.emit()

    def _always_execute_cb(self, state):
        """Handles changes to the always execute checkbox.

        :param state the new state of the checkbox
        """
        self.item_data.always_execute = self.always_execute.isChecked()

    def _valid_action_names(self):
        """Returns a list of valid actions for this InputItemWidget.

        :return list of valid action names
        """
        action_names = []
        if self.item_data.input_type == gremlin.types.DeviceType.VJoy:
            entry = gremlin.plugin_manager.ActionPlugins().repository.get(
                "response-curve",
                None
            )
            if entry is not None:
                action_names.append(entry.name)
            else:
                raise gremlin.error.GremlinError(
                    "Response curve plugin is missing"
                )
        else:
            for entry in gremlin.plugin_manager.ActionPlugins().repository.values():
                if self.item_data.input_type in entry.input_types:
                    action_names.append(entry.name)
        return sorted(action_names)


class ActionContainerModel(gremlin.ui.ui_common.AbstractModel):

    """Stores action containers for display using the corresponding view."""

    def __init__(self, containers, item_data : InputItemConfiguration = None, input_type: InputType = None, parent=None):
        """Creates a new instance.

        :param containers: the container instances of this model
        :param item_data: the input mapping data (InputItemConfiguration)
        :param input_type: the override input type if different from the input item configuration
        :param parent: the parent of this widget
        """
        super().__init__(parent)
        self._containers = containers
        self._item_data = item_data
        self._input_type = input_type if input_type is not None else item_data._input_type

    @property
    def item_data(self) -> InputItemConfiguration:
        ''' get the item data associated with this action container '''
        return self._item_data
    
    @property
    def input_type(self) -> InputType:
        return self._input_type
    
    def rows(self):
        """Returns the number of rows in the model.

        :return number of rows in the model
        """
        return len(self._containers)

    def data(self, index):
        """Returns the data stored at the given location.

        :param index the location for which to return data
        :return the data stored at the requested location
        """
        assert len(self._containers) > index
        return self._containers[index]

    def add_container(self, container):
        """Adds a container to the model.

        :param container the container instance to be added
        """
        self._containers.append(container)
        self.data_changed.emit()

    def remove_container(self, container):
        """Removes an existing container from the model.

        :param container the container instance to remove
        """
        eh = gremlin.event_handler.EventListener()

        if container in self._containers:
            # notify actions that the container is closing
            for action_set in container.action_sets:
                for action in action_set:
                    eh.action_delete.emit(action)

            del self._containers[self._containers.index(container)]
        self.data_changed.emit()

        el = gremlin.event_handler.EventListener()
        el.mapping_changed.emit(self.item_data)


class ActionContainerView(gremlin.ui.ui_common.AbstractView):

    """View class used to display ActionContainerModel contents."""

    def __init__(self, parent=None):
        """Creates a new view instance.

        :param parent the parent of the widget
        """
        super().__init__(parent)

        # Create required UI items
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.redraw_lock = False

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()

        # Configure the widget holding the layout with all the buttons
        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding
        )
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        # Configure the scroll area
        self.scroll_area.setMinimumWidth(400)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        # Add the scroll area to the main layout
        self.main_layout.addWidget(self.scroll_area)

        self._widgets = []

    def redraw(self):
        """Redraws the entire view."""

        if not self.redraw_lock:
            try:
                self.redraw_lock = True
                import gremlin.ui.ui_common
                
                # if there is a cleanup handler defined for any actions widgets - call them before removing them
                for container_widget in self._widgets:
                    for action_widget in container_widget.action_widgets:
                        for widget in action_widget._widgets:
                            if hasattr(widget,"_cleanup_ui"):
                                widget._cleanup_ui()
                self._widgets.clear()

                gremlin.ui.ui_common.clear_layout(self.scroll_layout)
                container_count = self.model.rows()
                if container_count:
                    for index in range(container_count):
                        widget = self.model.data(index).widget(self.model.data(index))
                        widget.closed.connect(self._create_closed_cb(widget))
                        widget.container_modified.connect(self.model.data_changed.emit)
                        self.scroll_layout.addWidget(widget)
                        self._widgets.append(widget)
                else:
                    input_type = self.model.input_type # InputType.JoystickAxis
                    label = QtWidgets.QLabel(f"Please add an action or container for {self.model.item_data.display_name} ({InputType.to_display_name(input_type)})")
                    label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
                    self.scroll_layout.addWidget(label)
                self.scroll_layout.addStretch(1)
            finally:
                self.redraw_lock = False
        else:
            logging.getLogger("system").error("re-entry code detected")

    def _create_closed_cb(self, widget):
        """Create callbacks to remove individual containers from the model.

        :param widget the container widget to be removed
        :return callback function to remove the provided widget from the
            model
        """

        return lambda: self.model.remove_container(widget.profile_data)
    




class JoystickDeviceTabWidget(gremlin.ui.ui_common.QSplitTabWidget):

    """Widget used to display the input joystick device."""

    inputChanged = QtCore.Signal(str, object, object) # indicates the input selection changed sends (device_guid string, input_type, input_id)

    def __init__(
            self,
            device,
            device_profile,
            current_mode,
            parent=None
    ):
        """Creates a new object instance.

        :param device device information about this widget's device
        :param device_profile profile data of the entire device
        :param current_mode currently active mode
        :param parent the parent of this widget
        """
        super().__init__(parent)

        import gremlin.plugin_manager

        # Store parameters
        self.device_profile = device_profile
        self.current_mode = current_mode
        self.curve_update_handler = {} # map of curve handlers to the input by index

        self.device = device
        self.last_item_data_key = None
        self.last_item_index = 0

     
        self.device_profile.ensure_mode_exists(current_mode, self.device)

        # List of inputs
        self.input_item_list_model = input_item.InputItemListModel(
            device_profile,
            current_mode
        )
        self.input_item_list_view = input_item.InputItemListView(name=device.name, custom_widget_handler = self._custom_widget_handler)

        

        # Handle vJoy as input and vJoy as output devices properly
        vjoy_as_input = self.device_profile.parent.settings.vjoy_as_input

        # For vJoy as output only show axes entries, for all others treat them
        # as if they were physical input devices
        if device.is_virtual and not vjoy_as_input.get(device.vjoy_id, False):
            self.input_item_list_view.limit_input_types([InputType.JoystickAxis])
        self.input_item_list_view.set_model(self.input_item_list_model)

        self.input_item_list_view.item_edit_curve.connect(self._edit_curve_item_cb)
        self.input_item_list_view.item_delete_curve.connect(self._delete_curve_item_cb)

        # load the model
        self.input_item_list_view.redraw()
    

        # Handle user interaction
        self.input_item_list_view.item_selected.connect(
            self.input_item_selected_cb
        )

        # Add modifiable device label
        label_layout = QtWidgets.QHBoxLayout()
        label_layout.setContentsMargins(10, 9, 9, 0)
        label_layout.addWidget(QtWidgets.QLabel("<b>Device Label</b>"))
        line_edit = QtWidgets.QLineEdit()
        line_edit.setText(device_profile.label)
        line_edit.textChanged.connect(self.update_device_label)
        label_layout.addWidget(line_edit)

        self._left_panel_layout.addLayout(label_layout)
        self._left_panel_layout.addWidget(self.input_item_list_view)
        self._left_panel_layout.setContentsMargins(0,0,0,0)

        # Add a help text for the purpose of the vJoy tab
        if device is not None and \
                device.is_virtual and \
                not vjoy_as_input.get(device.vjoy_id, False):
            label = QtWidgets.QLabel(
                "This tab allows assigning a response curve to virtual axis. "
                "The purpose of this is to enable split and merge axis to be "
                "customized to a user's needs with regards to dead zone and "
                "response curve."
            )
            label.setStyleSheet("QLabel { background-color : '#FFF4B0'; }")
            label.setWordWrap(True)
            label.setFrameShape(QtWidgets.QFrame.Box)
            label.setMargin(10)
            self._left_panel_layout.addWidget(label)



        #self._empty_widget = InputItemConfiguration(parent = self)
        
        config = gremlin.config.Configuration()

        if config.debug_ui:
            self._debug_widget = QtWidgets.QLabel("Debug widget")
            self._debug_widget.setMaximumHeight(32)
            self._right_panel_layout.addWidget(self._debug_widget)

        

        # update on any specific mode change
        eh = gremlin.event_handler.EventHandler()
        eh.mode_changed.connect(self._mode_change_cb)
        

        # update on any general mode change
        el = gremlin.event_handler.EventListener()
        el.modes_changed.connect(self._modes_changed_cb)
        

        # el.joystick_event.connect(self._device_update)


        self.updating = False
        self.last_event = None

        # update the selection if nothing is selected
        selected_index = self.input_item_list_view.current_index
        if selected_index is not None and selected_index != -1:
            self.input_item_selected_cb(selected_index)

        # update display on config change
        el.config_changed.connect(self._config_changed_cb)

        # update all curve icons
        self.update_curve_icons()


    def clear_layout(self):
        ''' clear data references '''
        self.input_item_list_model = None
        self.input_item_list_view = None
        gremlin.util.clear_layout(self.main_layout)
        
        
    def _edit_curve_item_cb(self, widget, index, data):
        ''' edit curve request '''
        import gremlin.curve_handler
        import gremlin.event_handler
        curve_data : gremlin.curve_handler.AxisCurveData = data.curve_data
        if not curve_data:
            curve_data = gremlin.curve_handler.AxisCurveData()
            curve_data.curve_update()
            data.curve_data = curve_data
            
        dialog = gremlin.curve_handler.AxisCurveDialog(curve_data)
        gremlin.util.centerDialog(dialog, dialog.width(), dialog.height())

        # hook input value changed handler
        update_handler = dialog.curve_update_handler
        self.curve_update_handler[index] = update_handler
        # update the dialog with the current input value
        value = gremlin.joystick_handling.get_axis(data.device_guid, data.input_id)
        update_handler(value)

        # disable highlighting
        gremlin.shared_state.push_suspend_highlighting()
        dialog.exec()
        self.curve_update_handler[index] = None
        print ("update curve data")
        data.curve_data.curve_update()

        # update the registered curve state
        eh = gremlin.event_handler.EventListener()
        eh.registerInput(data)

        # renable highlighting
        gremlin.shared_state.pop_suspend_highlighting()

        
        
        self._update_curve_icon(index, data)


    def _delete_curve_item_cb(self, widget, index, data):
        ''' delete curve request '''
        message_box = QtWidgets.QMessageBox()
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setText("Delete this input curve?")
        message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            print ("delete curve data")
            data.curve_data = None
            self._update_curve_icon(index, data)
        


    def _update_input_value_changed_cb(self, index : int, value : float):
        if index in self.curve_update_handler and self.curve_update_handler[index] is not None:
            self.curve_update_handler[index](value)

    @QtCore.Slot(str)
    def _mode_change_cb(self, mode):
        ''' occurs on mode change '''
        self._modes_changed_cb()

    @QtCore.Slot()
    def _modes_changed_cb(self):
        self.current_mode = gremlin.shared_state.current_mode
        self.update_curve_icons()



    def update_curve_icons(self):
        for index, widget in self.input_item_list_view.widget_map.items():
            if widget is not None:
                self._update_curve_icon(index, self.input_item_list_view.model.data(index))

    def _update_curve_icon(self, index : int, data):
        widget = self.input_item_list_view.widget_map[index]
        input_item = widget.data
        enabled = data.curve_data is not None
        widget.update_curve_icon(enabled)



    def _config_changed_cb(self):
        self.input_item_list_view.redraw()

    def _custom_widget_handler(self, list_view : input_item.InputItemListView, index : int, identifier : input_item.InputIdentifier, data, parent = None):
        ''' creates a widget for the input
        
        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item
        
        '''
        
        
        if data.input_type == InputType.JoystickAxis:
            #widget = input_item.InputItemWidget(identifier = identifier, parent=parent,  populate_ui_callback=self._populate_axis_input_widget_ui, data = data)
            widget = input_item.InputItemWidget(identifier = identifier, parent=parent, data = data)
            widget.setIcon("joystick_no_frame.png",use_qta=False)
            if widget.axis_widget is not None:
                widget.axis_widget.valueChanged.connect(lambda x: self._update_input_value_changed_cb(index, x))
        elif data.input_type == InputType.JoystickButton:
            #widget = input_item.InputItemWidget(identifier = identifier, parent=parent, populate_ui_callback=self._populate_button_input_widget_ui, data = data)
            widget = input_item.InputItemWidget(identifier = identifier, parent=parent, data = data)
            widget.setIcon("mdi.gesture-tap-button")
        elif data.input_type == InputType.JoystickHat:
            widget = input_item.InputItemWidget(identifier = identifier, parent=parent, data = data)
            widget.setIcon("ei.fullscreen")
        widget.create_action_icons(data)
        widget.disable_close()
        widget.disable_edit()
        widget.setDescription(data.description)
        widget.index = index


        return widget
    

    def _populate_axis_input_widget_ui(self, input_widget, container_widget, data):
        ''' called when the widget is created for an axis input  '''

        if gremlin.config.Configuration().show_input_axis:
            layout = QtWidgets.QVBoxLayout(container_widget)
            widget = gremlin.ui.ui_common.AxisStateWidget(show_label = False, orientation=QtCore.Qt.Orientation.Horizontal, show_percentage=False)
            widget.setWidth(10)
            widget.setMaximumWidth(200)
            # automatically update from the joystick
            widget.hookDevice(data.device_guid, data.input_id)
            widget.setContentsMargins(0,0,0,0)
            layout.setContentsMargins(0,0,0,0)
            layout.addWidget(widget)
            layout.addStretch()
            widget.valueChanged.connect(self._input_value_changed) # hook value changed event on the axis repeater when displayed
            return widget
        return None
    
    def _populate_button_input_widget_ui(self, input_widget, container_widget, data):
        ''' called when the widget is created for a button input  '''
        if gremlin.config.Configuration().show_input_axis:
            layout = QtWidgets.QVBoxLayout(container_widget)
            widget = gremlin.ui.ui_common.ButtonStateWidget()
            #widget.setMaximumWidth(20)
            # automatically update from the joystick
            widget.hookDevice(data.device_guid, data.input_id)
            widget.setContentsMargins(0,0,0,0)
            layout.setContentsMargins(0,0,0,0)
            layout.addWidget(widget)
            layout.addStretch()
            return widget
        
    @property
    def running(self):
        return gremlin.shared_state.is_running

    @QtCore.Slot(int)
    def input_item_selected_cb(self, index):
        """ Handles the loading of mappings for a given input item - handler for select_input event

        :param index the index of the selected item
        """

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_details
        syslog = logging.getLogger("system")

        item_data = input_item_index_lookup(
            index,
            self.device_profile.modes[self.current_mode]
        )

        if verbose:
            if item_data:
                syslog.info(f"Selecting input config item for input index [{index}] mode: {self.current_mode}: {item_data.debug_display}")
            else:
                syslog.info(f"Selecting input config item for input index [{index}] mode: {self.current_mode}: Empty content")

        new_key = None
        if item_data is not None:
            new_key = _cache.getKey(item_data)

            if new_key == self.last_item_data_key:
                # same input - nothing to do
                return

        # hide all the existing widgets 
        widgets = gremlin.util.get_layout_widgets(self._right_container_layout)
        for widget in widgets:
            if isinstance(widget, InputItemConfiguration):
                # if verbose:
                #     syslog.info(f"Hide widget:{widget.id} {widget.item_data.debug_display if widget.item_data else 'N/A'}")
                widget.setVisible(False)
            else:
                self._right_container_layout.removeWidget(widget)
                widget.deleteLater()
            
        self.last_item_data_key = new_key
        self.last_item_index = index



        if item_data is not None:
            # if there is data, hide the empty container and grab the last content, or create a new widget for it
            # there is a widget for each combination of device, input type and input ID
            # self._empty_widget.hide()
            widget = _cache.retrieve(new_key)
            if not widget:
                # not in cache, create it and add to cache for this device/input combination
                widget = InputItemConfiguration(item_data, parent = self)
                _cache.register(item_data, widget)
                

                widget.action_model.data_changed.connect(self._create_change_cb(index))
                widget.description_changed.connect(lambda x: self._description_changed_cb(index, x))
                widget.description_clear.connect(lambda: self._description_clear_cb(index,widget))

                # indicate the input changed
                device_guid = str(item_data.device_guid)
                input_type = item_data.input_type
                input_id = item_data.input_id
                self.inputChanged.emit(device_guid, input_type, input_id)
                self._right_container_layout.addWidget(widget)       

     


            assert widget.item_data == item_data,"cache mismatch"

            if verbose:
                syslog.info(f"Show widget:  {widget.id} {item_data.debug_display}")
            
            widget.setVisible(True)
            if config.debug_ui:
                self._debug_widget.setText(f"Contents for : {item_data.debug_display}")

            # if verbose:
            #     syslog.info("Map layout contents:")
            #     for widget in gremlin.util.get_layout_widgets(self.right_container_layout):
            #         if isinstance(widget, InputItemConfiguration):
            #             syslog.info(f"\t{widget.id} {widget.isVisible()} {widget.item_data.debug_display}")
            #         else:
            #             syslog.info(f"\tlabel {widget.isVisible()}")


        else:
            # show the empty widget
            self._debug_widget.setText(f"Contents for : N/A")
            self._right_container_layout.insertWidget(0,QtWidgets.QLabel("Please select an input to configure"))


        
        #self.right_container_layout.update()
            

    
    def _description_changed_cb(self, index, text):
        ''' called when the description text of the widget changes to update the description on the input item 
        
        :param: index = the index of the input widget to update with the new text
        
        '''
        item = self.input_item_list_view.itemAt(index)
        item.data.description = text
        item.setDescription(text)

    def _description_clear_cb(self, index, widget):
        ''' delete description entry '''
        with QtCore.QSignalBlocker(widget.description_field):
            widget.description_field.setText('')
        item = self.input_item_list_view.itemAt(index)
        item.data.description = None
        item.setDescription('')
        
        

    def set_mode(self, mode):
        ''' changes the mode of the tab '''

        if gremlin.config.Configuration().verbose:
            syslog = logging.getLogger("system")
            syslog.info(f"Device tab: change mode requested: device tab: {gremlin.shared_state.get_device_name(self.device.device_guid)} current mode: [{self.current_mode}]  new mode: [{mode}] ")
            
        self.current_mode = mode
        self.device_profile.ensure_mode_exists(self.current_mode, self.device)

        index = self.last_item_index
        self.input_item_list_model.mode = mode
        self.input_item_list_view.redraw()
        self.input_item_list_view.select_item(index, emit=False)
        self.input_item_selected_cb(index)


    def mode_changed_cb(self, mode):
        """Handles mode change.

        :param mode the new mode
        """
        self.set_mode(mode)
        
    def refresh(self):
        """Refreshes the current selection, ensuring proper synchronization."""
        if self.input_item_list_view.current_index is not None:
            self.input_item_selected_cb(self.input_item_list_view.current_index)

    def _create_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.input_item_list_view.redraw_index(index)
    
    def _create_description_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.description_changed_cb(index)

    def update_device_label(self, text):
        """Updates the label assigned to this device.

        :param text the new label text
        """
        self.device_profile.label = text




def input_item_index_lookup(index, input_items):
    """Returns the profile data belonging to the provided index.

    This function determines which actual input item a given index refers to
    and then returns the content for it.

    :param index the index for which to return the data
    :param input_items the profile data from which to return the data
    :return profile data corresponding to the provided index
    """
    axis_count = len(input_items.config[InputType.JoystickAxis])
    button_count = len(input_items.config[InputType.JoystickButton])
    hat_count = len(input_items.config[InputType.JoystickHat])
    key_count = len(input_items.config[InputType.Keyboard])

    

    if key_count > 0:
        if not input_items.has_data(InputType.Keyboard, index):
            logging.getLogger("system").error(
                "Attempting to retrieve non existent input, "
                f"type={InputType.to_string(InputType.Keyboard)} index={index}"
            )
        return input_items.get_data(InputType.Keyboard, index)
    else:
        if index < axis_count:
            # Handle non continuous axis setups
            axis_keys = sorted(input_items.config[InputType.JoystickAxis].keys())
            if not input_items.has_data(InputType.JoystickAxis, axis_keys[index]):
                logging.getLogger("system").error(
                    "Attempting to retrieve non existent input, "
                    f"type={InputType.to_string(InputType.JoystickAxis)} index={axis_keys[index]}"
                )

            return input_items.get_data(
                InputType.JoystickAxis,
                axis_keys[index]
            )
        elif index < axis_count + button_count:
            if not input_items.has_data(
                    InputType.JoystickButton,
                    index - axis_count + 1
            ):
                logging.getLogger("system").error(
                    "Attempting to retrieve non existent input, "
                    f"type={InputType.to_string(InputType.JoystickButton)} index={index - axis_count + 1}"
                )

            return input_items.get_data(
                InputType.JoystickButton,
                index - axis_count + 1
            )
        elif index < axis_count + button_count + hat_count:
            if not input_items.has_data(
                    InputType.JoystickHat,
                    axis_count + button_count + hat_count
            ):
                logging.getLogger("system").error(
                    "Attempting to retrieve non existent input, "
                    f"type={ InputType.to_string(InputType.JoystickHat)} index={index - axis_count - button_count + 1}"
                )

            return input_items.get_data(
                InputType.JoystickHat,
                index - axis_count - button_count + 1
            )



@gremlin.singleton_decorator.SingletonDecorator
class InputConfigurationWidgetCache():
    ''' caches the joystick input widget for each device/input combination  '''
    def __init__(self):
        self._widget_map = {}


    def register(self, item_data, widget):
        if item_data:
            key = self.getKey(item_data)
            if not key in self._widget_map:
                self._widget_map[key] = widget
                if gremlin.config.Configuration().verbose:
                    syslog = logging.getLogger("system")            
                    syslog.info(f"Cache: register {item_data.debug_display}")
            
    def clear(self):
        ''' clears the cache '''
        if gremlin.config.Configuration().verbose:
            syslog = logging.getLogger("system")            
            syslog.info(f"Cache: clear widget cache")
        self._widget_map.clear()


    def getKey(self, item_data):
        # device_guid = item_data.device_guid
        # input_id = item_data.input_id
        # input_type = item_data.input_type
        # mode = item_data.profile_mode
        id = item_data.id
        return id # (device_guid, input_id, input_type, mode, id)
        

    def retrieve(self, key):
        if key in self._widget_map:
            return self._widget_map[key]
        return None
    
    def retrieve_by_data(self,item_data):
        if item_data:
            key = self.getKey(item_data)
            if key in self._widget_map:
                return self._widget_map[key]
        return None
        
    def remove(self,item_data):
        if item_data:
            key = self.getKey(item_data)
            if key in self._widget_map:
                del self._widget_map[key]

    def dump(self):
        ''' dumps the cache content to the log for debug purposes '''
        syslog = logging.getLogger("system")
        items = list(self._widget_map.values())
        items.sort(key = lambda x: (x.item_data.profile_mode, x.item_data.device_guid, x.item_data.input_type, x.item_data.input_id))
        current_device_guid = None
        current_mode = None
        current_input_type = None
        
        syslog.info("-"*50)
        syslog.info("UI widget cache dump")
        for index, input_item_config in enumerate(items):
            item: gremlin.base_profile.InputItem = input_item_config.item_data
            if not current_mode or current_mode != item.profile_mode:
                current_mode = item.profile_mode
                syslog.info(f"Mode {current_mode}:")
            if not current_device_guid or current_device_guid != item.device_guid:
                device_name = gremlin.shared_state.get_device_name(item.device_guid)
                current_device_guid = item.device_guid
                syslog.info(f"\tDevice {device_name} id {str(item.device_guid)}:")
            if not current_input_type or current_input_type != item.input_type:
                current_input_type = item.input_type
                syslog.info(f"\t\tInput Type: {InputType.to_display_name(item.input_type)}")
            syslog.info(f"\t\t\tInput Id: {item.display_name} cache index [{index:,}]")

            

# primary cache instantiation to prevent GC
_cache = InputConfigurationWidgetCache()