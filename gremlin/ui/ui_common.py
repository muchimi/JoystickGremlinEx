# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - Joystick Gremlin Ex is (C) EMCS 2025 
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
import enum
import time
import threading
import os
from typing import Optional
import logging
from PySide6 import QtWidgets, QtCore, QtGui
import PySide6.QtGui
import PySide6.QtWidgets
import gremlin.base_classes
import gremlin.base_profile
import gremlin.clipboard
import gremlin.config
import gremlin.error
import qtawesome as qta
import gremlin.event_handler
from gremlin.input_types import InputType
from  gremlin.clipboard import Clipboard
import gremlin.input_types
import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.shared_state
import gremlin.types
from qtpy.QtCore import (
    Qt, QSize, QPoint, QPointF, QRectF,
    QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup,
    Slot, Property)

from qtpy.QtWidgets import QCheckBox
from qtpy.QtGui import QColor, QBrush, QPaintEvent, QPen, QPainter, QStandardItemModel, QStandardItem
from gremlin.util import load_pixmap, load_icon
import gremlin.util
import gremlin.ui.ui_common
from gremlin.singleton_decorator import SingletonDecorator
from gremlin.types import HatDirection
from dinput import DeviceSummary

syslog = logging.getLogger("system")



class Color():
    @staticmethod
    def activeColor():
        return "#51f56f" if gremlin.shared_state.is_dark_theme else "#365a75"
    @staticmethod
    def inactiveColor():
        return "#686a6e" if gremlin.shared_state.is_dark_theme else "#8c8c8c"
    @staticmethod
    def normalColor():
        return "#AAAAAA" if gremlin.shared_state.is_dark_theme else "#111111"
    @staticmethod
    def normalDarkColor():
        return "#AAAAAA" 
    @staticmethod
    def selectedDockTabBackgroundColor():
        return "#303030" if gremlin.shared_state.is_dark_theme else "#DDDDDD"
    @staticmethod
    def normalLightColor():
        return "#111111" 
    @staticmethod
    def normalGradientColor():
        return "#777777" if gremlin.shared_state.is_dark_theme else "#CCCCCC"
    @staticmethod
    def backgroundColor():
        return "#212121" if gremlin.shared_state.is_dark_theme else "#EEEEEE"
    @staticmethod
    def highlightBackgroundColor():
        return "#66612f" if gremlin.shared_state.is_dark_theme else "#FFF4B0"
    @staticmethod
    def borderColor():
        return "#444444" if gremlin.shared_state.is_dark_theme else "#111111"
    @staticmethod
    def titleBackgroundColor():
        return "#222222" if gremlin.shared_state.is_dark_theme else "#AAAAAA"
    @staticmethod
    def warningColor():
        return "#b39f32"
    @staticmethod
    def selectColor():
        return "#658265" if gremlin.shared_state.is_dark_theme else "#8FBC8F"
    @staticmethod
    def selectGradientColor():
        return "#658265" if gremlin.shared_state.is_dark_theme else "#8FBC8F"
    @staticmethod
    def selectBorderColor():
        return "#408540" if gremlin.shared_state.is_dark_theme else "#76c276"    
    @staticmethod
    def rangeColor():
        return "#8FBC8F"
    @staticmethod
    def alternateRangeColor():
        return "#8fb9bc"
    @staticmethod
    def rangeBorderColor():
        return "#8FBC8F"
    @staticmethod
    def actionIconBackgroundColor():
        return "#424242" if gremlin.shared_state.is_dark_theme else "#EEEEEE"
    @staticmethod
    def keyBackgroundColor():
        return "#424242" if gremlin.shared_state.is_dark_theme else "#EEEEEE"
    @staticmethod
    def keyEntryBackgroundColor():
        return "#293d2d" if gremlin.shared_state.is_dark_theme else "#EEEEEE"
    @staticmethod
    def keyForegroundColor():
        return "#AAAAAA" if gremlin.shared_state.is_dark_theme else "#000000"
    @staticmethod
    def keyBorderColor():
        return "#AAAAAA" if gremlin.shared_state.is_dark_theme else "#000000"
    @staticmethod
    def keyHoverBorderColor():
        return "#457d45" if gremlin.shared_state.is_dark_theme else "#56b056"
    @staticmethod
    def containerBackgroundColor():
        return "#101010" if gremlin.shared_state.is_dark_theme else "#EEEEEE"
    @staticmethod
    def actionBackgroundColor():
        return "#202020" if gremlin.shared_state.is_dark_theme else "#CCCCCC"
    @staticmethod
    def sliderTickColor():
        return "#303030" if gremlin.shared_state.is_dark_theme else "#232323"
    @staticmethod
    def sliderHandleColor():
        return "#a7b59e" if gremlin.shared_state.is_dark_theme else "#a7b59e"
    @staticmethod
    def sliderHandleBorderColor():
        return "#e0e0e0" if gremlin.shared_state.is_dark_theme else "#e0e0e0"
    @staticmethod
    def sliderRangeBorderColor():
        return "#8fb9bc" if gremlin.shared_state.is_dark_theme else "#8fb9bc"
    @staticmethod
    def sliderRangeColor():
        return "#8fb9bc" if gremlin.shared_state.is_dark_theme else "#8fb9bc"
    @staticmethod
    def sliderAlternateRangeColor():
        return "#8fb9bc" if gremlin.shared_state.is_dark_theme else "#8fb9bc"
    @staticmethod
    def sliderBackgroundColor():
        return "#060606" if gremlin.shared_state.is_dark_theme else "#c3c3c3"
    @staticmethod
    def recordColor():
        return "#c7450e"
    @staticmethod
    def activeContentColor():
        return "#458ae6"

        

    @staticmethod
    def warningColor(): # color for the warning flag
        return "#ab8d18" if gremlin.shared_state.is_dark_theme else "#fc1900"

    @staticmethod
    def cssApplication():
        border_color = Color.borderColor()
        background_color = Color.backgroundColor()
        if gremlin.config.Configuration().is_debug:
            relative_path = "gfx/"
        else:
            relative_path = "_internal/gfx/"
        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""

        checkbox_unchecked = f"{prefix}checkbox_blank_outline.png"
        checkbox_checked = f"{prefix}checkbox_intermediate.png"

        radio_unchecked = f"{prefix}radiobox_blank.png"
        radio_checked = f"{prefix}radiobox_marked.png"
        
        css = f'''
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
            }}
            QCheckBox::indicator:checked {{
                image: url({relative_path}{checkbox_checked});
            }}
            QCheckBox::indicator:unchecked {{
                image: url({relative_path}{checkbox_unchecked}); 
            }}
            QRadioButton::indicator {{
                width: 18px;
                height: 18px;
            }}
            QRadioButton::indicator:checked {{
                image: url({relative_path}{radio_checked});
            }}
            QRadioButton::indicator:unchecked {{
                image: url({relative_path}{radio_unchecked}); 
            }}
            QPlainTextEdit {{ 
                 border: 1px solid {border_color};
            }}
            QMenu::separator {{
                border: {border_color};
            }}
  
            
            '''
        # print (css)


        
        # css = '''  
        #     QCheckBox::indicator {
        #         width: 18px;
        #         height: 18px;
        #     }
        #     QCheckBox::indicator:checked {
        #         image: url(gfx/dark_checkbox_intermediate.png);
        #     }
        #     QCheckBox::indicator:unchecked {
        #         image: url(gfx/dark_checkbox_blank_outline.png);
        #     }
        #     QRadioButton::indicator {
        #         width: 18px;
        #         height: 18px;
        #     }
        #     QRadioButton::indicator:checked {
        #         image: url(gfx/dark_radiobox_marked.png);
        #     }
        #     QRadioButton::indicator:unchecked {
        #         image: url(gfx/dark_radiobox_blank.png);
        #     }
        #     QPlainTextEdit {
        #          border: 1px solid #444444;
        #     }
        #     QMenu::separator {
        #         border: #444444;
        #     }

           
        # '''

        return css
    
    @staticmethod
    def cssButtonState():
        ''' gets a pushbutton state for the input viewer '''

        # buttons = ("mdi.radiobox-blank","mdi.radiobox-marked","mdi.checkbox-blank-outline","mdi.checkbox-intermediate")
        # colors = (
        #     ("#AAAAAA","dark_"),
        #     ("#111111","")
        #     )


        # root_folder = gremlin.shared_state.root_path
        # icon_size = QtCore.QSize(64,64)
        # for name in buttons:
        #     for color, prefix in colors:
        #         icon = load_icon(name, qta_color=color)
        #         fname = prefix + name.replace("mdi.","").replace("-","_")
        #         the_path = os.path.join(root_folder, "gfx", f"{fname}.png")
        #         if os.path.isfile(the_path):
        #             os.unlink(the_path)
        #         the_path = the_path.replace("\\","/")
                
        #         # f = QtCore.QFile(the_path)
        #         # f.open(QtCore.QIODeviceBase.OpenModeFlag.WriteOnly)
        #         pixmap = icon.pixmap(icon_size)
        #         pixmap.save(the_path,"PNG")
        #         print (the_path)

        normal_color = Color.normalColor()
        normal_gradient_color = Color.normalGradientColor()
        background_color = Color.keyBackgroundColor()
        
        border_color = Color.borderColor()
        selected_border_color = Color.selectBorderColor()
        selected_color = Color.selectColor()
        selected_gradient_color = Color.selectGradientColor()
        css = f'''
        QPushButton {{
            border: 2px solid #8f8f91;
            border-radius: 15px;
            background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {normal_color}, stop: 1 {normal_gradient_color});
            min-width: 30px;
            min-height: 30px;
            max-width: 30px;
            max-height: 30px;
        }}

        QPushButton:pressed {{
            background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {selected_color}, stop: 1 {selected_gradient_color});
            border-color: {selected_border_color};
        }}

        QPushButton:flat {{
            border: none; /* no border for a flat push button */
        }}

        QPushButton:!enabled
        {{
             color: {background_color};
        }}
        '''
        return css
    
    @staticmethod
    def PenColors():
        ''' list of pen colors '''

        colors = {
            0: "#c0c0c0" if gremlin.shared_state.is_dark_theme else "#111111",
            1: "#e41a1c",
            2: "#377eb8",
            3: "#4daf4a",
            4: "#984ea3",
            5: "#ff7f00",
            6: "#ffff33",
            7: "#9cad1c",
            8: "#2cb2f5",
        }
        return colors
        
    
    @staticmethod
    def Pens():
        # Pre-defined colors for eight time series
        pens = {}
        colors = Color.PenColors()
        for index in colors.keys():
            pens[index] = QtGui.QPen(QtGui.QColor(colors[index]), 2 if index else 1)
        return pens

class WidgetTracker():

    def __init__(self):
        self._widget_cache = {}
    
    def registerWidget(self, widget):
        ''' registers widget for cleanup - this is needed because QT doesn't tell us when widgets are discarded so we need to manually track this here 
        so widgets cleanup correctly and remove any hooks / references '''
        self._widget_cache[widget] = widget

    def unregisterWidget(self, widget):
        ''' removes a widget from the cleanup list'''
        if widget in self._widget_cache:
            if hasattr(widget, "_cleanup_ui"):
                widget._cleanup_ui()
            del self._widget_cache[widget]
            widget.setParent(None)

    def clearRegisteredWidgets(self):
        ''' cleanup all widgets '''
        for widget in self._widget_cache.values():
            if hasattr(widget, "_cleanup_ui"):
                widget._cleanup_ui()
            widget.setParent(None)
        self._widget_cache = {}
        verbose = gremlin.config.Configuration().verbose
        if verbose: syslog.info("TRACKER: clear()")
        



@SingletonDecorator
class DeviceWidgetTracker():
    def __init__(self):
        self._widget_cache = {}
        self.any_mode = "[any]"

    def registerWidget(self, widget, device_guid, mode, input_type, input_id, key):
        if not mode:
            mode = self.any_mode
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if not device_guid in self._widget_cache:
            self._widget_cache[device_guid] = {}
        if not mode in self._widget_cache[device_guid]:
            self._widget_cache[device_guid][mode] = {}
        if not input_type in self._widget_cache[device_guid][mode]:
            self._widget_cache[device_guid][mode][input_type] = {}
        if not input_id in self._widget_cache[device_guid][mode][input_type]:
            self._widget_cache[device_guid][mode][input_type][input_id] = {}

        self._widget_cache[device_guid][mode][input_type][input_id][key] = widget

    def unregisterWidget(self, device_guid, mode, input_type, input_id, key):
        if not mode:
            mode = self.any_mode
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._widget_cache:
            for mode in self._widget_cache[device_guid]:
                if input_type in self._widget_cache[device_guid][mode]:
                    if input_id in self._widget_cache[device_guid][mode][input_type]:
                        if key in self._widget_cache[device_guid][mode][input_type][input_id]:
                            self._widget_cache[device_guid][mode][input_type][input_id] = None


    def clear(self):
        self._widget_cache = {}
        verbose = gremlin.config.Configuration().verbose
        if verbose: syslog.info("DEVICE WIDGET TRACKER: clear()")

    def getWidget(self, device_guid, mode, input_type, input_id, key):
        if not mode:
            mode = self.any_mode
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._widget_cache:
            for mode in self._widget_cache[device_guid]:
                if input_type in self._widget_cache[device_guid][mode]:
                    if input_id in self._widget_cache[device_guid][mode][input_type]:
                        if key in self._widget_cache[device_guid][mode][input_type][input_id]: 
                            return self._widget_cache[device_guid][mode][input_type][input_id][key]
            

    def getCache(self, device_guid, mode, input_type):
        if not mode:
            mode = self.any_mode
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._widget_cache:
            for mode in self._widget_cache[device_guid]:
                if input_type in self._widget_cache[device_guid][mode]:
                    return self._widget_cache[device_guid][mode][input_type]
        self._widget_cache[device_guid] = {}
        self._widget_cache[device_guid][mode] = {}
        self._widget_cache[device_guid][mode][input_type] = {}
        return self._widget_cache[device_guid][mode][input_type]
            


@SingletonDecorator
class StateTracker():
    def __init__(self):
        self._axis_cache = {}
        
        self._button_cache = {}
        self._state_cache = {}
        el = gremlin.event_handler.EventListener()
        el.button_state_change.connect(self._button_state_change)
        el.axis_state_change.connect(self._axis_state_change)
        el.select_input_completed.connect(self._select_input_completed)
        el.update_input_state.connect(self._update_input_state)
        self._queue = []


    def _key(self, input_id):
        if hasattr(input_id, "message_key"):
            # item has a special key to use for indexing input ID
            return input_id.message_key
        return str(input_id)


    def registerButtonState(self, widget, device_guid, input_type, input_id):
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if not device_guid in self._button_cache:
            self._button_cache[device_guid] = {}
        if not input_type in self._button_cache[device_guid]:
            self._button_cache[device_guid][input_type] = {}
        key = self._key(input_id)
        if key:
            # print (f"Add button {key}")
            self._button_cache[device_guid][input_type][key] = widget
        else:
            pass

    def unregisterButtonState(self, device_guid, input_type, input_id):
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._button_cache:
            if input_type in self._button_cache[device_guid]:
                key = self._key(input_id)
                if key in self._button_cache[device_guid][input_type]:
                    # print (f"Remove button {key}")
                    del self._button_cache[device_guid][input_type][key]

    def registerAxisState(self, widget, device_guid, input_type, input_id):
        if hasattr(widget,"deleted"):
            widget.deleted.connect(self._widget_deleted)
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if not device_guid in self._axis_cache:
            self._axis_cache[device_guid] = {}
        if not input_type in self._axis_cache[device_guid]:
            self._axis_cache[device_guid][input_type] = {}
        key = self._key(input_id)
        # print (f"Add axis {key}")
        self._axis_cache[device_guid][input_type][key] = widget

    @QtCore.Slot(object)
    def _widget_deleted(self, widget):
        widget.deleted.disconnect(self._widget_deleted)
        self._delete_widget(widget)
        
        
    def _delete_widget(self, widget):
        ''' deletes a widget '''
        for device_guid in self._axis_cache:
            for input_type in self._axis_cache[device_guid]:
                for key in self._axis_cache[device_guid][input_type]:
                    if self._axis_cache[device_guid][input_type][key] == widget:
                        del self._axis_cache[device_guid][input_type][key]
                        break
        

    def clear(self):
        self._axis_cache.clear()
        self._button_cache.clear()

    def unregisterAxisState(self, device_guid, input_type, input_id):
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._axis_cache:
            if input_type in self._axis_cache[device_guid]:
                key = self._key(input_id)
                if key in self._axis_cache[device_guid][input_type]:
                    del self._axis_cache[device_guid][input_type][key]


    def _button_state_change(self, event: gremlin.event_handler.Event):


        if gremlin.shared_state.is_running:
            # do not update while profile is running
            return 
        
        self._process_event(event)

    def _process_event(self, event):
        device_guid = event.device_guid
        input_type = event.event_type
        input_id = event.identifier
        match input_type:
            case InputType.JoystickButton:
                state = event.is_pressed
            case InputType.JoystickHat:
                state = event.value
            case InputType.OpenSoundControl:
                state = input_id.button_value
            case InputType.Midi:
                state = input_id.button_value

        self._store_state(device_guid, input_type, input_id, state)
        self._update_widget(device_guid, input_type, input_id, state)

    def _get_device_state(self, device_guid, input_type, input_id):
        ''' gets the current state or value of the item '''
        state = None
        match input_type:
            case InputType.JoystickAxis:
                state = gremlin.joystick_handling.get_axis(device_guid, input_id)
            case InputType.JoystickButton:
                state = gremlin.joystick_handling.get_button(device_guid, input_id)
            case InputType.JoystickHat:
                value = gremlin.joystick_handling.get_hat(device_guid, input_id)
                import vjoy.vjoy
                if value in vjoy.vjoy.Hat.to_continuous_position: 
                    state = vjoy.vjoy.Hat.to_continuous_position[value]


            case InputType.OpenSoundControl:
                pass
            case InputType.Midi:
                pass
            case InputType.KeyboardLatched:
                pass        
        return state

    def _update_widget(self, device_guid, input_type, input_id, state):
        ''' updates the state of the widget'''
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        # syslog = logging.getLogger("system")
        device_name = gremlin.shared_state.get_device_name(device_guid)
        if device_guid in self._button_cache:
            if input_type in self._button_cache[device_guid]:
                key = self._key(input_id)
                if key in self._button_cache[device_guid][input_type]:
                    widget = self._button_cache[device_guid][input_type][key]
                    try:
                        if widget.enabled:
                            match input_type:
                                case InputType.JoystickButton:
                                    if hasattr(widget, "_update_value"):
                                        widget._update_value(state)
                                case InputType.JoystickHat:
                                    if hasattr(widget, "_update_hat"):
                                        widget._update_hat(state)
                                case InputType.OpenSoundControl:
                                    if hasattr(widget, "_update_value"):
                                        widget._update_value(state)
                                case InputType.Midi:
                                    if hasattr(widget, "_update_value"):
                                        widget._update_value(state)

                            
                    except:
                        # discarded by QT - ignore
                        pass
                # else:
                #     syslog.info(f"ButtonState: {device_name} type {InputType.to_display_name(event.event_type)} input {event.identifier} connect")              
                
                    
    def _store_state(self, device_guid, input_type, input_id, state):
        ''' stores the last button state for the given input '''
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if not device_guid in self._state_cache:
            self._state_cache[device_guid] = {}
        if not input_type in self._state_cache[device_guid]:
            self._state_cache[device_guid][input_type] = {}
        # device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
        # print (f"Store: {device_name} {InputType.to_display_name(input_type)} {input_id} state: {state}")
        self._state_cache[device_guid][input_type][input_id] = state

    def _get_state(self, device_guid, input_type, input_id):
        ''' gets the last button state for the given input '''
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._state_cache:
            if input_type in self._state_cache[device_guid]:
                if input_id in self._state_cache[device_guid][input_type]:
                    return self._state_cache[device_guid][input_type][input_id]
        return None




    
    def _axis_state_change(self, event : gremlin.event_handler.Event):
        if gremlin.shared_state.is_running:
            # do not update while profile is running
            return 
        
        device_guid = event.device_guid
        input_type = event.event_type
        input_id = event.identifier
        value = event.value
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._axis_cache:
            if input_type in self._axis_cache[device_guid]:
                key = self._key(input_id)
                if key in self._axis_cache[device_guid][input_type]:
                    widget = self._axis_cache[device_guid][input_type][key]
                    try:
                        if widget.enabled:
                            widget._update_value(value)
                    except:
                        # discarded by QT - ignore
                        pass
                
                    
                        
    
    def getButtonWidget(self, device_guid, input_type, input_id):
        ''' gets the widget registered for a button state tracking'''
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._button_cache:
            if input_type in self._button_cache[device_guid]:
                key = self._key(input_id)
                if key in self._button_cache[device_guid][input_type]:
                    widget = self._button_cache[device_guid][input_type][key]
                    return widget
                
        return None
    
    def getAxisWidget(self, device_guid, input_type, input_id):
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._axis_cache:
            if input_type in self._axis_cache[device_guid]:
                key = self._key(input_id)
                if key in self._axis_cache[device_guid][input_type]:
                    widget = self._axis_cache[device_guid][input_type][key]
                    return widget
        return None
    
    @QtCore.Slot(object, object, object)
    def _select_input_completed(self, device_guid, input_type, input_id):
        state = self._get_state(device_guid, input_type, input_id)
        # device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
        # print (f"Completed: {device_name} {InputType.to_display_name(input_type)} {input_id} state: {state}")
        if state is not None:
            self._update_widget(device_guid, input_type, input_id, state)

    
    @QtCore.Slot(object)
    def _update_input_state(self, device_guid):
        ''' updates all the state widgets related to a single device based on stored state '''
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
            # buttons
        if device_guid in self._button_cache:
            for input_type in self._button_cache[device_guid]:
                for key in self._button_cache[device_guid][input_type]:
                    widget = self._button_cache[device_guid][input_type][key]
                    input_id = widget.input_id
                    # get the current state
                    state = self._get_device_state(device_guid, input_type, input_id)
                    if state is not None:
                        self._update_widget(device_guid, input_type, input_id, state)
        # axes
        if device_guid in self._axis_cache:
            for input_type in self._axis_cache[device_guid]:
                for key in self._axis_cache[device_guid][input_type]:
                    widget = self._axis_cache[device_guid][input_type][key]
                    input_id = widget.input_id
                    # get the current state
                    state = self._get_device_state(device_guid, input_type, input_id)
                    if state is not None:
                        self._update_widget(device_guid, input_type, input_id, state)
 


_tabsplitter_tracker = WidgetTracker()
_state_tracker = StateTracker()

class ContainerViewTypes(enum.Enum):

    """Enumeration of view types used by containers."""

    Action = 1
    Conditions = 2
    VirtualButton = 3

    @staticmethod
    def to_string(value):
        try:
            return _ContainerView_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                f"Invalid type in container lookup, {value}"
            )

    @staticmethod
    def to_enum(value):
        try:
            return _ContainerView_to_enum_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(
                f"Invalid type in container lookup, {value}"
            )


_ContainerView_to_enum_lookup = {
    "action": ContainerViewTypes.Action,
    "conditions": ContainerViewTypes.Conditions,
    "virtual button": ContainerViewTypes.VirtualButton
}


_ContainerView_to_string_lookup = {
    ContainerViewTypes.Action: "Action",
    ContainerViewTypes.Conditions: "Conditions",
    ContainerViewTypes.VirtualButton: "Virtual Button"
}


class AbstractModel(QtCore.QObject):

    """Base class for MVC models."""

    data_changed = QtCore.Signal()

    def __init__(self, parent=None):
        """Creates a new model.

        :param parent the parent of this model
        """
        super().__init__(parent)

    def rows(self):
        """Returns the number of rows in the model.

        :return number of rows
        """
        pass

    def data(self, index):
        """Returns the data entry stored at the provided index.

        :param index the index for which to return data
        :return data stored at the given index
        """
        pass


class AbstractView(QtWidgets.QWidget):

    """Base class for MVC views."""

    # Signal emitted when a entry is selected
    item_selected = QtCore.Signal(int, bool) # index of the item being selected
    item_edit = QtCore.Signal(object, int, object)  # widget, index, model data object
    item_edit_curve = QtCore.Signal(object, int, object) # widget, index , model data object
    item_delete_curve = QtCore.Signal(object, int, object) # widget, index , model data object
    item_closed = QtCore.Signal(object, int, object)  # widget, index, model data object


    def __init__(self, parent=None):
        """Creates a new view instance.

        :param parent the parent of this view widget
        """
        super().__init__(parent)
        self._model = None

    @property
    def model(self):
        return self._model
    @model.setter
    def model(self, value):
        if value != self._model:
            if self._model is not None:
                self._model.data_changed.disconnect(self.redraw)
            self._model = value
            self._model_changed()
            self._model.data_changed.connect(self.redraw)

    def set_model(self, model):
        """Sets the model to display with this view.

        :param model the model to visualize
        """
        self.model = model

    def select_item(self, index):
        """Selects the item at the provided index

        :param index the index of the item to select
        """
        pass

    def redraw(self):
        """Redraws the view."""
        pass

    def _model_changed(self):
        """Called when a model is added or updated to allow user code to run."""
        pass


class LeftRightPushButton(QtWidgets.QPushButton):

    """Implements a push button that distinguishes between left and right
    mouse clicks."""

    # Signal emitted when the button is pressed using the right mouse button
    clicked_right = QtCore.Signal()

    def __init__(self, label, parent=None):
        """Creates a new button instance.

        :param label the text to display on the button
        :param parent the parent of this button
        """
        super().__init__(label, parent)

    def mousePressEvent(self, event):
        """Handles mouse press events.

        :param event the mouse press event to handle
        """
        if event.button() == QtCore.Qt.RightButton:
            self.clicked_right.emit()
        else:
            super().mousePressEvent(event)


class NoKeyboardPushButton(QtWidgets.QPushButton):

    """Standard PushButton which does not react to keyboard input."""

    def __init__(self, *args, **kwargs):
        """Creates a new instance."""
        super().__init__(*args, **kwargs)

    def keyPressEvent(self, event):
        """Handles key press events by ignoring them.

        :param event the key event to handle
        """
        pass



    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self._data = value




class QFloatLineEdit(QtWidgets.QLineEdit):
    ''' double input validator with optional range limits for input axis

        this line edit behaves like a spin box so it's interchangeable

    '''

    valueChanged = QtCore.Signal(float) # fires when the value changes
    doubleClick = QtCore.Signal() # fires when the input is double clicked

    def __init__(self, data = None, min_range = -1.0, max_range = 1.0, decimals = 3, step = 0.01, value = 0.0, chars = 8, parent = None):
        super().__init__(parent)
        self._min_range = min_range
        self._max_range = max_range
        self._step = step
        self._decimals = decimals

        #self._validator = QFloatLineEdit.FloatValidator(bottom=min_range, top=max_range)
        # self._validator = QtGui.QDoubleValidator(bottom=min_range, top=max_range)
        # self._validator.setLocale(self.locale()) # handle correct floating point separator
        # self._validator.setNotation(QtGui.QDoubleValidator.Notation.StandardNotation)
        #self.setValidator(self._validator)
        self.textChanged.connect(self._validate)
        self.installEventFilter(self)
        #self.setText("0")
        self.setValue(value)
        self._data = data
        if chars > 0:
            self._chars = chars
            self._update_width(chars)
        else:
            self.chars = 0


    @property
    def chars(self) -> int:
        return self._chars
    @chars.setter
    def chars(self, value : int):
        if value > 0 and value != self._chars:
            self._chars = value
            self._update_width(value)
        else:
            self._chars = 0
            self.setMaximumWidth(QSize.maxQSize().width())

    def _update_width(self, chars):
        w = get_text_width(str("m"*chars))
        self.setMaximumWidth(w)





    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.Wheel:
            # handle wheel up/down change
            if self.isReadOnly():
                return True # cannot change the value if readonly
            v = self._to_value()
            if v is not None:
                eh = gremlin.event_handler.EventListener()
                is_shifted = eh.get_shifted_state()
                factor = 0.1 if is_shifted else 1.0
                if event.angleDelta().y() > 0:
                    # up
                    v += self._step * factor
                else:
                    # down
                    v -= self._step * factor
                v = gremlin.util.clamp(v, self._min_range, self._max_range)
                self.setValue(v)

            return True # filter the wheel event
        elif t == QtCore.QEvent.Type.FocusAboutToChange:
            value = self._to_value()
            if value is None:
                return True # skip the event
        elif t == QtCore.QEvent.Type.FocusOut:
            # format the input to the correct decimals
            self.setValue(self.value())
        elif t == QtCore.QEvent.Type.MouseButtonDblClick:
            self.doubleClick.emit()
        return False
    
    def keyPressEvent(self, event):
        if event == QtGui.QKeySequence.StandardKey.Paste:
            text = QtWidgets.QApplication.clipboard().text()
            if text:
                text = text.strip()
            try:
                value = float(text)
                self.setValue(value)
                return True
            except:
                pass

        return super().keyPressEvent(event)


    def _update_value(self, value):
        if value is None:
            return
        s_value = f"{float(value):0.{self._decimals}f}"
        self.setText(s_value)
        self.valueChanged.emit(value)



    @QtCore.Slot()
    def _validate(self):
        ''' called whenever the text changes '''
        text = self.text()
        value = self._to_value(text)
        return value is not None

    def setValue(self, value : float):
        ''' sets the value '''
        self._update_value(value)

    def _to_value(self, text : str = None):
        if text is None:
            text = self.text()
        try:
            value = float(text)
        except:
            return None
        
        if value < self._min_range:
            value = self._min_range
            with QtCore.QSignalBlocker(self):
                self.setText(f"{value:0.{self._decimals}f}")
        elif value > self._max_range:
            value = self._max_range
            with QtCore.QSignalBlocker(self):
                self.setText(f"{value:0.{self._decimals}f}")
        return value
        

    def value(self) -> float:
        ''' current value, None if not a valid input'''
        value = self._to_value()
        if value is not None:
            return value
        return None

    def isValid(self):
        ''' true if the input in the box is currently valid'''
        return self.hasAcceptableInput()

    def step(self):
        ''' mouse wheel step value'''
        return self._step

    def setStep(self, step):
        self._step = step

    def setSingleStep(self, step):
        self._step = step

    def decimals(self):
        return self._decimals

    def setDecimals(self, decimals):
        if decimals < 0:
            decimals = 0
        if self._decimals != decimals:
            self._decimals = decimals
            v = self._to_value()
            if v is not None:
                # correct to the new number of decimals
                self.setValue(v)

    def setRange(self, bottom, top):
        if top < bottom:
            bottom, top = top, bottom
        self._min_range = bottom
        self._max_range = top
        # self._validator.setBottom(bottom)
        # self._validator.setTop(top)
        self._update_value(self.value())

    def setMaximum(self, top):
        self._max_range = top
        #self._validator.setTop(top)
        self._update_value(self.value())

    def setMinimum(self, bottom):
        self._min_range = bottom
        #self._validator.setBottom(bottom)
        self._update_value(self.value())

    def minimum(self):
        return self._min_range

    def maximum(self):
        return self._max_range
    

class QFloatLineEditEx(QtWidgets.QLineEdit):
    ''' double input validator with optional range limits for input axis

        this line edit behaves like a spin box so it's interchangeable

    '''

    valueChanged = QtCore.Signal(float) # fires when the value changes
    doubleClick = QtCore.Signal() # fires when the input is double clicked

    def __init__(self, data = None, min_range = -1.0, max_range = 1.0, decimals = 3, step = 0.01, value = 0.0, chars = 8, parent = None):
        super().__init__(parent)
        self._min_range = min_range
        self._max_range = max_range
        self._step = step
        self._decimals = decimals

        #self._validator = QFloatLineEdit.FloatValidator(bottom=min_range, top=max_range)
        self._validator = QtGui.QDoubleValidator(bottom=min_range, top=max_range)
        self._validator.setLocale(self.locale()) # handle correct floating point separator
        self._validator.setNotation(QtGui.QDoubleValidator.Notation.StandardNotation)
        self.setValidator(self._validator)
        self.textChanged.connect(self._validate)
        self.installEventFilter(self)
        #self.setText("0")
        self.setValue(value)
        self._data = data
        if chars > 0:
            self._chars = chars
            self._update_width(chars)
        else:
            self.chars = 0


    @property
    def chars(self) -> int:
        return self._chars
    @chars.setter
    def chars(self, value : int):
        if value > 0 and value != self._chars:
            self._chars = value
            self._update_width(value)
        else:
            self._chars = 0
            self.setMaximumWidth(QSize.maxQSize().width())

    def _update_width(self, chars):
        w = get_text_width(str("m"*chars))
        self.setMaximumWidth(w)





    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.Wheel:
            # handle wheel up/down change
            if self.isReadOnly():
                return True # cannot change the value if readonly
            v = self.value()
            if v is not None:
                eh = gremlin.event_handler.EventListener()
                is_shifted = eh.get_shifted_state()
                factor = 0.1 if is_shifted else 1.0
                if event.angleDelta().y() > 0:
                    # up
                    v += self._step * factor
                else:
                    # down
                    v -= self._step * factor
                v = gremlin.util.clamp(v, self._min_range, self._max_range)
                self.setValue(v)

            return True # filter the wheel event
        elif t == QtCore.QEvent.Type.FocusAboutToChange:
            if not self.hasAcceptableInput():
                return True # skip the event
        elif t == QtCore.QEvent.Type.FocusOut:
            if not self.hasAcceptableInput():
                return True # skip the event
            # format the input to the correct decimals
            self.setValue(self.value())
        elif t == QtCore.QEvent.Type.MouseButtonDblClick:
            self.doubleClick.emit()
        return False


    def _update_value(self, value):
        if value is None:
            return
        other = self.value()
        if other is None or other != value:
            s_value = f"{float(value):0.{self._decimals}f}"
            if s_value != self.text():
                self.setText(s_value)
            self.valueChanged.emit(value)



    @QtCore.Slot()
    def _validate(self):
        ''' called whenever the text changes '''
        if self.hasAcceptableInput():
            value = self.value()
            self.valueChanged.emit(value)

    def setValue(self, value : float):
        ''' sets the value '''
        self._update_value(value)

    def value(self) -> float:
        ''' current value, None if not a valid input'''
        if self.hasAcceptableInput():
            return float(self.text())
        try:
            text = self.text()
            if text:
                v = float(text)
                return v
        except:
            pass
        return None

    def isValid(self):
        ''' true if the input in the box is currently valid'''
        return self.hasAcceptableInput()

    def step(self):
        ''' mouse wheel step value'''
        return self._step

    def setStep(self, step):
        self._step = step

    def setSingleStep(self, step):
        self._step = step

    def decimals(self):
        return self._decimals

    def setDecimals(self, decimals):
        if decimals < 0:
            decimals = 0
        if self._decimals != decimals:
            self._decimals = decimals
            v = self.value()
            if v is not None:
                # correct to the new number of decimals
                self.setValue(v)

    def setRange(self, bottom, top):
        if top < bottom:
            bottom, top = top, bottom
        self._min_range = bottom
        self._max_range = top
        self._validator.setBottom(bottom)
        self._validator.setTop(top)
        self._update_value(self.value())

    def setMaximum(self, top):
        self._max_range = top
        self._validator.setTop(top)
        self._update_value(self.value())

    def setMinimum(self, bottom):
        self._min_range = bottom
        self._validator.setBottom(bottom)
        self._update_value(self.value())

    def minimum(self):
        return self._min_range

    def maximum(self):
        return self._max_range    

class QIntLineEdit(QtWidgets.QLineEdit):
    ''' integer input validator with optional range limits for input axis

        this line edit behaves like a spin box so it's interchangeable

    '''

    valueChanged = QtCore.Signal(float) # fires when the value changes
    doubleClick = QtCore.Signal() # fires when the input is double clicked

    def __init__(self, data = None, min_range = -16383, max_range = 16384, step = 1, value = 0, chars = 8, parent = None):
        super().__init__(parent)
        if min_range > max_range:
            max_range, min_range = min_range, max_range
        self._min_range = min_range
        self._max_range = max_range
        self._step = step


        self._validator = QtGui.QIntValidator(min_range, max_range) 
        self._validator.setLocale(self.locale()) # handle correct floating point separator
        self.textChanged.connect(self._validate)
        self.setValidator(self._validator)
        self.installEventFilter(self)
        self.setValue(value)
        self._data = data
        if chars > 0:
            self._chars = chars
            self._update_width(chars)
        else:
            self.chars = 0


    @property
    def chars(self) -> int:
        return self._chars
    
    @chars.setter
    def chars(self, value : int):
        if value > 0 and value != self._chars:
            self._chars = value
            self._update_width(value)
        else:
            self._chars = 0
            self.setMaximumWidth(QSize.maxQSize().width())

    def _update_width(self, chars):
        w = get_text_width(str("m"*chars))
        self.setMaximumWidth(w)

    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self._data = value

    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.Wheel:
            # handle wheel up/down change
            if self.isReadOnly():
                return True # cannot change the value if readonly
            v = self.value()
            if v is not None:
                eh = gremlin.event_handler.EventListener()
                is_shifted = eh.get_shifted_state()
                factor = 2 if is_shifted else 1
                if event.angleDelta().y() > 0:
                    # up
                    v += self._step * factor
                else:
                    # down
                    v -= self._step * factor
                v = gremlin.util.clamp(v, self._min_range, self._max_range)
                self.setValue(v)

            return True # filter the wheel event
        elif t == QtCore.QEvent.Type.FocusAboutToChange:
            if not self.hasAcceptableInput():
                return True # skip the event
        elif t == QtCore.QEvent.Type.FocusOut:
            if not self.hasAcceptableInput():
                return True # skip the event
            # format the input to the correct decimals
            self.setValue(self.value())
        elif t == QtCore.QEvent.Type.MouseButtonDblClick:
            self.doubleClick.emit()
        return False


    def _update_value(self, value : int):
        other = self.value()

        if value is None and other is None:
            return
        s_value = str(int(value))
        if s_value != self.text():
            self.setText(s_value)
        if other is not None and other != value:
            self.valueChanged.emit(int(value))



    @QtCore.Slot()
    def _validate(self):
        ''' called whenever the text changes '''
        if self.hasAcceptableInput():
            value = self.value()
            self.valueChanged.emit(value)

    def setValue(self, value : int):
        ''' sets the value '''
        self._update_value(int(value))

    def value(self) -> int:
        ''' current value, None if not a valid input'''
        if self.hasAcceptableInput():
            return int(self.text())
        try:
            text = self.text()
            if text:
                value = int(self.text())
                return value
        except:
            pass
        return None

    def isValid(self):
        ''' true if the input in the box is currently valid'''
        return self.hasAcceptableInput()

    def step(self):
        ''' mouse wheel step value'''
        return self._step

    def setStep(self, step):
        self._step = step

    def setSingleStep(self, step: int):
        self._step = step

    def setRange(self, bottom, top):
        if top < bottom:
            bottom, top = top, bottom
        self._min_range = bottom
        self._max_range = top
        self._validator.setBottom(bottom)
        self._validator.setTop(top)
        value = int(self.text())
        value = int(gremlin.util.clamp(value, bottom, top))
        self._update_value(value)

    def setMaximum(self, top):
        self._max_range = top
        self._validator.setTop(top)
        self._update_value(self.value())

    def setMinimum(self, bottom):
        self._min_range = bottom
        self._validator.setBottom(bottom)
        self._update_value(self.value())

    def minimum(self):
        return self._min_range

    def maximum(self):
        return self._max_range



class DynamicDoubleSpinBox(QFloatLineEdit):
    pass

    @property
    def decimal_point(self):
        return self.locale().decimalPoint

class DynamicDoubleSpinBox_legacy(QtWidgets.QDoubleSpinBox):

    """Implements a double spin box which dynamically overwrites entries."""

    valid_chars = [str(v) for v in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]] + ["-"]
    decimal_point = "."

    def __init__(self, parent=None, data = None):
        """Create a new instance with the specified parent.

        :param parent the parent of this widget
        """
        super().__init__(parent)
        DynamicDoubleSpinBox.decimal_point = self.locale().decimalPoint()
        if DynamicDoubleSpinBox.decimal_point not in DynamicDoubleSpinBox.valid_chars:
            DynamicDoubleSpinBox.valid_chars.append(
                DynamicDoubleSpinBox.decimal_point
            )

        self._data = data

    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self._data = value

    def validate(self, text, pos):
        """Validates the provided string.

        This takes the pre-validation string and formats it as a float of fixed
        length before submitting it for validation.

        :param text the input to be validated
        :param pos the position in the string
        """
        try:
            # Discard invalid characters
            if 0 <= pos-1 < len(text):
                if text[pos-1] not in DynamicDoubleSpinBox.valid_chars:
                    text = text[:pos-1] + text[pos:]
                    pos -= 1

            # Replace empty parts with the value 0
            point = self.locale().decimalPoint()
            if point in text:
                parts = text.split(point)
                for part in parts:
                    if len(part) == 0:
                        part = "0"
                value_string = f"{parts[0]}.{parts[1]}"
            else:
                value_string = text

            # Convert number to a string representation we can convert to
            # a float so we can truncate the decimal places as required

            format_string = f"{{:.{self.decimals():d}f}}"

            try:
                value_string = format_string.format(float(value_string))
            except:
                return False

            # Use decimal place separator dictated by the locale settings
            text = value_string.replace(".", DynamicDoubleSpinBox.decimal_point)

            return super().validate(text, pos)
        except (ValueError, IndexError):
            return super().validate(text, pos)



class AbstractInputSelector(QtWidgets.QWidget):

    def __init__(self, change_cb, valid_types, parent=None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.change_cb = change_cb
        self.valid_types = valid_types
        self.device_list = []

        self.device_dropdown = None
        self.input_item_dropdowns = []
        self._device_id_registry = []
        self._input_type_registry = []

        self._initialize()
        self._create_device_dropdown()
        self._create_input_dropdown()

    def get_selection(self):
        device_id = None
        input_id = None
        input_type = None

        device_index = self.device_dropdown.currentIndex()
        if device_index != -1:
            device_id = self._device_id_registry[device_index]
            input_index = self.input_item_dropdowns[device_index].currentIndex()

            if input_index == -1:
                input_index = 0
                input_value = self.input_item_dropdowns[device_index].itemText(
                    input_index)
            else:
                input_value = self.input_item_dropdowns[device_index].currentText()

            input_type, input_id = self.input_item_dropdowns[device_index].itemData(input_index)

            # input_type = self._input_type_registry[device_index][input_index]

            # if input_type == InputType.JoystickAxis:
            #     input_id = gremlin.types.AxisNames.to_enum(input_value).value
            # else:
            #     input_id = int(input_value.split()[-1])

        return {
            "device_id": device_id,
            "input_id": input_id,
            "input_type": input_type
        }

    def set_selection(self, input_type, device_id, input_id):
        if device_id not in self._device_id_registry:
            return

        # Get the index of the combo box associated with this device
        dev_id = self._device_id_registry.index(device_id)

        # input_name = gremlin.common.input_to_ui_string(input_type, input_id)
        # entry_id = self.input_item_dropdowns[dev_id].findText(input_name)
        entry_id = -1
        # for some reason, findData doesn't work so we iterate manually
        item_count = self.input_item_dropdowns[dev_id].count()
        # print (f"looking for: {input_type} {input_id}   count of items: {item_count}")
        for index in range(item_count):
            match_input_type, match_input_id = self.input_item_dropdowns[dev_id].itemData(index)
            # print (f"match: type {match_input_type} id {match_input_id} ")
            if match_input_type == input_type and match_input_id == input_id:
                entry_id = index
                # print ("found!")
                break



        # Select and display correct combo boxes and entries within
        with QtCore.QSignalBlocker(self.device_dropdown):
            self.device_dropdown.setCurrentIndex(dev_id)


            for entry in self.input_item_dropdowns:
                with QtCore.QSignalBlocker(entry):
                    entry.setVisible(False)

            entry = self.input_item_dropdowns[dev_id]
            with QtCore.QSignalBlocker(entry):
                entry.setVisible(True)
                entry.setCurrentIndex(entry_id)



    def _update_device(self, index):
        # Hide all selection dropdowns

        for entry in self.input_item_dropdowns:
            with QtCore.QSignalBlocker(entry):
                entry.setVisible(False)

        # Show correct dropdown
        entry = self.input_item_dropdowns[index]
        with QtCore.QSignalBlocker(entry):
            entry.setVisible(True)
            entry.setCurrentIndex(0)
        self._execute_callback()


    def _initialize(self):
        raise gremlin.error.MissingImplementationError(
            "Missing implementation of AbstractInputSelector._initialize"
        )

    def _format_device_name(self, device):
        raise gremlin.error.MissingImplementationError(
            "Missing implementation of AbstractInputSelector._format_device_name"
        )

    def _device_identifier(self, device):
        raise gremlin.error.MissingImplementationError(
            "Missing implementation of AbstractInputSelector._device_identifier"
        )

    def _create_device_dropdown(self):
        self.device_dropdown = gremlin.ui.ui_common.QComboBox(self)
        for device in self.device_list:
            self.device_dropdown.addItem(self._format_device_name(device))
            self._device_id_registry.append(self._device_identifier(device))
        self.main_layout.addWidget(self.device_dropdown)
        self.device_dropdown.activated.connect(self._update_device)



    def _create_input_dropdown(self):
        count_map = {
            InputType.JoystickAxis: lambda x: x.axis_count,
            InputType.JoystickButton: lambda x: x.button_count,
            InputType.JoystickHat: lambda x: x.hat_count
        }

        self.input_item_dropdowns = []
        self._input_type_registry = []

        # Create input item selections for the devices. Each selection
        # will be invisible unless it is selected as the active device
        for device in self.device_list:
            selection = QComboBox(self)
            # limit drop down size
            selection.setMaxVisibleItems(20)
            selection.setStyleSheet("QComboBox { combobox-popup: 0; }")
            self._input_type_registry.append([])
            self.selection_widget = selection


            # Add items based on the input type
            max_col = 32

            for input_type in self.valid_types:
                item_count = count_map[input_type](device)
                for i in range(item_count):
                    input_id = i+1
                    if input_type == InputType.JoystickAxis:
                        input_id = device.axis_map[i].axis_index
                        s_ui = f"Axis {device.axis_names[i]}"
                    else:
                        s_ui = gremlin.common.input_to_ui_string(
                            input_type,
                            input_id
                        )
                    selection.addItem(s_ui, (input_type, input_id))

                    self._input_type_registry[-1].append(input_type)

            # Add the selection and hide it
            selection.setVisible(False)
            selection.activated.connect(self._execute_callback)
            self.main_layout.addWidget(selection)
            self.input_item_dropdowns.append(selection)

            selection.currentIndexChanged.connect(self._execute_callback)

        # Show the first entry by default
        if len(self.input_item_dropdowns) > 0:
            self.input_item_dropdowns[0].setVisible(True)


    def _execute_callback(self):
        self.change_cb(self.get_selection())

    def sync(self):
        ''' forces the change cb to be called to update dependents based on values '''
        self._execute_callback()



class JoystickSelector(AbstractInputSelector):

    """Widget allowing the selection of input items on a physical joystick."""


    def __init__(self, change_cb, valid_types, parent=None):
        """Creates a new JoystickSelector instance.

        :param change_cb function to call when changes occur
        :param valid_types valid input types for selection
        :param parent the parent of this widget
        """
        super().__init__(change_cb, valid_types, parent)


    def _initialize(self):
        potential_devices = sorted(
            gremlin.joystick_handling.joystick_devices(),
            key=lambda x: (x.name, x.device_guid)
        )
        for dev in potential_devices:
            input_counts = {
                InputType.JoystickAxis: dev.axis_count,
                InputType.JoystickButton: dev.button_count,
                InputType.JoystickHat: dev.hat_count
            }

            has_inputs = False
            for valid_type in self.valid_types:
                if input_counts.get(valid_type, 0) > 0:
                    has_inputs = True

            if has_inputs:
                self.device_list.append(dev)

    def _format_device_name(self, device):
        return device.name

    def _device_identifier(self, device):
        return device.device_guid


class VJoySelector(AbstractInputSelector):

    """Widget allowing the selection of vJoy inputs."""





    def __init__(self, change_cb, valid_types, invalid_ids={}, parent=None):
        """Creates a widget to select a vJoy output.

        :param change_cb callback to execute when the widget changes
        :param valid_types the input type to present in the selection
        :param invalid_ids list of vid values of vjoy devices to not consider
        :param parent of this widget
        """
        self.invalid_ids = invalid_ids
        super().__init__(change_cb, valid_types, parent)

    def _initialize(self):
        potential_devices = sorted(
            gremlin.joystick_handling.vjoy_devices(),
            key=lambda x: x.vjoy_id
        )
        for dev in potential_devices:
            input_counts = {
                InputType.JoystickAxis: dev.axis_count,
                InputType.JoystickButton: dev.button_count,
                InputType.JoystickHat: dev.hat_count
            }

            has_inputs = False
            for valid_type in self.valid_types:
                if input_counts.get(valid_type, 0) > 0:
                    has_inputs = True

            if not self.invalid_ids.get(dev.vjoy_id, False) and has_inputs:
                self.device_list.append(dev)

    def _format_device_name(self, device):
        return device.name
        #return f"{device.name} ({device.vjoy_id:d})"
        #return f"vJoy Device {device.vjoy_id:d}"

    def _device_identifier(self, device):
        return device.vjoy_id



class ActionSelector(QtWidgets.QWidget):

    """Widget permitting the selection of actions."""

    # Signal emitted when an action is going to be added
    action_added = QtCore.Signal(str)  # add button pressed
    action_paste = QtCore.Signal(object, object) # paste button pressed


    def __init__(self, input_type, container, parent=None):
        """Creates a new selector instance.

        :param input_type the input type for which the action selector is being created
        :param container: the owner container
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.input_type = input_type

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.action_label = QtWidgets.QLabel("Action")
        self.main_layout.addWidget(self.action_label)
        self._container = container

        self.action_dropdown = QComboBox()
        
        for name in self._valid_action_list():
            self.action_dropdown.addItem(name)
        config = gremlin.config.Configuration()
        self.action_dropdown.setCurrentText(config.last_action)
        self.action_dropdown.currentIndexChanged.connect(self._action_changed)
        self.add_button = QtWidgets.QPushButton("Add")
        self.add_button.clicked.connect(self._add_action)

        # clipboard
        self.paste_button = QtWidgets.QPushButton()
        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
        icon = gremlin.util.load_icon(f"{prefix}button_paste.svg")
        self.paste_button.setIcon(icon)
        self.paste_button.clicked.connect(self._paste_action)
        self.paste_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Minimum)
        self.paste_button.setToolTip("Paste Action")


        self.main_layout.addWidget(self.action_dropdown)
        self.main_layout.addWidget(self.add_button)
        self.main_layout.addWidget(self.paste_button)
        self.main_layout.addStretch(1)

        eh = gremlin.event_handler.EventHandler()
        eh.last_action_changed.connect(self._last_action_changed)
        self._container = None


    @property
    def container(self):
        return self._container
    # @container.setter
    # def container(self, container):
    #     self._container = container

    @QtCore.Slot(object, str)
    def _last_action_changed(self, widget, name):
        if widget != self.action_dropdown:
            with QtCore.QSignalBlocker(self.action_dropdown):
                self.action_dropdown.setCurrentText(name)

    def _action_changed(self):
        ''' remember the last selection '''
        name = self.action_dropdown.currentText()
        config = gremlin.config.Configuration()
        config.last_action = name
        if config.sync_last_selection:
            eh = gremlin.event_handler.EventHandler()
            eh.last_action_changed.emit(self.action_dropdown, name)

    def _valid_action_list(self):
        """Returns a list of valid actions for this InputItemWidget.

        :return list of valid action names
        """
        action_list = []
        # if self.input_type == InputType.JoystickAxis:
        #     action_list.append("Response Curve")
        # else:

        config = gremlin.config.Configuration()
        convert_vjoy = config.convert_vjoy_remap
        convert_curve = config.convert_response_curve
        control_enabled = config.show_input_enable

        #all_entries = [entry.name for entry in gremlin.plugin_manager.ActionPlugins().repository.values()]
        for entry in gremlin.plugin_manager.ActionPlugins().repository.values():
            if self.input_type in entry.input_types:
                if convert_vjoy and entry.name == "Remap":
                    continue
                elif convert_curve and entry.name == "Response Curve":
                    continue
                if entry.name == "Control" and not control_enabled:
                    continue
                action_list.append(entry.name)
        return sorted(action_list)


    def _add_action(self, clicked=False):
        """Handles selecting of an action to be added.

        :param clicked flag indicating whether or not the action resulted from
            a click
        """
        self.action_added.emit(self.action_dropdown.currentText())

    def _paste_action(self):
        ''' handle paste action '''
        import gremlin.plugin_manager
        container = self.container
        if container is None:
            # find the container if we can
            parent = self
            while parent is not None:
                if hasattr(parent,"profile_data"):
                    if isinstance(parent.profile_data, gremlin.base_profile.AbstractContainer):
                        container = parent.profile_data
                        break
                parent = parent.parent()


        action = gremlin.plugin_manager.ActionPlugins().fromClipboard(container)
        if action is None:
            return
        valid_actions = self._valid_action_list()
        if action.name in valid_actions:
            # valid action - clone it and add it
            # syslog.info("Clipboard paste action trigger...")
            self.action_paste.emit(action, self.container)
        else:
            # dish out a message
            MessageBox(title =  f"Invalid Action type ({action.name})",
                prompt = "Unable to paste action because it is not valid for the current input")


    def _clipboard_changed(self, clipboard):
        ''' handles paste button state based on clipboard data '''
        self.paste_button.setEnabled(clipboard.is_action)
        ''' updates the paste button tooltip with the current clipboard contents'''
        if clipboard.is_action:
            self.paste_button.setToolTip(f"Paste action ({clipboard.data.name})")
        else:
            self.paste_button.setToolTip(f"Paste action (not available)")



def _inheritance_tree_to_labels(labels, tree, level):
    """Generates labels to use in the dropdown menu indicating inheritance.

    :param labels the list containing all the labels
    :param tree the part of the tree to be processed
    :param level the indentation level of this tree
    """
    for mode, children in sorted(tree.items()):
        labels.append((mode,
            f"{"  " * level}{"" if level == 0 else "└"}{mode}"))
        _inheritance_tree_to_labels(labels, children, level+1)

def get_mode_list(profile_data):
    ''' gets a pairs (display_name, mode) '''
    profile = profile_data
    mode_list = []
    modes = gremlin.shared_state.current_profile.get_modes()
    # Create mode name labels visualizing the tree structure
    inheritance_tree = profile.build_inheritance_tree()
    labels = []
    _inheritance_tree_to_labels(labels, inheritance_tree, 0)

    # Filter the mode names such that they only occur once below
    # their correct parent
    mode_names = [n[0] for n in labels]
    display_names = [n[1] for n in labels]



    # for entry in labels:
    #     if not entry[0] in modes:
    #         continue
    #     if entry[0] in mode_names:
    #             idx = mode_names.index(entry[0])
    #             if len(entry[1]) > len(display_names[idx]):
    #                 del mode_names[idx]
    #                 del display_names[idx]
    #                 mode_names.append(entry[0])
    #                 display_names.append(entry[1])
    #     else:

    #         mode_names.append(entry[0])
    #         display_names.append(entry[1])

    # Add properly arranged mode names to the drop down list
    for display_name, mode_name in zip(display_names, mode_names):
        mode_list.append((display_name, mode_name))


    return mode_list



class ModeWidget(QtWidgets.QWidget):

    """Displays the ui for mode selection and management of a device."""

    # Signal emitted when the mode changes
    edit_mode_changed = QtCore.Signal(str) # when the edit mode changes


    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent widget
        """
        QtWidgets.QWidget.__init__(self, parent)

        self.mode_list = []

        self.profile = None
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self._create_widget()

        el = gremlin.event_handler.EventListener()
        el.mode_list_update.connect(self._mode_list_update)


    def setRuntimeDisabled(self, value):
        ''' enables or disables profile runtime behavior'''

        el = gremlin.event_handler.EventListener()
        try:
            if value:
                # hook the profile start/stop to enable/disable at runtime
                el.profile_start.connect(self._profile_start_cb)
                el.profile_stop.connect(self._profile_stop_cb)
            else:
                el.profile_start.disconnect(self._profile_start_cb)
                el.profile_stop.disconnect(self._profile_stop_cb)
        except:
            pass


    @QtCore.Slot()
    def _profile_start_cb(self):
        self.setEnabled(False)
    @QtCore.Slot()
    def _profile_stop_cb(self):
        self.setEnabled(True)

    @QtCore.Slot()
    def _mode_list_update(self):
        ''' occurs when mode list may have changed '''
        profile = gremlin.shared_state.current_profile
        mode = gremlin.shared_state.current_mode
        self.populate_selector(profile, mode)
        self.select_mode(mode)


    def select_mode(self, mode: str):
        ''' selects the mode without firing a change event - ignored if the mode doesn't exist '''
        # syslog = logging.getLogger("system")
        syslog.info(f"Mode: set edit selector mode to [{mode}]")
        index =  self.edit_mode_selector.findData(mode)
        if index >= 0:
            syslog.info(f"Mode: mode exists")
            with QtCore.QSignalBlocker(self.edit_mode_selector):
                self.edit_mode_selector.setCurrentIndex(index)
        else:
            # not found, update the selector
            syslog.info(f"Mode: mode does not exist, repopulating")
            self.populate_selector(gremlin.shared_state.current_profile, mode)

    def populate_selector(self, profile, mode_to_select : str = None, emit : bool = False):
        """Adds entries for every mode present in the profile.

        :param profile_data the device for which the mode selection is generated
        :param current_mode the currently active mode
        """
        # To prevent emitting lots of change events the slot is first
        # disconnected and then at the end reconnected again.
        with QtCore.QSignalBlocker(self.edit_mode_selector):
            self.profile = profile

            modes = gremlin.shared_state.current_profile.get_modes()
            while self.edit_mode_selector.count() > 0:
                    self.edit_mode_selector.removeItem(0)

            mode_list_pairs = get_mode_list(profile)
            self.mode_list = [x[1] for x in mode_list_pairs]
            # Create mode name labels visualizing the tree structure
            # inheritance_tree = self.profile.build_inheritance_tree()
            # labels = []
            # _inheritance_tree_to_labels(labels, inheritance_tree, 0)

            # # Filter the mode names such that they only occur once below
            # # their correct parent
            # mode_names = []
            # display_names = []
            # for entry in labels:
            #     if entry[0] in mode_names:
            #         idx = mode_names.index(entry[0])
            #         if len(entry[1]) > len(display_names[idx]):
            #             del mode_names[idx]
            #             del display_names[idx]
            #             mode_names.append(entry[0])
            #             display_names.append(entry[1])
            #     else:
            #         mode_names.append(entry[0])
            #         display_names.append(entry[1])

            # Add properly arranged mode names to the drop down list
            index = 0
            current_index = 0
            select_index = None
            last_edit_mode = gremlin.config.Configuration().get_profile_last_edit_mode()

            if not last_edit_mode in modes:
                last_edit_mode = gremlin.shared_state.current_profile.get_default_mode()

            for display_name, mode_name in mode_list_pairs:
                self.edit_mode_selector.addItem(display_name, mode_name)
                # self.mode_list.append(mode_name)
                if mode_to_select and select_index is None and mode_to_select == mode_name:
                    select_index = index
                if mode_name == last_edit_mode:
                    current_index = index
                index += 1

            if select_index:
                self.edit_mode_selector.setCurrentIndex(select_index)    
            else:
                self.edit_mode_selector.setCurrentIndex(current_index)
            if emit:
                self._edit_mode_changed_cb(current_index)


    @QtCore.Slot(int)
    def _edit_mode_changed_cb(self, idx):
        """Callback function executed when the mode selection changes.

        :param idx id of the now selected entry
        """
        # tell the UI about the mode change
        new_mode = self.mode_list[idx]
        # syslog = logging.getLogger("system")
        syslog.info(f"Mode: edit selector request change to [{new_mode}]")
        self.edit_mode_changed.emit(new_mode)




    def _create_widget(self):
        """Creates the mode selection and management dialog."""
        # Size policies used
        from gremlin.util import load_icon
        min_min_sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Minimum,
            QtWidgets.QSizePolicy.Minimum
        )
        exp_min_sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding,
            QtWidgets.QSizePolicy.Minimum
        )

        self.profile_options_button_widget = QtWidgets.QPushButton()
        self.profile_options_button_widget.setIcon(load_icon("fa.gear"))
        self.profile_options_button_widget.setToolTip("Profile Options")
        self.profile_options_button_widget.clicked.connect(self._profile_options_cb)



        # Create mode selector and related widgets
        self.edit_label = QtWidgets.QLabel("Profile Edit Mode")
        self.edit_label.setSizePolicy(min_min_sp)
        self.edit_mode_selector = QComboBox()
        self.edit_mode_selector.setSizePolicy(exp_min_sp)
        self.edit_mode_selector.setMinimumContentsLength(20)
        self.edit_mode_selector.setToolTip("Selects the active profile mode being edited")


        # add the mode change button
        self.mode_change = QtWidgets.QPushButton()
        is_dark = gremlin.shared_state.is_dark_theme    
        manage_modes_icon = "gfx/dark_manage_modes.svg" if is_dark else "gfx/manage_modes.svg"
        self.mode_change.setIcon(load_icon(manage_modes_icon))
        self.mode_change.setToolTip("Manage Profile Modes")
        self.mode_change.clicked.connect(self._manage_modes_cb)

        # Connect signal
        self.edit_mode_selector.currentIndexChanged.connect(self._edit_mode_changed_cb)

        # Add widgets to the layout
        self.main_layout.addStretch(10)

        self.main_layout.addWidget(self.edit_label)
        self.main_layout.addWidget(self.edit_mode_selector)
        self.main_layout.addWidget(self.mode_change)
        self.main_layout.addWidget(self.profile_options_button_widget)

    def _manage_modes_cb(self):
        ''' calls up the mode change dialog '''
        
        if not self.profile.profile_file or not os.path.isfile(self.profile.profile_file):
            MessageBox(prompt = "Please save the profile before configuring modes.")
            return

        import gremlin.shared_state
        ui = gremlin.shared_state.ui
        ui.manage_modes()

    def _profile_options_cb(self):
        import gremlin.ui.dialogs
        import gremlin.ui.ui_common
        if not self.profile.profile_file or not os.path.isfile(self.profile.profile_file):
            gremlin.ui.ui_common.MessageBox(prompt = "Please save the profile before setting options.")
            return

        dialog = gremlin.ui.dialogs.ProfileOptionsUi()
        dialog.exec()

    def currentIndex(self) -> int:
        ''' current selector index '''
        return self.edit_mode_selector.currentIndex()

    def currentMode(self) -> str:
        ''' gets the current mode '''
        return self.edit_mode_selector.currentData()


    def setCurrentIndex(self, index):
        self.edit_mode_selector.setCurrentIndex(index)

    def setCurrentMode(self, current_mode):
        index = self.edit_mode_selector.findData(current_mode)
        if index != -1:
            with QtCore.QSignalBlocker(self):
                self.setCurrentIndex(index)
        else:
            syslog.error(f"SetModeError: mode '{current_mode}' is not defined")

    def setShowModeEdit(self, value):
        ''' determines if the mode edit button is visible or not '''
        self.mode_change.setVisible(value)

    def setShowProfileOptions(self, value):
        ''' determines if the profile option button is visible or not '''
        self.profile_options_button_widget.setVisible(value)

    def setLabelText(self, text):
        ''' changes the label text if needed '''
        self.edit_label.setText(text)

class QBoxFrame(QtWidgets.QFrame):
    ''' boxed frame widget '''
    def __init__(self, data = None, parent = None, selected = False):
        super().__init__(parent)

        border_color = Color.borderColor()
        background_color = Color.backgroundColor()
        css = f'''
            QFrame {{
                border: 1px solid {border_color};
                background: {background_color};
            }}
            QLabel {{
                border: none;
            }}
            '''
        
        self.setFrameStyle(QtWidgets.QFrame.Plain | QtWidgets.QFrame.Box)
        self.setStyleSheet(css)


    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value


class InputListenerWidget(QBoxFrame):

    """Widget overlaying the main gui while waiting for the user
    to press a key or a joystick button """

    item_selected = QtCore.Signal(object) # called when the items are selected

    def __init__(
            self,
            event_types,
            return_kb_event=False,
            multi_keys=False,
            filter_func=None,
            parent=None
    ):
        """Creates a new instance.

        :param callback the function to pass the key pressed by the
            user to
        :param event_types the events to capture and return
        :param return_kb_event whether or not to return the kb event (True) or
            the key itself (False)
        :param multi_keys whether or not to return multiple key presses (True)
            or return after the first initial press (False)
        :param filter_func function applied to inputs which filters out more
            complex unwanted inputs
        :param parent the parent widget of this widget
        """
        super().__init__(parent)
        from gremlin.keyboard import key_from_code, key_from_name
        self._event_types = event_types
        self._return_kb_event = return_kb_event
        self._multi_keys = multi_keys
        self.filter_func = filter_func
        self._aborting = False
        self._closing = False
        self._abort_timer = threading.Timer(1.0, self._abort_request)
        self._multi_key_storage = []

        self._close_on_key = not (InputType.Keyboard in event_types or InputType.KeyboardLatched in event_types)
        self._esc_key = key_from_name("esc")

        # Create and configure the ui overlay
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(
            QtWidgets.QLabel(f"""<center>Please press the desired {self._valid_event_types_string()}.<br/><br/>Hold ESC{'' if self._close_on_key else ' for one second'} to abort.</center>""")
        )

        gremlin.shared_state.push_suspend_highlighting()
        gremlin.shared_state.push_suspend_ui_keyinput()

        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setFrameStyle(QtWidgets.QFrame.Plain | QtWidgets.QFrame.Box)
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColorConstants.DarkGray)
        self.setPalette(palette)

        # Start listening to user key presses
        event_listener = gremlin.event_handler.EventListener()
        event_listener.keyboard_event.connect(self._kb_event_cb)
        if InputType.JoystickAxis in self._event_types or \
                InputType.JoystickButton in self._event_types or \
                InputType.JoystickHat in self._event_types:
            event_listener.joystick_event.connect(self._joy_event_cb)
        elif InputType.Mouse in self._event_types:
            if not event_listener.mouseEnabled():
                # hook mouse
                event_listener.enableMouse()

            gremlin.windows_event_hook.MouseHook().start()
            event_listener.mouse_event.connect(self._mouse_event_cb)


    def _joy_event_cb(self, event):
        """Passes the pressed joystick event to the provided callback
        and closes the overlay.

        This only passes on joystick button presses.

        :param event the keypress event to be processed
        """
        # Only react to events we're interested in
        if event.event_type not in self._event_types:
            return
        if self.filter_func is not None and not self.filter_func(event):
            return

        # Ensure the event corresponds to a significant enough change in input
        process_event = gremlin.input_devices.JoystickInputSignificant().should_process(event)
        if event.event_type == InputType.JoystickButton:
            process_event &= event.is_pressed

        if process_event:
            gremlin.input_devices.JoystickInputSignificant().reset()
            self.item_selected.emit(event)
            self.close()

    def _kb_event_cb(self, event):
        """Passes the pressed key to the provided callback and closes
        the overlay.

        :param event
        the keypress event to be processed
        """

        if self._aborting:
            self.close()

        key = gremlin.keyboard.KeyMap.from_event(event)

        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_keyboard
        if verbose: syslog.info(f"LISTEN: Keyboard event: {event} {key}")

        if self._close_on_key:
            if key == self._esc_key:
                self.close()
            return # ignore keys otherwise

        # Return immediately once the first key press is detected
        if not self._multi_keys:
            if event.is_pressed and key == self._esc_key:
                if not self._abort_timer.is_alive():
                    self._abort_timer.start()
            elif not event.is_pressed and \
                    InputType.Keyboard in self._event_types:
                if not self._return_kb_event:
                    self.item_selected.emit(key)
                else:
                    self.item_selected.emit(event)
                self._abort_timer.cancel()
                self.close()
        # Record all key presses and return on the first key release
        else:
            if event.is_pressed:
                if InputType.Keyboard in self._event_types:
                    if not self._return_kb_event:
                        self._multi_key_storage.append(key)
                    else:
                        self._multi_key_storage.append(event)
                if key == self._esc_key:
                    # Start a timer and close if it expires, aborting the
                    # user input request
                    if not self._abort_timer.is_alive():
                        self._abort_timer.start()
            else:

                self._abort_timer.cancel()
                if not self._aborting:
                    self.item_selected.emit(self._multi_key_storage)
                self.close()

        # Ensure the timer is cancelled and reset in case the ESC is released
        # and we're not looking to return keyboard events
        if key == self._esc_key and not event.is_pressed:
            self._abort_timer.cancel()
            self._abort_timer = threading.Timer(1.0, self._abort_request)

    def _mouse_event_cb(self, event):
        self.item_selected.emit(event)
        self.close()

    def _abort_request(self):
        import time
        self._aborting = True
        if self._abort_timer.is_alive():
            self._abort_timer.cancel()
            time.sleep(0.1)


    def closeEvent(self, evt):
        """Closes the overlay window."""
        event_listener = gremlin.event_handler.EventListener()
        event_listener.keyboard_event.disconnect(self._kb_event_cb)
        if InputType.JoystickAxis in self._event_types or \
                InputType.JoystickButton in self._event_types or \
                InputType.JoystickHat in self._event_types:
            event_listener.joystick_event.disconnect(self._joy_event_cb)
        elif InputType.Mouse in self._event_types:
            event_listener.mouse_event.disconnect(self._mouse_event_cb)

        # Stop mouse hook in case it is running
        gremlin.windows_event_hook.MouseHook().stop()

        # restore highlighting
        gremlin.shared_state.pop_suspend_highlighting()
        gremlin.shared_state.pop_suspend_ui_keyinput()

        # print ("input widget close")
        super().closeEvent(evt)



    def _valid_event_types_string(self):
        """Returns a formatted string containing the valid event types.

        :return string representing the valid event types
        """
        valid_str = []
        if InputType.JoystickAxis in self._event_types:
            valid_str.append("Axis")
        if InputType.JoystickButton in self._event_types:
            valid_str.append("Button")
        if InputType.JoystickHat in self._event_types:
            valid_str.append("Hat")
        if InputType.Keyboard in self._event_types:
            valid_str.append("Key")

        return ", ".join(valid_str)


def clear_layout(layout):
    """Removes all items from the given layout.

    :param layout the layout from which to remove all items
    """
    while layout.count() > 0:
        child = layout.takeAt(0)
        if child.layout():
            clear_layout(child.layout())
        elif child.widget():
            widget = child.widget()
            if hasattr(widget,"_cleanup_ui"):
                widget._cleanup_ui()
            widget.hide()
            widget.deleteLater()
        layout.removeItem(child)

def get_layout_widgets(layout) -> list:
    ''' returns a list of layout widgets '''
    widgets = []
    while layout.count() > 0:
        child = layout.takeAt(0)
        if child.layout():
            widgets.extend(get_layout_widgets(child.layout()))
        elif child.widget():
            widgets.append(child.widget())

    return widgets



class QComboBox (QtWidgets.QComboBox):
    ''' a max limited combo box '''
    def __init__(self, parent = None):
        super().__init__(parent)

        # hack to ensure maximum items property is respected
        #self.setEditable(True) # this is so max items works
        # self.lineEdit().setFrame(False)
        # self.lineEdit().setReadOnly(True)
        self.setStyleSheet('QComboBox {combobox-popup: 0}')


        self.setMaxVisibleItems(20)

class NoWheelComboBox (QComboBox):
    ''' implements a combo box with no-wheel scrolling to avoid inadvertent switching of entries while scolling containers '''

    def __init__(self, parent = None):
        super().__init__(parent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)


    def wheelEvent(self, event) -> None:
        # blitz wheel events if the box is not in focus
        if self.hasFocus():
            return super().wheelEvent(event)

class ConfirmPushButton(QtWidgets.QPushButton):
    ''' confirmation push button '''

    confirmed = QtCore.Signal(object)

    def __init__(self, text = None, title = "Confirmation Required", prompt = "Are you sure?", show_callback = None, parent = None ) -> None:
        ''' shows a confirm dialog box on click

        :param text button text
        :param title dialog title
        :param prompt dialog body (question)
        :param show_callback boolean callback that determines if the dialog should show (return true if it should)
        '''
        super().__init__(parent)

        if text:
            self.setText(text)

        self.prompt = prompt
        self.title = title
        self.show_callback = show_callback

        self.clicked.connect(self._clicked_cb)


    def _clicked_cb(self):
        if self.show_callback is not None:
            result = self.show_callback()
            if not result:
                return

        from gremlin.util import load_pixmap
        message_box = QtWidgets.QMessageBox()
        pixmap = load_pixmap("warning.svg")
        pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        message_box.setIconPixmap(pixmap)
        message_box.setText(self.title)
        message_box.setInformativeText(self.prompt)
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
            )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self.confirmed.emit(self)

class ConfirmBox():
    def __init__(self, title = "Confirmation Required", prompt = "Are you sure?", parent = None):

        from gremlin.util import load_pixmap
        self._message_box = QtWidgets.QMessageBox(parent = parent)
        pixmap = load_pixmap("warning.svg")
        pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        self._message_box.setIconPixmap(pixmap)
        self._message_box.setText(title)
        self._message_box.setInformativeText(prompt)
        self._message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
            )
        self._message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(self._message_box)

    def show(self):
        return self._message_box.exec()

class QMessageBox(QtWidgets.QMessageBox):
    def __init__(self, width = 400, height = 100, parent = None):
        super().__init__(parent)
        self._width = width
        self._height = height

    def resizeEvent(self, event):
        self.setFixedWidth(self._width)
        self.setFixedHeight(self._height)


class MessageBox():
    def __init__(self, title = "Notice", prompt = "Operation", is_warning = True, parent = None):

        from gremlin.util import load_pixmap
        self._message_box = QMessageBox(parent = parent)

        if is_warning:
            pixmap = load_pixmap("warning.svg")
            pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
            self._message_box.setIconPixmap(pixmap)
        self._message_box.setText(title)
        self._message_box.setInformativeText(prompt)
        self._message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok
            )
        self._message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(self._message_box)
        self._message_box.exec()




class QHLine(QtWidgets.QFrame):
    ''' horizontal line '''
    def __init__(self, parent = None):
        super().__init__(parent)
        self.setContentsMargins(0,1,0,1)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)

class QWrapableLabel(QtWidgets.QLabel):
    ''' wrappable label '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setWordWrapAt(self, char):
        ''' sets the word wrap on a given character '''
        newtext = self.text().replace(char, f"{char}\u200b")
        self.setText(newtext)
        self.setWordWrap(True)


class QIconLabel(QtWidgets.QWidget):
    ''' label with an icon using the QAWESEOME lib '''

    HorizontalSpacing = 2

    def __init__(self, icon_path = None, text = None, stretch=True, use_qta = False, icon_color = None, use_wrap = True, icon_size = 16, parent = None):
        super().__init__(parent)

        if text is None:
            text = icon_path
            icon_path = None
        container_widget = QtWidgets.QWidget()
        container_widget.setContentsMargins(0, 0, 0, 0)
        container_layout = QtWidgets.QHBoxLayout(container_widget)
        container_layout.setContentsMargins(0, 0, 0, 0)

        w = get_text_width("M")*80
        container_widget.setMaximumWidth(w)

        self._icon_size = QtCore.QSize(icon_size, icon_size)
        self._icon_widget = QtWidgets.QLabel()
        if icon_path:
            self.setIcon(icon_path, use_qta, color = icon_color)

        if use_wrap:
            self._label_widget = QWrapableLabel(text)
            self._label_widget.setWordWrap(True)
        else:
            self._label_widget = QtWidgets.QLabel(text)
        container_layout.addWidget(self._label_widget)
        if stretch:
            container_layout.addStretch()

        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self._icon_widget,0,0,alignment= QtCore.Qt.AlignmentFlag.AlignTop)
        layout.addWidget(container_widget, 0, 1)
        layout.addWidget(QtWidgets.QWidget(),0,2)
        layout.setColumnStretch(2,2)

        self.setContentsMargins(0,0,0,0)



    def setIcon(self, icon_or_path = None, use_qta = True, color = None):
        ''' sets the icon of the label, pass a blank or None path to clear the icon'''
        if isinstance(icon_or_path, QtGui.QIcon):
            pixmap = icon_or_path.pixmap(self._icon_size)

        elif isinstance(icon_or_path, str):
            if use_qta:
                if color:
                    pixmap = qta.icon(icon_or_path, color=color).pixmap(self._icon_size)
                else:
                    pixmap = qta.icon(icon_or_path).pixmap(self._icon_size)
            else:
                pixmap = load_pixmap(icon_or_path) if icon_or_path else None
        else:
            pixmap = None
        if pixmap:
            pixmap = pixmap.scaled(self._icon_size, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._icon_widget.setPixmap(pixmap)
        else:
            # clear the pixmap
            self._icon_widget.setPixmap(QtGui.QPixmap())

    def setText(self, text = None):
        ''' sets the text of the label '''
        if text:
            self._label_widget.setText(text)
        else:
            self._label_widget.setText("")

    def setTextMinWidth(self, value):
        self._label_widget.setMinimumWidth(value)

    def showIcon(self):
        ''' hides the icon '''
        self._icon_widget.setVisible(True)

    def hideIcon(self):
        ''' shows the icon '''
        self._icon_widget.setVisible(False)

    def text(self):
        ''' gets the text of the widget '''
        return self._icon_widget.text()

class QDataWidget(QtWidgets.QWidget):
    ''' data widgets '''
    def __init__(self, data = None, parent = None):
        super().__init__(parent)
        self._data = data

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value


class QDataLabel(QtWidgets.QLabel):
    ''' data enabled label widget '''
    def __init__(self, data = None, parent = None):
        super().__init__(parent)
        self._data = data

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

class QDataCheckbox(QtWidgets.QCheckBox):
    ''' a checkbox that has a data property to track an object associated with the checkbox '''
    def __init__(self, text = None, data = None, parent = None):
        super().__init__(text, parent)
        self._data = data
        self._ignore_keyboard = False
        self.installEventFilter(self)

    #     foreground_color = Color.normalColor()
    #     self._icon_unchecked = load_icon("fa.circle-thin", qta_color=QtGui.QColor(foreground_color))
    #     self._icon_checked = load_icon("fa5.check-circle", qta_color=QtGui.QColor(foreground_color))

    #     self.stateChanged.connect(self._update_state)

    #     self._update_state()

    # @QtCore.Slot()
    # def _update_state(self):
    #     icon = self._icon_checked if self.isChecked() else self._icon_unchecked
    #     self.setIcon(icon)
            

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

    
    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.KeyPress and self._ignore_keyboard:
            return True
        return super().eventFilter(widget, event)

    def setIgnoreKeyboard(self, value : bool):
        self._ignore_keyboard = value

class QDataRadioButton(QtWidgets.QRadioButton):
    ''' a radio button that has a data property to track an object associated with the checkbox '''
    def __init__(self, text = None, data = None, parent = None):
        super().__init__(text, parent)
        self._data = data

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

class QDataPushButton(QtWidgets.QPushButton):
    ''' a checkbox that has a data property to track an object associated with the checkbox '''
    def __init__(self, text = None, data = None, parent = None):
        super().__init__(text, parent)
        self._data = data

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value


class QDataLineEdit(QtWidgets.QLineEdit):
    ''' a checkbox that has a data property to track an object associated with the checkbox '''
    valueChanged = QtCore.Signal() # fires when the text has changed AND we lost the focus
    lostFocus = QtCore.Signal() # fires when the input looses focus

    def __init__(self, text = None, data = None, parent = None):
        super().__init__(text, parent)
        self._data = data
        self._text_changed = True
        self.setAlignment(Qt.AlignLeft)
        #self.setStyleSheet("QLineEdit{border: #8FBC8F;}")
        super().textChanged.connect(self._text_changed_cb)


    def _text_changed_cb(self):
        self._text_changed = True


    def focusOutEvent(self, event):
        if self._text_changed:
            self.lostFocus.emit()
            self.valueChanged.emit()
        return super().focusOutEvent(event)


    def setText(self, value):
        ''' sets the text '''
        super().setText(value)
        if self.isReadOnly():
            self.home(True) # move the cursor left to left align the box in readonly mode
            self.deselect() # deselect the text selected by the home command

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value





class QDataIPLineEdit(QDataLineEdit):
    ''' IP input text box '''
    def __init__(self, text = None, data = None, parent = None):
        super().__init__(text, data, parent)
        regex = r'^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5]).){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$'
        validator = QtGui.QRegularExpressionValidator(regex)
        self.setValidator(validator)



class QDataComboBox(QComboBox):
    ''' a combo box that has a data property to track an object associated with the checkbox '''
    def __init__(self, data = None, parent = None):
        super().__init__(parent)
        self._data = data

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

class QLimitedComboBox(QDataComboBox):
    ''' a row limited combo box '''
    def __init__(self, data = None, parent = None):
        super().__init__(data, parent)
        self.setMaxVisibleItems(20)
        self.setStyleSheet("QComboBox { combobox-popup: 0; }")

class QHatSelectorComboBox(QDataComboBox):
    ''' a combo box for hat directions '''

    valueChanged = QtCore.Signal(HatDirection) # fires when a value is selected 

    def __init__(self, data = None, parent = None):

        super().__init__(data, parent)

        self._direction = HatDirection.Center
        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""

        for position in HatDirection:
            match position:
                case HatDirection.Center:
                    png = f"{prefix}hat_ctr.png"
                case HatDirection.North:
                    png = f"{prefix}hat_n.png"
                case HatDirection.NorthEast:
                    png = f"{prefix}hat_ne.png"
                case HatDirection.NorthWest:
                    png = f"{prefix}hat_nw.png"
                case HatDirection.East:
                    png = f"{prefix}hat_e.png"
                case HatDirection.South:
                    png = f"{prefix}hat_s.png"
                case HatDirection.SouthEast:
                    png = f"{prefix}hat_se.png"
                case HatDirection.SouthWest:
                    png = f"{prefix}hat_sw.png"      
                case HatDirection.West:
                    png = f"{prefix}hat_w.png"  
            icon = load_icon(png)   
            #icon_active = load_icon(png_active)        
            self.addItem(icon, HatDirection.to_display_name(position), HatDirection.to_enum(position))
            
        self.currentIndexChanged.connect(self._update_value)

    @property
    def direction(self) -> str:
        ''' direction selected '''
        return self.currentData(self.currentIndex())
    
    @property
    def value(self):
        ''' direction as a tuple '''
        direction = HatDirection.to_enum(self.currentData(self.currentIndex()))
        return direction.value
    
    def setValue(self, value, emit = False):
        ''' sets the value as a tuple '''
        with QtCore.QSignalBlocker(self):
            if isinstance(value, tuple):
                value = HatDirection(value)
            elif isinstance(value, str):
                value = HatDirection.to_enum(value)
            index = self.findData(value)
            if index != -1:
                self.setCurrentIndex(index)
        if emit:
            self._update_value()

    @QtCore.Slot()
    def _update_value(self):
        ''' index changed '''
        self.valueChanged.emit(self.currentData())



class QPathLineItem(QtWidgets.QWidget):
    ''' An editable text input line with a file selector button '''

    open = QtCore.Signal(object) # event that fires when the open button is clicked, and passes the control
    pathChanged = QtCore.Signal(object, str) # fires when the line item changes

    IconSize = QtCore.QSize(16, 16)

    def __init__(self, header = None, text = None, data = None, dir_mode = False, parent = None, open_tooltip_text = "Browse"):
        '''
        displays the path to a file or a folder
        :param: header - the header text
        :param: text - the default content
        :data: optional data parameters
        :dir_mode: true if the entry is a folder, false if it's a file

        '''
        super().__init__(parent)

        self._text = text
        self._header = header
        self._dir_mode = dir_mode


        self._file_widget = QtWidgets.QLineEdit()
        self._file_widget.installEventFilter(self)
        self._file_widget.returnPressed.connect(self._open_button_cb) # open the dialog on enter
        self._file_widget.setText(text)
        self._file_widget.textChanged.connect(self._file_changed)
        self._open_button = QtWidgets.QPushButton("...")
        self._open_button.setMaximumWidth(20)
        self._open_button.clicked.connect(self._open_button_cb)
        if open_tooltip_text:
            self._open_button.setToolTip(open_tooltip_text)
        self._icon_widget = QtWidgets.QLabel()
        self._icon_widget.setMaximumWidth(20)
        self._layout = QtWidgets.QHBoxLayout()

        if header:
            self._header_widget = QtWidgets.QLabel(header)
            self._layout.addWidget(self._header_widget)

        self._layout.addWidget(self._icon_widget)
        self._layout.addWidget(self._file_widget)
        self._layout.addWidget(self._open_button)
        self._layout.setContentsMargins(0,0,0,0)

        self._data = data

        self._file_changed()
        

        self.setLayout(self._layout)

    @property
    def header_width(self):
        return self._header_widget.frameGeometry().width()

    @header_width.setter
    def header_width(self, value):
        self._header_widget.setMaximumWidth(value)
        self._header_widget.setMinimumWidth(value)

    def _open_button_cb(self):
        self.open.emit(self)

    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.FocusOut:
            new_text = self._file_widget.text()
            if self._text != new_text:
                self._text = new_text
                self.pathChanged.emit(self, self._text)
        return super().eventFilter(widget, event)

    def _setIcon(self, icon_path = None, use_qta = True, color = None):
        ''' sets the icon of the label, pass a blank or None path to clear the icon'''
        if icon_path:
            if use_qta:
                if color:
                    pixmap = qta.icon(icon_path, color=color).pixmap(self.IconSize)
                else:
                    pixmap = qta.icon(icon_path).pixmap(self.IconSize)
            else:
                pixmap = load_pixmap(icon_path) if icon_path else None
        else:
            pixmap = None
        if pixmap:
            pixmap = pixmap.scaled(QPathLineItem.IconSize, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._icon_widget.setPixmap(pixmap)
        else:
            # clear the pixmap
            self._icon_widget.setPixmap(QtGui.QPixmap())

    def setText(self, text = None):
        ''' sets the text of the label '''
        with QtCore.QSignalBlocker(self._file_widget):
            if text:
                self._text = text
                self._file_widget.setText(text)
            else:
                self._text = ""
                self._file_widget.setText("")
        self._file_changed()


    def text(self):
        return self._text

    def showIcon(self):
        ''' hides the icon '''
        self._icon_widget.setVisible(True)

    def hideIcon(self):
        ''' shows the icon '''
        self._icon_widget.setVisible(False)


    def _file_changed(self):
        fname = self._file_widget.text()

        valid = os.path.isdir(fname) if self._dir_mode else os.path.isfile(fname)
        if valid:
            self._setIcon("fa.check", color= Color.activeColor())
        else:
            self._setIcon("fa.exclamation-circle", color = Color.warningColor())
        self._text = fname
        self.pathChanged.emit(self, self._text)

    @property
    def valid(self):
        ''' true if the file exists '''
        return os.path.isfile(self._text)

    @property
    def data(self):
        ''' object reference for this widget '''
        return self._data

    @data.setter
    def data(self, value):
        self._data = value


class ButtonStateWidget(QtWidgets.QWidget):
    ''' visualizes the state of a button '''

    deleted = QtCore.Signal() # triggers on delete

    def __init__(self, parent = None):
        super().__init__(parent)


        self.setContentsMargins(0,0,0,0)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0,0,0,0)

        self._icon_size = QtCore.QSize(16,16)
        self._device_guid = None
        self._input_id = None
        self._input_type = None
        self._button_widget = QtWidgets.QLabel()
        self._button_widget.setContentsMargins(0,0,0,0)
        on_icon = load_icon("mdi.checkbox-blank-circle",use_qta=True,qta_color=Color.activeColor())
        self._on_pixmap = on_icon.pixmap(self._icon_size)
        off_icon = load_icon("mdi.checkbox-blank-circle",use_qta=True,qta_color=Color.inactiveColor())
        self._off_pixmap = off_icon.pixmap(self._icon_size)
        height = self._icon_size.height()+2
        self._button_widget.setMinimumHeight(height)
        self._button_widget.setMaximumHeight(height)
        self._button_widget.setStyleSheet("")

        self._hat_icons = {} # icon hats, keyed by position
        
        self.main_layout.addWidget(self._button_widget)

        self._handler_connected = False
        el = gremlin.event_handler.EventListener()
        el.tab_selected.connect(self._tab_selected)
        el.tab_unselected.connect(self._tab_unselected)
        
        

    def _cleanup_ui(self):
        self.unhookDevice()
        self.deleted.emit()


    def hookDevice(self, device_guid, input_type, input_id):
        ''' hooks the input  '''
        import gremlin.joystick_handling
        self._device_guid = device_guid
        self._input_id = input_id
        self._input_type = input_type
        self.updateState()
        self._tab_selected(device_guid)
        
    def updateState(self):
        ''' updates the widget state with the cached state  '''
        tracker = StateTracker()
        state = tracker._get_state(self._device_guid, self._input_type, self._input_id)
        if state:
            self._update_value(state)

    def unhookDevice(self):
        self._tab_unselected(self._device_guid)
        
 

    @QtCore.Slot(str)
    def _tab_selected(self, device_guid):
        ''' triggered when a tab is selected 
        
        :param device_guid: the device selected
        
        '''        
        if self._handler_connected:
            # already connected
            return
        if self._device_guid:
            # syslog = logging.getLogger("system")
            device_name = gremlin.shared_state.get_device_name(device_guid)
            if isinstance(device_guid, str):
                device_guid = gremlin.util.parse_guid(device_guid)
            #el = gremlin.event_handler.EventListener()
            if self._device_guid == device_guid:
                # connect the handler
                #input_id = self._input_id
                #syslog.info(f"ButtonState: {device_name} type {InputType.to_display_name(self._input_type)} input {self._input_id} connect")
                _state_tracker.registerButtonState(self, self._device_guid, self._input_type, self._input_id)
                self._handler_connected = True


    @property
    def enabled(self) -> bool:
        return self._handler_connected
    
    @property
    def input_id(self) -> object:
        return self._input_id
    @property
    def device_guid(self) -> str:
        return self._device_guid
    @property
    def input_type(self) -> InputType:
        return self._input_type


    
    @QtCore.Slot(str)
    def _tab_unselected(self, device_guid):
        ''' triggered when a device tab is deselected, also used to force a disconnect
         
        :param device_guid: the device to deselect - if None - deselect all
          
        '''
        if not self._handler_connected:
            # not connected
            return 
        # # syslog = logging.getLogger("system")
        # el = gremlin.event_handler.EventListener()
        if device_guid:
            if isinstance(device_guid, str):
                device_guid = gremlin.util.parse_guid(device_guid)
            disconnect = self._device_guid == device_guid
            #device_name = gremlin.shared_state.get_device_name(device_guid)
        else:
            disconnect = True
            #device_name = 'reset'
            
        if disconnect:
            #input_id = self._input_id
            # syslog.info(f"ButtonState: (unselect) {device_name} button {input_id} disconnect")
            _state_tracker.unregisterButtonState(self._device_guid, self._input_type, self._input_id)
            self._handler_connected = False


    def _update_value(self, is_pressed):
        ''' updates a button position '''
        if is_pressed:
            self._button_widget.setPixmap(self._on_pixmap)
            # syslog.info(f"button {self.input_id} pressed")
            # self._button_widget.update()
            #self._button_widget.setText("pressed")
        else:
            self._button_widget.setPixmap(self._off_pixmap)
            # syslog.info(f"button {self.input_id} released")
            # self._button_widget.update()
            #self._button_widget.setText(" ")

    def _update_hat(self, position):
        ''' updates a hat position '''
        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
        if not isinstance(position,tuple):
            # convert from value to position tuple
            import vjoy.vjoy
            position =  vjoy.vjoy.Hat.to_continuous_position[position]
        position = HatDirection.to_enum(position) 
        
        if not position in self._hat_icons:
            match position:
                case HatDirection.Center:
                    png = "hat_ctr_inactive.png"
                    png_active = "hat_ctr_active.png"
                case HatDirection.North:
                    png = f"{prefix}hat_n.png"
                    png_active = "hat_n_active.png"
                case HatDirection.NorthEast:
                    png = f"{prefix}hat_ne.png"
                    png_active = "hat_ne_active.png"
                case HatDirection.NorthWest:
                    png = f"{prefix}hat_nw.png"
                    png_active = "hat_nw_active.png"
                case HatDirection.East:
                    png = f"{prefix}hat_e.png"
                    png_active = "hat_e_active.png"
                case HatDirection.South:
                    png = f"{prefix}hat_s.png"
                    png_active = "hat_s_active.png"
                case HatDirection.SouthEast:
                    png = f"{prefix}hat_se.png"
                    png_active = "hat_se_active.png"
                case HatDirection.SouthWest:
                    png = f"{prefix}hat_sw.png"      
                    png_active = "hat_sw_active.png"
                case HatDirection.West:
                    png = f"{prefix}hat_w.png"  
                    png_active = "hat_w_active.png"
            on_pixmap = load_icon(png_active).pixmap(self._icon_size)
            off_pixmap = load_icon(png).pixmap(self._icon_size)
            self._hat_icons[position] = (off_pixmap, on_pixmap)

        off_pixmap, on_pixmap = self._hat_icons[position]
        if position != HatDirection.Center:
            self._button_widget.setPixmap(on_pixmap)
        else:
            self._button_widget.setPixmap(off_pixmap)


    def setValue(self, is_pressed):
        ''' value '''
        self._update_value(is_pressed)




_widget_cache = []

class AxisStateWidget(QtWidgets.QWidget):

    """Visualizes the current state of an axis."""



    #css_vertical = r"QProgressBar::chunk {background: QLinearGradient( x1: 0, y1: 0, x2: 1, y2: 0,stop: 0 #78d,stop: 0.4999 #46a,stop: 0.5 #45a,stop: 1 #238 ); border-radius: 7px; border: 1px solid black;}"
    css_vertical = r"QProgressBar::chunk {background: QLinearGradient( x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #69e060, stop: 1 #1f8c33 ); border-radius: 7px; border: 1px solid black;}"
    #css_horizontal = r"QProgressBar::chunk {background: QLinearGradient( x1: 0, y1: 0, x2: 0, y2: 1,stop: 0 #78d,stop: 0.4999 #46a,stop: 0.5 #45a,stop: 1 #238 ); border-radius: 7px; border: 1px solid black;}"
    #css_horizontal = r"QProgressBar::chunk {background: QLinearGradient( x1: 0, y1: 0, x2: 0, y2: 1,stop: 0 #77a ,stop: 0.4999 #477,stop: 0.5 #45a,stop: 1 #238 ); border-radius: 7px; border: 1px solid black;}"
    css_horizontal = r"QProgressBar::chunk {background: QLinearGradient( x1: 0, y1: 0, x2: 1, y2: 0,stop: 0 #69e060 stop: 1 #1f8c33 ); border-radius: 7px; border: 1px solid black;}"

    valueChanged = QtCore.Signal(float, float) # (input_value, curved_value)
    deleted = QtCore.Signal(object) # indicates the item is being deleted

    def __init__(self, axis_id = None, show_percentage = True, show_value = True, show_label = True, show_curve = True, orientation = QtCore.Qt.Orientation.Vertical, parent=None):
        """Creates a new instance.

        :param axis_id id of the axis, used in the label
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._joystick_hooked = False # true if joystick input is directly hooked to this widget 
        self._scale_factor = 1000
        self.main_layout = QtWidgets.QVBoxLayout(self)

        if orientation == QtCore.Qt.Orientation.Vertical:
            self.container_layout = QtWidgets.QGridLayout()
        else:
            self.container_layout = QtWidgets.QHBoxLayout()
            
        self.setContentsMargins(0,0,0,0)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.container_layout.setSpacing(0)
        self.container_layout.setContentsMargins(0,0,0,0)
       
        
        self._data = None

        self._progress_widget = QtWidgets.QProgressBar()



        self._orientation = orientation
        self._show_percentage = show_percentage
        self._show_value = show_value
        self._show_label = show_label
        self._show_curved = show_curve


        self._display_value_widget = QtWidgets.QLabel()
        self._display_percent_widget = QtWidgets.QLabel()
        self._display_curve_widget = QtWidgets.QLabel()
        self._display_label_widget = QtWidgets.QLabel()

        widget_list = [self._display_label_widget,
                       self._display_value_widget,
                       self._display_percent_widget,
                       self._display_curve_widget,
                       ]

        if orientation == QtCore.Qt.Orientation.Vertical:
            widget, layout = getVContainer(widget_list)
        else:
            widget, layout = getHContainer(widget_list)
        
        self._readout_widget = widget
        self._readout_layout = layout

        

        
        
        if axis_id:
            self.setLabel(f"Axis {axis_id}")


        if orientation == QtCore.Qt.Orientation.Vertical:
            self.container_layout.addWidget(self._display_label_widget,0,0, alignment=QtCore.Qt.AlignCenter)
            self.container_layout.addWidget(self._progress_widget,1,0, alignment=QtCore.Qt.AlignCenter)
            self.container_layout.addWidget(self._readout_widget,2,0, alignment=QtCore.Qt.AlignCenter)
            
        else:
            self.container_layout.addWidget(self._display_label_widget)
            self.container_layout.addWidget(self._progress_widget)
            self.container_layout.addWidget(self._readout_widget)

        self._min_range = -1.0
        self._max_range = 1.0
        self._device_guid = None
        self._input_id = None
        self._value = 0
        self._raw_value = 0
        self._reverse = False
        self._decimals = 3
        self._is_hardware_input = False # true if the device is a hardware device, set in HookDevice()
        self._handler_connected = False # not connected

        self._width = 10
        self._update_css()
        self._update_range()

        # hook tab events
        el = gremlin.event_handler.EventListener()
        el.tab_selected.connect(self._tab_selected)
        el.tab_unselected.connect(self._tab_unselected)

        if orientation == QtCore.Qt.Orientation.Horizontal:
            self.container_layout.addStretch()
            
        self._progress_widget.setContentsMargins(0,0,0,0)
        self._progress_widget.setOrientation(orientation)
        self._progress_widget.setTextVisible(False)

        self.main_layout.addLayout(self.container_layout)

        el = gremlin.event_handler.EventListener()
        el.ui_ready.connect(self._ui_ready)
        
    @QtCore.Slot()
    def _ui_ready(self):
        ''' fires when the UI is ready '''
        self._setValue(self._value, self._curve_value)

    def _cleanup_ui(self):
        ''' item is being deleted '''
        self.unhookDevice()
        self.deleted.emit(self)

    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self._data = value        

    @property
    def show_curved(self) -> bool:
        ''' true if repeater shows curved data '''
        return self._show_curved
    @show_curved.setter
    def show_curved(self, value: bool):
        if value != self._show_curved:
            self._show_curved = value
            self._setValue(self._value, self._curve_value)

    @property
    def input_id(self) -> object:
        return self._input_id
    @property
    def device_guid(self) -> str:
        return self._device_guid
    @property
    def input_type(self) -> InputType:
        return self._input_type



    def _create_primitives(self):
        self._marker = [
            QtCore.QPoint(0,0),
            QtCore.QPoint(-10,-5),
            QtCore.QPoint(-5,10)
        ]

    def _update_visible(self):
        ''' updates visible state for data label'''
        if gremlin.shared_state.ui_ready and self.parent() is not None:
            self._display_value_widget.setVisible(self._show_value)
            self._display_percent_widget.setVisible(self._show_percentage)
            self._display_curve_widget.setVisible(self._show_curved)
            self._display_label_widget.setVisible(self._show_label)
            visible = self._show_label or self._show_percentage or self._show_value or self._show_curved
            self._readout_widget.setVisible(visible)

    def setPercentageVisible(self, value: bool):
        ''' shows or hides the percentage value on the axis '''
        self._show_percentage = value
        self._update_visible()

    def setValueVisible(self, value: bool):
        self._show_value = value
        self._update_visible()

    def _update_css(self):
        if self._orientation == QtCore.Qt.Orientation.Vertical:
            css = AxisStateWidget.css_vertical + f";width {self._width}px"
            self._progress_widget.setMaximumWidth(self._width)

        elif self._orientation == QtCore.Qt.Orientation.Horizontal:
            css = AxisStateWidget.css_horizontal+ f";height {self._width}px"
            self._progress_widget.setMaximumHeight(self._width)

        self._progress_widget.setStyleSheet(css)

    def setLabel(self, value : str):
        ''' sets the label for the axis '''
        self._display_label_widget.setText(value)

    def setLabelVisible(self, value: bool):
        self._show_label = value
        self._display_label_widget.setVisible(value)
        self._update_visible()

    def setWidth(self, value):
        if value > 0:
            self._width = value
            self._update_css()

    def value(self):
        return self._value

    def setValue(self, value, curve_value = None, percent_value = None, other_value = None):
        """Sets the value shown by the widget.
        :param value new value to show
        """
        assert not self._joystick_hooked,"Cannot set value on a hooked input"
        self._setValue(value, curve_value, percent_value, other_value)

    def _setValue(self, value, curve_value = None, percent_value = None, other_value = None):
        ''' internal set value '''
        try:
            if value < self._min_range:
                value = self._min_range
            if value > self._max_range:
                value = self._max_range
            value += 0   # avoid negative 0 (WHY?)
            self._value = value

            if curve_value is not None:
                # eh = gremlin.event_handler.EventListener()
                # curve_value = eh._apply_curve_ex(self._device_guid, self._input_id, value)
                self._curve_value = curve_value
                display_value = curve_value
            else:
                display_value = value
                self._curve_value = value


            if self._reverse:
                display_value = gremlin.util.scale_to_range(display_value, invert=True)

            if value is None:
                display_value = None
            else:
                scaled_value = self._scale_factor * display_value
                

            self._progress_widget.setValue(scaled_value)
            self._progress_widget.update()

            self._update_visible()
            if self._readout_widget.isVisible():
                if self._show_value and display_value is not None:
                    self._display_value_widget.setText(f"{display_value:+0.3f}")
                if self._show_curved and curve_value is not None:
                    self._display_curve_widget.setText(f"C{curve_value:+0.3f}")
                if self._show_percentage:
                    if percent_value is None:
                        if curve_value is None:
                            percent = gremlin.util.scale_to_range(display_value, target_min=0, target_max = 100)
                        else:
                            percent = gremlin.util.scale_to_range(curve_value, target_min=0, target_max = 100)
                    else:
                        percent = percent_value
                    self._display_percent_widget.setText(f"{percent:0.1f} %")

            self.valueChanged.emit(self._value, self._curve_value)
        except:
            pass # C++ QT exception because of sync issues with Python/QT

    def value(self):
        ''' gets the current value '''
        return self._value

    def setRange(self, min = -1.0, max = 1.0, decimals = 3):
        ''' sets the range of the widget '''
        if min > max:
            max, min = min, max
        self._min_range = min
        self._max_range = max
        self._decimals = decimals
        self._update_range()

    def _update_range(self):
        self._progress_widget.setRange(
            self._scale_factor * self._min_range,
            self._scale_factor * self._max_range
        )
        self._setValue(self._value)

    def setMaximum(self, value):
        ''' sets the upper range value '''
        self.setRange(self._min_range, value)

    def setMinimum(self, value):
        ''' sets the lower range value'''
        self.setRange(value, self._max_range)

    def setReverse(self, value):
        self._reverse = value
        self._setValue(self._value)

    def reverse(self):
        ''' reverse flag '''
        return self._reverse

    def hookDevice(self, device_guid, input_type, input_id):
        ''' hooks an axis (manual)'''
        import gremlin.joystick_handling
        import gremlin.event_handler
        if device_guid is None: 
            # not a valid device to hook
            return
  
        self._device_guid = device_guid
        self._input_id = input_id
        self._input_type = input_type
        self._scale_factor = 1000
        self._value = -1
        self.setRange(-1, 1)
        
        
        self._is_hardware_input = gremlin.joystick_handling.is_hardware_device(device_guid)
        if self._input_type in (InputType.OpenSoundControl, InputType.Midi):
            self._value = input_id.axis_value
        elif self._is_hardware_input:
            self._value = gremlin.joystick_handling.get_axis(device_guid, input_id)
            el = gremlin.event_handler.EventListener()
            el.joystick_event.connect(self._joystick_event)
            el.profile_start.connect(self._profile_start)
            el.profile_stop.connect(self._profile_stop)
            self._joystick_hooked = True
        self._update_value(self._value)

        self._handler_connected = False
        
        #self._tab_selected(device_guid)

    @QtCore.Slot()
    def _profile_start(self):
        # de-attach when profile stops
        if self._joystick_hooked:
            el = gremlin.event_handler.EventListener()
            el.joystick_event.disconnect(self._joystick_event)
            
    
    @QtCore.Slot()
    def _profile_stop(self):
        # re-attach when profile stops
        if self._joystick_hooked:
            el = gremlin.event_handler.EventListener()
            el.joystick_event.connect(self._joystick_event)
            self._value = gremlin.joystick_handling.get_axis(self._device_guid, self._input_id)



    @QtCore.Slot(object)
    def _joystick_event(self, event):
        if gremlin.shared_state.is_running:
            # do not update while profile is running
            return
        if self._device_guid is None:
            return 
        if not event.is_axis:
            return 
        if self._device_guid != event.device_guid:
            return
        if self._input_type != event.event_type:
            return
        if self._input_id != event.identifier:
            return
        self._update_value(event.value)

    def unhookDevice(self):
        import gremlin.event_handler
        if self._joystick_hooked:
            el = gremlin.event_handler.EventListener()
            el.joystick_event.disconnect(self._joystick_event)
        self._tab_unselected(self._device_guid)
        self._device_guid = None
        

    @property
    def enabled(self) -> bool:
        return self._handler_connected        

    @QtCore.Slot(str)
    def _tab_selected(self, device_guid):
        ''' triggered when a tab is selected 
        
        :param device_guid: the device selected
        
        '''
        if self._handler_connected:
            # already connected
            return
        
        device_name = gremlin.shared_state.get_device_name(device_guid)
        if isinstance(device_guid, str):
            device_guid = gremlin.util.parse_guid(device_guid)
        
        if self._device_guid == device_guid:
            # connect the handler
            input_id = self._input_id
            verbose = gremlin.config.Configuration().verbose_mode_inputs
            if verbose: 
                # syslog = logging.getLogger("system")
                syslog.info(f"AxisState: {device_name} axis {str(input_id)} connect")
            _state_tracker.registerAxisState(self, self._device_guid, self._input_type, self._input_id)
            self._handler_connected = True


    
    @QtCore.Slot(str)
    def _tab_unselected(self, device_guid):
        ''' triggered when a device tab is deselected, also used to force a disconnect
         
        :param device_guid: the device to deselect - if None - deselect all
          
        '''
        if not self._handler_connected:
            # not connected 
            return
        # syslog = logging.getLogger("system")
        el = gremlin.event_handler.EventListener()
        if device_guid:
            if isinstance(device_guid, str):
                device_guid = gremlin.util.parse_guid(device_guid)
            disconnect = self._device_guid == device_guid
            device_name = gremlin.shared_state.get_device_name(device_guid)
        else:
            disconnect = True
            device_name = "reset"
            
        if disconnect:
            # disconnect the handler
            input_id = self._input_id
            # syslog.info(f"AxisState: (unselect) {device_name} axis {input_id} disconnect")
            _state_tracker.unregisterAxisState(self._device_guid, self._input_type, self._input_id)
            self._handler_connected = False
        


    def _update_value(self, value):
        # invert the input if needed
        if self._is_hardware_input:
            #eh = gremlin.event_handler.EventListener()
            # value = eh._apply_calibration_ex(self._device_guid, self._input_id, raw_value)
            # curve_value = eh._apply_curve_ex(self._device_guid, self._input_id, value)
            #print (f"raw: {raw_value:0.3f} calibrated: {value:0.3f} curved: {curve_value:0.3f}")
            #self.setValue(value, curve_value)
            self._setValue(value)
        else:
            self._setValue(value)
            #self.setValue(raw_value)




class AxesCurrentState(QtWidgets.QGroupBox):

    """Displays the current state of all axes on a device (input viewer)"""

    def __init__(self, device : DeviceSummary, parent=None):
        """Creates a new instance.

        :param device the device of which to display the axes sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.device = device
        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Axes")
        else:
            self.setTitle(f"{device.name} - Axes")

        self.axes = {}
        self.value_labels = {}
        self.percent_labels = {}
        self.index_map = {}
        axes_layout = QtWidgets.QGridLayout()
        axes_layout.setSpacing(0)
        axis_list = device.axis_index_list() 

        for i in range(8): 
            index = i + 1
            
            widget,layout = getVContainer()
            # widget.setStyleSheet("border: 1px solid;")
            widget.setFixedWidth(80)
            if index in axis_list:
                axis_id = gremlin.joystick_handling.linear_axis_index(self.device.axis_map,index)
                self.index_map[axis_id] = index
                axis = AxisStateWidget(index, show_value = False, show_label=False, show_percentage=False)
                value = gremlin.joystick_handling.get_axis(device.device_guid, index)
                #print (f"Axis {axis_id} value: {value:0.3f}")
                value_label = QtWidgets.QLabel(f"{value:+0.3f}")
                #axis.setValue(value)
                self.axes[index] = axis
                self.value_labels[index] = value_label
                percent = gremlin.util.scale_to_range(value,target_min=0, target_max=100)
                value_label = QtWidgets.QLabel(f"{value:+0.3f}")
                percent_label = QtWidgets.QLabel(f"{percent:0.1f} %")
                self.percent_labels[index] = percent_label
                axis.setValue(value)
                layout.addWidget(axis)
            else:
                value_label = QtWidgets.QLabel(" ")
                percent_label = QtWidgets.QLabel(" ")
                
            axes_layout.addWidget(widget, 0, i, alignment=QtCore.Qt.AlignCenter)
            axes_layout.addWidget(value_label, 1, i, alignment=QtCore.Qt.AlignCenter)
            axes_layout.addWidget(percent_label, 2, i, alignment=QtCore.Qt.AlignCenter)

        #axes_layout.addStretch()
        axes_layout.setColumnStretch(i+1,2)
        self.setLayout(axes_layout)

    def process_event(self, event):
        """Updates state visualization based on the given event.

        :param event the event with which to update the state display
        """
        if event.event_type == InputType.JoystickAxis:
            axis_id = gremlin.joystick_handling.linear_axis_index(
                self.device.axis_map,
                event.identifier
            )
            index = self.index_map[axis_id]
            value = event.value
            self.axes[index].setValue(value)
            self.value_labels[index].setText(f"{value:+0.3f}")
            percent = gremlin.util.scale_to_range(value,target_min=0, target_max=100)
            self.percent_labels[index].setText(f"{percent:0.1f} %")


class HatWidget(QtWidgets.QWidget):

    """Widget visualizing the state of a hat."""

    # Polygon path for a triangle
    triangle = QtGui.QPolygon(
        [QtCore.QPoint(-10, 0), QtCore.QPoint(10, 0), QtCore.QPoint(0, 15)]
    )

    # Mapping from event values to rotation angles
    lookup = {
        (0, 0): -1,
        (0, 1): 180,
        (1, 1): 225,
        (1, 0): 270,
        (1, -1): 315,
        (0, -1): 0,
        (-1, -1): 45,
        (-1, 0): 90,
        (-1, 1): 135
    }

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.angle = -1

    def minimumSizeHint(self):
        """Returns the minimum size of the widget.

        :return the widget's minimum size
        """
        return QtCore.QSize(120, 120)

    def set_angle(self, state):
        """Sets the current direction of the hat.

        :param state the direction of the hat
        """
        self.angle = HatWidget.lookup.get(state, -1)
        self.update()

    def paintEvent(self, event):
        """Draws the entire hat state visualization.

        :param event the paint event
        """
        # Define pens and brushes

        active_color = Color.activeColor()
        border_color = Color.borderColor()
        inactive_color = Color.inactiveColor()
        
        normal_color = Color.normalColor()

        # pen_default = QtGui.QPen(QtGui.QColor("#8f8f91"))
        # pen_default.setWidth(2)
        # pen_active = QtGui.QPen(QtGui.QColor("#1f8c33"))
        # pen_active.setWidth(2)
        # brush_default = QtGui.QBrush(QtGui.QColor("#f6f7fa"))
        # brush_active = QtGui.QBrush(QtGui.QColor("#69e060"))

        pen_default = QtGui.QPen(QtGui.QColor(normal_color))
        pen_default.setWidth(2)
        pen_active = QtGui.QPen(QtGui.QColor(active_color))
        pen_active.setWidth(2)
        brush_default = QtGui.QBrush(QtGui.QColor(inactive_color))
        brush_active = QtGui.QBrush(QtGui.QColor(active_color))

        # Prepare painter instance
        p = QtGui.QPainter(self)
        # p.begin(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        p.setPen(pen_default)
        p.setBrush(brush_default)

        p.translate(50, 50)

        # Center dot
        if self.angle == -1:
            p.setBrush(brush_active)
        p.drawEllipse(-8, -8, 16, 16)
        p.setBrush(brush_default)
        # Directions
        for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
            p.save()
            p.rotate(angle)
            p.translate(0, 35)

            if angle == self.angle:
                p.setBrush(brush_active)
                p.setPen(pen_active)

            p.drawPolygon(HatWidget.triangle)
            p.restore()


        p.end()

class HatState(QtWidgets.QGroupBox):

    """Visualizes the sate of a device's hats."""

    def __init__(self, device, parent=None):
        """Creates a new instance.

        :param device the device of which to display the hat sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._event_times = {}

        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Hats")
        else:
            self.setTitle(f"{device.name} - Hats")

        self.hats = [None]
        hat_layout = QtWidgets.QGridLayout()
        for i in range(device.hat_count):
            hat = HatWidget()
            self.hats.append(hat)
            hat_layout.addWidget(hat, int(i / 2), int(i % 2))

        self.setLayout(hat_layout)

    def process_event(self, event):
        """Updates state visualization based on the given event.

        :param event the event with which to update the state display
        """
        if event.event_type == InputType.JoystickHat:
            self.hats[event.identifier].set_angle(event.value)
            self._event_times[event.identifier] = time.time()


class AxesTimeline(QtWidgets.QGroupBox):

    """Visualizes axes state as a timeline."""

    def __init__(self, device, parent=None):
        """Creates a new instance.

        :param device the device of which to display the axes sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Axes")
        else:
            self.setTitle(f"{device.name} - Axes")

        self.setLayout(QtWidgets.QVBoxLayout())
        self.plot_widget = TimeLinePlotWidget()
        self.legend_layout = QtWidgets.QHBoxLayout()
        self.legend_layout.addStretch()
        colors = Color.PenColors()
        for i in range(device.axis_count):
            index = device.axis_map[i].axis_index
            label = QtWidgets.QLabel(f"Axis {index:d}")
            css = f"QLabel {{ color: {colors.get(index,"#000000")}; font-weight: bold }}"
            label.setStyleSheet(css)
            self.legend_layout.addWidget(label)
        self.layout().addWidget(self.plot_widget)
        self.layout().addLayout(self.legend_layout)

    def add_point(self, value, series_id):
        """Adds a new point to the timline.

        :param value the value to add
        :param series_id id of the axes to which to add the value
        """
        self.plot_widget.add_point(value, series_id)






class TimeLinePlotWidget(QtWidgets.QWidget):

    """Visualizes temporal data as a line graph."""



    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._background_color = Color.actionBackgroundColor()

        self._render_flags = QtGui.QPainter.Antialiasing |  QtGui.QPainter.SmoothPixmapTransform

        # Plotting canvas
        self._pens = Color.Pens()
        self._pixmap = QtGui.QPixmap(1000, 200)
        self._pixmap.fill()
        self._rect = QtCore.QRect(0,0,1000,200)
        self._background_qcolor = QtGui.QColor(self._background_color)
        self._background_brush = QtGui.QBrush(self._background_qcolor)

        # Grid drawing variables
        self._horizontal_steps = 0
        self._vertical_timestep = time.time()

        # Last recorded value for a data series
        self._series = {}

        # Step size per update
        self._step_size = 1

        interval = int(1000/60)

        # Update the plot
        self._update_timer = QtCore.QTimer(self)
        self._update_timer.timeout.connect(self._update_pixmap)
        self._update_timer.start(interval)

        # Redrawing of the widget
        self._repaint_timer = QtCore.QTimer(self)
        self._repaint_timer.timeout.connect(self.update)
        self._repaint_timer.start(interval)

    def resizeEvent(self, event):
        """Handles resizing this widget.

        :param event the resize event
        """
        self._pixmap = QtGui.QPixmap(event.size())
        self._pixmap.fill(self._background_qcolor)
        self._horizontal_steps = 0
        self._vertical_timestep = time.time()

    def minimumSizeHint(self):
        """Returns the minimum size of this widget.

        :return the widget's minimum size
        """
        return QtCore.QSize(400, 150)

    def paintEvent(self, event):
        """Refreshes the timeline view.

        :param event the paint event
        """
        p = QtGui.QPainter(self)
        
        
        p.drawPixmap(0, 0, self._pixmap)
        p.end()




    def add_point(self, value, series_id=0):
        """Adds a data point to a time series.

        :param value the value to add
        :param series_id the series to which to add the value
        """
        if series_id not in self._series:
            self._series[series_id] = [value, value]
        self._series[series_id][1] = value

    def _update_pixmap(self):
        """Updates the pixmap that contains the moving timeline."""
        p = QtGui.QPainter(self._pixmap)
        p.setBackground(QtGui.QBrush(QtGui.QColor(self._background_color)))
        

        # p.begin(self)
        p.setRenderHint(self._render_flags)

        self._pixmap.scroll(-self._step_size, 0, QtCore.QRect(0, 0, self._pixmap.width(), self._pixmap.height())
        )
        p.eraseRect(self._pixmap.width() - self._step_size, 0, 1,self._pixmap.height())

        # Draw vertical line in one second intervals
        p.setPen(self._pens[0])
        if self._vertical_timestep < time.time()-1:
            p.drawLine(
                self._pixmap.width()-1,
                0,
                self._pixmap.width() - 1,
                self._pixmap.height()
            )
            self._vertical_timestep = time.time()
        self._horizontal_steps += 1
        if self._horizontal_steps <= 5:
            quarter = int(self._pixmap.height() / 4)
            x = self._pixmap.width()-1
            p.drawPoint(x, quarter)
            p.drawPoint(x, 2*quarter)
            p.drawPoint(x, 3*quarter)
        elif self._horizontal_steps > 10:
            self._horizontal_steps = 0

        # Draw onto the pixmap all series data that has been accumulated
        for key, value in self._series.items():
            p.setPen(self._pens[key])
            p.drawLine(
                self._pixmap.width()-self._step_size-1,
                int(2 + (self._pixmap.height()-4) * (value[0] + 1) / 2.0),
                self._pixmap.width()-1,
                int(2 + (self._pixmap.height()-4) * (value[1] + 1) / 2.0)
            )
            value[0] = value[1]


        p.end()

class VigemDeviceWidget(QtWidgets.QWidget):

    """ joystick visualization widget  """

    def __init__(self, device, vis_type, parent=None):
        super().__init__(parent)
        self.pad = device
        self.vis_type = vis_type
        self.widgets = []
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        self.setLayout(layout)
        self.vis_type = vis_type
        self._hooked = False
        

    def unhook(self):
        ''' unhooks events '''
        if not self._hooked:
            return
        vis_type = self.vis_type
        el = gremlin.event_handler.EventListener()
        if vis_type == gremlin.types.VisualizationType.AxisCurrent:
            el.joystick_event.disconnect(self._current_axis_update)
        elif vis_type == gremlin.types.VisualizationType.AxisTemporal:
            el.joystick_event.disconnect(self._temporal_axis_update)
        elif vis_type == gremlin.types.VisualizationType.ButtonHat:
            el.joystick_event.disconnect(self._button_hat_update)
        self._hooked = False

    def _clear_ui(self):
        self.unhook()   




class JoystickDeviceWidget(QtWidgets.QWidget):

    """ joystick visualization widget  """

    def __init__(self, device_data : DeviceSummary, vis_type, parent=None):
        """Creates a new instance.

        :param device_data information about the device itself
        :param vis_type the visualization type to use
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.device_data = device_data
        self.device_guid = device_data.device_guid
        self.vis_type = vis_type
        self.widgets = []
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        self.setLayout(layout)
        self.vis_type = vis_type
        self._hooked = False
        

        

    def hook(self):
        ''' hooks events '''
        if self._hooked:
            return
        vis_type = self.vis_type
        el = gremlin.event_handler.EventListener()
        if vis_type == gremlin.types.VisualizationType.AxisCurrent:
            self._create_current_axis()
            el.joystick_event.connect(self._current_axis_update)
        elif vis_type == gremlin.types.VisualizationType.AxisTemporal:
            self._create_temporal_axis()
            el.joystick_event.connect(self._temporal_axis_update)
            for widget in self.widgets:
                for i in self.device_data.axis_index_list():
                    value = gremlin.joystick_handling.get_axis(self.device_guid, i)
                    widget.add_point(value, i)
        elif vis_type == gremlin.types.VisualizationType.ButtonHat:
            self._create_button_hat()
            el.joystick_event.connect(self._button_hat_update)

        self._hooked = True

    def unhook(self):
        ''' unhooks events '''
        if not self._hooked:
            return
        vis_type = self.vis_type
        el = gremlin.event_handler.EventListener()
        if vis_type == gremlin.types.VisualizationType.AxisCurrent:
            el.joystick_event.disconnect(self._current_axis_update)
        elif vis_type == gremlin.types.VisualizationType.AxisTemporal:
            el.joystick_event.disconnect(self._temporal_axis_update)
        elif vis_type == gremlin.types.VisualizationType.ButtonHat:
            el.joystick_event.disconnect(self._button_hat_update)
        self._hooked = False

    def _clear_ui(self):
        self.unhook()

    def minimumSizeHint(self):
        """Returns the minimum size of this widget.

        :return minimum size of this widget
        """
        width = 0
        height = 0
        for widget in self.widgets:
            hint = widget.minimumSizeHint()
            height = max(height, hint.height())
            width += hint.width()
        return QtCore.QSize(width, height)

    def _create_button_hat(self):
        """Creates display for button and hat data."""
        self.widgets = [
            ButtonState(self.device_data),
            HatState(self.device_data)
        ]
        for widget in self.widgets:
            self.layout().addWidget(widget)
        self.layout().addStretch(1)

    def _create_current_axis(self):
        """Creates display for current axes data."""
        self.widgets = [AxesCurrentState(self.device_data)]
        for widget in self.widgets:
            self.layout().addWidget(widget)

    def _create_temporal_axis(self):
        """Creates display for temporal axes data."""
        self.widgets = [AxesTimeline(self.device_data)]
        for widget in self.widgets:
            self.layout().addWidget(widget)

    def _button_hat_update(self, event):
        """Updates the button and hat display.

        :param event the event to use in the update
        """
        if self.device_guid != event.device_guid:
            return

        for widget in self.widgets:
            widget.process_event(event)

    def _current_axis_update(self, event):
        if self.device_guid != event.device_guid:
            return

        for widget in self.widgets:
            widget.process_event(event)

    def _temporal_axis_update(self, event):
        """Updates the temporal axes display.

        :param event the event to use in the update
        """
        if self.device_guid != event.device_guid:
            return

        if event.event_type == InputType.JoystickAxis:
            for widget in self.widgets:
                widget.add_point(event.value, event.identifier)


class ButtonState(QtWidgets.QGroupBox):

    """Widget representing the state of a device's buttons."""

    def __init__(self, device : DeviceSummary, parent=None):
        """Creates a new instance.

        :param device the device of which to display the button sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._event_times = {}

        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Buttons")
        else:
            self.setTitle(f"{device.name} - Buttons")

        css = Color.cssButtonState()
        self.buttons = [None]
        button_layout = QtWidgets.QGridLayout()
        for i in range(device.button_count):
            btn = QtWidgets.QPushButton(str(i+1))
            btn.setStyleSheet(css)
            btn.setDisabled(True)
            # read the current state
            is_pressed = gremlin.joystick_handling.get_button(device.device_guid, i+1)
            btn.setDown(is_pressed)
            self.buttons.append(btn)
            button_layout.addWidget(btn, int(i / 10), int(i % 10))
        button_layout.setColumnStretch(10, 1)
        self.setLayout(button_layout)

        

    def process_event(self, event):
        """Updates state visualization based on the given event.

        :param event the event with which to update the state display
        """
        if event.event_type == InputType.JoystickButton:
            state = event.is_pressed if event.is_pressed is not None else False
            self.buttons[event.identifier].setDown(state)
            self._event_times[event.identifier] = time.time()




class QRowSelectorFrame(QtWidgets.QFrame):

    selected_changed = QtCore.Signal(object)

    def __init__(self, data = None, parent = None, selected = False):
        super().__init__(parent)
        self._emit = False
        self._selected = not selected # force an update to the stylesheet
        self.selected = selected
        self._data = data
        self._emit = True
        self.installEventFilter(self)
        self._selectable = True

        border_color = Color.borderColor()
        background_color = Color.actionBackgroundColor()
        css = f"Qframe {{ border 1px solid {border_color}; border-top: none; background-color:{background_color} }}"
        self.setStyleSheet(css)


    def setSelectable(self, value):
        self._selectable = value

    def getSelectable(self):
        return self._selectable

    def eventFilter(self, widget, event):
        ''' ensure line changes are saved '''
        t = event.type()
        if self._selectable and t == QtCore.QEvent.Type.MouseButtonPress:
            self.selected = not self.selected
        return False

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, value):
        # change selection mode
        if value != self._selected:
            self._selected = value
            
            if value:
                background_color = Color.selectColor()
            else:
                background_color = Color.actionBackgroundColor()

            style = f"QRowSelectorFrame{{background-color: {background_color}; }}"
            self.setStyleSheet(style)
            if self._emit:
                self.selected_changed.emit(self)

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value


def get_text_width(text):
    ''' gets the average text width '''
    lbl = QtWidgets.QLabel("M")
    char_width = lbl.fontMetrics().averageCharWidth()
    return char_width * (len(text) if text else 1)

def get_text_height(text = None):
    ''' gets the average text width '''
    lbl = QtWidgets.QLabel(text if text else "M")
    fm = lbl.fontMetrics()
    rect = fm.boundingRect(QtCore.QRect(0,0,100,100), QtCore.Qt.TextWordWrap, lbl.text())
    return rect.height()
    


def get_char_width(count = 1):
    return get_text_width("w") * count




class QToggle(QCheckBox):

    _transparent_pen = QPen(Qt.transparent)
    _light_grey_pen = QPen(Qt.lightGray)

    def __init__(self,
        parent=None,
        bar_color=Qt.gray,
        checked_color="#8FBC8F",
        handle_color=Qt.white,
        ):
        super().__init__(parent)

        # Save our properties on the object via self, so we can access them later
        # in the paintEvent.
        self._bar_brush = QBrush(bar_color)
        self._bar_checked_brush = QBrush(QColor(checked_color).lighter())

        self._handle_brush = QBrush(handle_color)
        self._handle_checked_brush = QBrush(QColor(checked_color))

        # Setup the rest of the widget.

        self.setContentsMargins(8, 0, 8, 0)
        self._handle_position = 0

        self.stateChanged.connect(self.handle_state_change)

    def sizeHint(self):
        return QSize(48, 32)

    def hitButton(self, pos: QPoint):
        return self.contentsRect().contains(pos)

    def paintEvent(self, e: QPaintEvent):

        contRect = self.contentsRect()
        handleRadius = round(0.24 * contRect.height())

        p = QPainter(self)
        # p.begin(self)
        p.setRenderHint(QPainter.Antialiasing)

        p.setPen(self._transparent_pen)
        barRect = QRectF(
            0, 0,
            contRect.width() - handleRadius, 0.40 * contRect.height()
        )
        barRect.moveCenter(contRect.center())
        rounding = barRect.height() / 2

        # the handle will move along this line
        trailLength = contRect.width() - 2 * handleRadius
        xPos = contRect.x() + handleRadius + trailLength * self._handle_position

        if self.isChecked():
            p.setBrush(self._bar_checked_brush)
            p.drawRoundedRect(barRect, rounding, rounding)
            p.setBrush(self._handle_checked_brush)

        else:
            p.setBrush(self._bar_brush)
            p.drawRoundedRect(barRect, rounding, rounding)
            p.setPen(self._light_grey_pen)
            p.setBrush(self._handle_brush)

        p.drawEllipse(
            QPointF(xPos, barRect.center().y()),
            handleRadius, handleRadius)

        p.end()

    @Slot(int)
    def handle_state_change(self, value):
        self._handle_position = 1 if value else 0

    @Property(float)
    def handle_position(self):
        return self._handle_position

    @handle_position.setter
    def handle_position(self, pos):
        """change the property
        we need to trigger QWidget.update() method, either by:
            1- calling it here [ what we're doing ].
            2- connecting the QPropertyAnimation.valueChanged() signal to it.
        """
        self._handle_position = pos
        self.update()

    @Property(float)
    def pulse_radius(self):
        return self._pulse_radius

    @pulse_radius.setter
    def pulse_radius(self, pos):
        self._pulse_radius = pos
        self.update()



class QAnimatedToggle(QToggle):

    _transparent_pen = QPen(Qt.transparent)
    _light_grey_pen = QPen(Qt.lightGray)

    def __init__(self, *args, pulse_unchecked_color="#44999999",
        pulse_checked_color="#4400B0EE", **kwargs):

        self._pulse_radius = 0

        super().__init__(*args, **kwargs)

        self.animation = QPropertyAnimation(self, b"handle_position", self)
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.animation.setDuration(200)  # time in ms

        self.pulse_anim = QPropertyAnimation(self, b"pulse_radius", self)
        self.pulse_anim.setDuration(350)  # time in ms
        self.pulse_anim.setStartValue(10)
        self.pulse_anim.setEndValue(20)

        self.animations_group = QSequentialAnimationGroup()
        self.animations_group.addAnimation(self.animation)
        self.animations_group.addAnimation(self.pulse_anim)

        self._pulse_unchecked_animation = QBrush(QColor(pulse_unchecked_color))
        self._pulse_checked_animation = QBrush(QColor(pulse_checked_color))



    @Slot(int)
    def handle_state_change(self, value):
        self.animations_group.stop()
        if value:
            self.animation.setEndValue(1)
        else:
            self.animation.setEndValue(0)
        self.animations_group.start()

    def paintEvent(self, e: QPaintEvent):

        contRect = self.contentsRect()
        handleRadius = round(0.24 * contRect.height())

        p = QPainter(self)
        # p.begin(self)
        p.setRenderHint(QPainter.Antialiasing)

        p.setPen(self._transparent_pen)
        barRect = QRectF(
            0, 0,
            contRect.width() - handleRadius, 0.40 * contRect.height()
        )
        barRect.moveCenter(contRect.center())
        rounding = barRect.height() / 2

        # the handle will move along this line
        trailLength = contRect.width() - 2 * handleRadius

        xPos = contRect.x() + handleRadius + trailLength * self._handle_position

        if self.pulse_anim.state() == QPropertyAnimation.Running:
            p.setBrush(
                self._pulse_checked_animation if
                self.isChecked() else self._pulse_unchecked_animation)
            p.drawEllipse(QPointF(xPos, barRect.center().y()),
                          self._pulse_radius, self._pulse_radius)

        if self.isChecked():
            p.setBrush(self._bar_checked_brush)
            p.drawRoundedRect(barRect, rounding, rounding)
            p.setBrush(self._handle_checked_brush)

        else:
            p.setBrush(self._bar_brush)
            p.drawRoundedRect(barRect, rounding, rounding)
            p.setPen(self._light_grey_pen)
            p.setBrush(self._handle_brush)

        p.drawEllipse(
            QPointF(xPos, barRect.center().y()),
            handleRadius, handleRadius)

        p.end()



class QToggleText(QtWidgets.QWidget):
    ''' switched checkbox  '''
    clicked = QtCore.Signal()

    def __init__(self, text = None, parent = None):
        super().__init__(parent)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self._button = QToggle()
        self.main_layout.addWidget(self._button)
        self._label = QtWidgets.QLabel()
        self.main_layout.addWidget(self._label)
        self.main_layout.addStretch()
        if text is not None:
            self._label.setText(text)
        self._button.clicked.connect(self._clicked_cb)


    @QtCore.Slot()
    def _clicked_cb(self):
        self.clicked.emit()

    def text(self):
        return self._label.text()
    def setText(self, value):
        self._label.setText(value)

    def isChecked(self):
        return self._button.isChecked()
    def setChecked(self, value):
        self._button.setChecked(value)

    @property
    def value(self):
        return self._button.isChecked()
    @value.setter
    def value(self, checked):
        self._button.setChecked(checked)


class QDelayWidget(QtWidgets.QWidget):
    ''' widget to collect a delay time in milliseconds '''

    valueChanged = QtCore.Signal() # fired when the value changes

    def __init__(self, value = 250, parent = None):
        '''

        :params value: default delay in milliseconds '''
        super().__init__(parent)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)

        self.delay_container_widget = QtWidgets.QWidget()
        self.delay_container_layout = QtWidgets.QHBoxLayout()
        self.delay_container_widget.setLayout(self.delay_container_layout)

        width = gremlin.ui.ui_common.get_char_width(8)

        delay_label = QtWidgets.QLabel("Delay (ms)")
        self._delay_widget = QIntLineEdit()
        self._delay_widget.setRange(0, 20000) # up to 20 seconds
        self._delay_widget.setMaximumWidth(width)
        self._delay_widget.setValue(value) # default
        self._delay_widget.valueChanged.connect(self._value_changed)

        quarter_sec_button = QtWidgets.QPushButton("1/4s")
        half_sec_button = QtWidgets.QPushButton("1/2s")
        sec_button = QtWidgets.QPushButton("1s")

        quarter_sec_button.clicked.connect(self._quarter_sec_delay)
        half_sec_button.clicked.connect(self._half_sec_delay)
        sec_button.clicked.connect(self._sec_delay)


        self.delay_container_layout.addWidget(delay_label)
        self.delay_container_layout.addWidget(self._delay_widget)
        self.delay_container_layout.addWidget(quarter_sec_button)
        self.delay_container_layout.addWidget(half_sec_button)
        self.delay_container_layout.addWidget(sec_button)
        self.delay_container_layout.addStretch()

        self.main_layout.addWidget(self.delay_container_widget)

    def value(self):
        ''' gets the delay in milliseconds '''
        return self._delay_widget.value()

    def setValue(self, value : int):
        if value >= 0 and value != self._delay_widget.value():
            self._delay_widget.setValue(value)
            self.valueChanged.emit()

    @QtCore.Slot()
    def _value_changed(self):
        self.valueChanged.emit()

    @QtCore.Slot()
    def _quarter_sec_delay(self):
        self._delay_widget.setValue(250)

    @QtCore.Slot()
    def _half_sec_delay(self):
        self._delay_widget.setValue(500)

    @QtCore.Slot()
    def _sec_delay(self):
        self._delay_widget.setValue(1000)


import gremlin.singleton_decorator
@gremlin.singleton_decorator.SingletonDecorator
class QHelper():

    def __init__(self, show_percent = False, decimals = 3, single_step = 0.01):
        self._show_percent = show_percent
        self._decimals = decimals
        self._single_step = single_step
        self._min_range = -1.0
        self._max_range = 1.0


    @property
    def decimals(self):
        if self.show_percent:
            return 2
        return self._decimals

    @decimals.setter
    def decimals(self, value):
        self._decimals = value

    @property
    def single_step(self):
        if self.show_percent:
            return 0.1
        return self._single_step

    @property
    def min_range(self):
        ''' current min range '''
        return self._min_range

    @min_range.setter
    def min_range(self, value):
        self._min_range = value

    @property
    def max_range(self):
        ''' current max range '''
        return self._max_range

    @max_range.setter
    def max_range(self, value):
        self._max_range = value

    @property
    def show_percent(self):
        return self._show_percent
    @show_percent.setter
    def show_percent(self, value):
        self._show_percent = value

    def get_double_spinbox(self, id, value, min_range = -1.0, max_range = 1.0) -> DynamicDoubleSpinBox:
        ''' creates a double spin box formatted for the display mode '''
        show_percent = self.show_percent
        assert isinstance(id, str)
        sb_widget = DynamicDoubleSpinBox(data = id)
        if show_percent:
            sb_widget.setMinimum(0)
            sb_widget.setMaximum(100)
            sb_widget.setDecimals(2)
            sb_widget.setSingleStep(0.1)
        else:
            sb_widget.setRange(min_range, max_range)
            sb_widget.setDecimals(self.decimals)
            sb_widget.setSingleStep(self.single_step)

        sb_widget.setValue(value)

        return sb_widget

    def to_value(self, value):
        ''' returns a [-1,+1] value converted to the range output'''
        if self.show_percent:
            return gremlin.util.scale_to_range(value, target_min = 0, target_max = 100)
        else:
            return gremlin.util.scale_to_range(value, target_min = self.min_range, target_max = self.max_range)


class QDoubleClickSpinBox(QtWidgets.QSpinBox):
    ''' double click to reset spinbox '''
    doubleClick = QtCore.Signal()

    def __init__(self, parent = None):
        super().__init__(parent = None)
        self.installEventFilter(self)

    def eventFilter(self, object, event):
        t = event.type()
        if t == QtCore.QEvent.Type.MouseButtonDblClick:
            self.doubleClick.emit()
        return False


class DualSlider(QtWidgets.QWidget):

    """Slider widget which provides two sliders to define a range. The
    lower and upper slider cannot pass through each other."""

    # Signal emitted when a value changes. (Handle, Value)
    valueChanged = QtCore.Signal(int, int)
    # Signal emitted when a handle is pressed (Handle)
    sliderPressed = QtCore.Signal(int)
    # Signal emitted when a handle is moved (Handle, Value)
    sliderMoved = QtCore.Signal(int, int)
    # Signal emitted when a handle is released (Handle)
    sliderReleased = QtCore.Signal(int)

    # Enumeration of handle codes used by the widget
    LowerHandle = 1
    UpperHandle = 2

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent widget
        """
        super().__init__(parent)

        self._lower_position = 0
        self._upper_position = 100
        self._range = [0, 100]
        self._active_handle = None

    def setRange(self, min_val, max_val):
        """Sets the range of valid values of the slider.

        :param min_val the minimum value any slider can take on
        :param max_val the maximum value any slider can take on
        """
        if min_val > max_val:
            min_val, max_val = max_val, min_val
        self._range = [min_val, max_val]
        self._lower_position = min_val
        self._upper_position = max_val

    def range(self):
        """Returns the range, i.e. minimum and maximum of accepted
        values.

        :return pair containing (minimum, maximum) allowed values
        """
        return self._range

    def setPositions(self, lower, upper):
        """Sets the position of both handles.

        :param lower value of the lower handle
        :param upper value of the upper handle
        """
        lower = self._constrain_value(self.LowerHandle, lower)
        upper = self._constrain_value(self.UpperHandle, upper)
        self._lower_position = lower
        self._upper_position = upper
        self.valueChanged.emit(self.LowerHandle, lower)
        self.valueChanged.emit(self.UpperHandle, upper)
        self.update()

    def positions(self):
        """Returns the positions of both handles.

        :return tuple containing the values of (lower, upper) handle
        """
        return [self._lower_position, self._upper_position]

    def setLowerPosition(self, value):
        """Sets the position of the lower handle.

        :param value the new value of the lower handle
        """
        value = self._constrain_value(self.LowerHandle, value)
        self._lower_position = value
        self.valueChanged.emit(self.LowerHandle, value)
        self.update()

    def setUpperPosition(self, value):
        """Sets the position of the upper handle.

        :param value the new value of the upper handle
        """
        value = self._constrain_value(self.UpperHandle, value)
        self._upper_position = value
        self.valueChanged.emit(self.UpperHandle, value)
        self.update()

    def lowerPosition(self):
        """Returns the position of the lower handle.

        :return position of the lower handle
        """
        return self._lower_position

    def upperPosition(self):
        """Returns the position of the upper handle.

        :return position of the upper handle
        """
        return self._upper_position

    def _get_common_option(self):
        """Returns a QStyleOptionSlider object with the common options
        already specified.

        :return pre filled options object
        """
        option = QtWidgets.QStyleOptionSlider()
        option.initFrom(self)
        option.minimum = self._range[0]
        option.maximum = self._range[1]
        return option

    def _constrain_value(self, handle, value):
        """Returns a value constraint such that it is valid in the given
        setting.

        :param handle the handle for which this value is intended
        :param value the desired value for the handle
        :return a value constrained such that it is valid for the
            slider's current state
        """
        slider = self.style().subControlRect(
            QtWidgets.QStyle.CC_Slider,
            self._get_common_option(),
            QtWidgets.QStyle.SC_SliderHandle
        )

        if handle == self.LowerHandle:
            return gremlin.util.clamp(
                value,
                self._range[0],
                self._upper_position - self._width_to_logical(slider.width())
            )
        else:
            return gremlin.util.clamp(
                value,
                self._lower_position + self._width_to_logical(slider.width()),
                self._range[1]
            )

    def _width_to_logical(self, value):
        """Converts a width in pixels to the logical representation.

        :param value the width in pixels
        :return logical value corresponding to the provided width
        """
        groove_rect = self.style().subControlRect(
            QtWidgets.QStyle.CC_Slider,
            self._get_common_option(),
            QtWidgets.QStyle.SC_SliderGroove
        )
        return int(round(
            (value / groove_rect.width()) * (self._range[1] - self._range[0])
        ))

    def _position_to_logical(self, pos):
        """Converts a pixel position on a slider to it's logical
        representation.

        :param pos the pixel position on the slider
        :return logical representation of the position on the slider
        """
        groove_rect = self.style().subControlRect(
            QtWidgets.QStyle.CC_Slider,
            self._get_common_option(),
            QtWidgets.QStyle.SC_SliderGroove
        )

        return QtWidgets.QStyle.sliderValueFromPosition(
            self._range[0],
            self._range[1],
            pos - groove_rect.left(),
            groove_rect.right() - groove_rect.left()
        )

    def sizeHint(self):
        """Returns the size hint for the widget in its current state.

        :return hint about the correct size of this widget
        """
        return QtWidgets.QSlider().sizeHint()

    def minimumSizeHint(self):
        """Returns the minimal size of this widget.

        :return minimal size of this widget
        """
        return QtCore.QSize(31, 17)

    def mousePressEvent(self, evt):
        """Tracks active state of the handles.

        :param evt the mouse event
        """
        position = QtCore.QPoint(evt.pos().x(), evt.pos().y())
        option = QtWidgets.QStyleOptionSlider(self._get_common_option())
        option.sliderPosition = self._lower_position
        option.sliderValue = self._lower_position
        option.subControls = QtWidgets.QStyle.SC_SliderHandle

        control = self.style().hitTestComplexControl(
            QtWidgets.QStyle.CC_Slider,
            option,
            position
        )
        lower_clicked = False
        if control == QtWidgets.QStyle.SC_SliderHandle:
            lower_clicked = True

        option.sliderPosition = self._upper_position
        option.sliderValue = self._upper_position
        control = self.style().hitTestComplexControl(
            QtWidgets.QStyle.CC_Slider,
            option,
            position
        )
        upper_clicked = False
        if control == QtWidgets.QStyle.SC_SliderHandle:
            upper_clicked = True

        if lower_clicked:
            self._active_handle = self.LowerHandle
            self.sliderPressed.emit(self.LowerHandle)
        elif upper_clicked:
            self._active_handle = self.UpperHandle
            self.sliderPressed.emit(self.UpperHandle)
        else:
            self._active_handle = None

        self.update()

    def mouseReleaseEvent(self, evt):
        """Ensures active handles get released.

        :param evt the mouse event
        """
        if self._active_handle is not None:
            self.sliderReleased.emit(self._active_handle)
            self._active_handle = None
            self.update()

    def mouseMoveEvent(self, evt):
        """Updates the position of the active slider if applicable.

        :param evt the mouse event
        """
        if self._active_handle:
            value = self._position_to_logical(evt.pos().x())
            if self._active_handle == self.LowerHandle:
                self._lower_position =\
                    self._constrain_value(self.LowerHandle, value)
                value = self._lower_position
            elif self._active_handle == self.UpperHandle:
                self._upper_position =\
                    self._constrain_value(self.UpperHandle, value)
                value = self._upper_position
            self.valueChanged.emit(self._active_handle, value)
            self.sliderMoved.emit(self._active_handle, value)
            self.update()

    def paintEvent(self, evt):
        """Repaints the entire widget.

        :param evt the paint event
        """
        painter = QtWidgets.QStylePainter(self)

        common_option = self._get_common_option()

        # Draw the groove for the handles to move on
        option = QtWidgets.QStyleOptionSlider(common_option)
        option.subControls = QtWidgets.QStyle.SC_SliderGroove
        painter.drawComplexControl(QtWidgets.QStyle.CC_Slider, option)

        # Draw lower handle
        option_lower = QtWidgets.QStyleOptionSlider(common_option)
        option_lower.sliderPosition = self._lower_position
        option_lower.sliderValue = self._lower_position
        option_lower.subControls = QtWidgets.QStyle.SC_SliderHandle

        # Draw upper handle
        option_upper = QtWidgets.QStyleOptionSlider(common_option)
        option_upper.sliderPosition = self._upper_position
        option_upper.sliderValue = self._upper_position
        option_upper.subControls = QtWidgets.QStyle.SC_SliderHandle

        if self._active_handle:
            if self._active_handle == self.LowerHandle:
                option = option_lower
            else:
                option = option_upper
            option.activeSubControls = QtWidgets.QStyle.SC_SliderHandle
            option.state |= QtWidgets.QStyle.State_Sunken

        painter.drawComplexControl(QtWidgets.QStyle.CC_Slider, option_lower)
        painter.drawComplexControl(QtWidgets.QStyle.CC_Slider, option_upper)



class QCustomFlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None):
        super().__init__(parent)

        if parent is not None:
            self.setContentsMargins(QtCore.QMargins(0, 0, 0, 0))

        self._item_list = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self._item_list.append(item)

    def count(self):
        return len(self._item_list)

    def itemAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list[index]

        return None

    def takeAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)

        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self._do_layout(QtCore.QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()

        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())

        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._item_list:
            style = item.widget().style()
            layout_spacing_x = style.layoutSpacing(
                QtWidgets.QSizePolicy.PushButton, QtWidgets.QSizePolicy.PushButton, Qt.Orientation.Horizontal
            )
            layout_spacing_y = style.layoutSpacing(
                QtWidgets.QSizePolicy.PushButton, QtWidgets.QSizePolicy.PushButton, Qt.Vertical
            )
            space_x = spacing + layout_spacing_x
            space_y = spacing + layout_spacing_y
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QtCore.QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y()




class QFlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None, margin=-1, hspacing=-1, vspacing=-1):
        '''
        :params:
        parent = parent of the object
        margin = margin, -1 for auto
        hspacing = horizontal spacing, -1 for auto
        vspacing = vertical spacing, -1 for auto
        sort_property = name of the index member of the item to set the display order, None to disable
        '''
        super().__init__(parent)
        self._hspacing = hspacing
        self._vspacing = vspacing
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self._grid_layout = True
        self._row = 0
        self._col = 0


    def __del__(self):
        del self._items[:]

    def addItem(self, item):
        self._items.append(item)

    def sortItems(self, callback):
        ''' sorts the items based on the given sort property '''
        self._items.sort(key = lambda item: callback(item))

    def horizontalSpacing(self):
        if self._hspacing >= 0:
            return self._hspacing
        else:
            return self.smartSpacing(
                QtWidgets.QStyle.PM_LayoutHorizontalSpacing)

    def verticalSpacing(self):
        if self._vspacing >= 0:
            return self._vspacing
        else:
            return self.smartSpacing(
                QtWidgets.QStyle.PM_LayoutVerticalSpacing)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)

    def expandingDirections(self):
        return QtCore.Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.doLayout(QtCore.QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        lineheight = 0
        for item in self._items:
            lineheight = max(lineheight, item.sizeHint().height())
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
            #size = size.expandedTo(item.sizeHint()) + QSize(item.geometry().x(), item.geometry().y())
        left, top, right, bottom = self.getContentsMargins()
        size += QtCore.QSize(left + right, top + bottom)
        size += QSize(0, lineheight * self._row)
        return size

    def doLayout(self, rect, testonly):
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(+left, +top, -right, -bottom)
        x = effective.x()
        y = effective.y()
        lineheight = 0


        # visible_count = len(self._items)
        # invisible_count = 0

        if self._grid_layout:
            # compute max width
            max_w = 0
            pos_x = {}
            pos_x[0] = x

            for item in self._items:
                widget = item.widget()
                if not widget.isVisible():
                    #invisible_count+=1
                    continue
                # if hasattr(widget,"display_name"):
                #     print (f"layout: {str(widget.display_name())}")
                hspace = self.horizontalSpacing()
                if hspace == -1:
                    hspace = widget.style().layoutSpacing(
                        QtWidgets.QSizePolicy.PushButton,
                        QtWidgets.QSizePolicy.PushButton, QtCore.Qt.Horizontal)
                vspace = self.verticalSpacing()
                if vspace == -1:
                    vspace = widget.style().layoutSpacing(
                        QtWidgets.QSizePolicy.PushButton,
                        QtWidgets.QSizePolicy.PushButton, QtCore.Qt.Vertical)
                item_w = item.sizeHint().width() + hspace
                max_w = max(max_w,item_w)
                lineheight = max(lineheight, item.sizeHint().height())
            # compute columns

            usable_width = effective.right() - x
            if max_w == 0:
                max_w = usable_width
            max_col = max(1, usable_width // max_w)

            # print (f"available width {usable_width} max widget {max_w} columns: {max_col}")
            for col in range(max_col):
                pos_x[col] = col * max_w
                # print(f"\tcol {col} position {pos_x[col]}")

            col = 0
            row = 0
            index = 0
            for item in self._items:
                widget = item.widget()
                if not widget.isVisible():
                    continue
                x = pos_x[col]

                if not testonly:
                    item.setGeometry(
                        QtCore.QRect(QtCore.QPoint(x, y), item.sizeHint()))
                    # print (f"flow [{index}] position {x} {y}")
                    index+=1

                col += 1
                if col == max_col:
                    col = 0
                    row += 1
                    y += lineheight + vspace

            self._row = row
            self._col = max_col


            #print (f"layout visible: {visible_count} invisible: {invisible_count}")

            return y + lineheight - rect.y() + bottom

        else:
            item : QtWidgets.QWidgetItem
            for item in self._items:
                widget = item.widget()
                hspace = self.horizontalSpacing()
                if hspace == -1:
                    hspace = widget.style().layoutSpacing(
                        QtWidgets.QSizePolicy.PushButton,
                        QtWidgets.QSizePolicy.PushButton, QtCore.Qt.Horizontal)
                vspace = self.verticalSpacing()
                if vspace == -1:
                    vspace = widget.style().layoutSpacing(
                        QtWidgets.QSizePolicy.PushButton,
                        QtWidgets.QSizePolicy.PushButton, QtCore.Qt.Vertical)
                nextX = x + item.sizeHint().width() + hspace

                if nextX - hspace > effective.right() and lineheight > 0:
                    x = effective.x()
                    y = y + lineheight + vspace
                    nextX = x + item.sizeHint().width() + hspace
                    lineheight = 0

                if not testonly:
                    item.setGeometry(
                        QtCore.QRect(QtCore.QPoint(x, y), item.sizeHint()))
                x = nextX

                lineheight = max(lineheight, item.sizeHint().height())

        return y + lineheight - rect.y() + bottom

    def smartSpacing(self, pm):
        parent = self.parent()
        if parent is None:
            return -1
        elif parent.isWidgetType():
            return parent.style().pixelMetric(pm, None, parent)
        else:
            return parent.spacing()

class QBubble(QtWidgets.QLabel):
    def __init__(self, text):
        super(QBubble, self).__init__(text)
        self.word = text
        self.setContentsMargins(5, 5, 5, 5)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        # p.begin(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.drawRoundedRect(
            0, 0, self.width() - 1, self.height() - 1, 5, 5)
        super(QBubble, self).paintEvent(event)
        p.end()




class ActionLabel(QtWidgets.QLabel):

    """Handles showing the correct icon for the given action.  This control is used to display action icons in the input item."""



    def __init__(self, action_entry, parent=None):
        """Creates a new label for the given entry.

        :param action_entry the entry to create the label for
        :param parent the parent
        """
        QtWidgets.QLabel.__init__(self, parent)
        icon = action_entry.icon()
        if icon is None:
            icon = gremlin.util.load_icon("fa.question-circle-o")

        self._width = 20
        if isinstance(icon, str):
            # convert to icon if a path is given
            icon = load_icon(icon)

        if isinstance(icon, QtGui.QIcon):
            pixmap = icon.pixmap(self._width)
        else:
            pixmap = QtGui.QPixmap(icon)
        pixmap = pixmap.scaled(self._width, self._width, QtCore.Qt.KeepAspectRatio)
        self.setPixmap(pixmap)

        self.action_entry = action_entry
        # mask = QtGui.QBitmap(pixmap.createMaskFromColor(Qt.transparent))
        # self.setMask(mask)

        # el = gremlin.event_handler.EventListener()
        # el.icon_changed.connect(self._icon_change)
        background_color = Color.actionIconBackgroundColor()
        border_color = Color.keyBorderColor()
        self.setStyleSheet(f"QLabel {{ border: 1px solid {border_color}; border-radius: 4px; padding: 1px; background-color: {background_color}; }}")


    def _icon_change(self, event):
        icon = self.action_entry.icon()
        if icon is None:
            icon = gremlin.util.load_icon("fa.question-circle-o")
        if isinstance(icon, QtGui.QIcon):
            self.setPixmap(QtGui.QPixmap(icon.pixmap(self._width)))
        else:
            self.setPixmap(QtGui.QPixmap(icon))



class QContentWidget(QtWidgets.QWidget):
    ''' a widget that fires a resize event when its size changes '''

    resized = QtCore.Signal(QtCore.QSize)
    def __init__(self, parent = None):
        super().__init__(parent)

    def resizeEvent(self, event):
        self.resized.emit(event.size)
        return super().resizeEvent(event)




class QSplitTabWidget(QDataWidget):
    ''' tab content widgeth split '''
    def __init__(self, parent = None):
        super().__init__(parent)

        self._lock = False

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.setContentsMargins(0,0,0,0)

        self._content_widget = QContentWidget()
        self._content_widget.resized.connect(self._content_resized)
        self._content_widget.setContentsMargins(0,0,0,0)

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self._content_widget)


        self._left_panel_widget = QtWidgets.QWidget()
        #self._left_panel_widget.setStyleSheet("background: green")
        self._left_panel_widget.setContentsMargins(0,0,0,0)
        self._left_panel_widget.setMinimumWidth(200)

        self._right_panel_widget = QtWidgets.QWidget()
        #self._right_panel_widget.setStyleSheet("background: blue")
        self._right_panel_widget.setContentsMargins(0,0,0,0)

        self._left_panel_layout = QtWidgets.QVBoxLayout(self._left_panel_widget)
        self._left_panel_layout.setContentsMargins(0,0,0,0)

        self._right_panel_layout = QtWidgets.QVBoxLayout(self._right_panel_widget)
        self._right_panel_layout.setContentsMargins(0,0,0,0)
        


        # left panel, list view on top, buttons on bottom
        self._left_container_widget = QtWidgets.QWidget()
        self._left_container_widget.setContentsMargins(0,0,0,0)
        self._left_container_layout = QtWidgets.QVBoxLayout(self._left_container_widget)
        self._left_container_layout.setContentsMargins(0,0,0,0)

        # right panel
        self._right_container_widget = QtWidgets.QWidget()
        self._right_container_widget.setContentsMargins(0,0,0,0)
        self._right_container_layout = QtWidgets.QVBoxLayout(self._right_container_widget)
        self._right_container_layout.setContentsMargins(0,0,0,0)
        
        # place items in left_container_layout or right_container_layout
        self._left_panel_layout.addWidget(self._left_container_widget)
        self._right_panel_layout.addWidget(self._right_container_widget)

        self._splitter.addWidget(self._left_panel_widget)
        self._splitter.addWidget(self._right_panel_widget)
        self._splitter.setStretchFactor(0,1)
        self._splitter.setStretchFactor(1,3)

        width = self.frameGeometry().width()
        w1 = width // 5
        self._splitter.setSizes((w1, w1*4))

        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self.main_layout.addWidget(self._content_widget)

        _tabsplitter_tracker.registerWidget(self)

    def _cleanup_ui(self):
        ''' remove '''
        if not self._lock:
            self._lock = True
            _tabsplitter_tracker.unregisterWidget(self)
            self._lock = False

    def _select_item_cb(self, index):
        assert False,"Must be implemented by subclass"

    def select_item(self, index):
        # implemented by a subclass
        self._select_item_cb(index)



    @QtCore.Slot(QtCore.QSize)
    def _content_resized(self, size : QtCore.QSize):
        ''' called when the container object is resized '''

        # resize the splitter to the container's size as it doesn't happen by itself for some reason
        width = self._content_widget.frameGeometry().width()
        height = self._content_widget.frameGeometry().height()
        if width > 0:
            self._splitter.setFixedWidth(width)
            self._splitter.setFixedHeight(height)


    def setLeftPanelWidget(self, widget : QtWidgets.QWidget):
        ''' sets the left panel widget '''
        gremlin.util.clear_layout(self._left_container_layout)
        if widget is not None:
            self._left_container_layout.addWidget(widget)

    def addLeftPanelWidget(self, widget : QtWidgets.QWidget):
        ''' sets the left panel widget '''
        if widget is not None:
            self._left_container_layout.addWidget(widget)

    def setRightPanelWidget(self, widget : QtWidgets.QWidget):
        ''' sets the right panel widget '''
        #print ("set right panel")
        widgets = gremlin.util.get_layout_widgets(self._right_container_layout)
        if widget in widgets:
            return
        self.clearRightPanel()
        self.addRightPanelWidget(widget)


    def addRightPanelWidget(self, widget : QtWidgets.QWidget):
        ''' sets the left panel widget '''
        #print ("add right panel")
        if widget is not None:
            self._right_container_layout.addWidget(widget)

    def removeRightPanelWidget(self, widget : QtWidgets.QWidget):
        ''' removes a widget from the right panel '''
        widgets = gremlin.util.get_layout_widgets(self._right_container_layout)
        if widget and widget in widgets:
            self._right_container_layout.removeWidget(widget)

    def clearLeftPanel(self):
        ''' removes all widgets from the left panel '''
        gremlin.util.clear_layout(self._left_container_layout)

    def clearRightPanel(self):
        ''' removes all widgets from the right panel '''
        #print ("clear right panel")
        gremlin.util.clear_layout(self._right_container_layout)

    def getRightPanelWidgets(self):
        ''' gets the widgets in the right panel'''
        return gremlin.util.get_layout_widgets(self._right_container_layout)

    def hasRightContent(self):
        ''' true if the widget has contents on the right '''
        widgets = gremlin.util.get_layout_widgets(self._right_container_layout)
        return len(widgets) > 0

class QRememberDialog(QtWidgets.QDialog):
    ''' a dialog window that remembers its size and location '''

    def __init__(self, key: str, parent = None):
        super().__init__(parent)

        self._resize_count = 0
        assert key,"unique key must be provided"
        self.window_key = key
        self.apply_window_settings()



    def getResizable(self) -> bool:
        return self._resizable
    def setResizable(self, value: bool):
        self._resizable = value
        if value:
            self.layout().setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetNoConstraint)
        else:
            self.layout().setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetFixedSize)


    def apply_window_settings(self):
        """Restores the stored window geometry settings."""
        config = gremlin.config.Configuration()
        window_size = config.getWindowSize(self.window_key)
        window_location = config.getWindowLocation(self.window_key)
        if window_size:
            self.resize(window_size[0], window_size[1])
        if window_location:
            self.move(window_location[0], window_location[1])

    def moveEvent(self, evt):
        """Handle changing the position of the window.

        :param evt event information
        """
        config = gremlin.config.Configuration()
        config.setWindowLocation(self.window_key, evt.pos().x(), evt.pos().y())
        super().moveEvent(evt)

    def resizeEvent(self, evt):
        """Handling changing the size of the window.

        :param evt event information
        """
        if self._resize_count > 1:
            config = gremlin.config.Configuration()
            config.setWindowSize(self.window_key, evt.size().width(), evt.size().height())

        self._resize_count += 1
        super().resizeEvent(evt)





class MarkdownDialog(QRememberDialog):
    '''
    Dialog box for instructions in markdown format
    '''
    def __init__(self, title = "Markdown Instructions", source = None, parent = None):
        super().__init__(self.__class__.__name__, parent = parent)
        self.setWindowTitle(title)
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._view = QtWidgets.QTextEdit()
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._view)
        if source is not None:
            self.load(source)


    def load(self, source : str):
        ''' loads a source '''
        if source is not None and os.path.isfile(source):
            location = source
        else:
            location = gremlin.util.find_file(source, gremlin.shared_state.root_path)
        if location is not None and os.path.isfile(location):
            syslog.info(f"dialog: found file : {location}")
            self._source = location
            with open(location,"+rt") as f:
                md = f.read()
            self._view.setMarkdown(md)
            return True
        return False




class BaseDialogUi(QRememberDialog):

    """Base class for all UI dialogs.

    The main purpose of this class is to provide the closed signal to dialogs
    so that the main application can react to the dialog being closed if
    desired.
    """

    # Signal emitted when the dialog is being closed
    closed = QtCore.Signal()

    def __init__(self, key, parent=None):
        """Creates a new options UI instance.

        :param parent the parent of this widget
        """
        super().__init__(key, parent = parent)

    def closeEvent(self, event):
        """Closes the calibration window.

        :param event the close event
        """
        if hasattr(self, "confirmClose"):
            self.confirmClose(event)
        if event.isAccepted():
            self.closed.emit()

class QDataTab(QtWidgets.QTabWidget):
    ''' tab header with a data field '''
    def __init__(self, data = None, parent = None):
        super().__init__(parent)
        self._data = data


    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self._data = value
  



class QTabHeader(QtWidgets.QTabBar):
    ''' wrapper for tab bar to catch mouse events on tab bar '''

    tabMoveCompleted = QtCore.Signal(int, int) # triggers once a tab moved has been completed 
    tabChanged = QtCore.Signal(int) # triggers when a tab is selected, aware of tab drag ops

    def __init__(self, parent = None):
        super().__init__(parent)

        self.installEventFilter(self)
        self._mouse_down = False
        self._to_index = None
        self._from_index = None
        self._mouse_down_index = None
        self._move_in_progress = False
        self.tabMoved.connect(self._tab_moved)
        #self.currentChanged.connect(self._tab_selected)

    @property
    def moveInProgress(self) -> bool:
        return self._move_in_progress or self._mouse_down
    
    @QtCore.Slot(int)
    def _tab_selected(self, index):
        # print (f"internal tab selected {index}")
        self._current_index = index
        if not (self._move_in_progress or self._mouse_down):
            self.tabChanged.emit(index)

    @QtCore.Slot(int, int)
    def _tab_moved(self, from_index, to_index):
        self._move_in_progress = True
        self._from_index = from_index
        self._to_index = to_index
        # print (f"internal tab move {from_index} {to_index}")


    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.MouseButtonPress:
            self._mouse_down = True
            self._mouse_down_index = self.currentIndex()
            #print (f"mouse down - {self._mouse_down_index}")
        elif t == QtCore.QEvent.Type.MouseButtonRelease:
            self._mouse_down = False
            index = self.currentIndex()
            # print (f"mouse up {index}")
            if self._move_in_progress:
                # print (f"move completed: {self._from_index} to {self._to_index}")
                self._move_in_progress = False
                self.tabMoveCompleted.emit(self._from_index, self._to_index)
            elif index != self._mouse_down_index:
                # fire the tab change on release if there is a tab change
                self.tabChanged.emit(index)
            
        return False # allow further processing
    
def getRadioContainer(label_data_pairs, callback, default = None, horizontal = True, label = None, parent = None):
    ''' returns an H container for radio buttons 
    :param label_data_pairs: list of tuples of (label, data, [tooltip]) for each radio button to create - tooltip is optional
    :param callback: the callback for each radio button - the data component will indicate which radio button was selected 
    :param default: the default value to select, set to None to not select anything, if the default doesn't exist, nothing is selected
    :param label: label text to add, if any
    :param horizontal: creates an H container, if false, creates a V container
    '''
    widget = QtWidgets.QWidget(parent=parent)
    if horizontal:
        layout = QtWidgets.QHBoxLayout(widget)
    else:
        layout = QtWidgets.QVBoxLayout(widget)
    widget.setContentsMargins(0,0,0,0)
    layout.setContentsMargins(0,0,0,0)
    if label:
        layout.addWidget(QtWidgets.QLabel(label))
    for data in label_data_pairs:
        tooltip = None
        if len(data) == 2:
            text, data = data
        elif len(data) == 3:
            text, data, tooltip = data
        else:
            continue # malformed
        rb = QDataRadioButton(text, data)
        if tooltip:
            rb.setToolTip(tooltip)
        if data == default:
            rb.setChecked(True)
        rb.clicked.connect(callback)
        layout.addWidget(rb)
    layout.addStretch()
    return (widget, layout)

   
def getHContainer(widget_or_list = None, label = None, parent = None):
    ''' gets a qt H container widget '''
    widget = QtWidgets.QWidget(parent=parent)
    layout = QtWidgets.QHBoxLayout(widget)
    widget.setContentsMargins(0,0,0,0)
    layout.setContentsMargins(0,0,0,0)
    stretch = False
    if label:
        layout.addWidget(QtWidgets.QLabel(label))
        stretch = True
    if widget_or_list:
        if isinstance(widget_or_list, list)  or isinstance(widget_or_list, tuple):
            for item in widget_or_list:
                layout.addWidget(item)
        else:
            layout.addWidget(widget_or_list)
        stretch = True
    if stretch:
        layout.addStretch()
    return (widget, layout)
    

def getVContainer(widget_or_list = None, label = None, alignment = None, parent = None):
    ''' gets a qt H container widget '''
    widget = QtWidgets.QWidget(parent=parent)
    layout = QtWidgets.QVBoxLayout(widget)
    widget.setContentsMargins(0,0,0,0)
    layout.setContentsMargins(0,0,0,0)
    if alignment is not None:
        layout.setAlignment(widget, alignment)
    stretch = False
    if label:
        layout.addWidget(QtWidgets.QLabel(label))
        
        stretch = True
    if widget_or_list:
        if isinstance(widget_or_list, list)  or isinstance(widget_or_list, tuple):
            for item in widget_or_list:
                layout.addWidget(item)
        else:
            layout.addWidget(widget_or_list)
        stretch = True
    if stretch:
        layout.addStretch()
    return (widget, layout)

def getGridContainer(widget_or_list = None, alignment = QtCore.Qt.AlignmentFlag.AlignLeft, start_col = 0, start_row = None, stretch_col = None, add_to_widget = None):
    ''' gets a qt grid container widget
     
    :param widget_or_list: the widget or widgets to add to the next row
    :param alignment: cell alignment
    :param start_col: starting column where to add the new widget, starting from the left column
    :param start_row: starting row where to add the new widgets
    :param add_to_widget: add widgets to an existing grid widget
       
    '''

    if add_to_widget is not None:
        widget = add_to_widget
        layout : QtWidgets.QGridLayout = widget.layout()
        row = layout.rowCount() if start_row is None else start_row
        stretch = False

    else:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout(widget)
        widget.setContentsMargins(0,0,0,0)
        layout.setContentsMargins(0,0,0,0)
        row = 0 if start_row is None else start_row
        stretch = True


    col = 0 if start_col is None else start_col
    
    
    if widget_or_list:
        if isinstance(widget_or_list, list) or isinstance(widget_or_list, tuple):
            for item in widget_or_list:
                layout.addWidget(item, row, col, alignment)
                col+=1
        else:
            layout.addWidget(widget_or_list, row, col, alignment)
            col+=1

    if stretch:
        if stretch_col is not None:
            col = stretch_col
        else:
            col = layout.columnCount()
        layout.addWidget(QtWidgets.QWidget(), 0, col)
        layout.setColumnStretch(col, 2)
    return (widget, layout)


def synchronize_grids(widget_list : list):
    ''' synchronizes cell widths between multiple grid layouts '''
    if len(widget_list) < 2:
        return # nothing to do
    
    g: QtWidgets.QGridLayout
    max_cols = 0
    layouts = [g.layout() for g in widget_list]
    max_cols = max(g.columnCount() for g in layouts)
    
    for col in range(max_cols):
        width = 0    
        for g in layouts:
            rows = g.rowCount()
            if col < g.columnCount():
                for row in range(rows):
                    width = max(width, g.itemAtPosition(row, col).minimumSize().width())

        for g in layouts:
            g.setColumnMinimumWidth(col, width)
    

    
class QJoystickRangeWidget(QtWidgets.QWidget):
    ''' a widget that displays and collects range information for a joytick '''


    valueChanged = QtCore.Signal(object) # occurs when the data range value changes ((min,max)) or (value) - passes the normalized values or single value
    modeChanged = QtCore.Signal() # occurs if the mode changes from single value to range mode
    rangeChanged = QtCore.Signal(object) # occurs when the range (command) data changes  ((min,max)) or (value) - passes the new command data or single value
    invertChanged = QtCore.Signal() # occurs when inversion flag is changed

    def __init__(self,
                 data = None, 
                 min_cmd = -1, 
                 max_cmd = 1,
                 min_norm = -1, 
                 max_norm = 1, 
                 decimals = 3, 
                 min_range = -1,
                 max_range = 1,
                 is_range = True, 
                 show_mode_change = False, 
                 show_inverted = True, 
                 inverted = False,
                 parent = None):
        '''
        :param data: the data object if any
        :param min_range: the default min range of the widget
        :param max_range: the default max range of the widget
        :param decimals: the number of decimal places to display 
        :param is_range: if set, the widget displays a min/max range, if false displays a single value range
        '''
        super().__init__(parent)
        
        self.data = data

        assert gremlin.util.valueInRange(min_norm,-1,1)
        assert gremlin.util.valueInRange(max_norm,-1,1)

        self._min_range = min_range # min possible input range
        self._max_range = max_range # max possible input range
        self._showCommandRange = True
        self._showNormalizedRange = True
        self._showPercentRange = True
        self._showDataRange = True
        self._showModeChange = show_mode_change
        self._decimals = decimals
        self._is_range = is_range
        self._inverted = inverted
        self._verbose = gremlin.config.Configuration().verbose

        min_cmd = gremlin.util.clamp(min_cmd, min_range, max_range)
        max_cmd = gremlin.util.clamp(max_cmd, min_range, max_range)

        self._last_cmd_min = min_cmd
        self._last_cmd_max = max_cmd

        self._last_min = min_cmd
        self._last_max = max_cmd


        main_layout = QtWidgets.QVBoxLayout(self)

        w = gremlin.shared_state.char_width * 12 # gremlin.ui.ui_common.get_text_width("0000000.0000")

        output_data_entry_widget = QtWidgets.QWidget()
        output_data_entry_layout = QtWidgets.QGridLayout(output_data_entry_widget)


         # output range                 
        self._command_min_widget = QFloatLineEdit()
        self._command_min_widget.setRange(min_range, max_range)
        self._command_min_widget.setValue(min_cmd)
        self._command_min_widget.valueChanged.connect(self._update_from_command)
        self._command_min_widget.setMinimumWidth(w)

        # output value
        min_output = gremlin.util.scale_to_range(min_norm, target_min = min_cmd, target_max = max_cmd)
        max_output = gremlin.util.scale_to_range(max_norm, target_min = min_cmd, target_max = max_cmd)

        # output percentage
        min_percent = gremlin.util.scale_to_range(min_norm, target_min = 0, target_max = 100) 
        max_percent = gremlin.util.scale_to_range(max_norm, target_min = 0, target_max = 100)

        # output range                 
        self._command_max_widget = QFloatLineEdit()
        self._command_max_widget.setRange(min_range, max_range)
        self._command_max_widget.setValue(max_cmd)
        self._command_max_widget.setMinimumWidth(w)
        self._command_max_widget.valueChanged.connect(self._update_from_command)
        

        # output min
        self._data_min_widget = QFloatLineEdit()
        self._data_min_widget.setRange(min_range, max_range)
        self._data_min_widget.setValue(min_output)
        self._data_min_widget.setMinimumWidth(w)
        self._data_min_widget.valueChanged.connect(self._update_from_output)

        # output max
        self._data_max_widget = QFloatLineEdit()
        self._data_max_widget.setRange(min_range, max_range)
        self._data_max_widget.setValue(max_output)
        self._data_max_widget.setMinimumWidth(w)
        self._data_max_widget.valueChanged.connect(self._update_from_output)

        
        

        # normalized is -1 to + 1
        self._normalized_min_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._normalized_min_widget.setRange(-1,1)
        self._normalized_min_widget.setValue(min_norm)
        self._normalized_min_widget.setMinimumWidth(w)
        self._normalized_min_widget.valueChanged.connect(self._update_from_normalized)
        
        
        
        self._normalized_max_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._normalized_max_widget.setRange(-1,1)
        self._normalized_max_widget.setValue(max_norm)
        self._normalized_max_widget.setMinimumWidth(w)
        
        self._normalized_max_widget.valueChanged.connect(self._update_from_normalized)
        
        

        self._percent_min_widget = gremlin.ui.ui_common.QFloatLineEdit(decimals=2)
        #self._output_min_percent_range_widget.setReadOnly(True)
        self._percent_min_widget.setRange(0,100)
        self._percent_min_widget.setValue(min_percent)
        self._percent_min_widget.setMinimumWidth(w)
        self._percent_min_widget.valueChanged.connect(self._update_from_percent)

        self._percent_max_widget = gremlin.ui.ui_common.QFloatLineEdit(decimals=2)
        #self._output_max_percent_range_widget.setReadOnly(True)
        self._percent_max_widget.setRange(0,100)
        self._percent_max_widget.setValue(max_percent)
        self._percent_max_widget.setMinimumWidth(w)
        self._percent_max_widget.valueChanged.connect(self._update_from_percent)
        


        # inverted flag
        self._invert_output_widget = QtWidgets.QCheckBox("Invert Output")
        self._invert_output_widget.setChecked(inverted)
        self._invert_output_widget.clicked.connect(self._inverted_changed)

        # options container
        widget, options_layout = getHContainer()
        options_layout.addWidget(self._invert_output_widget)

        main_layout.addWidget(widget)

        # single or range mode
        widgets = []
        widget = QDataRadioButton("Single Value",data=False)
        widget.clicked.connect(self._mode_changed)
        widgets.append(widget)
        widget = QDataRadioButton("Range Mode",data=True)
        widget.clicked.connect(self._mode_changed)
        widgets.append(widget)

        self._output_mode_widget, _ = getHContainer(widgets,"Output Mode:")
        

        options_layout.addWidget(self._output_mode_widget)
        options_layout.addStretch()

        grids = []

        self.grid_header, _ = getGridContainer(
            [   
                QtWidgets.QLabel(""),
                QtWidgets.QLabel("Min:"),
                QtWidgets.QLabel("Max:"),
            ]
        )

        grids.append(self.grid_header)

        self.grid_data, _ = getGridContainer(
            [   
                QtWidgets.QLabel("Output Value:"),
                self._data_min_widget,
                self._data_max_widget,
            ]
        )

        grids.append(self.grid_data)

        self.grid_normalized, _ = getGridContainer(
            [   
                QtWidgets.QLabel("Normalized:"),
                self._normalized_min_widget,
                self._normalized_max_widget,
            ]
        )

        grids.append(self.grid_normalized)

        self.grid_percent, _ = getGridContainer(
            [   
                QtWidgets.QLabel("Percent:"),
                self._percent_min_widget,
                self._percent_max_widget,
            ]
        )

        grids.append(self.grid_percent)


        
        self.grid_command, _ = getGridContainer(
            [   
                QtWidgets.QLabel("Command Range:"),
                self._command_min_widget,
                self._command_max_widget,
            ]
        )

        grids.append(self.grid_command)


        for grid in grids:
            main_layout.addWidget(grid)

        # make the grids line up
        synchronize_grids(grids)

        # hide grids by default
        self.grid_data.setVisible(self._showDataRange)
        self.grid_command.setVisible(self._showCommandRange)
        self.grid_header.setVisible(is_range)
        self._percent_max_widget.setVisible(is_range)
        self._output_mode_widget.setVisible(show_mode_change)
        self._normalized_max_widget.setVisible(is_range)
        self._normalized_min_widget.setVisible(is_range)
        self._data_max_widget.setVisible(is_range)
        self._invert_output_widget.setVisible(is_range)


        if self._verbose: syslog.info(f"JRANGE: init():   output: {min_output:0.3f} {max_output:0.3f} normalized: {min_norm:0.3f} {max_norm:0.3f} percent: {min_percent:0.3f} {max_percent:0.3f} cmd: {min_cmd:0.3f} {max_cmd:0.3f} ")


    @QtCore.Slot(bool)
    def _inverted_changed(self, checked):
        self.inverted = checked
        self.invertChanged.emit()

    @QtCore.Slot()
    def _mode_changed(self):
        ''' called when the mode changes from range (true) to single (false)'''
        widget = self.sender()
        self.isRange = widget.data
        is_range = widget.data
        self.isRange = is_range
        

    def _update_from_normalized(self, emit = True):

        min_cmd = self._command_min_widget.value() # minimum range
        if min_cmd is None:
            return # bad data
        
        max_cmd = self._command_max_widget.value() # maximum range
        if max_cmd is None:
            return # bad data

        min_norm = self._normalized_min_widget.value()
        if min_norm is None:
            return # bad data
        max_norm = self._normalized_max_widget.value()
        if max_norm is None:
            return # bad data
        min_cmd = self._command_min_widget.value() # minimum range
        max_cmd = self._command_max_widget.value() # maximum range

        min_value = gremlin.util.scale_to_range(min_norm, source_min = min_norm, source_max = max_norm, target_min=min_cmd, target_max=max_cmd) 
        max_value = gremlin.util.scale_to_range(max_norm, source_min = min_norm, source_max = max_norm, target_min=min_cmd, target_max=max_cmd) 
   
        if self._last_min != min_value or \
           self._last_max != max_value:


            min_percent = gremlin.util.scale_to_range(min_value, source_min=min_cmd, source_max=max_cmd, target_min = 0, target_max = 100) 
            max_percent = gremlin.util.scale_to_range(max_value, source_min=min_cmd, source_max=max_cmd, target_min = 0, target_max = 100)
            
            self._last_min = min_value
            self._last_max = max_value

            with QtCore.QSignalBlocker(self._data_min_widget):
                self._data_min_widget.setValue(min_value)
            with QtCore.QSignalBlocker(self._data_max_widget):
                self._data_max_widget.setValue(max_value)

            with QtCore.QSignalBlocker(self._percent_min_widget):
                self._percent_min_widget.setValue(min_percent)
            with QtCore.QSignalBlocker(self._percent_max_widget):
                self._percent_max_widget.setValue(max_percent)


            if self._verbose: syslog.info(f"JRANGE: update from normalized:   output: {min_value:0.3f} {max_value:0.3f} normalized: {min_norm:0.3f} {max_norm:0.3f} percent: {min_percent:0.3f} {max_percent:0.3f} cmd: {min_cmd:0.3f} {max_cmd:0.3f} ")

            if emit:
                if self._is_range:
                    self.valueChanged.emit((min_norm, max_norm))
                else:
                    self.valueChanged.emit(min_norm)


    def _update_from_percent(self, value : float,  emit = True):
        min_percent = self._percent_min_widget.value()
        if min_percent is None:
            return # bad data
        max_percent = self._percent_max_widget.value()
        if max_percent is None:
            return # bad data
        min_cmd = self._command_min_widget.value() # minimum range
        if min_cmd is None:
            return # bad data
        max_cmd = self._command_max_widget.value() # maximum range
        if max_cmd is None:
            return # bad data
        min_value = gremlin.util.scale_to_range(min_percent, source_min = 0, source_max = 100, target_min=min_cmd, target_max=max_cmd) 
        max_value = gremlin.util.scale_to_range(max_percent, source_min = 0, source_max = 100, target_min=min_cmd, target_max=max_cmd) 
        min_norm = gremlin.util.scale_to_range(min_value, source_min=min_cmd, source_max=max_cmd) # to -1, 1
        max_norm = gremlin.util.scale_to_range(max_value, source_min=min_cmd, source_max=max_cmd) # to -1, 1

        if self._last_min != min_value or \
           self._last_max != max_value:
            
            self._last_min = min_value
            self._last_max = max_value

            with QtCore.QSignalBlocker(self._data_min_widget):
                self._data_min_widget.setValue(min_value)
            with QtCore.QSignalBlocker(self._data_max_widget):
                self._data_max_widget.setValue(max_value)

            with QtCore.QSignalBlocker(self._normalized_min_widget):
                self._normalized_min_widget.setValue(min_norm)
            with QtCore.QSignalBlocker(self._normalized_max_widget):
                if max_norm == -1:
                    pass
                self._normalized_max_widget.setValue(max_norm)

            if self._verbose: syslog.info(f"JRANGE: update from percent:   output: {min_value:0.3f} {max_value:0.3f} normalized: {min_norm:0.3f} {max_norm:0.3f} percent: {min_percent:0.3f} {max_percent:0.3f} cmd: {min_cmd:0.3f} {max_cmd:0.3f} ")

            if emit:
                if self._is_range:
                    self.valueChanged.emit((min_norm, max_norm))
                else:
                    self.valueChanged.emit(min_norm)


    def _update_from_output(self, value, emit = True):
        min_cmd = self._command_min_widget.value() # minimum range
        if min_cmd is None:
            return # bad data
        
        max_cmd = self._command_max_widget.value() # maximum range
        if max_cmd is None:
            return # bad data

        min_norm = self._normalized_min_widget.value()
        if min_norm is None:
            return # bad data
        max_norm = self._normalized_max_widget.value()
        if max_norm is None:
            return # bad data
        min_cmd = self._command_min_widget.value() # minimum range
        max_cmd = self._command_max_widget.value() # maximum range

        min_source = self._data_min_widget.value()
        if min_source is None:
            return # bad data
        max_source = self._data_max_widget.value()
        if max_source is None:
            return # bad data
        
        min_range = self._min_range
        max_range = self._max_range

        min_value = gremlin.util.clamp(min_source, min_range, max_range)
        max_value = gremlin.util.clamp(max_source, min_range, max_range)

        min_norm = gremlin.util.scale_to_range(min_value, source_min=min_cmd, source_max=max_cmd) # to -1, 1
        max_norm = gremlin.util.scale_to_range(max_value, source_min=min_cmd, source_max=max_cmd) # to -1, 1
        min_percent = gremlin.util.scale_to_range(min_norm, source_min=min_norm, source_max=max_norm, target_min = 0, target_max = 100) 
        max_percent = gremlin.util.scale_to_range(max_norm, source_min=min_norm, source_max=max_norm, target_min = 0, target_max = 100)

        self._last_cmd_min = min_cmd
        self._last_cmd_max = max_cmd
        
        self._last_min = min_value
        self._last_max = max_value

        with QtCore.QSignalBlocker(self._normalized_min_widget):
            self._normalized_min_widget.setValue(min_norm)
        with QtCore.QSignalBlocker(self._normalized_max_widget):
            self._normalized_max_widget.setValue(max_norm)

        with QtCore.QSignalBlocker(self._percent_min_widget):
            self._percent_min_widget.setValue(min_percent)
        with QtCore.QSignalBlocker(self._percent_max_widget):
            self._percent_max_widget.setValue(max_percent)

        if self._verbose: syslog.info(f"JRANGE: update from output:   output: {min_value:0.3f} {max_value:0.3f} normalized: {min_norm:0.3f} {max_norm:0.3f} percent: {min_percent:0.3f} {max_percent:0.3f} cmd: {min_cmd:0.3f} {max_cmd:0.3f} ")

        if emit:
            if self._is_range:
                self.valueChanged.emit((min_norm, max_norm))
            else:
                self.valueChanged.emit(min_norm)
        

    def _update_from_command(self, value, emit = True):
        
        
        min_cmd = self._command_min_widget.value() # minimum range
        if min_cmd is None:
            return # bad data
        
        max_cmd = self._command_max_widget.value() # maximum range
        if max_cmd is None:
            return # bad data

        min_norm = self._normalized_min_widget.value()
        if min_norm is None:
            return # bad data
        max_norm = self._normalized_max_widget.value()
        if max_norm is None:
            return # bad data

        if self._last_cmd_min != min_cmd or \
           self._last_cmd_max != max_cmd:
        
            min_value = gremlin.util.scale_to_range(min_norm, source_min = min_norm, source_max = max_norm, target_min= min_cmd, target_max = max_cmd)
            max_value = gremlin.util.scale_to_range(max_norm, source_min = min_norm, source_max = max_norm, target_min= min_cmd, target_max = max_cmd)

            self._last_cmd_min = min_cmd
            self._last_cmd_max = max_cmd
            
            self._last_min = min_value
            self._last_max = max_value

            with QtCore.QSignalBlocker(self._data_min_widget):
                self._data_min_widget.setValue(min_value)
            with QtCore.QSignalBlocker(self._data_max_widget):
                self._data_max_widget.setValue(max_value)

            
            if self._verbose:
                min_percent = self._percent_min_widget.value()
                max_percent = self._percent_max_widget.value()
                if min_percent is None:
                    min_percent = self._percent_min_widget.value()
                    min_percent = 0
                if max_percent is None:
                    max_percent = 0

                syslog.info(f"JRANGE: update from command:   output: {min_value:0.3f} {max_value:0.3f} normalized: {min_norm:0.3f} {max_norm:0.3f} percent: {min_percent:0.3f} {max_percent:0.3f} cmd: {min_cmd:0.3f} {max_cmd:0.3f} ")

            if emit:
                if self._is_range:
                    self.rangeChanged.emit((min_cmd, max_cmd))
                    self.valueChanged.emit((min_norm, max_norm))
                else:
                    self.rangeChanged.emit(min_cmd)
                    self.valueChanged.emit(min_norm)



    @property
    def min_range(self) -> float:
        return self._data_min_widget.value()
    @min_range.setter
    def min_range(self, value: float):
        if self._data_min_widget.value() != value:
            self._data_min_widget.setValue(value)

    @property
    def max_range(self) -> float:
        return self._data_max_widget.value()
    @max_range.setter
    def max_range(self, value: float):
        if self._data_max_widget.value() != value:
            self._data_max_widget.setValue(value)


    @property
    def min_command(self) -> float:
        return self._command_min_widget.value()
    @min_command.setter
    def min_command(self, value: float):
        if self._command_min_widget.value() != value:
            self._command_min_widget.setValue(value)

    @property
    def max_command(self) -> float:
        return self._command_max_widget.value()
    @max_command.setter
    def max_command(self, value: float):
        if self._command_max_widget.value() != value:
            self._command_max_widget.setValue(value)      

    @property
    def inverted(self) -> bool:
        return self._inverted
    @inverted.setter
    def inverted(self, value : bool):
        if self._inverted != value:
            self._inverted = value
            self.invertChanged.emit()
            with QtCore.QSignalBlocker(self._invert_output_widget):
                self._invert_output_widget.setChecked(value)

    def setLimits(self, value : float, max_value : float = None):
        ''' sets the overall max values for command range and output values'''
        if value == max_value:
            # syslog = logging.getLogger("system")
            syslog.error(f"RANGE WIDGET: cannot set range to the same value: {value:0.3f} - skipping")
            return
        
        self._min_range = value
        self._max_range = value
        min_value = self._data_min_widget.value()
        max_value = self._data_min_widget.value()
        min_cmd = self._command_min_widget.value()
        max_cmd = self._command_max_widget.value()
        if not gremlin.util.valueInRange(min_value, self._min_range, self._max_range):
            value = gremlin.util.clamp(min_value, self._min_range, self._max_range)
            self._data_min_widget.setValue(value)
        if not gremlin.util.valueInRange(max_value, self._min_range, self._max_range):
            value = gremlin.util.clamp(max_value, self._min_range, self._max_range)
            self._data_max_widget.setValue(value)
        if not gremlin.util.valueInRange(min_cmd, self._min_range, self._max_range):
            value = gremlin.util.clamp(min_cmd, self._min_range, self._max_range)
            self._command_min_widget.setValue(value)
        if not gremlin.util.valueInRange(max_cmd, self._min_range, self._max_range):
            value = gremlin.util.clamp(max_cmd, self._min_range, self._max_range)
            self._command_max_widget.setValue(value)
        self._update_from_normalized()

    def setRange(self, value : float, max_value : float):
        ''' updates the overall command range min and max values '''
        
        with QtCore.QSignalBlocker(self._command_min_widget):
            self._command_min_widget.setRange(value, max_value)
            self._command_min_widget.setValue(value)
        
        with QtCore.QSignalBlocker(self._data_min_widget):
            self._data_min_widget.setRange(value, max_value)
        
        with QtCore.QSignalBlocker(self._command_max_widget):
            self._command_max_widget.setRange(value, max_value)
            self._command_max_widget.setValue(max_value)
    
        with QtCore.QSignalBlocker(self._data_max_widget):
            self._data_max_widget.setRange(value, max_value)

        self._update_from_command(None, False)

    def setPercent(self, percent : float, max_percent : float = None):
        ''' updates based on percentage'''
        percent = gremlin.util.clamp(percent,0, 100)
        with QtCore.QSignalBlocker(self._percent_min_widget):
            self._percent_min_widget.setValue(percent)

        if self._is_range:            
            assert max_percent is not None,"Missing max value must be provided in range mode"
            max_percent = gremlin.util.clamp(max_percent,0, 100)
            with QtCore.QSignalBlocker(self._percent_max_widget):
                self._percent_max_widget.setValue(max_percent)
        self._update_from_percent(None, False)

    def setNormalized(self, norm : float, max_norm : float = None):
        ''' updates range from normalized values (-1 to +1)'''
        norm = gremlin.util.clamp(norm,-1,1)
        with QtCore.QSignalBlocker(self._normalized_min_widget):
            self._normalized_min_widget.setValue(norm)

        if self._is_range:
            assert max_norm is not None,"Missing max value must be provided in range mode"
            max_norm = gremlin.util.clamp(max_norm,-1,1)
            with QtCore.QSignalBlocker(self._normalized_max_widget):
                self._normalized_max_widget.setValue(max_norm)
        
        self._update_from_normalized(False)

    def setValue(self, value : float, max_value: float = None):
        ''' updates normalized value '''
        self.setNormalized(value, max_value)


    def setOutput(self, min_value, max_value = None):
        ''' sets the output range value '''

        if self._is_range and max_value is None:
            # if the widget is a range value, expecting two data points
            raise ValueError()
        elif not self._is_range and max_value is None:
            # not a range item, make max the same as min
            max_value = min_value
        
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_detailed
        min_cmd = self._command_min_widget.value()
        if min_cmd is None:
            return # bad data
        max_cmd = self._command_max_widget.value()
        if max_cmd is None:
            return # bad data
        min_value = gremlin.util.clamp(min_value, min_cmd, max_cmd)
        max_value = gremlin.util.clamp(max_value, min_cmd, max_cmd)

        with QtCore.QSignalBlocker(self._data_min_widget):
            self._data_min_widget.setValue(min_value)
        with QtCore.QSignalBlocker(self._data_max_widget):
            self._data_max_widget.setValue(max_value)
        
        if verbose: syslog.info(f"Range widget set value: {min_value:0.3f} {max_value:0.3f}  commmand: {min_cmd:0.3f} {max_cmd:0.3f}")
        self._update_from_output(None, False)

    def getNormalized(self) -> tuple | float:
        ''' gets the normalized value '''
        if self._is_range:
            return (self._data_min_widget.value(), self._data_max_widget.value())
        else:
            return self._data_min_widget.value()
        
    def getValue(self) -> tuple | float:
        ''' returns normalized values -1 to + 1 (min,max)'''
        return self.getNormalized()


    def showCommandRange(self, value : bool):
        ''' show/hide the command range '''
        self._showCommandRange = value
        self.grid_command.setVisible(value)
        header_visible = not value and not self._is_range
        self.grid_header.setVisible(header_visible)
    
    def showPercentRange(self, value : bool):
        ''' show/hid the percentage range '''
        self._showPercentRange = value
        self.grid_percent.setVisible(value)
    
    def showNormalizedRange(self, value : bool):
        ''' show/hide the normalized range '''
        self._showNormalizedRange = value
        self.grid_normalized.setVisible(value)

    def showDataRange(self, value : bool):
        ''' show/hide the value range '''
        self._showDataRange = value
        self.grid_data.setVisible(value)

    def showModeChange(self, value: bool):
        ''' show/hide mode change radio buttons '''
        self._showModeChange = value
        self._output_mode_widget.setVisible(value)

    def showInverted(self, value: bool):
        self._showInverted = value
        self._invert_output_widget.setVisible(value)

    @property
    def isRange(self) -> bool:
        ''' enables single value mode if false or min/max mode if true'''
        return self._is_range
    @isRange.setter
    def isRange(self, value : bool):
        if value != self._is_range:
            self._is_range = value
            visible = value
            self._data_max_widget.setVisible(visible)
            self._normalized_max_widget.setVisible(visible)
            self._percent_max_widget.setVisible(visible)
            header_visible = self._is_range
            self.grid_header.setVisible(header_visible)
            self._invert_output_widget.setVisible(visible)
            self.modeChanged.emit()




class QVjoySelector(QtWidgets.QWidget):
    ''' widget to select a vjoy device '''

    selectionChanged = QtCore.Signal(object, int,  InputType, int) # fires when selection changes (device_guid, vjoy_id, input_type, input_id)

    def __init__(self, device_label = "Device:", input_label = "Input:", parent = None):
        super().__init__(parent)


        self._enable_hats = False # true if hat list enabled
        self._enable_buttons = False # true if button list enabled
        self._enable_axis = True  # true if axis list enabled

        self._current_device_guid = None # selected device
        self._current_vjoy_id = None # current vjoy #
        self._current_input_id = None # selected input id
        self._current_input_type = None # selected input type

        widget, layout = getVContainer()
        self.container_stepped_widget = widget
        self.container_stepped_layout = layout

        self.selector_device_widget = NoWheelComboBox()
        self.selector_input_widget = NoWheelComboBox()
        listen_widget = QtWidgets.QPushButton("Listen")
        listen_widget.clicked.connect(self._stepped_listen)

        device_widget = QtWidgets.QWidget()
        device_layout = QtWidgets.QGridLayout(device_widget)
        device_layout.addWidget(QtWidgets.QLabel(device_label),0,0)
        device_layout.addWidget(self.selector_device_widget,0,1)
        device_layout.addWidget(listen_widget,0,3)
        device_layout.addWidget(QtWidgets.QLabel(" "),0,4)
        device_layout.addWidget(QtWidgets.QLabel(input_label),1,0)
        device_layout.addWidget(self.selector_input_widget,1,1)
        device_layout.setColumnStretch(4,2)

        self.container_stepped_layout.addWidget(device_widget)
        self.container_stepped_layout.addWidget(self.step_value_container_widget)
        self.container_stepped_layout.addWidget(self.progression_container_widget)
        self.container_stepped_layout.addWidget(self.step_widget_container)

        self.selector_device_widget.currentIndexChanged.connect(self._device_changed_cb)
        self.selector_input_widget.currentIndexChanged.connect(self._input_changed_cb)

        self.stepped_device_map = {} # holds the device information keyed by device_id (str)
        self.input_map = {} # holds the list of buttons for the given device by device_id(str)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(self.container_stepped_widget)

        self._update_devices()
     


    def _update_devices(self):
        ''' reloads input choices in the selector '''
        
        devices = sorted(gremlin.joystick_handling.vjoy_devices(),key=lambda x: x.name)
        
        device_index = None
        current_index = 0
        dev: DeviceSummary
        axis_list = {}
        button_list = {}
        hat_list = {}
        with QtCore.QSignalBlocker(self.selector_device_widget):
            self.selector_device_widget.clear()
            for dev in devices:
                self.stepped_device_map[dev.device_id] = dev
                button_list = {}
                if self._enable_axis:
                    for input_id in range(1, dev.axis_count+1):
                        # if dev.device_guid == self.action_data.hardware_device_guid and \
                        #     input_id == self.action_data.hardware_input_id:
                        #     # skip self as a possible input
                        #     continue
                        axis_list[input_id] = f"Axis {input_id}"

                if self._enable_buttons:
                    for input_id in range(1, dev.button_count+1):
                        # if dev.device_guid == self.action_data.hardware_device_guid and \
                        #     input_id == self.action_data.hardware_input_id:
                        #     # skip self as a possible input
                        #     continue
                        button_list[input_id] = f"Button {input_id}"
                        
                if self._enable_hats:
                    for input_id in range(1, dev.hat_count+1):
                        # if dev.device_guid == self.action_data.hardware_device_guid and \
                        #     input_id == self.action_data.hardware_input_id:
                        #     # skip self as a possible input
                        #     continue
                        hat_list[input_id] = f"Hat {input_id}"


            
                    self.input_map[dev.device_id] = {}
                    self.input_map[dev.device_id][InputType.JoystickAxis] = axis_list
                    self.input_map[dev.device_id][InputType.JoystickButton] = button_list
                    self.input_map[dev.device_id][InputType.JoystickHat] = hat_list
                    self.selector_device_widget.addItem(dev.name, (dev.device_id, dev.joystick_id)) # data (device_guid, vjoy_id)

        self._select_first_device()


    def _update_inputs(self):
        ''' populates the device input list based on current filters - entry data is (input_type, input_id)'''
        device_guid, vjoy_id = self.selector_device_widget.currentData()
        current_index = 0
        selected_input_index = None
        self._current_device_guid = device_guid
        self._current_vjoy_id = vjoy_id
        active_input_id = self.current_input_id
        active_input_type = self.current_input_type

        with QtCore.QSignalBlocker(self.selector_input_widget):
            self.selector_input_widget.clear()
            first_input_id = None
            if self._enable_axis:
                for input_id, input_name in self.input_map[device_guid][InputType.JoystickAxis].items():
                    self.selector_input_widget.addItem(input_name, (InputType.JoystickAxis, input_id))
                    if first_input_id is None:
                        first_input_id = input_id
                    if selected_input_index is None and input_id == active_input_id:
                        selected_input_index = current_index
                    current_index +=1 
            if self._enable_buttons:
                for input_id, input_name in self.input_map[device_guid][InputType.JoystickButton].items():
                    self.selector_input_widget.addItem(input_name, (InputType.JoystickButton, input_id))
                    if first_input_id is None:
                        first_input_id = input_id
                    if selected_input_index is None and input_id == active_input_id:
                        selected_input_index = current_index
                    current_index +=1 
            if self._enable_hats:
                for input_id, input_name in self.input_map[device_guid][InputType.JoystickHat].items():
                    self.selector_input_widget.addItem(input_name, (InputType.JoystickHat, input_id))
                    if first_input_id is None:
                        first_input_id = input_id
                    if selected_input_index is None and input_id == active_input_id:
                        selected_input_index = current_index
                    current_index +=1 


            self._select_input(active_input_type, active_input_id)
                


    @property
    def input_id(self) -> int:
        return self._current_input_id
    
    def setAxisEnabled(self, value:bool):
        if self._enable_axis != value:
            self._enable_axis = value
            self._update_inputs()

    def setButtonsEnabled(self, value:bool):
        if self._enable_buttons != value:
            self._enable_buttons = value
            self._update_inputs()
    
    def setHatsEnabled(self, value:bool):
        if self._enable_hats != value:
            self._enable_hats = value
            self._update_inputs()

    
    @input_id.setter
    def input_id(self, value : int):
        
        if value < 1:
            syslog.error(f"Invalid input id: {value}")
            return # invalid value
        
        if value == self._current_input_id:
            # nothing to do
            return
        
        info = gremlin.joystick_handling.device_info_from_guid(self._current_device_guid)
        if info:
            match self._current_input_type:
                case InputType.JoystickAxis:
                    if value <= info.axis_count:
                        self._current_input_id = value
                case InputType.JoystickButton:
                    if value <= info.button_count:
                        self._current_input_id = value
                case InputType.JoystickHat:
                    if value <= info.hat_count:
                        self._current_input_id = value

            self._select_input(self._current_input_type, self._current_input_id)

    def _select_input(self, input_type, input_id):
        ''' selects the entry in the control for the given input type and input ID if it exists'''

        key = (input_type, input_id)
        index = self.selector_input_widget.findData(key)
        if index != -1:
            self.selector_input_widget.setCurrentIndex(index)
            return True
        return False
    

    def _select_first_device(self):
        ''' selects the first device if there is a device to select '''
        if self.selector_device_widget.count():
            self.selector_device_widget.setCurrentIndex(0)
    
    def _select_first_input(self):
        ''' selects the first input if there is an input to select '''
        if self.selector_input_widget.count():
            self.selector_input_widget.setCurrentIndex(0)
            
    def _select_device(self, device_guid, input_type, input_id):

        key = device_guid
        index = self.selector_device_widget.findData(key)
        if index != -1:
            self.selector_device_widget.setCurrentIndex(index)


    @QtCore.Slot()
    def _device_changed_cb(self):
        ''' called when device selection changes '''
        device_guid = self.selector_device_widget.currentData()
        self._current_device_guid = device_guid
        self._select_first_input()

    @QtCore.Slot()
    def _input_changed_cb(self):
        ''' called when the input selection changed '''
        input_type, input_id = self.selector_input_widget.currentData()
        
        self._current_input_id = input_id
        self._current_input_type = input_type
        self.selectionChanged.emit(self._current_device_guid, self._current_vjoy_id, input_type, input_id)


class QPaginator(QtWidgets.QWidget):
    ''' table view that displays paginated data '''
    pageChanged = QtCore.Signal(int, int, int) # fires when the page is changed (page_number, start_index, end_index)

    def __init__(self, item_count = 0, page_size=10):
        ''' setups the data model and callback to get a model by index '''
        super().__init__()
        self._item_count = item_count
        self._page_size = page_size
        self._current_page = 1
        self._total_pages = 0
        self._start_index = 0
        self._end_index = 0

        self.init_ui()
        self._update_data()
        
    @property
    def totalPages(self) -> int:
        ''' number of total pages '''
        return self._total_pages
    
    @property
    def startIndex(self) -> int:
        ''' gets the paginators first row index '''
        return self._start_index
    
    @property
    def endIndex(self) -> int:
        ''' gets the paginator end row index '''
        return self._end_index
    
    @property
    def itemCount(self) -> int:
        return self._item_count

    def _update_data(self, emit = True):
        self.total_pages = (self._item_count + self._page_size - 1) // self._page_size
        self._update_data_view(emit)

    def setItemCount(self, count, emit = True):
        self._item_count = count
        self._update_data(emit)
    
    def setPageSize(self, page_size: int, emit = True):
        self._page_size = page_size
        self._update_data(emit)

    def setPageNumber(self, page_number: int, emit = True):
        ''' set page 1 to n'''
        if page_number < 1:
            page_number = 1
        self._current_page = page_number
        self._update_data(emit)


    def init_ui(self):
        self._prev_button_widget = QtWidgets.QPushButton("Previous")
        self._prev_button_widget.clicked.connect(self._prev_page)
        self._next_button_widget = QtWidgets.QPushButton("Next")
        self._next_button_widget.clicked.connect(self._next_page)

        self._page_label_widget = QtWidgets.QLabel(f"Page {self._current_page} of {self._total_pages}")
        self._page_input_widget = QtWidgets.QLineEdit()
        self._page_input_widget.returnPressed.connect(self._go_to_page)

        hbox = QtWidgets.QHBoxLayout()
        hbox.addWidget(self._prev_button_widget)
        hbox.addWidget(self._page_label_widget)
        hbox.addWidget(self._page_input_widget)
        hbox.addWidget(self._next_button_widget)

        vbox = QtWidgets.QVBoxLayout()
        vbox.addLayout(hbox)

        self.setLayout(vbox)

    def _update_data_view(self, emit = True):

        self._page_label_widget.setText(f"Page {self._current_page} of {self.total_pages}")
        if self._item_count:
            self._start_index = (self._current_page - 1) * self._page_size
            self._end_index = min(self._start_index + self._page_size,  self._item_count)
            if emit:
                self.pageChanged.emit(self._current_page, self._start_index, self._end_index)
            

    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._update_data_view()

    def _next_page(self):
        if self._current_page < self.total_pages:
            self._current_page += 1
            self._update_data_view()
    
    def _go_to_page(self):
        text = self._page_input_widget.text()
        if text and text.isnumeric():
            page_num = int(text)
            if 1 <= page_num <= self.total_pages:
                self._current_page = page_num
                self._update_data_view()
            else:
                self._page_input_widget.clear()



class IconGenerator():
    def __init__(self):
        for index in range(128):
            text = f"{index+1}"
            name = f"icon_button_{index+1:03}"
            self.gen(text, name,  False)
            self.gen(text, name, True)
        axes = ["X","Y","Z","S1","S2","RX","RY","RZ"]
        for index, text in enumerate(axes):
            axis = index+1
            name = f"icon_axis_{axis:03}"
            self.gen(text, name, False)
            self.gen(text, name, True)

    def gen(self, text : str, name : str,  is_dark = False):
        ''' creates the background for the image'''
        size = 64
        image = QtGui.QImage(size,size,QtGui.QImage.Format.Format_ARGB32)
        painter = QtGui.QPainter(image)
        background_color = QtGui.QColor(0x00, 0x00, 0x00, 0x00)
        image.fill(background_color)

        foreground_color = QtGui.QColor(Color.normalDarkColor() if is_dark else Color.normalLightColor())
        painter.setPen(foreground_color)
        font = QtGui.QFont("Arial", 24)
        painter.setFont(font)

        metrics = QtGui.QFontMetrics(font)
        text_rect = metrics.boundingRect(text)
        widget_rect = QtCore.QRect(0,0,size,size)
        

        text_y = widget_rect.y() + (widget_rect.height() - text_rect.height()) / 2 + metrics.ascent()
        text_x = widget_rect.x() + (widget_rect.width() - text_rect.width()) / 2
       

        painter.drawText(text_x, text_y, text)

        painter.end()

        prefix = "dark_" if is_dark else ""
        folder = os.path.join(gremlin.shared_state.root_path,"icons")
        if not os.path.isdir(folder):
            os.mkdir(folder)

        image_path = os.path.join(folder,f"{prefix}{name.casefold()}.png")
        if os.path.isfile(image_path):
            os.unlink(image_path)

        pixmap = QtGui.QPixmap.fromImage(image)
        pixmap.save(image_path, "PNG")

        
