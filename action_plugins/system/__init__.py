# from __future__ import annotations
# import logging
# import threading
# import time
# from lxml import etree as ElementTree

# from PySide6 import QtWidgets, QtCore, QtGui
# import gremlin.actions
# import gremlin.base_conditions
# import gremlin.base_profile
# import gremlin.config
# import gremlin.event_handler
# import gremlin.execution_graph
# import gremlin.input_types
# import gremlin.joystick_handling
# import gremlin.shared_state
# import gremlin.types
# from gremlin.util import load_icon

# from gremlin.base_conditions import InputActionCondition
# from gremlin.input_types import InputType
# from gremlin import input_devices, joystick_handling, util
# from gremlin.error import ProfileError
# from gremlin.util import safe_format, safe_read
# import gremlin.ui.ui_common
# import gremlin.ui.input_item
# import os
# import enum
# from gremlin.input_devices import SystemAction, remote_state
# from gremlin.util import *
# import gremlin.util


# syslog = logging.getLogger("system")

# class CommandList(enum.IntEnum):
#     ToggleRemote = 1
    

# _command_list_description = {
#     CommandList.ToggleRemote : "Toggle remote control"
# }

# _command_list_display

# class SystemWidget(gremlin.ui.input_item.AbstractActionWidget):
#     ''' System plugin UI '''

#     def __init__(self, action_data, parent=None):
#         """Creates a new system  widget.

#         :param action_data profile data managed by this widget
#         :param parent the parent of this widget
#         """
#         super().__init__(action_data, parent=parent)
#         assert(isinstance(action_data, System))


#     def _create(self, action_data):
#         ''' initialization '''
#         self.profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
#         el = gremlin.event_handler.EventListener()
#         el.edit_mode_changed.connect(self._profile_edit_mode_changed)
        
#     def _create_ui(self):
#         """Creates the UI components."""
#         self.action_widget = gremlin.ui.ui_common.NoWheelComboBox()
#         index = 0
#         set_index = None
#         for index, action in enumerate(SystemAction):
#             self.action_widget.addItem(SystemAction.to_display_name(action), action)
#             if set_index is None and action == self.action_data.action:
#                 set_index = index
#             index+=1

#         if set_index:
#             self.action_widget.setCurrentIndex(set_index)

#         self.action_widget.currentIndexChanged.connect(self._action_changed_cb)

#         self._update_input_list()

#         self.grid_widget = QtWidgets.QWidget()
#         self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)

#         row = 0
#         self.grid_layout.addWidget(QtWidgets.QLabel("Action:"), row, 0)
#         self.grid_layout.addWidget(self.action_widget, row, 1)
#         row +=1

#         self.grid_layout.addWidget(QtWidgets.QLabel(),row, 2)
#         self.grid_layout.setColumnStretch(3,1)

#         self.main_layout.addWidget(self.grid_widget)

        
        
        
        

#     def _populate_ui(self):
#         pass

#     def _update_actions(self):
#         with QtCore.QSignalBlocker(self.action_widget):
#             self.action_widget.clear()




#     @QtCore.Slot()
#     def _action_changed_cb(self):
#         action = self.action_widget.currentData()
#         self.action_data.action = action

                    
#     @QtCore.Slot()
#     def _mode_changed_cb(self):
#         mode = self.mode_selector.currentData()
#         self.action_data.mode = mode # None means an mode
#         self._update_device_list()
#         self._update_input_list()

#     @QtCore.Slot()
#     def _profile_edit_mode_changed(self):
#         ''' called when the list of modes changes in the profile '''
#         modes = self.profile.get_modes()
#         if self.action_data.mode in modes:
#             # nothing to do
#             return
#         # mode no longer exists
#         self.action_data.mode = None
#         self._update_mode_list()
#         self._update_device_list()
#         self._update_input_list()


                            
#     @QtCore.Slot()
#     def _device_changed_cb(self):
#         device = self.device_widget.currentData()
#         self.action_data.device_guid = device.device_guid
#         self._update_input_list()

#     @QtCore.Slot()
#     def _input_changed_cb(self):
#         input_item = self.input_widget.currentData()
#         self.action_data.target_input_item = input_item
        
        

# class SystemFunctor(gremlin.base_conditions.AbstractFunctor):
#     ''' System functor '''
    
#     def __init__(self, action_data, parent = None):
#         super().__init__(action_data, parent)
#         self.action_data = action_data


#     def process_event(self, event, action_value : gremlin.actions.Value, extra_data = None):
    
#         if event.is_pressed is None:
#             return
#         is_pressed = event.is_pressed
#         if is_pressed:
#             # find the actionable input
#             verbose = gremlin.config.Configuration().verbose
#             profile = gremlin.shared_state.current_profile
#             device_guid = self.action_data.device_guid
#             input_item = self.action_data.target_input_item
#             input_id = input_item.input_id
#             action = self.action_data.action
#             if device_guid in profile.devices:
#                 dev = profile.devices[device_guid]
#                 for mode_name in dev.modes.keys():
#                     mode = dev.modes[mode_name]
#                     for input_type in mode.config.keys():
#                         item : gremlin.base_profile.InputItem
#                         for item in mode.config[input_type].values():
#                             if item.input_id == input_id:
#                                 match action:
#                                     case SystemAction.DisableInput:
#                                         if verbose: syslog.info(f"System: disable input {item.display_name}")
#                                         item.enabled = False
#                                     case SystemAction.EnableInput:
#                                         if verbose: syslog.info(f"System: enable input {item.display_name}")
#                                         item.enabled = True
#                                     case SystemAction.ToggleInput:
#                                         item.enabled = not item.enabled
#                                         if verbose: syslog.info(f"System: toggle input {item.display_name} -> {item.enabled}")
#                                 return True
                            
#             return True

                            






# class System(gremlin.base_profile.AbstractAction):

#     """Action remapping physical joystick inputs to vJoy inputs."""

#     name = "System"
#     tag = "gremlin-System"
#     # trigger condition (trigger_on_press, trigger_on_release)
#     default_button_activation = (True, True)

#     functor = SystemFunctor
#     widget = SystemWidget
    
#     input_types = [
#         InputType.JoystickButton,
#         InputType.JoystickHat,
#         InputType.Keyboard,
#         InputType.KeyboardLatched,
#         InputType.OpenSoundSystem,
#         InputType.Midi,
        
#     ]

#     def __init__(self, parent):
#         super().__init__(parent)
#         self.parent = parent
#         self.action : SystemAction = SystemAction.ToggleInput
#         self.mode = gremlin.shared_state.edit_mode # selected mode
#         self.device_guid = None
#         self.target_input_item = None

#     def icon(self):
#         return "fa6s.gears"
    
#     def requires_virtual_button(self):
#         return False
    
  
    
#     def _parse_xml(self, node, data = None):
#         self.mode = None
#         self.device_guid = None
#         self.target_input_item = None

#         #input_items = self._get_input_items()
        
#         if "mode" in node.attrib:
#             self.mode = node.get("mode")
#         if "device_guid" in node.attrib:
#             self.device_guid = parse_guid(node.get("device_guid"))
#             #device_type = gremlin.types.DeviceType.to_enum(node.get("device_type"))
#         for node_target in node:
#             input_item = gremlin.base_profile.InputItem()
#             input_item.from_xml(node_target, data)
#             self.target_input_item = input_item
#             break


    
#     def _generate_xml(self):
#         node = ElementTree.Element(System.tag)
#         if self.mode is not None:
#             node.set("mode", self.mode)
#         if self.device_guid is not None:
#             node.set("device_guid", str(self.device_guid))
#             device_type = self.get_device_type()
#             if device_type is not None:
#                 node.set("device_type", gremlin.types.DeviceType.to_string(device_type))
#             else:
#                 pass


#         if self.target_input_item is not None:
#             node_target = self.target_input_item.to_xml()
#             node_target.set("target_type", type(self.target_input_item).__name__)
#             node.append(node_target)

#         return node
    

#     def _is_valid(self):
#         if self.device_guid is not None and self.target_input_item is not None:
#             return True
#         return False



# version = 1
# name = "System"
# create = System