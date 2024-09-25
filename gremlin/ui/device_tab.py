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
import gremlin.event_handler
import gremlin.profile
import gremlin.shared_state
import gremlin.types
from gremlin.types import DeviceType
from gremlin.input_types import InputType
import gremlin.util
import gremlin.ui.input_item as input_item
import gremlin.ui.ui_common


class InputItemConfiguration(QtWidgets.QFrame):

    """ mapping viewer for a selected input item (this is the right side of the device tab) """

    # Signal emitted when the description changes
    description_changed = QtCore.Signal(str)

    def __init__(self, item_data = None, parent=None):
        """Creates a new object instance.

        :param item_data profile data associated with the item, can be none to display an empty box
        :param parent the parent of this widget
        """
        super().__init__(parent)

        

        self.item_data : gremlin.base_profile.InputItem = item_data
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.button_layout = QtWidgets.QHBoxLayout()
        self.widget_layout = QtWidgets.QVBoxLayout()

        if item_data is None:
            parent = self.parent()
            while parent and not isinstance(parent, JoystickDeviceTabWidget):
                parent = self.parent()
            parent :JoystickDeviceTabWidget
            if parent is not None:
                item_data = parent.last_item_data
        
            label = QtWidgets.QLabel("Please select an input to configure")
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
            self.main_layout.addWidget(label)
            return

        
        if not item_data.is_action:
            # only draw description if not a sub action item
            self._create_description()
        
        if self.item_data.device_type == DeviceType.VJoy:
            self._create_vjoy_dropdowns()
        else:
            self._create_dropdowns()

        self.action_model = ActionContainerModel(self.item_data.containers, self.item_data)
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
        

    def _paste_action(self, action):
        """ paste action to the input item """
        import container_plugins.basic
        import gremlin.plugin_manager
        if self.item_data.get_device_type() == DeviceType.VJoy:
            if len(self.item_data.containers) > 0:
                return

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action)
        container = container_plugins.basic.BasicContainer(self.item_data)
        # remap inputs
        action_item.update_inputs(self.item_data)
        container.add_action(action_item)
        
        if len(container.action_sets) > 0:
            self.action_model.add_container(container)
        self.action_model.data_changed.emit()

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
        return container
    

    def _paste_container(self, container):
        """Adds a new container to the input item.

        :param container container to be added
        """
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        container_item = plugin_manager.duplicate(container)
        if hasattr(container_item, "action_model"):
            container_item.action_model = self.action_model
        self.action_model.add_container(container_item)
        plugin_manager.set_container_data(self.item_data, container_item)
        return container_item

    def _remove_container(self, container):
        """Removes an existing container from the InputItem.

        :param container the container instance to be removed
        """
        self.action_model.remove_container(container)

                

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
        

        self.main_layout.addLayout(self.description_layout)

    def _create_dropdowns(self):
        """Creates a drop down selection with actions that can be
        added to the current input item.
        """
        import gremlin.ui.input_item as input_item
        import gremlin.ui.ui_common as ui_common
        self.action_layout = QtWidgets.QHBoxLayout()

        # repeat the current active mode for editing
        mode_widget = QtWidgets.QLineEdit(text=gremlin.shared_state.current_mode)
        mode_widget.setReadOnly(True)

        self.action_layout.addWidget(QtWidgets.QLabel("Mode:"))
        self.action_layout.addWidget(mode_widget)

        self.action_selector = ui_common.ActionSelector(
            self.item_data.input_type
        )
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.action_paste.connect(self._paste_action)

        self.container_selector = input_item.ContainerSelector(
            self.item_data.input_type
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

    def _edit_description_cb(self, text):
        """Handles changes to the description text field.

        :param text the new contents of the text field
        """
        self.item_data.description = text
        self.description_changed.emit(text)

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

    def __init__(self, containers, item_data = None, parent=None):
        """Creates a new instance.

        :param containers the container instances of this model
        :param parent the parent of this widget
        """
        super().__init__(parent)
        self._containers = containers
        self._item_data = item_data

    @property
    def item_data(self):
        ''' get the item data associated with this action container '''
        return self._item_data
    
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
        if container in self._containers:
            del self._containers[self._containers.index(container)]
        self.data_changed.emit()


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
        self.scroll_area.setMinimumWidth(800)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        # Add the scroll area to the main layout
        self.main_layout.addWidget(self.scroll_area)

    def redraw(self):
        """Redraws the entire view."""

        if not self.redraw_lock:
            try:
                self.redraw_lock = True
                import gremlin.ui.ui_common
                gremlin.ui.ui_common.clear_layout(self.scroll_layout)
                container_count = self.model.rows()
                if container_count:
                    for index in range(container_count):
                        widget = self.model.data(index).widget(self.model.data(index))
                        widget.closed.connect(self._create_closed_cb(widget))
                        widget.container_modified.connect(self.model.data_changed.emit)
                        self.scroll_layout.addWidget(widget)
                else:
                    label = QtWidgets.QLabel(f"Please add an action or container for {self.model.item_data.display_name}")
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


from gremlin.ui.qdatawidget import QDataWidget
class JoystickDeviceTabWidget(QDataWidget):

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

        self.device = device
        self.last_item_data = None
        self.last_item_index = 0

        label = QtWidgets.QLabel("Please select an input to configure")
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
        self._empty_widget = label

        # the main layout has a left input selection panel and a right configuration panel, two widgets, the last one is always the configuration panel
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.left_panel_layout = QtWidgets.QVBoxLayout()
        self.device_profile.ensure_mode_exists(current_mode, self.device)

        # List of inputs
        self.input_item_list_model = input_item.InputItemListModel(
            device_profile,
            current_mode
        )
        self.input_item_list_view = input_item.InputItemListView(name=device.name, custom_widget_handler = self._custom_widget_handler)
        self.input_item_list_view.setMinimumWidth(375)
        

        # Handle vJoy as input and vJoy as output devices properly
        vjoy_as_input = self.device_profile.parent.settings.vjoy_as_input

        # For vJoy as output only show axes entries, for all others treat them
        # as if they were physical input devices
        if device.is_virtual and not vjoy_as_input.get(device.vjoy_id, False):
            self.input_item_list_view.limit_input_types([InputType.JoystickAxis])
        self.input_item_list_view.set_model(self.input_item_list_model)

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
        

        self.left_panel_layout.addLayout(label_layout)
        self.left_panel_layout.addWidget(self.input_item_list_view)
        self.left_panel_layout.setContentsMargins(0,0,0,0)

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
            self.left_panel_layout.addWidget(label)

        self.main_layout.addLayout(self.left_panel_layout,1)

        # add a list input view even if nothing is selected yet
        # right_panel = self.main_layout.takeAt(1)
        # if right_panel is not None and right_panel.widget():
        #     right_panel.widget().hide()
        #     right_panel.widget().deleteLater()
        # if right_panel:
        #     self.main_layout.removeItem(right_panel)

        self._empty_widget = InputItemConfiguration(parent = self)
        self.main_layout.addWidget(self._empty_widget,3)


        # # listen to device changes
        el = gremlin.event_handler.EventListener()
        # el.joystick_event.connect(self._device_update)


        self.updating = False
        self.last_event = None

        # update the selection if nothing is selected
        selected_index = self.input_item_list_view.current_index
        if selected_index is not None and selected_index != -1:
            self.input_item_selected_cb(selected_index)


        # update display on config change
        el.config_changed.connect(self._config_changed_cb)

    def clear_layout(self):
        ''' clear data references '''
        self.input_item_list_model = None
        self.input_item_list_view = None
        gremlin.util.clear_layout(self.main_layout)
        
        
        

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
        """ Handles the selection of an input item.

        :param index the index of the selected item
        """
        item_data = input_item_index_lookup(
            index,
            self.device_profile.modes[self.current_mode]
        )

        # grab the last widget visible, if there is one
        last_widget = _cache.retrieve(self.last_item_data)
        if last_widget:
            # hide it
            last_widget.hide()

        self.last_item_data = item_data
        self.last_item_index = index


        if item_data is not None:
            # if there is data, hide the empty container and grab the last content, or create a new widget for it
            # there is a widget for each combination of device, input type and input ID
            self._empty_widget.hide()
            widget = _cache.retrieve(item_data)
            if not widget:
                # not in cache, create it and add to cache for this device/input combination
                widget = InputItemConfiguration(item_data, parent = self)    
                _cache.register(item_data, widget)

                change_cb = self._create_change_cb(index)
                widget.action_model.data_changed.connect(change_cb)
                widget.description_changed.connect(change_cb)

                # indicate the input changed
                device_guid = str(item_data.device_guid)
                input_type = item_data.input_type
                input_id = item_data.input_id
                self.inputChanged.emit(device_guid, input_type, input_id)
        
                self.main_layout.addWidget(widget,3)
            widget.show()

        else:
            # empty widget
            self._empty_widget.show()
            


    def set_mode(self, mode):
        ''' changes the mode of the tab '''
            
        self.current_mode = mode
        self.device_profile.ensure_mode_exists(self.current_mode, self.device)
        
   
        # Remove the existing widget, if there is one
        item = self.main_layout.takeAt(1)
        if item is not None and item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        if item:
            self.main_layout.removeItem(item)

        index = self.last_item_index
        item_data = self.last_item_data

        widget = InputItemConfiguration(item_data = item_data, parent = self)
        self.main_layout.addWidget(widget,3)


        self.input_item_list_model.mode = mode

        
        self.input_item_list_view.redraw()
        self.input_item_list_view.select_item(index, emit=False)



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


    def getKey(self, item_data):
        device_guid = item_data.device_guid
        input_id = item_data.input_id
        input_type = item_data.input_type
        return (device_guid, input_id, input_type)
        

    def retrieve(self,item_data):
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

# primary cache instantiation to prevent GC
_cache = InputConfigurationWidgetCache()