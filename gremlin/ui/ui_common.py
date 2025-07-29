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
import enum
import time
import threading
import anytree
import os
from typing import Optional
import logging
from PySide6 import QtWidgets, QtCore, QtGui
import gremlin.actions
import gremlin.base_classes
import gremlin.config
import gremlin.error
import qtawesome as qta
import gremlin.event_handler
from gremlin.input_types import InputType
from shiboken6 import Shiboken
import gremlin.input_types
import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.shared_state
import gremlin.types
from lxml import etree
from qtpy.QtCore import (
    Qt, QSize, QPoint, QPointF, QRectF,
    QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup,
    Slot, Property)

from qtpy.QtWidgets import QCheckBox
from qtpy.QtGui import QColor, QBrush, QPaintEvent, QPen, QPainter, QStandardItemModel, QStandardItem, QLinearGradient



from gremlin.util import load_pixmap, load_icon, safe_format, safe_read
import gremlin.util
import gremlin.ui.ui_common
from gremlin.singleton_decorator import SingletonDecorator
from gremlin.types import HatDirection
from dinput import DeviceSummary
import psygnal
from psygnal import Signal

syslog = logging.getLogger("system")

    
       

class Color():
    ''' general UI color and stylesheet handling '''
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
    def selectedBackgroundColor():
        return Color.selectColor()
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
    def alternateSelectColor():
        return "#8a761c" if gremlin.shared_state.is_dark_theme else "#bcaf8f"
    @staticmethod
    def selectGradientColor():
        return "#448044" if gremlin.shared_state.is_dark_theme else "#568f56"
    @staticmethod
    def alternateSelectGradientColor():
        return "#754e17" if gremlin.shared_state.is_dark_theme else "#568f56"
    @staticmethod
    def selectEndGradientColor():
        return "#8ac18a" if gremlin.shared_state.is_dark_theme else "#8FBC8F"
    @staticmethod
    def selectGradientAltColor():
        return "#448080" if gremlin.shared_state.is_dark_theme else "#568c8f"
    @staticmethod
    def selectEndGradientAltColor():
        return "#8ac1be" if gremlin.shared_state.is_dark_theme else "#8fb5bc"    
    @staticmethod
    def selectBorderColor():
        return "#408540" if gremlin.shared_state.is_dark_theme else "#76c276"    
    @staticmethod
    def alternateSelectBorderColor():
        return "#997e14" if gremlin.shared_state.is_dark_theme else "#c2b476"    
    @staticmethod
    def expressionColor():
        return "#cc7d1f"
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
    def keyHoverBackgroundColor():
        return "#525252" if gremlin.shared_state.is_dark_theme else "#F0F0F0"
    @staticmethod
    def keyHoverSelectedBackgroundColor():
        return "#9ab19a" if gremlin.shared_state.is_dark_theme else "#F0F0F0"
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
        return "#CCCCCC" if gremlin.shared_state.is_dark_theme else "#222222"
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
    def buttonBackgroundColor():
        return "#414141" if gremlin.shared_state.is_dark_theme else "#414141"
    @staticmethod
    def buttonColor():
        return Color.normalColor()
    @staticmethod
    def buttonBorderColor():
        return Color.keyBorderColor()
    def buttonHoverBorderColor():
        return Color.keyHoverBorderColor()
    @staticmethod
    def buttonHoverBackgroundColor():
        return Color.keyHoverBackgroundColor()
    @staticmethod
    def warningColor(): # color for the warning flag
        return "#ab8d18" if gremlin.shared_state.is_dark_theme else "#fc1900"
    @staticmethod
    def disconnectedBackgroundColor(): # color for the disconnected device 
        return "#ab8d18" if gremlin.shared_state.is_dark_theme else "#fc1900"
    @staticmethod
    def disconnectedColor(): # color for the disconnected device 
        return "#db6512"
    @staticmethod
    def unmappedColor(): # color for the unmapped device 
        return "#a1a1a1" if gremlin.shared_state.is_dark_theme else "#5a5a5a"
    @staticmethod
    def mappedColor(): # color for the unmapped device 
        return "#ffffff" #if gremlin.shared_state.is_dark_theme else "#5a5a5a"
    @staticmethod
    def listenColor(): # color used for listen type buttons
        return "#34b7eb"
    @staticmethod
    def infoColor(): # color used for information boxes
        return "#92882b"
    @staticmethod
    def inputTitleColor(): # color for the input title bar
        return "#5A725A" if gremlin.shared_state.is_dark_theme else "#678867"
    @staticmethod
    def inputTitleUnselectedColor(): # color for the input title bar
        return "#3A3A3A" if gremlin.shared_state.is_dark_theme else "#7C7C7C"
    @staticmethod
    def repeaterColor(): # color for repeaters
        return "#0C8D12"
    def repeaterBackgroundColor(): # color for repeaters
        return "#374438"
    
    @staticmethod
    def cssInputHeader(): 
        background_color = Color.inputTitleColor()
        button_background_color = Color.buttonBackgroundColor()
        css = f"#title_bar {{ background: {background_color}; max-height = 32px;}} QPushButton {{ background: {button_background_color};}}"
        return css
    
    @staticmethod
    def cssUnselectedInputHeader(): 
        background_color = Color.inputTitleUnselectedColor()
        button_background_color = Color.buttonBackgroundColor()
        css = f"#title_bar {{ background: {background_color}; max-height = 32px; }} QPushButton {{ background: {button_background_color};}}"
        return css
    
    

    @staticmethod
    def cssButton(): 
        background_color = Color.buttonBackgroundColor()
        css = f" QPushButton {{ background: {background_color};}}"
        return css

    @staticmethod
    def cssRepeater():
        background_color = Color.repeaterBackgroundColor()
        color = Color.repeaterColor()
        css = f"QProgressBar {{ background: {background_color}; color: {color}}}"
        return css


    @staticmethod
    def cssInfoBox(): 
        border_color = Color.borderColor()
        background_color = Color.infoColor()
        css = f'''
            QFrame {{
                border: 0px solid {border_color};
                background: {background_color};
            }}
            QLabel {{
                border: none;
            }}
            '''
        return css
    
    

    @staticmethod
    def cssApplication():
        border_color = Color.borderColor()
        background_color = Color.backgroundColor()
        foreground_color = Color.normalColor
        selected_background_color = Color.selectedBackgroundColor()
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
            QLineEdit {{
                border: 1px solid {border_color};
            }}
            QScrollArea {{
                border: 1px solid {border_color};
            }}
            QComboBox {{
                border: 1px solid {border_color};
            }}
            QListView::item:selected {{
                background: {selected_background_color}
            }}

            QListView {{
                border: 1px solid {border_color};
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

        QPushButton:checked {{
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
    def _cssStateButton(font_size,
                        normal_color,
                        normal_gradient_color,
                        background_color,
                        border_color,
                        selected_border_color,
                        selected_color,
                        selected_gradient_color):
        min_size = font_size * 2
        radius = font_size 
        css = f'''
        QPushButton {{
            border: 2px solid #8f8f91;
            border-radius: {radius}px;
            background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {normal_color}, stop: 1 {normal_gradient_color});
            min-width: {min_size}px;
            min-height: {min_size}px;
            padding-left: 4px;
            padding-right: 4px;
            font-size: {font_size}px;
        }}

        QPushButton:pressed {{
            background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {selected_color}, stop: 1 {selected_gradient_color});
            border-color: {selected_border_color};
        }}

        QPushButton:checked {{
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
    def cssStateButton(font_size = 16):
        ''' gets a pushbutton state for the input viewer '''

        normal_color = Color.normalColor()
        normal_gradient_color = Color.normalGradientColor()
        background_color = Color.keyBackgroundColor()
        
        border_color = Color.borderColor()
        selected_border_color = Color.selectBorderColor()
        selected_color = Color.selectColor()
        selected_gradient_color = Color.selectGradientColor()
        return Color._cssStateButton(font_size, 
                                    normal_color,
                                    normal_gradient_color,
                                    background_color,
                                    border_color,
                                    selected_border_color,
                                    selected_color,
                                    selected_gradient_color)

    
    @staticmethod
    def cssStateExpressionButton(font_size = 16):
        ''' gets a pushbutton state for the input viewer '''

        normal_color = Color.normalColor()
        normal_gradient_color = Color.normalGradientColor()
        background_color = Color.keyBackgroundColor()
        border_color = Color.borderColor()
        selected_border_color = Color.alternateSelectBorderColor()
        selected_color = Color.alternateSelectColor()
        selected_gradient_color = Color.alternateSelectGradientColor()
        return Color._cssStateButton(font_size, 
                                normal_color,
                                normal_gradient_color,
                                background_color,
                                border_color,
                                selected_border_color,
                                selected_color,
                                selected_gradient_color)
 
    
    
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
    


class Icons():
    ''' general UI icon handling '''
    @staticmethod
    def listUpIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("ph.caret-circle-up-light", qta_color)
    @staticmethod
    def listDownIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("ph.caret-circle-down-light", qta_color)
    @staticmethod
    def listTopIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("ph.caret-circle-double-up-light", qta_color)
    @staticmethod
    def listBottomIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("ph.caret-circle-double-down-light", qta_color)
    @staticmethod
    def trashIcon(qta_color = "#34b7eb") -> QtGui.QIcon:
        return Icons._icon("ei.trash", qta_color)
    @staticmethod
    def keyboardIcon(qta_color = "#34b7eb") -> QtGui.QIcon:
        return Icons._icon("fa6s.keyboard", qta_color)
    @staticmethod
    def addIcon(qta_color = "#34b7eb") -> QtGui.QIcon:
        return Icons._icon("msc.diff-added", qta_color)
    @staticmethod
    def removeIcon(qta_color = "#34b7eb") -> QtGui.QIcon:
        return Icons._icon("fa6s.minus", qta_color)
    @staticmethod
    def gearIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("fa6s.gear", qta_color)
    @staticmethod
    def findIcon(qta_color = "#34b7eb") -> QtGui.QIcon:
        return Icons._icon("fa6s.magnifying-glass", qta_color)
    @staticmethod
    def refreshIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("ei.refresh", qta_color)
    @staticmethod
    def copyIcon(qta_color = "#34b7eb") -> QtGui.QIcon:
        return Icons._icon("fa6.copy", qta_color)
    @staticmethod
    def pasteIcon(qta_color = "#34b7eb") -> QtGui.QIcon:
        return Icons._icon("fa6.paste", qta_color)
    @staticmethod
    def configureIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("fa6s.gear", qta_color)
    @staticmethod
    def editIcon(qta_color = "#34b7eb") -> QtGui.QIcon:
        return Icons._icon("mdi6.rename-box-outline", qta_color)
    @staticmethod
    def horizontalSeparatorIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("mdi.power-on", qta_color)
    @staticmethod
    def calculateIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("ph.math-operations", qta_color)
    @staticmethod
    def axisIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("mdi.axis", qta_color)
    @staticmethod
    def buttonIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("ri.radio-button-line", qta_color)
    @staticmethod
    def hatIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("fa5s.arrows-alt", qta_color)
    @staticmethod
    def validIcon(qta_color = "#2abd38") -> QtGui.QIcon:
        return Icons._icon("fa5.check-circle", qta_color = qta_color)
    @staticmethod
    def invalidIcon(qta_color = "#b35f1b") -> QtGui.QIcon:
        return Icons._icon("ei.remove-circle", qta_color = qta_color)
    @staticmethod
    def recordIcon(qta_color = "#c7450e"):
        return Icons._icon("mdi.checkbox-blank-circle", qta_color = qta_color)
    @staticmethod
    def listenIcon(qta_color = "#34b7eb"):
        return Icons._icon("fa6s.microphone", qta_color = qta_color)
    @staticmethod
    def disconnectedIcon(qta_color = Color.disconnectedColor()):
        return Icons._icon("mdi.power-plug-off", qta_color = qta_color)
    @staticmethod
    def warningIcon():
        return Icons._icon("ph.shield-warning-fill",qta_color=QtGui.QColor(Color.warningColor()))
    @staticmethod
    def mappedIcon():
        return Icons._icon("fa5.map")

    def _icon(value : str, qta_color = None):
        if qta_color and isinstance(qta_color, str):
            qta_color = QtGui.QColor(qta_color)
        return load_icon(value, qta_color = qta_color) if qta_color is not None else load_icon(value)
    
    def to_pixmap(icon : QtGui.QIcon, pixels = 24):
        ''' convers an icon to a pixmap'''
        #icon : QtGui.QIcon = Icons.warningIcon()
        return icon.pixmap(QtCore.QSize(pixels, pixels))
        
        

class Buttons():
    ''' common UI button widgets '''

    maxHeight = 24 # max height in pixels

    @staticmethod
    def _template(label = "", icon_source : str = "", tooltip = None, callback = None, no_keyboard = True, data = None, width : int = None):
        if no_keyboard:
            widget = NoKeyboardPushButton()
        else:
            widget = QDataPushButton()

        widget.data = data
        if label:
            widget.setText(label)

        if icon_source:
            if isinstance(icon_source, str):
                icon = gremlin.util.load_icon(icon_source)
            elif isinstance(icon_source, QtGui.QIcon):
                icon = icon_source
            else:
                icon = None
            if icon:
                widget.setIcon(icon)
        widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Minimum)
        if tooltip:
            widget.setToolTip(tooltip)
        if callback:
            widget.clicked.connect(callback)
        widget.setMaximumHeight(Buttons.maxHeight)
        if width is not None:
            widget.setMaximumWidth(width)
        return widget
    
    @staticmethod
    def getDeleteWidget(label = None, tooltip = "Delete", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, "mdi6.delete", tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getAddWidget(label = "Add", tooltip = "Add", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, "ri.add-line", tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getRemoveWidget(label = "Remove", tooltip = "Remove", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, "mdi.close-box-outline", tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getEditWidget(label = None, tooltip = "Edit", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, "msc.edit", tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getKeyboardWidget(label = None, tooltip = "Select Keys", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, "fa5.keyboard", tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getHelpWidget(label = None, tooltip = "Help", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, "mdi.help", tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getGrabWidget(label = None, tooltip = "Grab Value", callback = None, no_keyboard = True, data = None, width = 24):
        return Buttons._template(label, Icons.recordIcon(), tooltip, callback, no_keyboard, data, width = width)
    
    @staticmethod
    def getListenWidget(label = "Listen", tooltip = "Listen for input", callback = None, no_keyboard = True, data = None, width = None):
        return Buttons._template(label, Icons.listenIcon(), tooltip, callback, no_keyboard, data, width = width)

    @staticmethod
    def getClearWidget(label = "Clear", tooltip = "Clear", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, Icons.trashIcon(), tooltip, callback, no_keyboard, data)

    @staticmethod
    def getOkWidget(label = "Ok", tooltip = "Accept", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, None, tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getCancelWidget(label = "Cancel", tooltip = "Cancel", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, None, tooltip, callback, no_keyboard, data)
    
        

    @staticmethod
    def getPasteWidget(tooltip = "Paste", callback = None):
        ''' creates a paste widget 
        
        :param tooltip: the tooltip to show
        :callback : optional the callback on click
        '''
        return Buttons._template(None, Icons.pasteIcon(), tooltip, callback)
        
    
    @staticmethod
    def getCopyWidget(tooltip = "Copy", callback = None):
        ''' creates a copy widget 
        
        :param tooltip: the tooltip to show
        :callback : optional the callback on click
        
        '''
        return Buttons._template(None, Icons.copyIcon(), tooltip, callback)
        
    

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
        verbose = gremlin.config.Configuration().verbose_mode_ui
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
                        if self._widget_cache[device_guid][mode][input_type][input_id]:
                            if key in self._widget_cache[device_guid][mode][input_type][input_id]:
                                self._widget_cache[device_guid][mode][input_type][input_id][key] = None


    def clear(self):
        self._widget_cache = {}
        verbose = gremlin.config.Configuration().verbose_mode_ui
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
        
        if gremlin.shared_state.is_repeater_suspended():
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
        
        from shiboken6 import Shiboken
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        # syslog = logging.getLogger("system")
        #device_name = gremlin.shared_state.get_device_name(device_guid)
        if device_guid in self._button_cache:
            if input_type in self._button_cache[device_guid]:
                key = self._key(input_id)
                if key in self._button_cache[device_guid][input_type]:
                    widget = self._button_cache[device_guid][input_type][key]
                    if Shiboken.isValid(widget) and widget.enabled:
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
        if gremlin.shared_state.is_repeater_suspended():
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
 


#_tabsplitter_tracker = WidgetTracker()
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

    data_changed = Signal()

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
        self._container = None

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

    def setModel(self, model):
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




class QFloatLineEdit(QtWidgets.QWidget):
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
        self._value = None
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)

        self._widget = QtWidgets.QLineEdit()
        self._widget.textChanged.connect(self._validate)

        self.main_layout.addWidget(self._widget)

        self.installEventFilter(self)
        #self.setText("0")
        self.setValue(value)
        self._data = data
        if chars > 0:
            self._chars = chars
            self._update_width(chars)
        else:
            self.chars = 0


    def setReadOnly(self, value : bool):
        ''' sets or clears readonly state '''
        self._widget.setReadOnly(value)

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
            if self._widget.isReadOnly():
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
                return True

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


    def _update_value(self, value, format = True):
        gremlin.util.assert_ui_thread()
        if value is None:
            return
        current_value = self._value

        if self._decimals:
            s_value = f"{float(value):0.{self._decimals}f}"
        else:
            s_value = str(value)
        if self._widget.text() != s_value:
            with QtCore.QSignalBlocker(self):
                self._widget.setText(s_value)
        if current_value is None or current_value != value:
            self._value = value
            self.valueChanged.emit(value)



    @QtCore.Slot()
    def _validate(self):
        ''' called whenever the text changes '''
        text = self._widget.text()
        try:
            value = float(text)
            self._update_value(value, format = False)
            return True
        except:
            return False
        

    def setValue(self, value : float):
        ''' sets the value '''
        if not gremlin.util.is_close(self._value, value):
            gremlin.util.InvokeUiMethod(self._update_value, value)
            

    def _to_value(self, text : str = None):
        if text is None:
            text = self._widget.text()
        try:
            if text:
                value = float(text)
            else:
                return None
        except:
            return None
        
        if value < self._min_range:
            value = self._min_range
        elif value > self._max_range:
            value = self._max_range
        
        return value
        

    def value(self) -> float:
        ''' current value, None if not a valid input'''
        return self._value

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
    
    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self._data = value
    

class QFloatLineEditEx(QtWidgets.QWidget):
    ''' double input validator with optional range limits for input axis

        this line edit behaves like a spin box so it's interchangeable

    '''
    
    valueChanged = QtCore.Signal(float) # fires when the value changes
    doubleClick = QtCore.Signal() # fires when the input is double clicked


    def __init__(self, data = None, min_range = -1.0, max_range = 1.0, decimals = 3, step = 0.01, value = 0.0, chars = 8, parent = None):
        super().__init__(parent)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self._widget = QtWidgets.QLineEdit()
        self.main_layout.addWidget(self._widget)
        
        self._min_range = min_range
        self._max_range = max_range
        self._step = step
        self._decimals = decimals
        self._value = None      
        #self._validator = QFloatLineEdit.FloatValidator(bottom=min_range, top=max_range)
        self._validator = QtGui.QDoubleValidator(bottom=min_range, top=max_range)
        self._validator.setLocale(self.locale()) # handle correct floating point separator
        self._validator.setNotation(QtGui.QDoubleValidator.Notation.StandardNotation)
        self._widget.setValidator(self._validator)
        self._widget.textChanged.connect(self._validate)
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


    def isReadOnly(self) -> bool:
        return self._widget.isReadOnly()
    
    def setReadOnly(self, value : bool):
        self._widget.setReadOnly(value)


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
        other = self._value
        if other is None or other != value:
            s_value = f"{float(value):0.{self._decimals}f}"
            self._value = value
            if s_value != self._widget.text():
                with QtCore.QSignalBlocker(self):
                    self._widget.setText(s_value)
                
            self.valueChanged.emit(value)



    @QtCore.Slot()
    def _validate(self):
        ''' called whenever the text changes '''
        if self._widget.hasAcceptableInput():
            value = self.value()
            self._update_value(value)
            
            

    def setValue(self, value : float):
        ''' sets the value '''
        self._update_value(value)

    def value(self) -> float:
        ''' current value, None if not a valid input'''
        if self._widget.hasAcceptableInput():
            return float(self._widget.text())
        try:
            text = self._widget.text()
            if text:
                v = float(text)
                return v
        except:
            pass
        return None

    def isValid(self):
        ''' true if the input in the box is currently valid'''
        return self._widget.hasAcceptableInput()

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

    input_changed = QtCore.Signal() # fires when the input changes 

    def __init__(self, change_cb, valid_types, parent=None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.grid_layout = QtWidgets.QGridLayout()
        self.main_layout.addLayout(self.grid_layout)

        self.grid_layout.addWidget(QtWidgets.QWidget(),0,2)
        self.grid_layout.setColumnStretch(2,2)

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
        self.grid_layout.addWidget(QtWidgets.QLabel("Device:"),0,0)
        self.grid_layout.addWidget(self.device_dropdown,0,1)
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
            selection_widget = QComboBox(self)
            # limit drop down size
            selection_widget.setMaxVisibleItems(20)
            selection_widget.setStyleSheet("QComboBox { combobox-popup: 0; }")
            self._input_type_registry.append([])
            self.selection_widget = selection_widget
            selection_widget.currentIndexChanged.connect(self._input_changed)

            # Add items based on the input type
            max_col = 32

            for input_type in self.valid_types:
                item_count = count_map[input_type](device)
                for i in range(item_count):
                    input_id = i+1
                    if input_type == InputType.JoystickAxis:
                        input_id = device.axismap_list[i].axis_index
                        s_ui = f"Axis {device.axis_names[i]}"
                    else:
                        s_ui = gremlin.common.input_to_ui_string(
                            input_type,
                            input_id
                        )
                    selection_widget.addItem(s_ui, (input_type, input_id))

                    self._input_type_registry[-1].append(input_type)

            # Add the selection and hide it
            selection_widget.setVisible(False)
            selection_widget.activated.connect(self._execute_callback)
            self.grid_layout.addWidget(QtWidgets.QLabel("Input:"),1,0)
            self.grid_layout.addWidget(selection_widget, 1,1)

            self.input_item_dropdowns.append(selection_widget)

            selection_widget.currentIndexChanged.connect(self._execute_callback)

        # Show the first entry by default
        if len(self.input_item_dropdowns) > 0:
            self.input_item_dropdowns[0].setVisible(True)

    @QtCore.Slot()
    def _input_changed(self):
        ''' called when the input changes '''
        self.input_changed.emit()


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


    def __init__(self, input_type, input_item, parent=None):
        """Creates a new selector instance.

        :param input_type the input type for which the action selector is being created
        :param container: the owner container
        :param parent the parent of this widget
        """
        super().__init__(parent)



        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.action_label = QtWidgets.QLabel("Action")
        self.main_layout.addWidget(self.action_label)


        self.action_dropdown = QComboBox()
        self.action_dropdown.currentIndexChanged.connect(self._action_changed)
        self.refresh(input_type)
        
        self.add_button = QtWidgets.QPushButton("Add")
        self.add_button.clicked.connect(self._add_action)

        # clipboard
        self.paste_button = gremlin.ui.ui_common.Buttons.getPasteWidget(callback=self._paste_action)
        self.paste_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Minimum)
        self.paste_button.setToolTip("Paste Action")


        self.main_layout.addWidget(self.action_dropdown)
        self.main_layout.addWidget(self.add_button)
        self.main_layout.addWidget(self.paste_button)
        self.main_layout.addStretch(1)

        eh = gremlin.event_handler.EventHandler()
        eh.last_action_changed.connect(self._last_action_changed)
        self._container = None

    def refresh(self, input_type):
        ''' reloads the selector based on the input '''
        self.input_type = input_type
        with QtCore.QSignalBlocker(self.action_dropdown):
            self.action_dropdown.clear()
            for name in self._valid_action_list(input_type):
                self.action_dropdown.addItem(name)
            config = gremlin.config.Configuration()
            self.action_dropdown.setCurrentText(config.last_action)
        

    @property
    def inputItem(self):
        return self._input_item
    @inputItem.setter
    def inputItem(self, value):
        self._input_item = value


    @QtCore.Slot(object, str)
    def _last_action_changed(self, widget, name):
        if not Shiboken.isValid(self):
            return
        if not Shiboken.isValid(widget):
            return
        if widget != self.action_dropdown:
            with QtCore.QSignalBlocker(self.action_dropdown):
                self.action_dropdown.setCurrentText(name)

    def _action_changed(self):
        ''' remember the last selection '''
        if not Shiboken.isValid(self):
            return
        name = self.action_dropdown.currentText()
        config = gremlin.config.Configuration()
        config.last_action = name
        if config.sync_last_selection:
            eh = gremlin.event_handler.EventHandler()
            eh.last_action_changed.emit(self.action_dropdown, name)

    def _valid_action_list(self, input_type: InputType):
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
            if entry.tag == "map_to_state":
                pass
            if not entry.input_types or input_type in entry.input_types:
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

        container = None
        # find the container if we can
        parent = self
        while parent is not None:
            if hasattr(parent,"profile_data"):
                if isinstance(parent.profile_data, gremlin.base_profile.AbstractContainer):
                    container = parent.profile_data
                    break
            parent = parent.parent()

        if container is None:
            if self.inputItem is None:
                MessageBox(title =  f"Invalid paste operation",
                    prompt = "Unable to paste action because it is not valid for the current input")
                return 
            # create a new basic container 
            container_plugins = gremlin.plugin_manager.ContainerPlugins()
            container_tag_map = container_plugins.tag_map
            container = container_tag_map['basic'](self.inputItem)
        

        action_list = gremlin.plugin_manager.ActionPlugins().fromClipboard(container, self.inputItem)
        if not action_list:
            return
        

        valid_actions = self._valid_action_list(self.input_type)
        warning = False
        for action in action_list:
            if action.name in valid_actions:
                # valid action - clone it and add it
                # syslog.info("Clipboard paste action trigger...")
                self.action_paste.emit(action, container)
            else:
                warning = True

        if warning:
            MessageBox(title =  f"Invalid Action type",
                prompt = "Unable to paste one or more actions because the action is invalid for the current input")


    def _clipboard_changed(self, clipboard):
        ''' handles paste button state based on clipboard data '''
        self.paste_button.setEnabled(clipboard.is_action)
        ''' updates the paste button tooltip with the current clipboard contents'''
        if clipboard.is_action:
            self.paste_button.setToolTip(f"Paste action ({clipboard.data.name})")
        else:
            self.paste_button.setToolTip(f"Paste action (not available)")

class ModeStyle(anytree.AbstractStyle):
    """ style for anytree mode rendering """

    def __init__(self):
        super().__init__("\u2502 ", "\u251c\u2500 ", "\u2514\u2500 ")


def _inheritance_tree_to_labels(labels, tree, level):
    """Generates labels to use in the dropdown menu indicating inheritance.

    :param labels the list containing all the labels
    :param tree the part of the tree to be processed
    :param level the indentation level of this tree
    """
    # skip the root node
    for child in tree.children:
        for pre, _, node in anytree.RenderTree(child, style=ModeStyle()):
            labels.append((node.name,f"{pre}{node.name}"))

def get_mode_list(profile_data):
    ''' gets a pairs (display_name, mode) '''
    profile = profile_data
    mode_list = []
    
    # Create mode name labels visualizing the tree structure
    inheritance_tree = profile.build_inheritance_tree()
    labels = []


    _inheritance_tree_to_labels(labels, inheritance_tree, 0)

    # Filter the mode names such that they only occur once below
    # their correct parent
    mode_names = [n[0] for n in labels]
    display_names = [n[1] for n in labels]

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
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose: syslog.info(f"Mode: set edit selector mode to [{mode}]")
        index =  self.edit_mode_selector.findData(mode)
        if index >= 0:
            if verbose: syslog.info(f"Mode: mode exists")
            with QtCore.QSignalBlocker(self.edit_mode_selector):
                self.edit_mode_selector.setCurrentIndex(index)
        else:
            # not found, update the selector
            if verbose: syslog.info(f"Mode: mode does not exist, repopulating")
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
        self.profile_options_button_widget.setIcon(gremlin.ui.ui_common.Icons.gearIcon())
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
    def __init__(self, data = None, parent = None, selected = False, transparent = False):
        super().__init__(parent)
        self._transparent = transparent
        
        self.setFrameStyle(QtWidgets.QFrame.Plain | QtWidgets.QFrame.Box)
        self._update_css()
        

    def setTransparent(self, transparent : bool):
        self._transparent = transparent
        self._update_css()


    def _update_css(self):
        ''' internal style sheet update '''
        border_color = Color.borderColor()
        background_color = "none" if self._transparent else Color.backgroundColor()
        css = f'''
            QFrame {{
                border: 1px solid {border_color};
                background: {background_color};
            }}
            QLabel {{
                border: none;
            }}
            '''
        self.setStyleSheet(css)

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

class QBoxFrameLayout(QBoxFrame):
    def __init__(self, title = None, data = None, parent = None, selected = False, transparent = False):
        super().__init__(data, parent, selected, transparent)
        main_layout = QtWidgets.QVBoxLayout(self)

        self._layout = QtWidgets.QVBoxLayout()
        self._title_widget = QtWidgets.QLabel()

        main_layout.addWidget(self._title_widget)
        main_layout.addLayout(self._layout)
        main_layout.addStretch(1)

        if title:
            self._title_widget.setText(title)

    def setTitle(self, title):
        ''' sets the box title (optional)'''
        self._title_widget.setText(title)
        visible = bool(title)
        self._title_widget.setVisible(visible)


    def addWidget(self, widget):
        ''' adds a widget '''
        self._layout.addWidget(widget)
    
    def clearWidgets(self):
        ''' removes all widgets '''
        gremlin.util.clear_layout(self._layout)

    def removeWidget(self, widget):
        ''' removes a widget '''
        self._layout.removeWidget(widget)

class InputListenerWidget(QBoxFrame):

    """Widget overlaying the main gui while waiting for the user
    to press a key or a joystick button """

    item_selected = QtCore.Signal(object) # called when the items are selected
    keyInput = Signal(object) # called when a keyboard input is made - the parameter will be a key if mouse/keyboard input
    closed = QtCore.Signal(bool) # closed - passes the accepted flag

    def __init__(
            self,
            event_types,
            return_kb_event=False,
            multi_keys=False,
            filter_func=None,
            callback = None, 
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
        :param callback : callback on selection
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
        self._callback = callback
        self._accepted = False # true if the input is accepted
        
        
        self._listen_mouse = InputType.Keyboard in event_types or InputType.KeyboardLatched in event_types or InputType.Mouse in event_types

        self._close_on_key = not (InputType.Keyboard in event_types or InputType.KeyboardLatched in event_types)
        self._esc_key = key_from_name("esc")

        # Create and configure the ui overlay
        self.main_layout = QtWidgets.QVBoxLayout(self)


        if self._multi_keys:
            self.main_layout.addWidget(QtWidgets.QLabel("<center>Multi-Key/Mouse Listen Mode</center>"))
            self.repeater_container_widget, self.repeater_container_layout = gremlin.ui.ui_common.getHContainer()
            self.repeater_container_widget.setMinimumHeight(32)
            self.repeater_container_layout.addWidget(QtWidgets.QLabel("<i>waiting for input...</i>",alignment= QtCore.Qt.AlignmentFlag.AlignHCenter))
            self.main_layout.addWidget(self.repeater_container_widget)

        
        label = QtWidgets.QLabel()
        self.main_layout.addWidget(label)

        if self._multi_keys:
            
            self.cancel_widget = gremlin.ui.ui_common.Buttons.getCancelWidget(callback = self._cancel)
            self.ok_widget = gremlin.ui.ui_common.Buttons.getOkWidget(callback = self._accept)
            widget, _ = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget])
            self.main_layout.addWidget(widget, alignment= QtCore.Qt.AlignmentFlag.AlignHCenter)
            msg = f"""<center>Press Ok to accept, Cancel to quit.</center>"""
        else:
            msg = f"""<center>Please press the desired {self._valid_event_types_string()}.<br/><br/>Hold ESC{'' if self._close_on_key else ' for one second'} to abort.</center>"""

        label.setText(msg)

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
        if self._listen_mouse:

            # hook the mouse
            mh = gremlin.windows_event_hook.MouseHook()
            mh.register(self._mouse_event_cb)
            

    @property
    def accepted(self) -> bool:
        ''' true if the input is accepted'''
        return self._accepted

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
            gremlin.util.InvokeUiMethod(self._selected_ui, event)
        

    def _selected_ui(self, event):
        ''' input selected - runs on UI thread'''
        if self._callback:
            self._callback(event)
        self.item_selected.emit(event)
        self.close()


    def _kb_event_cb(self, event):            
        gremlin.util.InvokeUiMethod(self._kb_event_ui, event)

    def _kb_event_ui(self, event):
        """Passes the pressed key to the provided callback and closes
        the overlay.  Runs on UI thread.

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
            # single key mode
            if event.is_pressed and key == self._esc_key:
                if not self._abort_timer.is_alive():
                    self._abort_timer.start()
            elif not event.is_pressed and InputType.Keyboard in self._event_types:
                if not self._return_kb_event:
                    self.item_selected.emit([key])
                else:
                    self.item_selected.emit(event)
                self._accepted = True
                self._abort_timer.cancel()
                self.close()

            if not event.is_pressed and key == self._esc_key:
                self._abort_timer.cancel()
                self._abort_timer = threading.Timer(1.0, self._abort_request)


        # Record all key presses and return on the first key release
        else:
            # multi-key mode
            if event.is_pressed:
                if InputType.Keyboard in self._event_types:
                    if not self._return_kb_event:
                        self._multi_key_storage.append(key)
                    else:
                        self._multi_key_storage.append(event)
                    self.keyInput.emit(key) # notify a key was pressed
                    self._echo_key(key)

    def _mouse_event_ui(self, event):
        ''' process mouse events on UI thread '''
        syslog.info(f"mouse event ui: {event}")
        if event.is_pressed:
            # only handle press events
            key = gremlin.keyboard.key_from_mousebutton(event.button_id)
            if self._multi_keys:
                # record event if multiple keys
                # make sure the mouse is not over the buttons
                pos = QtGui.QCursor.pos()
                widget = QtWidgets.QApplication.widgetAt(pos)
                if widget and isinstance(widget, QtWidgets.QPushButton):
                    return # ignore if click is on the button
                self._multi_key_storage.append(key)
                self.keyInput.emit(key) # notify a key was pressed
                self._echo_key(key)
            else:
                # not listening to multiple keys
                self.item_selected.emit([key])
                self._accepted = True
                self.close()                    
                

    def _echo_key(self, key):
        ''' echoes the last keypress '''
        if self._multi_keys:
            gremlin.util.InvokeUiMethod(self._echo_key_ui, key)

    def _echo_key_ui(self, key):
        import gremlin.ui.virtual_keyboard
        widget = gremlin.ui.virtual_keyboard.QKeyWidget()
        icon = gremlin.keyboard.KeyMap.icon(key)
        name = gremlin.keyboard.KeyMap.get_name(key)
        tooltip = gremlin.keyboard.KeyMap.get_description(key)
        if icon:
            widget.setIcon(icon)
        if name:
            widget.setText(name)
        if tooltip:
            widget.setToolTip(tooltip)
        widget.keySize = 2
        widget.autoSize = True
        gremlin.util.clear_layout(self.repeater_container_layout)
        self.repeater_container_layout.addStretch()
        self.repeater_container_layout.addWidget(widget)
        self.repeater_container_layout.addStretch()


    def _accept(self):
        # multi key accept mode 
        if self._abort_timer:
            self._abort_timer.cancel()
        self.item_selected.emit(self._multi_key_storage)
        self.close()

    def _cancel(self):
        self._multi_key_storage.clear()
        if self._abort_timer:
            self._abort_timer.cancel()
        self.close()

    def _mouse_event_cb(self, event):            
        gremlin.util.InvokeUiMethod(self._mouse_event_ui, event)

  

    def _abort_request(self):
        ''' runs when the abort timer lapses '''
        import time
        self._aborting = True
        self._abort_timer = None
        gremlin.util.InvokeUiMethod(self.close)


    def closeEvent(self, evt):
        """Closes the overlay window."""
        event_listener = gremlin.event_handler.EventListener()
        event_listener.keyboard_event.disconnect(self._kb_event_cb)
        if InputType.JoystickAxis in self._event_types or \
                InputType.JoystickButton in self._event_types or \
                InputType.JoystickHat in self._event_types:
            event_listener.joystick_event.disconnect(self._joy_event_cb)
        if self._listen_mouse:
            # unhook mouse
            mh = gremlin.windows_event_hook.MouseHook()
            mh.unregister(self._mouse_event_cb)
            

        # restore highlighting
        gremlin.shared_state.pop_suspend_highlighting()
        gremlin.shared_state.pop_suspend_ui_keyinput()

        self.closed.emit(self._accepted)

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
        if InputType.Keyboard in self._event_types or InputType.KeyboardLatched in self._event_types:
            valid_str.append("Key/Mouse")

        return ", ".join(valid_str)


def clear_layout(layout):
    """Removes all items from the given layout.

    :param layout the layout from which to remove all items
    """
    gremlin.util.clear_layout(layout)

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
    def __init__(self, parent = None, width = 200, maxItems = 20):
        ''' combo box with max count 
        
        :param parent: the parent widget of the combo box
        :param width: min width in pixels
        :param maxitems: max number of items to display
        
        '''
        super().__init__(parent)

        # hack to ensure maximum items property is respected
        #self.setEditable(True) # this is so max items works
        # self.lineEdit().setFrame(False)
        # self.lineEdit().setReadOnly(True)
        self.setStyleSheet('QComboBox {combobox-popup: 0}')
        if width is not None:
            self.setMinimumWidth(width)
        else:
             self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)

        self.setMaxVisibleItems(maxItems)

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
        # pixmap = load_pixmap("warning.svg")
        # pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        pixmap = gremlin.ui.ui_common.Icons.to_pixmap(gremlin.ui.ui_common.Icons.warningIcon())
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



class ConfirmBoxEx(QtWidgets.QDialog):
    def __init__(self, title = "Confirmation Required", prompt = "Are you sure?", again_prompt = False, again_prompt_text = None, parent = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(200)
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(prompt)
        layout.addWidget(label)
        self._result =  QtWidgets.QMessageBox.StandardButton.Cancel
        self._cb = None
        if again_prompt:
            self._cb = QtWidgets.QCheckBox(again_prompt_text if again_prompt_text else "Don't show this again")
            layout.addWidget(self._cb)
        

        ok_button_widget =  QtWidgets.QPushButton("Ok")
        ok_button_widget.clicked.connect(self._execute_cb)
        cancel_button_widget = QtWidgets.QPushButton("Cancel")
        cancel_button_widget.clicked.connect(self._close_cb)
        button_container_widget, button_container_layout = getHContainer(
            [ok_button_widget, cancel_button_widget], left_stretch=True)
        
        layout.addWidget(button_container_widget)

    @property
    def checked(self) -> bool:
        if self._cb:
            return self._cb.isChecked()
        return False

    @QtCore.Slot()
    def _execute_cb(self):
        self._result = QtWidgets.QMessageBox.StandardButton.Ok
        self.setResult(QtWidgets.QDialog.DialogCode.Accepted)
        self.close()

    @QtCore.Slot()
    def _close_cb(self):
        self.setResult(QtWidgets.QDialog.DialogCode.Rejected)
        self.close()        

    @property
    def result(self):
        return self._result

class ConfirmBox():
    def __init__(self, title = "Confirmation Required", prompt = "Are you sure?", parent = None):

        from gremlin.util import load_pixmap
        self._message_box = QtWidgets.QMessageBox(parent = parent)
        # pixmap = load_pixmap("warning.svg")
        # pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        pixmap = gremlin.ui.ui_common.Icons.to_pixmap(gremlin.ui.ui_common.Icons.warningIcon())
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

        # force the cursor
        

        if is_warning:
            # pixmap = load_pixmap("warning.svg")
            # pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
            pixmap = gremlin.ui.ui_common.Icons.to_pixmap(gremlin.ui.ui_common.Icons.warningIcon())
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


class QLabel(QtWidgets.QLabel):
    ''' styled label widget '''
    def __init__(self, text, parent = None):
        super().__init__(text, parent)
        self.setStyleSheet("background: none;")


class QIconLabel(QtWidgets.QWidget):
    ''' label with an icon using the QAWESEOME lib '''

    HorizontalSpacing = 2

    def __init__(self, icon_path = None, text = None, stretch=True, use_qta = False, icon_color = None, use_wrap = False, icon_size = 16, parent = None):
        super().__init__(parent)

        if text is None and isinstance(icon_path, str):
            text = icon_path
            icon_path = None
        

        container_widget, container_layout = getHContainer()

        # w = get_text_width("M")*80
        # container_widget.setMaximumWidth(w)
        
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        
        self._icon_size = QtCore.QSize(icon_size, icon_size)
        self._icon_widget = QtWidgets.QLabel()
        if icon_path:
            self.setIcon(icon_path, use_qta, color = icon_color)

        if use_wrap:
            self._label_widget = QWrapableLabel(text)
            self._label_widget.setWordWrap(True)
        else:
            self._label_widget = QtWidgets.QLabel(text)

        self._label_widget.setStyleSheet("background: none;")
        container_layout.addWidget(self._label_widget)
        if stretch:
            container_layout.addStretch()

        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0,0,0,0)
        #layout.addWidget(self._icon_widget,0,0, alignment= QtCore.Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._icon_widget,0,0)
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
    def __init__(self, text = None, data = None, parent = None, tooltip = None):
        super().__init__(text, parent)
        self._data = data
        if tooltip:
            self.setToolTip(tooltip)

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

class QIconButton(QDataPushButton):
    def __init__(self, icon : str, icon_size = 24,  text = None, data = None, parent = None, tooltip = None):
        super().__init__(text,data, parent, tooltip)
        icon = load_icon(icon)
        self.setIcon(icon)
        size = QtCore.QSize(icon_size,icon_size)
        self.setIconSize(size)
        self.setStyleSheet("border: none;")
        #self.setMinimumWidth(icon_size)


class QReorderToolbar(QtWidgets.QWidget):
    ''' re-order control up/down/bottom/top '''
    moveRequested = QtCore.Signal(str) # move direction

    def __init__(self, index :int, count : int,  hide = False, parent = None):
        '''
        _summary_

        Arguments:
            index -- index of the current toolbar
            count -- max number of items that can move

        Keyword Arguments:
            hide -- true if the icon should hide when top or bottom (default: {False})
            parent -- parent widget (default: {None})
        '''
        super().__init__(parent)

        self.setContentsMargins(0,0,0,0)

        self.up_widget = gremlin.ui.ui_common.QIconButton(data = "up", icon = "ph.caret-circle-up-light", tooltip="Move up")
        self.up_widget.clicked.connect(self._move)
        
        self.down_widget = gremlin.ui.ui_common.QIconButton(data = "down", icon = "ph.caret-circle-down-light", tooltip = "Move down")
        self.down_widget.clicked.connect(self._move)

        self.top_widget = gremlin.ui.ui_common.QIconButton(data = "top", icon = "ph.caret-circle-double-up-light", tooltip = "Move top")
        self.top_widget.clicked.connect(self._move)

        self.bottom_widget = gremlin.ui.ui_common.QIconButton(data = "bottom", icon = "ph.caret-circle-double-down-light",  tooltip = "Move bottom")
        self.bottom_widget.clicked.connect(self._move)

        self._index = index
        self._count = count
        self._hide = hide

        widgets = [self.up_widget, self.down_widget, self.top_widget, self.bottom_widget]
        widget, layout = getHContainer(widgets)
        layout.setSpacing(0)

        self.setLayout(layout)

        self._update(index)

    
    def _update(self, index : int):
        self._index = index
        count = self._count
        up_enabled = index > 0
        down_enabled = index < count - 1
        top_enabled = index > 1
        bottom_enabled = index < count - 2
        if self._hide:
            # visible on/off
            self.up_widget.setVisible(up_enabled)
            self.top_widget.setVisible(top_enabled)
            self.down_widget.setVisible(down_enabled)
            self.bottom_widget.setVisible(bottom_enabled)
        else:
            # enable/disable instead
            self.up_widget.setEnabled(up_enabled)
            self.top_widget.setEnabled(top_enabled)
            self.down_widget.setEnabled(down_enabled)
            self.bottom_widget.setEnabled(bottom_enabled)

        
    @QtCore.Slot()
    def _move(self):
        widget = self.sender()
        direction = widget.data
        self.moveRequested.emit(direction)
    
    def setIndex(self, index : int):
        index = gremlin.util.clamp(index, 0, self._count-1)
        if index != self._index:
            self._index = index
            self._update()

        


class QDataLineEdit(QtWidgets.QLineEdit):
    ''' a checkbox that has a data property to track an object associated with the checkbox '''
    valueChanged = QtCore.Signal() # fires when the text has changed AND we lost the focus
    lostFocus = QtCore.Signal() # fires when the input looses focus

    def __init__(self, text = None, data = None, parent = None, width = 200):
        super().__init__(text, parent)
        self._data = data
        self._text_changed = True
        self.setAlignment(Qt.AlignLeft)
        #self.setStyleSheet("QLineEdit{border: #8FBC8F;}")
        super().textChanged.connect(self._text_changed_cb)
        self.setMinimumWidth(width)


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
    def __init__(self, data = None, parent = None, wheel_enabled = True):
        super().__init__(parent)
        self._data = data
        self._wheel_enabled = wheel_enabled
        self.installEventFilter(self)

    
    def eventFilter(self, widget, event):
        if not self._wheel_enabled:
            t = event.type()
            if t == QtCore.QEvent.Type.Wheel:
                return True # skip the event
        return super().eventFilter(widget, event)
        
    def setWheelEnabled(self, value : bool):
        ''' enables/disables the wheel function to change'''
        self._wheel_enabled = value
    

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
            self._setIcon("mdi.checkbox-marked-outline", color= Color.activeColor())
        else:
            self._setIcon("fa6s.circle-exclamation", color = Color.warningColor())
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



class QProgressBar(QtWidgets.QWidget):
    ''' visualizes a vertical or horizontal progress bar '''

    valueChanged = QtCore.Signal() # fires when the value changes (and widget is not in readonly mode)

    def __init__(self, orientation : Qt.Orientation = Qt.Orientation.Vertical, value : float = 0, min : float = -1.0, max : float = 1.0, readonly : bool = True, step : float = 0.1, data = None):
        super().__init__()
        self._value = value
        self._orientation = orientation
        self._step = step
        self._readOnly = readonly
        self._data = data
        self.setRange(min, max)
        if orientation == Qt.Orientation.Vertical:
            self._desired_width = 10
            self._desired_height = 100
        else:
            self._desired_width = 100
            self._desired_height = 10
        self.setMinimumSize(self.sizeHint())
        self.setMaximumSize(self.sizeHint())

        self._background_color = Color.actionBackgroundColor()
        self._border_color = Color.selectBorderColor()
        self._gradient_start_color = Color.selectGradientColor()
        self._gradient_end_color = Color.selectEndGradientColor()
        
        self.installEventFilter(self)
        
    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self._data = value                

    def setReadOnly(self, value: bool):
        self._readOnly = value

    def isReadOnly(self):
        return self._readOnly
    
    def value(self):
        return self._value
        
    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.Wheel:
            # handle wheel up/down change
            if self._readOnly:
                return True # cannot change the value if readonly
            v = self._value
            if v is not None:
                # keyboard shifted state
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
                self.valueChanged.emit()

            return True # filter the wheel event
        return False


    @property
    def backgroundColor(self):
        return self._background_color
    @backgroundColor.setter
    def backgroundColor(self, value):
        self._background_color = value
        try:
            self.update()
        except:
            pass


    
    @property
    def borderColor(self):
        return self._border_color
    @borderColor.setter
    def borderColor(self, value):
        self._border_color = value
        try:
            self.update()
        except:
            pass


    @property
    def gradientStartColor(self):
        return self._gradient_start_color
    @gradientStartColor.setter
    def gradientStartColor(self, value):
        self._gradient_start_color = value
        try:
            self.update()
        except:
            pass        

        
    @property
    def gradientEndColor(self):
        return self._gradient_end_color
    @gradientEndColor.setter
    def gradientEndColor(self, value):
        self._gradient_end_color = value
        try:
            self.update()
        except:
            pass


    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(self._desired_width, self._desired_height)


    def setRange(self, min : float, max : float):
        if min > max:
            min, max = max, min
        self._min_range = min
        self._max_range = max
        self._update_value()

    def setValue(self, value : float):
        gremlin.util.InvokeUiMethod(self._set_value_ui, value)

    def _set_value_ui(self, value : float):
        self._value = value
        self._update_value()

    def Value(self) -> float:
        return self._value
    
    def _update_value(self):
        gremlin.util.InvokeUiMethod(self._update_value_ui)
    
    def _update_value_ui(self):
        if not Shiboken.isValid(self):
            return
        self._percent = gremlin.util.scale_to_range(self._value, 
                                                    source_min= self._min_range, 
                                                    source_max = self._max_range,
                                                    target_min = 0.0,
                                                    target_max = 1.0)
        #syslog.info(f"value: {self._value:0.3f} percent: {self._percent:0.3f}")
        # force a repaint
        self.update()
        #self.repaint()
    
    def paintEvent(self, event):

        # syslog.info("progress paint start")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        x = 0
        y = 0
        r = 0 # radius
        w = int(self.size().width())
        h = int(self.size().height())

        backgroundBrush = QBrush(self._background_color)
        borderPen = QtGui.QPen(QtGui.QColor(self._border_color))
        borderPen.setWidth(1)

        # draw bar background
        painter.setPen(borderPen)
        
        # draw progress bar foreground
        painter.setBrush(backgroundBrush)
        painter.drawRoundedRect(x, y, w, h, r, r)

        if self._orientation == Qt.Orientation.Vertical:
            gradient = QLinearGradient(QPoint(x, y), QPoint(w,h))
            gradient.setColorAt(0, QtGui.QColor(self._gradient_end_color))
            gradient.setColorAt(1, QtGui.QColor(self._gradient_start_color))
            painter.setBrush(gradient)
            v = int(h * (1.0 - self._percent)) # start from the bottom
            painter.drawRoundedRect(x, y + v, w, h, r, r)
        else:
            # horizontal
            gradient = QLinearGradient(QPoint(x, y), QPoint(w,h))
            gradient.setColorAt(0, QtGui.QColor(self._gradient_start_color))
            gradient.setColorAt(1, QtGui.QColor(self._gradient_end_color))   
            painter.setBrush(gradient)
            v = int(w * self._percent)
            painter.drawRoundedRect(x, y, x + v, h, r, r)
        painter.end()

        #syslog.info("progress paint end")

        #syslog.info(f"X: {x} y: {y} w: {w} h: {h} v:{v} value: {self._percent:0.3f}")

class ButtonStateWidget(QtWidgets.QWidget):
    ''' visualizes the state of a button '''

    deleted = QtCore.Signal() # triggers on delete
    
    def __init__(self, parent = None):
        super().__init__(parent)


        self.setContentsMargins(0,0,0,0)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0,0,0,0)
        self._deleted = False

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


        self._last_state_value = None # not set

        self._button_widget.setStyleSheet("")

        self._hat_icons = {} # icon hats, keyed by position
        
        self.main_layout.addWidget(self._button_widget)

        self._handler_connected = False
        el = gremlin.event_handler.EventListener()
        el.tab_selected.connect(self._tab_selected)
        el.tab_unselected.connect(self._tab_unselected)

        self._hooked = False
        self._suspended = False

        config = gremlin.config.Configuration()
        config.changed.connect(self._config_changed)
        
    def _config_changed(self, option, value):
        ''' called when a configuration option changes '''
        match option: 
            case "highlight_input_axis":
                self._last_state_value = None
            case "highlight_device":
                self._last_state_value = None

    def _cleanup_ui(self):
        if not self._deleted:
            self._deleted = True
            self.unhookDevice()
            self.deleted.emit()



    def hookDevice(self, device_guid, input_type, input_id):
        ''' hooks the input  '''
        if self._hooked:
            return
        self._hooked = True
        self._device_guid = device_guid
        self._input_id = input_id
        self._input_type = input_type
        self._last_state_value = None # reset state
        self.updateState()
        self._tab_selected(device_guid)
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self.process_event)




    def process_event(self, event):
        if not Shiboken.isValid(self):
            return
        if self._suspended:
            return
        if event.is_axis:
            return
        if not gremlin.util.compare_guid(event.device_guid, self._device_guid):
            return
        if event.identifier != self._input_id:
            return
        state = event.is_pressed

        if self._last_state_value is None or self._last_state_value != state:
            # changed
            gremlin.util.InvokeUiMethod(self._update_value, state)

            # only issue a state change on press and if highlighing is enabled
            if state:
                config = gremlin.config.Configuration()
                if config.highlight_enabled and config.highlight_input_buttons:
                    el = gremlin.event_handler.EventListener()
                    el.button_state_change.emit(event)


    
        
    def updateState(self):
        ''' updates the widget state with the cached state  '''
        if not self._input_type ==InputType.JoystickButton:
            # not a button device
            return
        state = gremlin.joystick_handling.get_button(self._device_guid, self._input_id)
        if state is not None:
            self._update_value(state)


    def unhookDevice(self):
        if not Shiboken.isValid(self):
            return
        if not self._hooked:
            return
        self._hooked = False
        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self.process_event)


        # self._tab_unselected(self._device_guid)
        
 

    @QtCore.Slot(str)
    def _tab_selected(self, device_guid):
        ''' triggered when a tab is selected 
        
        :param device_guid: the device selected
        
        '''        
        pass
        if not gremlin.util.compare_guid(device_guid, self._device_guid):
            return
        self._suspended = False



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
        if gremlin.util.compare_guid(device_guid, self._device_guid):
            return
        self._suspended = True

    def _update_value(self, is_pressed):
        ''' updates a button position '''
        
        if self._last_state_value is None or self._last_state_value != is_pressed:

            gremlin.util.InvokeUiMethod(self._update_pixmap_ui, is_pressed)

            self._last_state_value = is_pressed
              

    def _update_pixmap_ui(self, state):
        # updates the visual, on UI thread
        if state:
            self._button_widget.setPixmap(self._on_pixmap)
        else:
            self._button_widget.setPixmap(self._off_pixmap)

    def _update_hat(self, position):
        ''' updates a hat position '''
        if self._deleted:
            return
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



class AxisStateWidget(QtWidgets.QWidget, gremlin.base_classes.JoystickHook):
    ''' input axis visualizer '''

    valueChanged = QtCore.Signal(float, float) # (input_value, curved_value)
    deleted = QtCore.Signal(object) # indicates the item is being deleted

    def __init__(self, axis_id = None, show_calibrated = False, show_percentage = True, show_value = True,
                  show_label = True, show_curve = True, orientation = QtCore.Qt.Orientation.Vertical,
                  min_range : float = -1.0, max_range : float = 1.0, comment = None, device = None, decimals = 3, parent=None):
        """Creates a new instance.

        :param axis_id: id of the axis, used in the label
        :param show_calibrated: show calibrated data 
        :param show_percentage: show percent label
        :param show_value : show value label 
        :param show_curve : show curve value label
        :param orientation: horizontal or vertical
        :param min_range: min range (-1)
        :param max_range: max range (+1)
        :param comment: comment label
        :param device : device to use
        :param decimals: decimals to use for value data (3)
        :param parent the parent of this widget

        """
        super().__init__(parent)

        self._scale_factor = 1000
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.device = device
        self.setObjectName("state_repeater")
        self._is_state = True # indicate this is a state widget
        

        self.container_widget = QtWidgets.QWidget()
        if orientation == QtCore.Qt.Orientation.Vertical:
            #self.container_layout = QtWidgets.QGridLayout()
            self.container_layout = QtWidgets.QVBoxLayout(self.container_widget)
        else:
            self.container_layout = QtWidgets.QHBoxLayout(self.container_widget)
            
        self.setContentsMargins(0,0,0,0)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.container_layout.setSpacing(0)
        self.container_layout.setContentsMargins(0,0,0,0)

        # container for the progress bars (regular + calibrated)
        self.progress_container_widget = None
        self.progress_container_layout = None

        self._orientation = orientation
        self._show_percentage = show_percentage
        self._show_value = show_value
        self._show_label = show_label
        self._show_curve = show_curve
        self._show_calibrated = show_calibrated
        self._decimals = decimals if decimals is not None else 3

        # widget references 
        self._progress_widget = None
        self._progress_calibrated_widget = None
        self._display_curve_widget = None
        self._display_label_widget = None
        self._display_percent_widget = None
        self._display_value_widget = None
        
        self._data = None
        self._comment = comment

        self._label_text = ""
        self._label_value = ""
        self._label_percentage = ""
        self._label_curve = ""

        self._display_value = 0.0
        self._calibrated_value = 0.0
        
        if axis_id:
            self._label_text = f"Axis {axis_id}"

        min = min_range
        max = max_range
        if min > max:
            min, max = max, min
        self._min_range = min_range
        self._max_range = max_range

        self._device_guid = device.device_guid if device else None
        self._input_id = axis_id
        self._value = 0
        self._raw_value = 0
        self._reverse = False
        self._decimals = 3
        self._width = 10

        # hook tab events
        el = gremlin.event_handler.EventListener()
        el.tab_selected.connect(self._tab_selected)
        el.tab_unselected.connect(self._tab_unselected)
        el.calibration_changed.connect(self._calibration_changed)
        el.calibration_options_changed.connect(self._calibration_options_changed)

        self.main_layout.addWidget(self.container_widget)

        el = gremlin.event_handler.EventListener()
        el.ui_ready.connect(self._ui_ready)

        self._setValue(self._value)


        css = Color.cssRepeater()
        self.setStyleSheet(css)
        self.installEventFilter(self)

    def eventFilter(self, widget, event):
        ''' grab mouse wheel events to avoid random scrolling '''
        t = event.type()
        if t == QtCore.QEvent.Type.Wheel:
            return True
        return False


    def hookDevice(self, device_guid, input_type, input_id):    
        ''' hooks the device '''    
        if not Shiboken.isValid(self):
            return
        self._hookDevice(device_guid, input_type, input_id, self._setValue)
        

    @QtCore.Slot(object)
    def _calibration_changed(self, calibration):
        ''' occurs when calibration data is changed '''
        if not Shiboken.isValid(self):
            return
        if self.device_guid == calibration.device_guid and self.input_id == calibration.input_id:
            # one of ours
            isCalibrated = calibration.hasData
            syslog.info(f"Device calibration changed to: {isCalibrated}")
            self.setCalibrated(isCalibrated)
            self.show_calibrated = isCalibrated
            self._clear_widgets()
            self._update_widgets()

    @QtCore.Slot()
    def _calibration_options_changed(self):
        ''' refresh when calibration options change '''
        self._clear_widgets()
        self._update_widgets()
            
    

    def _clear_widgets(self):
        ''' removes all the widgets for a clean slate '''
        if not Shiboken.isValid(self):
            return
        try:
            gremlin.ui.ui_common.clear_layout(self.container_layout)
            self._display_curve_widget = None
            self._display_label_widget = None
            self._display_percent_widget = None
            self._display_value_widget = None
            self._progress_widget = None
            self._progress_calibrated_widget = None
            self.progress_container_widget = None
            self.progress_container_widget = None
        except:
            pass

    def _update_widgets(self):
        ''' loads widgets into the control based on preferences
        
        Because QT (as of this writing) does not issue events when it deletes C++ underlying objects, and because the wiring may lead to automatic garbage collection without 
        Python being aware - we go through special handling to catch these situations and re-create garbage collected elements for this UI widget
        
        '''
        if not Shiboken.isValid(self):
            return

        # gremlin.ui.ui_common.clear_layout(self.container_layout)
        alignment = QtCore.Qt.AlignmentFlag.AlignCenter if self._orientation == QtCore.Qt.Orientation.Vertical else QtCore.Qt.AlignmentFlag.AlignLeft
        
        # progress bar label
        if self._show_label:
            try:
                if self._display_label_widget:
                    self._display_label_widget.setText(self._label_text)
            except:
                # C++ exception
                self._display_label_widget = None
            if not self._display_label_widget:
                self._display_label_widget = QtWidgets.QLabel(self._label_text)
                self.container_layout.addWidget(self._display_label_widget, alignment = alignment)

        # progress bar container 
        try:
            if self.progress_container_widget:
                pass
        except:
            try:
                self.container_layout.removeWidget(self.progress_container_widget)
            except:
                pass
            self.progress_container_widget = None
            self.progress_container_layout = None

        if not self.progress_container_widget:
            if self._orientation == QtCore.Qt.Orientation.Vertical:
                # stack horizontal
                self.progress_container_widget, self.progress_container_layout = getHContainer()
            else:
                # stack vertical
                self.progress_container_widget, self.progress_container_layout = getVContainer()
            self.progress_container_layout.setSpacing(0)
            self.container_layout.addWidget(self.progress_container_widget, alignment = alignment)


        # progress bar widget
        try:
            if self._progress_widget:
                self._progress_widget.setValue(self._display_value)        
        except:
            # C++ exception
            self._progress_widget = None

        if not self._progress_widget:
            self._progress_widget = QProgressBar(orientation= self._orientation, min = self._min_range, max = self._max_range, data = self._input_id)
            self._progress_widget.setFixedSize(self._progress_widget.sizeHint())
            self.progress_container_layout.addWidget(self._progress_widget, alignment = alignment)
            self._progress_widget.setValue(self._display_value)
            if self._orientation == QtCore.Qt.Orientation.Vertical:
                w = 2 + self._progress_widget.width()
                self.progress_container_widget.setFixedWidth(w)
            else:
                h = 2 + self._progress_widget.height()
                self.progress_container_widget.setFixedHeight(h)

            if self.device and self.device.is_virtual:
                self._progress_widget.setReadOnly(False)
                self._progress_widget.valueChanged.connect(self._value_changed)

            
                

        if self._show_calibrated:
            config = gremlin.config.Configuration()
            if config.splitJoystickRepeater:
                try:
                    if self._progress_calibrated_widget:
                        self._progress_calibrated_widget.setValue(self._calibrated_value)
                except:
                    # C++ exception
                    self._progress_calibrated_widget = None
                if not self._progress_calibrated_widget:
                    self._progress_calibrated_widget = QProgressBar(orientation= self._orientation, min = self._min_range, max = self._max_range, data = self.input_id)
                    self._progress_calibrated_widget.gradientStartColor = Color.selectGradientAltColor()
                    self._progress_calibrated_widget.gradientEndColor = Color.selectEndGradientAltColor()
                    self._progress_calibrated_widget.setFixedSize(self._progress_calibrated_widget.sizeHint())
                    self.progress_container_layout.addWidget(self._progress_calibrated_widget, alignment = alignment)
                    if self._orientation == QtCore.Qt.Orientation.Vertical:
                        w = 4 + self._progress_widget.width() + self._progress_calibrated_widget.width() 
                        self.progress_container_widget.setFixedWidth(w)
                    else:
                        h = 4 + self._progress_widget.height() + self._progress_calibrated_widget.height()
                        self.progress_container_widget.setFixedHeight(h)
                    
                    self._progress_calibrated_widget.setValue(self._calibrated_value)
                    if self.device and self.device.is_virtual:
                        self._progress_calibrated_widget.setReadOnly(False)
                        self._progress_calibrated_widget.valueChanged.connect(self._value_changed)


        # progress bar value
        if self._show_value:

            try:
                if self._display_value_widget:
                    self._display_value_widget.setText(self._label_value) 
            except:
                # C++ exception
                self._display_value_widget = None
            if not self._display_value_widget:
                if self.device and self.device.is_virtual:
                    self._display_value_widget = gremlin.ui.ui_common.QFloatLineEdit(value = self._value)
                    self._display_value_widget.valueChanged.connect(self._value_changed)
                else:
                    self._display_value_widget = QtWidgets.QLabel(self._label_value)
                self.container_layout.addWidget(self._display_value_widget, alignment = alignment)


        # progress bar percentage
        if self._show_percentage:
            try:
                if self._display_percent_widget:
                    self._display_percent_widget.setText(self._label_percentage) 
            except:
                # C++ exception
                self._display_percent_widget = None

            if not self._display_percent_widget:
                self._display_percent_widget = QtWidgets.QLabel(self._label_percentage)
                self.container_layout.addWidget(self._display_percent_widget, alignment = alignment)

        # progress curve 
        try:
            if self._show_curve: 
            
                if self._display_curve_widget:
                    self._display_curve_widget.setText(self._label_curve)
                    
                if not self._display_curve_widget:
                    self._display_curve_widget = QtWidgets.QLabel(self._label_curve)
                    self.container_layout.addWidget(self._display_curve_widget, alignment = alignment)
        
           
        except:
            pass

        self.container_layout.addStretch()

    @QtCore.Slot()
    def _value_changed(self):
        if not Shiboken.isValid(self):
            return
        widget = self.sender()        
        value = widget.value()
        input_id = widget.data
        device_guid = self.device.device_guid
        gremlin.joystick_handling.set_axis(device_guid, input_id, value)



    
    @QtCore.Slot()
    def _ui_ready(self):
        ''' fires when the UI is ready '''
        if not Shiboken.isValid(self):
            return
        self._setValue(self._value, self._curve_value)

    def _cleanup_ui(self):
        ''' item is being deleted '''
        if Shiboken.isValid(self):
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
        return self._show_curve
    @show_curved.setter
    def show_curved(self, value: bool):
        if not Shiboken.isValid(self):
            return
        if value != self._show_curve:
            self._show_curve = value
            self._setValue(self._value, self._curve_value)
            if value:
                self._update_widgets()
            else:
                try:
                    self.container_layout.removeWidget(self._display_curve_widget)
                    self._display_curve_widget = None
                except:
                    pass

    @property
    def show_percent(self) -> bool:
        ''' true if repeater shows percentd data '''
        return self._show_percentage
    @show_percent.setter
    def show_percent(self, value: bool):
        if not Shiboken.isValid(self):
            return
        if value != self._show_percentage:
            self._show_percentage = value
            if value:
                self._update_widgets()
            else:
                try:
                    self.container_layout.removeWidget(self._display_percent_widget)
                    self._display_percent_widget = None
                except:
                    pass

    @property
    def show_value(self) -> bool:
        ''' true if repeater shows percentd data '''
        return self._show_value
    @show_value.setter
    def show_value(self, value: bool):
        if not Shiboken.isValid(self):
            return
        if value != self._show_value:
            self._show_value = value
            if value:
                self._update_widgets()
            else:
                try:
                    self.container_layout.removeWidget(self._display_value_widget)
                    self._display_value_widget = None                
                except:
                    pass

    @property
    def show_label(self) -> bool:
        ''' true if repeater shows percentd data '''
        return self._show_label
    @show_label.setter
    def show_label(self, value: bool):
        if value != self._show_label:
            self._show_label = value
            if value:
                self._update_widgets()
            else:
                try:
                    self.container_layout.removeWidget(self._display_label_widget)
                    self._display_label_widget = None                
                except:
                    pass      

    @property
    def show_calibrated(self) -> bool:
        ''' true if repeater shows percentd data '''
        return self._show_calibrated
    @show_calibrated.setter
    def show_calibrated(self, value: bool):
        if value != self._show_calibrated:
            self.setCalibrated(value)
            self._show_calibrated = value
            self._clear_widgets()
            self._update_widgets()

    def setPercentageVisible(self, value: bool):
        ''' shows or hides the percentage value on the axis '''
        if not Shiboken.isValid(self):
            return
        self.show_percent(value)

    def setValueVisible(self, value: bool):
        self.show_value(value)

    def setLabel(self, value : str):
        ''' sets the label for the axis '''
        if not Shiboken.isValid(self):
            return
        self._label_text = value
        self._update_widgets()
        
    def setLabelVisible(self, value: bool):
        if not Shiboken.isValid(self):
            return
        self.show_label(value)
        
        

    def setWidth(self, value):
        if value > 0:
            self._width = value
            #self._update_css()

    def value(self):
        return self._value

    def setValue(self, value, curve_value = None, percent_value = None, other_value = None):
        """Sets the value shown by the widget.
        :param value new value to show
        """
        if Shiboken.isValid(self):
            self._setValue(value, curve_value, percent_value, other_value)

    def _setValue(self, value, calibrated_value = None, curve_value = None, percent_value = None, other_value = None):
        ''' internal set value '''

        if not Shiboken.isValid(self):
            return
        
        if value is None:
            return
        if isinstance(value, list) and value:
            value = value[0]

        
        if calibrated_value is None:
            calibrated_value = value
        
        if value < self._min_range:
            value = self._min_range
        if value > self._max_range:
            value = self._max_range
        value += 0   # avoid negative 0 (WHY?)
        self._value = value

        if curve_value is not None:
            self._curve_value = curve_value
            display_value = curve_value
        else:
            display_value = value
            self._curve_value = value


        if self._reverse:
            display_value = gremlin.util.scale_to_range(display_value, invert=True)
            calibrated_value = gremlin.util.scale_to_range(calibrated_value, invert=True)

        if value is None:
            display_value = None
        else:
            scaled_value = display_value # self._scale_factor * display_value
            
        
        self._display_value = scaled_value
        self._calibrated_value = calibrated_value
    
        
        if display_value is not None:
            self._label_value = f"{display_value:+0.{self._decimals}f}"
        else:
            self._label_value = "n/a"
            

        if self._show_curve and curve_value is not None:
            self._label_curve = f"C{curve_value:+0.{self._decimals}f}"
            
        if self._show_percentage:
            if percent_value is None:
                if curve_value is None:
                    percent = gremlin.util.scale_to_range(display_value, target_min=0, target_max = 100)
                else:
                    percent = gremlin.util.scale_to_range(curve_value, target_min=0, target_max = 100)
            else:
                percent = percent_value
            self._label_percentage = f"{percent:0.1f} %"

        self._update_widgets()

        
        self.valueChanged.emit(self._value, self._curve_value)

           


    def value(self):
        ''' gets the current value '''
        if Shiboken.isValid(self):
            return self._value
        return 0

    def setRange(self, min = -1.0, max = 1.0, decimals = 3):
        ''' sets the range of the widget '''
        if not Shiboken.isValid(self):
            return
        if min > max:
            max, min = min, max
        self._min_range = min
        self._max_range = max
        self._decimals = decimals
        self._update_range()

    def _update_range(self):
        if self._progress_widget:
            self._progress_widget = None
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
        if not Shiboken.isValid(self):
            return
        return self._reverse

    @property
    def enabled(self) -> bool:
        return self.getEnabled()

    @QtCore.Slot(str)
    def _tab_selected(self, device_guid):
        ''' triggered when a tab is selected 
        
        :param device_guid: the device selected
        
        '''
        if not Shiboken.isValid(self):
            return
        if self.getEnabled():
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
            self.setEnabled(True)


    
    @QtCore.Slot(str)
    def _tab_unselected(self, device_guid):
        ''' triggered when a device tab is deselected, also used to force a disconnect
         
        :param device_guid: the device to deselect - if None - deselect all
          
        '''
        if not Shiboken.isValid(self):
            return
        if not self.getEnabled():
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
            self.setEnabled(False)
        


    def _update_value(self, value):
        # invert the input if needed
        if not Shiboken.isValid(self):
            return
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

            device_guid = device.device_guid
            if index in axis_list:
                
                input_id = index
                axis_label = QtWidgets.QLabel(f"Axis {index}")
                axis_id = gremlin.joystick_handling.linear_axis_index(self.device.axismap_list,index)
                self.index_map[axis_id] = index
                axis = AxisStateWidget(index, show_value = False, show_label=False, show_percentage=False, device = device)
                calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(device_guid, input_id)
                axis.setCalibrated(calibration.hasData) # enable calibrated mode dual repeater

                value = gremlin.joystick_handling.get_axis(device.device_guid, index)
                #print (f"Axis {axis_id} value: {value:0.3f}")
                if self.device.is_virtual:
                    value_widget = QFloatLineEdit(data = index)
                    value_widget.valueChanged.connect(self._value_changed)
                else:
                    value_widget = QtWidgets.QLabel(f"{value:+0.3f}")

                #axis.setValue(value)
                self.axes[index] = axis
                self.value_labels[index] = value_widget
                percent = gremlin.util.scale_to_range(value,target_min=0, target_max=100)
                
                percent_label = QtWidgets.QLabel(f"{percent:0.1f} %")
                self.percent_labels[index] = percent_label
                axis.setValue(value)
                layout.addWidget(axis)

                row = 0
                axes_layout.addWidget(axis_label, row, i, alignment=QtCore.Qt.AlignCenter)    
                row += 1 
                axes_layout.addWidget(QtWidgets.QLabel(" "), row, i, alignment=QtCore.Qt.AlignCenter)    # spacer
                row += 1 
                axes_layout.addWidget(widget, row, i, alignment=QtCore.Qt.AlignCenter)
                row += 1 
                axes_layout.addWidget(value_widget, row, i, alignment=QtCore.Qt.AlignCenter)
                row += 1 
                axes_layout.addWidget(percent_label, row, i, alignment=QtCore.Qt.AlignCenter)
                row += 1 
            else:
                axes_layout.addWidget(QtWidgets.QLabel(" "), 0, i, alignment=QtCore.Qt.AlignCenter)    # spacer

            

        #axes_layout.addStretch()
        axes_layout.setColumnStretch(i+1,2)
        self.setLayout(axes_layout)

    @QtCore.Slot()
    def _value_changed(self):
        widget = self.sender()
        input_id = widget.data
        value = widget.value()
        device_guid = self.device.device_guid
        gremlin.joystick_handling.set_axis(device_guid, input_id, value)
        #self._set_value(index, value)

    def _set_value(self, index : int, value : float):
        self.axes[index].setValue(value)
        widget = self.value_labels[index]
        if hasattr(widget, "setValue"):
            widget.setValue(value)
        else:
            widget.setText(f"{value:+0.3f}")
        percent = gremlin.util.scale_to_range(value,target_min=0, target_max=100)
        self.percent_labels[index].setText(f"{percent:0.1f} %")


    def process_event(self, event):
        """Updates state visualization based on the given event.

        :param event the event with which to update the state display
        """

        if event.event_type == InputType.JoystickAxis:
            axis_id = gremlin.joystick_handling.linear_axis_index(
                self.device.axismap_list,
                event.identifier
            )
            index = self.index_map[axis_id]
            value = event.value
            self._set_value(index, value)


class HatWidget(QtWidgets.QWidget):

    """Widget visualizing the state of a hat."""

    clicked = QtCore.Signal(tuple) # click event (direction)

    # Polygon path for a triangle
    triangle = QtGui.QPolygon(
        [QtCore.QPoint(-10, 0), QtCore.QPoint(10, 0), QtCore.QPoint(0, 15)]
    )

    # Mapping from event values to rotation angles - center and 8 positions
    lookup = [
        ((0, 0), -1),     # 0 center
        ((0, 1), 0),    # 1 N
        ((1, 1), 45),    # 2 NE
        ((1, 0), 90),    # 3 E
        ((1, -1), 135),   # 4 SE
        ((0, -1), 180),      # 5 S
        ((-1, -1), 225),   # 6 SW
        ((-1, 0), 270),    # 7 W
        ((-1, 1), 315),   # 8 NW
    ]

    def __init__(self, direction = None, data = None, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.installEventFilter(self)
        self._data = data
        self._direction = direction
        self._radius = 35
        self._center = 50
        self._box = 24
        self._hotspots = []
        self.angle = -1
        self._directions = []
        self._angle_map = {}
        self._rect_map = {}
        self.setContentsMargins(0,0,0,0)

    def _update_hotspots(self):
        self._hotspots = []
        self._directions = []
        index = 0
        for direction, angle in HatWidget.lookup:
            if angle != -1:
                angle = angle - 90
                if angle < 0:
                    angle += 360
            rect = self._get_rect(angle)
            self._hotspots.append(rect)
            self._directions.append(direction)
            self._angle_map[direction] = angle
            # syslog.info(f"Index: [{index}] Angle: {angle} {direction} {rect}")
            self._rect_map[rect] = direction
            index +=1
        pass
                

    def resizeEvent(self, event):
        self._update_hotspots()
        return super().resizeEvent(event)

    def _get_rect(self, angle):
        ''' computes the click hotspot angle for the widget '''
        import math
        s = self._box
        s2 = s/2
        cx = self._center
        cy = self._center

        if angle == -1:
            # center rect
            x = cx - s2
            y = cy - s2
        else:
            rad = math.radians(angle) 
            x = cx + math.cos(rad) * self._radius - s2
            y = cy + math.sin(rad) * self._radius - s2 
        rect = QtCore.QRect(x,y,s,s)

        return rect


    def eventFilter(self, widget, event):
        ''' grab mouse wheel events to avoid random scrolling '''
        t = event.type()
        if t == QtCore.QEvent.Type.MouseButtonPress:
            # mouse press
            button = event.buttons()
            if button == QtCore.Qt.LeftButton:
                pos = event.pos()
                # syslog.info(f"Click: {pos}")
                for index, rect in enumerate(self._hotspots):
                    if rect.contains(pos):
                        direction = self._rect_map[rect] # self._directions[index]
                        # syslog.info(f"\tRect [{index}]: {direction} {rect} ")
                        self.clicked.emit(direction)
                        return True # handled
            
        return False

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value



    def minimumSizeHint(self):
        """Returns the minimum size of the widget.

        :return the widget's minimum size
        """
        return QtCore.QSize(120, 120)

    def set_angle(self, state):
        """Sets the current direction of the hat.

        :param state the direction of the hat
        """

        self.angle = self._angle_map.get(state,-1)
        # syslog.info(f"SetAngle: {state} {self.angle}")
        self.update()



    def paintEvent(self, event):
        """Draws the entire hat state visualization.

        :param event the paint event
        """
        # Define pens and brushes

        # syslog.info("hat paint start")

        active_color = Color.activeColor()
        border_color = Color.borderColor()
        inactive_color = Color.inactiveColor()
        
        normal_color = Color.normalColor()

        pen_default = QtGui.QPen(QtGui.QColor(normal_color))
        pen_default.setWidth(2)
        pen_active = QtGui.QPen(QtGui.QColor(active_color))
        pen_active.setWidth(2)
        brush_default = QtGui.QBrush(QtGui.QColor(inactive_color))
        brush_active = QtGui.QBrush(QtGui.QColor(active_color))

        # Prepare painter instance
        p = QtGui.QPainter(self)
        
        p.setRenderHint(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        p.setPen(pen_default)
        p.setBrush(brush_default)

        #p.save()
        p.translate(self._center, self._center)

        # Center dot
        if self.angle == -1:
            p.setBrush(brush_active)
        p.drawEllipse(-8, -8, 16, 16)
        p.setBrush(brush_default)
        # Directions
        for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
            p.save()
            p.rotate(angle - 90)
            p.translate(0, self._radius)

            if angle == self.angle:
                p.setBrush(brush_active)
                p.setPen(pen_active)

            p.drawPolygon(HatWidget.triangle)
            p.restore()

        #p.restore()
        # for rect in self._hotspots:
        #     p.drawRect(rect)

        p.end()

        # syslog.info("hat paint end")

class HatState(QtWidgets.QGroupBox):

    """Visualizes the sate of a device's hats."""


    def __init__(self, device, parent=None):
        """Creates a new instance.

        :param device the device of which to display the hat sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._event_times = {}
        self.device = device

        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Hats")
        else:
            self.setTitle(f"{device.name} - Hats")

        self.hats = [None]
        hat_layout = QtWidgets.QGridLayout()
        for i in range(device.hat_count):
            hat = HatWidget(data = i+1) # data is the hat #
            if device.is_virtual:
                hat.clicked.connect(self._hat_clicked)
            self.hats.append(hat)
            hat_layout.addWidget(hat, int(i / 2), int(i % 2))

        self.setLayout(hat_layout)

    @QtCore.Slot()
    def _hat_clicked(self, direction):
        widget = self.sender()
        input_id = widget.data
        #input_id = self.device.vjoy_id
        device_guid = self.device.device_guid
        #syslog.info(f"Set Hat: {input_id}  {direction}")
        gremlin.joystick_handling.set_hat(device_guid, input_id, direction)

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
            index = device.axismap_list[i].axis_index
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

        # syslog.info("timeline paint start")
        p = QtGui.QPainter(self)
        
        
        p.drawPixmap(0, 0, self._pixmap)
        p.end()
        # syslog.info("timeline paint end")



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

    def __init__(self, device : DeviceSummary, vis_type, parent=None):
        """Creates a new instance.

        :param device_data information about the device itself
        :param vis_type the visualization type to use
        :param parent the parent of this widget
        """
        super().__init__(parent)
        assert device is not None, "Device must be provided"

        self._device = device
        
        self.vis_type = vis_type
        self.widgets = []
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        self.setLayout(layout)
        self.vis_type = vis_type
        self._hooked = False
        self._create_visuals()

    @property
    def device_id(self):
        return self._device.device_id
    
    @property
    def device_guid(self):
        return self._device.device_guid

    def process_event(self, event):
        if self.device_guid != event.device_guid:
            # wrong device
            return
        vis_type = self.vis_type
        if vis_type == gremlin.types.VisualizationType.AxisCurrent:
            self._current_axis_update(event)
            
        elif vis_type == gremlin.types.VisualizationType.AxisTemporal:
            self._temporal_axis_update(event)
            for widget in self.widgets:
                for input_id in self._device.axis_index_list():
                    value = gremlin.joystick_handling.get_axis(self.device_guid, input_id)
                    widget.add_point(value, input_id)
        elif vis_type == gremlin.types.VisualizationType.ButtonHat:
            self._button_hat_update(event)

    def _create_visuals(self):
        ''' creates the visual for a given visualization type '''
        vis_type = self.vis_type
        if vis_type == gremlin.types.VisualizationType.AxisCurrent:
            self._create_current_axis()
                
        elif vis_type == gremlin.types.VisualizationType.AxisTemporal:
            self._create_temporal_axis()
            for widget in self.widgets:
                for input_id in self._device.axis_index_list():
                    value = gremlin.joystick_handling.get_axis(self.device_guid, input_id)
                    widget.add_point(value, input_id)
        elif vis_type == gremlin.types.VisualizationType.ButtonHat:
            self._create_button_hat()


    
    def hook(self):
        ''' hooks events '''
        if self._hooked:
            return
        vis_type = self.vis_type
        el = gremlin.event_handler.EventListener()
        if vis_type == gremlin.types.VisualizationType.AxisCurrent:
            self._create_current_axis()
            el.joystick_event.connect(self._current_axis_update)
            # if self._device.is_virtual:
            #     el.registerVjoyCallback(self._vjoy_current_axis_update)
                
        elif vis_type == gremlin.types.VisualizationType.AxisTemporal:
            self._create_temporal_axis()
            el.joystick_event.connect(self._temporal_axis_update)
            # if self._device.is_virtual:
            #     el.registerVjoyCallback(self._vjoy_temporal_axis_update)
            for widget in self.widgets:
                for input_id in self._device.axis_index_list():
                    value = gremlin.joystick_handling.get_axis(self.device_guid, input_id)
                    widget.add_point(value, input_id)
        elif vis_type == gremlin.types.VisualizationType.ButtonHat:
            self._create_button_hat()
            el.joystick_event.connect(self._button_hat_update)
            # if self._device.is_virtual:
            #     el.registerVjoyCallback(self._vjoy_button_hat_update)

        self._hooked = True

    def unhook(self):
        ''' unhooks events '''
        if not self._hooked:
            return
        vis_type = self.vis_type
        el = gremlin.event_handler.EventListener()
        if vis_type == gremlin.types.VisualizationType.AxisCurrent:
            el.joystick_event.disconnect(self._current_axis_update)
            # if self._device.is_virtual:
            #     el.unregisterVjoyCallback(self._vjoy_current_axis_update)
        elif vis_type == gremlin.types.VisualizationType.AxisTemporal:
            el.joystick_event.disconnect(self._temporal_axis_update)
            # if self._device.is_virtual:
            #     el.unregisterVjoyCallback(self._vjoy_temporal_axis_update)
        elif vis_type == gremlin.types.VisualizationType.ButtonHat:
            self._unhook_buttons()
            el.joystick_event.disconnect(self._button_hat_update)
            # if self._device.is_virtual:
            #     el.unregisterVjoyCallback(self._vjoy_button_hat_update)
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
            ButtonState(self._device),
            HatState(self._device)
        ]
        for widget in self.widgets:
            self.layout().addWidget(widget)
        self.layout().addStretch(1)

    def _unhook_buttons(self):
        if self._device.is_virtual:
            widgets = [widget for widget in self.widgets if isinstance(widget, ButtonState)]
            for widget in widgets:
                widget.unhook()

    def _create_current_axis(self):
        """Creates display for current axes data."""
        self.widgets = [AxesCurrentState(self._device)]
        for widget in self.widgets:
            self.layout().addWidget(widget)

    def _create_temporal_axis(self):
        """Creates display for temporal axes data."""
        self.widgets = [AxesTimeline(self._device)]
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

    def _vjoy_button_hat_update(self, event: gremlin.event_handler.VjoyEvent):
        if self._device.vjoy_id != event.vjoy_id:
            return
        
        event = gremlin.event_handler.Event(event_type = event.input_type, identifier = event.input_id, device_guid= self.device_guid, value = event.value)
        for widget in self.widgets:
            widget.process_event(event)

    def _current_axis_update(self, event):
        if self.device_guid != event.device_guid:
            return

        for widget in self.widgets:
            widget.process_event(event)

    def _vjoy_current_axis_update(self, event : gremlin.event_handler.VjoyEvent):
        if self._device.vjoy_id != event.vjoy_id:
            return
        
        event = gremlin.event_handler.Event(event_type = event.input_type, identifier = event.input_id, device_guid= self.device_guid, value=event.value)
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

    def _vjoy_temporal_axis_update(self, event : gremlin.event_handler.VjoyEvent):
        if self._device.vjoy_id != event.vjoy_id:
            return
        
        for widget in self.widgets:
            widget.add_point(event.value, event.input_id)


class ButtonState(QtWidgets.QGroupBox):

    """Widget representing the state of a device's buttons."""

    def __init__(self, device : DeviceSummary, parent=None):
        """Creates a new instance.

        :param device the device of which to display the button sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._event_times = {}
        self._device = device
        self.setObjectName("state_repeater")

        is_disabled = True
        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Buttons")
            is_disabled = False
        else:
            self.setTitle(f"{device.name} - Buttons")

        css = Color.cssRepeater()
        self.setStyleSheet(css)

        css = Color.cssButtonState()
        self.buttons = [None]
        button_layout = QtWidgets.QGridLayout()
        for i in range(device.button_count):
            btn = QDataPushButton(str(i+1), i+1)
            btn.setStyleSheet(css)
            
            btn.setDisabled(is_disabled)
            if not is_disabled:
                btn.setCheckable(True) # set checkable for state retention
                btn.clicked.connect(self._button_clicked)

            # read the current state
            is_pressed = gremlin.joystick_handling.get_button(device.device_guid, i+1)
            btn.setDown(is_pressed)
            self.buttons.append(btn)
            button_layout.addWidget(btn, int(i / 10), int(i % 10))
        button_layout.setColumnStretch(10, 1)
        self.setLayout(button_layout)


    
        
    @QtCore.Slot()
    def _button_clicked(self):
        btn = self.sender()
        input_id = btn.data
        device_guid = self._device.device_guid
        is_pressed = not gremlin.joystick_handling.get_button(device_guid, input_id)
        gremlin.joystick_handling.set_button(device_guid, input_id, is_pressed)

    def unhook(self):
        ''' unhooks buttons '''
        if self._device.is_virtual:
            for btn in self.buttons:
                if btn:
                    btn.clicked.disconnect(self._button_clicked)

    def process_event(self, event):
        """Updates state visualization based on the given event.

        :param event the event with which to update the state display
        """
        if not Shiboken.isValid(self):
            return
        input_type = event.getInputType()
        if input_type == InputType.JoystickButton:
            #is_pressed = event.is_pressed if event.is_pressed is not None else event.current
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


def get_text_width(text, percent = 30):
    ''' gets the average text width '''
    lbl = QtWidgets.QLabel("W")
    #width = lbl.sizeHint().width()
    char_width = lbl.fontMetrics().averageCharWidth()
    width =  char_width * (len(text) if text else 1)
    if percent:
        width += int(width * percent / 100)
    return width

def get_text_height(text = None):
    ''' gets the average text width '''
    lbl = QtWidgets.QLabel(text if text else "M")
    fm = lbl.fontMetrics()
    rect = fm.boundingRect(QtCore.QRect(0,0,100,100), QtCore.Qt.TextWordWrap, lbl.text())
    return rect.height()
    


def get_char_width(count = 1):
    return get_text_width("W") * count




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

        # syslog.info("toggle paint start")

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

        # syslog.info("toggle paint end")

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

        # syslog.info("animated toggle paint start")

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

        # syslog.info("animated toggle paint end")



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

    valueChanged = QtCore.Signal(int) # fired when the value changes

    def __init__(self, value = 250, is_seconds = False, parent = None, label = None):
        '''

        :params value: default delay in milliseconds '''
        super().__init__(parent)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)

        self.delay_container_widget = QtWidgets.QWidget()
        self.delay_container_layout = QtWidgets.QHBoxLayout()
        self.delay_container_widget.setLayout(self.delay_container_layout)

        self._is_seconds = is_seconds

        width = gremlin.ui.ui_common.get_char_width(8)
        delay_label = QtWidgets.QLabel(label if label else "Delay (ms)")
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

    def setSecondsMode(self, enabled : bool):
        self._is_seconds = enabled

    def value(self):
        ''' gets the delay in milliseconds '''
        value = self._delay_widget.value()
        if self._is_seconds:
            value /= 1000 # to seconds
        return value

    def setValue(self, value : float):
        ''' sets the widget value 
        :param value: value in ms or in seconds if the widget mode is set to seconds
        '''
        milliseconds = milliseconds = value * 1000 if self._is_seconds else value
        if milliseconds >= 0 and milliseconds != self._delay_widget.value():
            self._delay_widget.setValue(milliseconds)
            self.valueChanged.emit(milliseconds)

    @QtCore.Slot()
    def _value_changed(self):
        self.valueChanged.emit(self._delay_widget.value())

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

        # syslog.info("dual slider paint start")

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

        painter.end()

        # syslog.info("dual slider paint end")



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

        # syslog.info("bubble paint start")
        p = QtGui.QPainter(self)
        # p.begin(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.drawRoundedRect(
            0, 0, self.width() - 1, self.height() - 1, 5, 5)
        p.end()
        super(QBubble, self).paintEvent(event)
        

        # syslog.info("bubble paint end")




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
            icon = gremlin.util.load_icon("fa6.circle-question")

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
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        self.action_entry = action_entry
        
        background_color = Color.actionIconBackgroundColor()
        border_color = Color.keyBorderColor()
        self.setStyleSheet(f"QLabel {{ border: 1px solid {border_color}; border-radius: 4px; padding: 1px; background-color: {background_color}; }}")


    def _icon_change(self, event):
        icon = self.action_entry.icon()
        if icon is None:
            icon = gremlin.util.load_icon("fa6.circle-question")
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
    def __init__(self, object_name, device_guid, parent = None):
        super().__init__(parent)
        self.setObjectName(object_name)

        self._id = gremlin.util.get_guid() # unique ID
        self._blank_input_id = "c9a484aedbab4f518e5bab7ec402df65"  # input ID to use for the blank pages
        self._device_guid = device_guid
        self._device_id = str(device_guid)

        self._lock = False

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.setContentsMargins(0,0,0,0)

        self._content_widget = QContentWidget()
        self._content_widget.resized.connect(self._content_resized)
        self._content_widget.setContentsMargins(0,0,0,0)

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self._content_widget)


        self._left_panel_widget, self._left_panel_layout = getVContainer()
        self._left_panel_widget.setMinimumWidth(200)

        self._right_panel_widget, self._right_panel_layout = getVContainer()

        # left panel, list view on top, buttons on bottom
        self._left_container_widget, self._left_container_layout = getVContainer()

        # right panel content
        self._right_container_widget, self._right_container_layout = getVContainer()

        # input configuration content - new in m76 - have QT track the widgets itself to avoid reference problems in pyside
        self._config_widget = QtWidgets.QStackedWidget()
        self._right_container_layout.addWidget(self._config_widget)
        self._widget_config_index_map = {} # map of input id to widget index
        self._widget_config_device_map = {} # map of widget index to input id

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

        #_tabsplitter_tracker.registerWidget(self)

        syslog.info(f"Created Device content: [{self._id}] {self.objectName()}")

        self._blank_input()


    def _cleanup_ui(self):
        ''' remove '''
        self.unregisterAllWidgets()
        #_tabsplitter_tracker.unregisterWidget(self)

    def registerWidget(self, key, widget) -> int:
        ''' adds a new config input to the right panel '''

        assert widget is not None, "Invalid widget"
        
        index =  self._config_widget.indexOf(widget)
        if index != -1:
            # widget is already in the list
            return index
        
        self._config_widget.addWidget(widget)
        index = self._config_widget.indexOf(widget)
        self._widget_config_index_map[key] = index
        self._widget_config_device_map[index] = key

        return index
    
    def selectRegisteredWidget(self, key):
        ''' selects the content for the given device id if the content exists 
        
        returns: the widget selected
        
        '''
        
        #index = -1
        widget = self.getRegisteredWidget(key)
        assert widget is not None,f"Logic error - widget not found for key [{key}]"
        self._config_widget.setCurrentWidget(widget)
        return widget


    
    
    def unregisterWidget(self, key):
        ''' removes a widget from the cleanup list'''
        
        if key in self._widget_config_index_map:
            index = self._widget_config_index_map[key]
            if index != -1:
                widget = self._config_widget.widget(index)
                if hasattr(widget, "_cleanup_ui"):
                    widget._cleanup_ui()    
                widget.hide()
                self._config_widget.removeWidget(widget)
                widget.deleteLater()
            del self._widget_config_index_map[key]
            del self._widget_config_device_map[index]

    def getCurrentRegisteredWidgetDevice(self):
        ''' gets the device ID for the currently selected device widget '''
        index = self._config_widget.currentIndex()
        if index != -1:
            input_id = self._widget_config_device_map[index]
            return input_id
        return None


    def unregisterAllWidgets(self):
        ''' clears all device widgets '''
        while self._config_widget.count():
            widget = self._config_widget.widget(0)
            if hasattr(widget, "_cleanup_ui"):
                # tell the widget it's being deleted
                widget._cleanup_ui()    
            self._config_widget.removeWidget(widget)
            widget.deleteLater()
            
        self._widget_config_index_map.clear()
        self._widget_config_device_map.clear()

    def getRegisteredWidget(self, key) -> QtWidgets.QWidget:
        ''' gets the widget for the given device id, None if not found'''
        if key in self._widget_config_index_map:
            index = self._widget_config_index_map[key]
            return self._config_widget.widget(index)
        return None
    
    def getRegisteredWidgetIndex(self, key) -> int:
        if key in self._widget_config_index_map:
            return self._widget_config_index_map[key]
        return None

    def getRegisteredKeyIndex(self, index):
        ''' gets the registerted key for the specified index, starting at 0 '''
        keys = [k for k in self._widget_config_index_map.keys()]
        if index < len(keys):
            return keys[index]
        return None
    

    def getContentWidget(self):
        ''' returns configuration items currently displayed in the UI '''
        import gremlin.ui.input_item
        widget =  self._config_widget.currentWidget()
        if isinstance(widget, gremlin.ui.input_item.InputItemMappingWidget):
            return widget
        return None
    
    def getWidgetKey(self, input_type, input_id):
        ''' gets the content widget compound key for the item / input combination'''
        return (gremlin.shared_state.edit_mode, self._device_id, input_type, input_id)
    
    def getContentInputId(self):
        ''' gets the input id currently displayed '''
        import gremlin.ui.input_item
        widget : gremlin.ui.input_item.InputItemMappingWidget = self.getContentWidget()
        if widget:
            return widget.item_data.input_id
        return None
    
    def getContentInputItem(self):
        ''' gets the input id currently displayed '''
        import gremlin.ui.input_item
        widget : gremlin.ui.input_item.InputItemMappingWidget = self.getContentWidget()
        if widget:
            return widget.item_data
        return None
    
    


    
    def setContentWidget(self, input_type, input_id):
        key = self.getWidgetKey(input_type, input_id)
        widget = self.getRegisteredWidget(key)
        if not widget:
            self._ensure_blank_widget()
            key = self.getWidgetKey(input_type, self._blank_input_id)
            widget = self.getRegisteredWidget(key)
            
        if widget:
            self._config_widget.setCurrentWidget(widget)

        return widget
        
        
    def refresh(self, emit = True):
        assert False,"Required method Refresh() not implemented by derived class"


    def _blank_input(self):
        ''' sets a blank input '''
        self._ensure_blank_widget()
        
        # select it
        self.selectRegisteredWidget(self._blank_input_id)


    def _ensure_blank_widget(self):
        widget = self.getRegisteredWidget(self._blank_input_id)
        if not widget:

            label = QtWidgets.QLabel(f"Please select an input to configure for {self.objectName()}.")

            show_id = gremlin.config.Configuration().show_container_id
            if show_id:
                edit = QDataLineEdit(text = self._id)
                edit.setReadOnly(True)
                widget, _ = getHContainer([label, edit])
            else:
                widget = label

            contents, _ = getVContainer(widget)

            self.registerWidget(self._blank_input_id, contents)



    def _select_item_cb(self, index):
        assert False,"Must be implemented by subclass"

    def select_item(self, index):
        # implemented by a subclass
        if not Shiboken.isValid(self):
            return
        if index == -1:
            # nothing selected
            self._blank_input()
        else:
            self._select_item_cb(index)
            # select the corresponding widget
            if index in self._widget_config_device_map:
                key = self._widget_config_device_map[index]
                self.selectRegisteredWidget(key)



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
        ''' sets the right panel widget (only contains a single widget)'''
        pass
        # widgets = gremlin.util.get_layout_widgets(self._right_container_layout)
        # found = False
        # for w in widgets:
        #     if w == widget:
        #         w.setVisible(True)
        #         found = True
        #     w.setVisible(False)

        # if not found and widget is not None:
        #     self._right_container_layout.addWidget(widget)
        #     widget.setVisible(True)
        
        


    def addRightPanelWidget(self, widget : QtWidgets.QWidget):
        ''' adds a widget to the top of the right panel '''
        #print ("add right panel")
        if widget is not None:
            self._right_container_layout.insertWidget(0, widget)

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


class QRememberMainWindow(QtWidgets.QMainWindow):
    
    def __init__(self, key: str, parent = None):
        super().__init__(parent)

        self._resize_count = 0
        assert key,"unique key must be provided"
        self._window_key = key

        
        self._apply_window_settings()
        #gremlin.util.centerDialog(self, parent = parent)



    def _apply_window_settings(self):
        """Restores the stored window geometry settings."""
        config = gremlin.config.Configuration()
        window_size = config.getWindowSize(self._window_key)
        window_location = config.getWindowLocation(self._window_key)
        if window_size:
            self.resize(window_size[0], window_size[1])
        if window_location:
            self.move(window_location[0], window_location[1])

    def moveEvent(self, evt):
        """Handle changing the position of the window.

        :param evt event information
        """
        config = gremlin.config.Configuration()
        config.setWindowLocation(self._window_key, evt.pos().x(), evt.pos().y())
        super().moveEvent(evt)

    def resizeEvent(self, evt):
        """Handling changing the size of the window.

        :param evt event information
        """
        if self._resize_count > 1:
            config = gremlin.config.Configuration()
            config.setWindowSize(self._window_key, evt.size().width(), evt.size().height())

        self._resize_count += 1
        super().resizeEvent(evt)


class QRememberDialog(QtWidgets.QDialog):
    ''' a dialog window that remembers its size and location '''

    def __init__(self, key: str, parent = None):
        super().__init__(parent)

        self._resize_count = 0
        assert key,"unique key must be provided"
        self.window_key = key
        self._moving = False
        self._resizable = True
        self._move_stack = []
        self._move_lock = False
        self._visible = False




    def getResizable(self) -> bool:
        return self._resizable
    def setResizable(self, value: bool):
        self._resizable = value
        if value:
            self.layout().setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetNoConstraint)
        else:
            self.layout().setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetFixedSize)


    def apply_window_settings(self):
        gremlin.util.InvokeUiMethod(self._apply_window_settings_ui)

    def _apply_window_settings_ui(self):
        """Restores the stored window geometry settings."""
        config = gremlin.config.Configuration()
        window_size = config.getWindowSize(self.window_key)
        window_location = config.getWindowLocation(self.window_key)
        if window_size:
            self.resize(window_size[0], window_size[1])
        if window_location:
            x, y = window_location
            pos = QtCore.QPoint(x,y)
            # syslog.info(f"recall move window {self.window_key} to {x},{y}")
            self.move(pos)


    def showEvent(self, event): 
        ''' occurs when window is displayed (made visible)'''
        super().showEvent(event)
        self._visible = True
        self._apply_window_settings_ui()    
    
    def hideEvent(self, event):
        ''' occurs when window is hidden '''
        self._visible = False
        return super().hideEvent(event)
    
    def closeEvent(self, event):
        ''' occurs when window is closed '''
        self._visible = False
        return super().closeEvent(event)

    def hasConfig(self) -> bool:
        ''' checks if the window has saved geometry/position data '''
        config = gremlin.config.Configuration()
        window_location = config.getWindowLocation(self.window_key)
        return window_location is not None

    def moveEvent(self, evt):
        ''' occurs when window is moved '''
        if self._visible:
            # only save the position if the window is visible - that's because the move event can occur multiple times before the window is visible 
            pos = evt.pos()
            config = gremlin.config.Configuration()
            x = pos.x()
            y = pos.y()
            config.setWindowLocation(self.window_key, x, y)
            # syslog.info(f"move event save {self.window_key} to {x},{y}")
        
        super().moveEvent(evt)
        
    def resizeEvent(self, evt):
        """Handling changing the size of the window.

        :param evt event information
        """
        if self._resize_count:
            config = gremlin.config.Configuration()
            config.setWindowSize(self.window_key, evt.size().width(), evt.size().height())
        if not self._resize_count:
            self._resize_count = 1
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
    tabContextMenu = QtCore.Signal(int) # triggers a context menu request (index of the tab)

    def __init__(self, parent = None):
        super().__init__(parent)

        self.installEventFilter(self)
        self._mouse_down = False
        self._to_index = None
        self._from_index = None
        self._mouse_down_index = None
        self._move_in_progress = False
        self.tabMoved.connect(self._tab_moved)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_context_menu)

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

    @QtCore.Slot(QPoint)
    def _open_context_menu(self, position: QPoint):
        index = self.tabAt(position)
        if index != -1:
            self.tabContextMenu.emit(index)


    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.MouseButtonPress:
            self._mouse_down = True
            self._mouse_down_index = self.currentIndex()

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
            
        return super().eventFilter(widget, event)
    
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


class QHorizontalSeparator(QtWidgets.QLabel):
    ''' horizontal separator widget '''
    def __init__(self, parent = None):
        super().__init__(parent)
        icon = gremlin.ui.ui_common.Icons.horizontalSeparatorIcon()
        pixmap = icon.pixmap(QtCore.QSize(24,24))
        self.setPixmap(pixmap)

class QHorizontalLine(QtWidgets.QFrame):
    def __init__(self, parent = None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)

   
def getHContainer(widget_or_list = None, label = None, parent = None, left_stretch = False, alignment = None, set_alignment = True, min_height = None):
    ''' gets a qt H container widget 
    
    :param widget_or_list: list of widgets, or a single widget to add to the container - can contain strings that will be converted to a label automatically, use "|" for separator, "||" to insert a stretch
    :param label: label to add to the container (appears first if provided)
    :param parent: parent widget if any
    :param left_stretch: adds the stretch at the start of the container to right align it on the row
    
    '''
    widget = QtWidgets.QWidget(parent=parent)
    layout = QtWidgets.QHBoxLayout(widget)
    widget.setContentsMargins(0,0,0,0)
    layout.setContentsMargins(0,0,0,0)
    stretch = left_stretch

    if min_height is not None:
        widget.setMinimumHeight(min_height)

    if alignment is None and set_alignment:
        alignment = QtCore.Qt.AlignmentFlag.AlignCenter

    if label:
        layout.addWidget(QtWidgets.QLabel(label))
        stretch = True
    if widget_or_list:
        if isinstance(widget_or_list, list) or isinstance(widget_or_list, tuple):
            for item in widget_or_list:
                if isinstance(item, str):
                    if item == "|": 
                        # separator
                        item = QHorizontalSeparator()
                    elif item == "||":
                        layout.addStretch(1)
                        continue
                    else:
                        item = QtWidgets.QLabel(item)
                if alignment:
                    layout.addWidget(item, alignment = alignment)
                else:
                    layout.addWidget(item)
        else:
            if isinstance(widget_or_list, str):
                item = QtWidgets.QLabel(widget_or_list)
            if alignment:
                layout.addWidget(widget_or_list, alignment= alignment)
            else:
                layout.addWidget(widget_or_list)
        stretch = True
    if stretch:
        if left_stretch:
            layout.insertStretch(0)
        else:
            layout.addStretch()
    return (widget, layout)
    

def getVContainer(widget_or_list = None, label = None, alignment = None, parent = None):
    ''' gets a qt H container widget '''
    widget = QtWidgets.QWidget(parent=parent)
    layout = QtWidgets.QVBoxLayout(widget)
    widget.setContentsMargins(0,0,0,0)
    layout.setContentsMargins(0,0,0,0)
    if alignment is None:
        alignment = QtCore.Qt.AlignmentFlag.AlignTop

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




def getGridContainer(widget_or_list = None, label = None, alignment = QtCore.Qt.AlignmentFlag.AlignLeft, start_col = 0, start_row = None, stretch_col = None, add_to_widget = None ):
    ''' gets a qt grid container widget
     
    :param widget_or_list: the widget or widgets to add to the next row - if the item is a string, it's converted to a label, use "|" for a separator
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
        if isinstance(widget_or_list, tuple):
            widget_or_list = [item for item in widget_or_list]
        elif not isinstance(widget_or_list, list):
            widget_or_list = [widget_or_list]
        
        if label:
            if isinstance(label, str):
                if label == "|": 
                    # separator
                    item = QHorizontalSeparator()
                else:
                    item = QtWidgets.QLabel(label)
                widget_or_list.insert(0, item)

        for item in widget_or_list:
            if isinstance(item, str):
                if item == "|": 
                    # separator
                    item = QHorizontalSeparator()
                else:
                    item = QtWidgets.QLabel(item)
            layout.addWidget(item, row, col)
            col+=1

    if stretch:
        if stretch_col is not None:
            col = stretch_col
        else:
            col = layout.columnCount()
        layout.addWidget(QtWidgets.QWidget(), 0, col)
        layout.setColumnStretch(col, 2)
    return (widget, layout)


def synchronize_grids(grid_widget_list : list, fill_buttons = True):
    ''' synchronizes cell widths between multiple grid layouts 
    :param widget_or_list: the widget or widgets to add to the next row
    :param fill_buttons: if set, button widgets fill the column width
    
    '''
    if len(grid_widget_list) < 2:
        return # nothing to do
    
    g: QtWidgets.QGridLayout
    max_cols = 0
    layouts = [g.layout() for g in grid_widget_list]
    max_cols = max(g.columnCount() for g in layouts)
    
    for col in range(max_cols):
        width = 0   
        widgets = [] 
        for g in layouts:
            rows = g.rowCount()
            if col < g.columnCount():
                for row in range(rows):
                    widget_item = g.itemAtPosition(row, col)
                    if widget_item is not None:
                        widget = widget_item.wid
                        if fill_buttons:
                            if isinstance(widget, QtWidgets.QPushButton) and widget.text():
                                # push button with text
                                widgets.append(widget)
                        width = max(width, widget_item.minimumSize().width())
                        #width = max(width, widget.sizeHint().width())

        for g in layouts:
            g.setColumnMinimumWidth(col, width)
            widget : QtWidgets.QWidget
            for widget in widgets:
                widget.setMinimumWidth(width)
    

def getGroupContainer(widget_or_list = None, label = None, alignment = None, parent = None):
    ''' gets a qt H container widget '''
    widget = QtWidgets.QGroupBox(title = label, parent=parent)
    layout = QtWidgets.QVBoxLayout(widget)
    widget.setContentsMargins(0,0,0,0)
    #layout.setContentsMargins(0,0,0,0)
    if alignment is None:
        alignment = QtCore.Qt.AlignmentFlag.AlignTop

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
                 show_command = True,
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
        self._verbose = gremlin.config.Configuration().verbose_mode_ui

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
        self._total_pages = (self._item_count + self._page_size - 1) // self._page_size
        self._update_data_view(emit)

    def setItemCount(self, count, emit = True):
        self._item_count = count
        self._update_data(emit)
    
    def setPageSize(self, page_size: int, emit = True):
        if self._page_size != page_size:
            self._page_size = page_size
            self._update_data(emit)

    def setPageNumber(self, page_number: int, emit = True):
        ''' set page 1 to n'''
        if page_number < 1:
            page_number = 1
        self._current_page = page_number
        self._update_data(emit)


    def init_ui(self):

        self._first_button_widget = QtWidgets.QPushButton()
        icon = load_icon("fa5s.angle-double-left")
        self._first_button_widget.setIcon(icon)
        self._first_button_widget.setToolTip("Previous")
        self._first_button_widget.clicked.connect(self._first_page)

        self._prev_button_widget = QtWidgets.QPushButton()
        icon = load_icon("fa5s.angle-left")
        self._prev_button_widget.setIcon(icon)
        self._prev_button_widget.setToolTip("Previous")
        self._prev_button_widget.clicked.connect(self._prev_page)

        self._next_button_widget = QtWidgets.QPushButton()
        icon = load_icon("fa5s.angle-right")
        self._next_button_widget.setIcon(icon)
        self._next_button_widget.setToolTip("Next")
        self._next_button_widget.clicked.connect(self._next_page)

        self._last_button_widget = QtWidgets.QPushButton()
        icon = load_icon("fa5s.angle-double-right")
        self._last_button_widget.setIcon(icon)
        self._last_button_widget.setToolTip("Next")
        self._last_button_widget.clicked.connect(self._last_page)


        self._page_label_widget = QtWidgets.QLabel()
        self._page_input_widget = QtWidgets.QLineEdit()
        self._page_input_widget.returnPressed.connect(self._go_to_page)

        widgets = [ 
                self._page_label_widget,
                self._first_button_widget,
                self._prev_button_widget,
                self._page_input_widget,
                self._next_button_widget,
                self._last_button_widget
                ]

        _, layout = getHContainer(widgets)
        self.setLayout(layout)
        self._update_data()
        self._update_display()

    def _update_display(self):
        ''' updates the display items '''
        enabled = self._item_count > 0
        if enabled:
            self._page_label_widget.setText(f"Page {self._current_page} of {self._total_pages} ({self._start_index+1}-{self._end_index+1})")
            with QtCore.QSignalBlocker(self._page_input_widget):
                self._page_input_widget.setText(f"{self._current_page}")
        else:
            # no data
            self._page_label_widget.setText("No items")
            self._page_input_widget.setText("")
        self.setEnabled(enabled)

        

            


    def _update_data_view(self, emit = True):
        ''' updates the widget when pagination changes '''
        if self._item_count:
            self._start_index = (self._current_page - 1) * self._page_size
            self._end_index = min(self._start_index + self._page_size,  self._item_count)
            if emit:
                self.pageChanged.emit(self._current_page, self._start_index, self._end_index)
        self._update_display()
            

    @QtCore.Slot()
    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._update_data_view()

    @QtCore.Slot()
    def _next_page(self):
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._update_data_view()
    
   
    @QtCore.Slot()
    def _first_page(self):
        if self._current_page > 1:
            self._current_page = 1
            self._update_data_view()

    @QtCore.Slot()
    def _last_page(self):
        last_page = self._total_pages
        if self._current_page != last_page:
            self._current_page = last_page
            self._update_data_view()

    def _go_to_page(self):
        text = self._page_input_widget.text()
        if text and text.isnumeric():
            page_num = int(text)
            if 1 <= page_num <= self._total_pages:
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

        

class QGroupBox(QtWidgets.QGroupBox):
    def __init__(self, parent = None):
        super().__init__(parent)
        #self.setContentsMargins(0,0,0,0)
        #self.setStyleSheet("QGroupBox {border: none;}")


        

class QTypeSelectorWidget(QtWidgets.QWidget):
    ''' implements a type selector widget to select a data type '''
    valueChanged = QtCore.Signal(type) # fires when the data type changes 

    def __init__(self, allowed_types = [str, bool, int, float], label = "Datatype:", data_type = None, parent = None):
        super().__init__(parent)

        self._allowed_types = allowed_types
        self._data_type = data_type
        self._label = label
        self._widgets = None

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)

        self._build()

    def _build(self):
        widgets = []
        data = []
        if str in self._allowed_types:
            data.append(("String", str))
        if bool in self._allowed_types:
            data.append(("Bool", bool))
        if int in self._allowed_types:
            data.append(("Integer", int))
        if float in self._allowed_types:
            data.append(("Float", float))

        for label, datatype in data:
            widget = QDataRadioButton(label, data = datatype)
            if self._data_type == datatype:
                widget.setChecked(True)
            widget.clicked.connect(self._type_changed)
            widgets.append(widget)

        gremlin.util.clear_layout(self.main_layout)

        widget,_ = getHContainer(widgets, self._label)
        self.main_layout.addWidget(widget)
        self._widgets = widgets


    @QtCore.Slot()
    def _type_changed(self):
        widget = self.sender()
        value = widget.data
        self.valueChanged.emit(value)

    def value(self) -> type:
        for widget in self._widgets:
            if widget.isChecked():
                return widget.data
            
    def setValue(self, datatype : type):
        for widget in self._widgets:
            if widget.data == datatype:
                widget.setChecked(True)

    def allowedTypes(self) -> list:
        return self._allowed_types
    
    def setAllowedTypes(self, data : list):
        self._allowed_types = data
        self._build()




class QOnOffWidget(QtWidgets.QWidget):
    ''' widget that has a radio button on/off - like a checkbox but spells out the values '''

    valueChanged = QtCore.Signal(bool) # fires when the value changes 

    def __init__(self, value : bool = True, label = None, parent = None):
        super().__init__(parent)

        self._on_widget = QDataRadioButton("On", data = True)
        self._on_widget.setChecked(value)
        self._on_widget.clicked.connect(self._update)
        self._off_widget = QDataRadioButton("Off", data = True)
        self._off_widget.setChecked(not value)
        self._off_widget.clicked.connect(self._update)

        self._value = value

        widget, layout = getHContainer([self._on_widget, self._off_widget], label = label)
        self.setLayout(layout)


    @QtCore.Slot()
    def _update(self):
        widget = self.sender()
        self.setValue(widget.data)

    def value(self):
        return self._value
    
    def setValue(self, value : bool):
        if value != self._value:
            self._value = value
            with QtCore.QSignalBlocker(self._on_widget):
                self._on_widget.setChecked(value)
            with QtCore.QSignalBlocker(self._off_widget):
                self._off_widget.setChecked(not value)
            self.valueChanged.emit(value)


class QAxisSourceSelector(QtWidgets.QWidget):
    ''' axis input selector - lets the user pick an input device and an axis on that input device (physical or virtual) '''
    valueChanged = QtCore.Signal(object, int)  # fires when a device is selected

    def __init__(self, label = "Device:", device_id = None, input_id = None, exclude_list = None, parent = None):
        ''' param: exclude_list : list of device ID (strings) to exclude from the drop down '''

        super().__init__(parent)

        widgets = []
        self._device_selector_widget = QDataComboBox()
        self._device_selector_widget.currentIndexChanged.connect(self._device_changed)
        self._axis_selector_widget = QDataComboBox()
        self._axis_selector_widget.currentIndexChanged.connect(self._axis_changed)

        self._refresh_widget = QDataPushButton()
        icon = load_icon("ei.refresh")
        self._refresh_widget.setIcon(icon)
        self._refresh_widget.setMaximumWidth(24)
        self._refresh_widget.setToolTip("Refresh device list")
        self._refresh_widget.clicked.connect(self.refresh)

        if label:
            widgets.append(QtWidgets.QLabel(label))
        widgets.append(self._device_selector_widget)
        widgets.append(QtWidgets.QLabel("Axis:"))
        widgets.append(self._axis_selector_widget)
        widgets.append(self._refresh_widget)

        widget, layout = getHContainer(widgets)

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.main_layout.addWidget(widget)
        self._exclude_list = exclude_list or []
        self.refresh()
        if device_id:
            self.setDeviceId(device_id)
        if input_id is not None:
            self.setInputId(input_id)

    def sync(self, device_id, input_id):
        ''' sync the widget with the given device/input '''
        if not isinstance(device_id, str):
            device_id = str(device_id)

        # sync device
        device = next((device for device in gremlin.joystick_handling.all_joystick_devices() if device.device_id == device_id), None)
        if device and device != self._device_selector_widget.currentData():
            # change the device
            index = self._device_selector_widget.findData(device)
            if index != -1:
                self._device_selector_widget.setCurrentIndex(index)
                self._refresh_axes()

        # sync axis
        if input_id is not None:
            index = self._axis_selector_widget.findData(input_id)
            if index != -1:
                self._axis_selector_widget.setCurrentIndex(index)
            


        

        
    @QtCore.Slot()
    def refresh(self):
        ''' refreshes the device data '''
        self._refresh_devices()
        self._refresh_axes()
    
        
    def _refresh_devices(self):
        ''' refreshes available devices '''

        device = self._device_selector_widget.currentData() if self._device_selector_widget.count() else None
        with QtCore.QSignalBlocker(self._device_selector_widget):
            self._device_selector_widget.clear()
            for device in gremlin.joystick_handling.all_joystick_devices():
                if device.device_id in self._exclude_list or device.axis_count == 0:
                    continue # skip this one
                self._device_selector_widget.addItem(device.name, device)

            if device is not None:
                index = self._device_selector_widget.findData(device)
                if index != -1:
                    self._device_selector_widget.setCurrentIndex(index)


    def _refresh_axes(self):
        ''' refresh available axes on the device '''
        if self._device_selector_widget.count() > 0:
            input_id = self._axis_selector_widget.currentData() if self._axis_selector_widget.count() > 0 else None
            with QtCore.QSignalBlocker(self._axis_selector_widget):
                self._axis_selector_widget.clear()
                device : DeviceSummary
                device = self._device_selector_widget.currentData()
                count = device.axis_count
                self._axis_selector_widget.clear()
                for id in range(1, count+1):
                    axis_name = device.axis_names[id-1]
                    self._axis_selector_widget.addItem(f"Axis {axis_name}",id)

            if input_id is not None:
                index = self._axis_selector_widget.findData(input_id)
                if index != -1:
                    self._axis_selector_widget.setCurrentIndex(index)



    def device(self) -> DeviceSummary:
        ''' gets the selected device '''
        if self._device_selector_widget.count() > 0:
            return self._device_selector_widget.currentData()
        return None
    
    def deviceId(self) -> str:
        ''' gets the selected device ID '''
        if self._device_selector_widget.count() > 0:
            device = self._device_selector_widget.currentData()
            return device.device_id
        return None
    
    def setDeviceId(self, device_id) -> bool:
        ''' selects the device with the given ID '''
        if not isinstance(device_id, str):
            # got a guid
            device_id = str(device_id)
        device = next(( device for device in gremlin.joystick_handling.all_joystick_devices() if device.device_id == device_id), None)
        if device:
            index = self._device_selector_widget.findData(device)
            if index != -1:
                self._device_selector_widget.setCurrentIndex(index)
                return True
        return False

    def inputId(self) -> int:
        if self._axis_selector_widget.count() > 0:
            return self._axis_selector_widget.currentData()
        return None
    
    def setInputId(self, id : int):
        index = self._axis_selector_widget.findData(id)
        if index != -1:
            self._axis_selector_widget.setCurrentIndex(index)
        
    def axisName(self) -> str:
        if self._axis_selector_widget.count() > 0:
            return self._axis_selector_widget.currentText()
        return None

    @QtCore.Slot()
    def _device_changed(self):
        self._refresh_axes()
        self.valueChanged.emit(self.device(), self.inputId())

    @QtCore.Slot()
    def _axis_changed(self):
        self.valueChanged.emit(self.device(), self.inputId())



class QWarning(QIconLabel):
    def __init__(self, text = None, parent = None):
        super().__init__()
        self.setIcon(Icons.warningIcon())
        if text:
            self.setText(text)


class QRangeWidget(QtWidgets.QWidget):
    ''' range widget - two values, min/max '''
    valueChanged = QtCore.Signal(float, float) # fires when min or max changed 
    minChanged = QtCore.Signal(float) # fires when min changes only
    maxChanged = QtCore.Signal(float) # fires when max changes only


    def __init__(self, min_value : float, max_value = 0,  min_range : float = -1.0, max_range : float = 1.0, label = None, parent = None):
        '''
        :param min_value: starting min value
        :param max_value: starting max value
        :param min_range: min range for the value
        :param max_range: max range for the value
        
        '''


        super().__init__(parent)


        self._min_widget = gremlin.ui.ui_common.QFloatLineEdit(min_value, min_range = min_range, max_range = max_range)
        self._min_widget.valueChanged.connect(self._min_changed)
        self._max_widget = gremlin.ui.ui_common.QFloatLineEdit(max_value, min_range = min_range, max_range = max_range)
        self._min_widget.valueChanged.connect(self._max_changed)


        self._scale_widget, self._scale_layout = gremlin.ui.ui_common.getHContainer([QtWidgets.QLabel(f"{label + ' ' if label else ''}Min:"),
                                                                                     self._min_widget,
                                                                                     QtWidgets.QLabel("Max:"),
                                                                                     self._max_widget,
                                                                                     ])
    def setRange(self, min_range : float, max_range : float):
        ''' updates control ranges '''
        self._min_widget.setRange(min_range, max_range)
        self._max_widget.setRange(min_range, max_range)

    def setMin(self, value : float):
        ''' sets the min range value'''
        self._min_widget.setValue(value)

    def setMax(self, value : float):
        ''' sets the max range value'''
        self._max_widget.setValue(value)

    def minValue(self) -> float:
        v1 = self._min_widget.value()
        return v1
    
    def maxValue(self) -> float:
        v2 = self._max_widget.value()
        return v2
    
    def value(self) -> tuple:
        v1 = self._min_widget.value()
        v2 = self._max_widget.value()
        return (v1, v2)
        
    @QtCore.Slot()
    def _min_changed(self):
        v1 = self._min_widget.value()
        v2 = self._max_widget.value()
        self.minChanged.emit(v1)
        self.valueChanged.emit(v1, v2)

    @QtCore.Slot()
    def _max_changed(self):
        v1 = self._min_widget.value()
        v2 = self._max_widget.value()
        self.maxChanged.emit(v2)
        self.valueChanged.emit(v1, v2)


class QExecuteWidget(QtWidgets.QWidget):

    pressChanged = QtCore.Signal(bool) # fires when press changes
    releaseChanged = QtCore.Signal(bool) # fires when release changes
    valueChanged = QtCore.Signal(bool, bool) # fires when either press or release changed

    ''' widget presenting Execute on press, Execute on release options '''
    def __init__(self, execute_on_press : bool = True, execute_on_release : bool = True, label = None, parent = None):
        super().__init__(parent)

        self._execute_on_press = execute_on_press
        self._execute_on_release = execute_on_release

        self._press_widget = QtWidgets.QCheckBox("Execute on press")
        self._press_widget.setChecked(execute_on_press)
        self._press_widget.setToolTip("If checked, commands sends on a press event")
        self._press_widget.clicked.connect(self._press_changed)


        self._release_widget = QtWidgets.QCheckBox("Execute on release")
        self._release_widget.setChecked(execute_on_release)
        self._release_widget.setToolTip("If checked, commands sends on a release event")
        self._release_widget.clicked.connect(self._release_changed)


        self.main_layout = QtWidgets.QVBoxLayout(self)
        widget, _ = getHContainer([self._press_widget, self._release_widget], label = label)
        self.main_layout.addWidget(widget)
        self.main_layout.setSpacing(0)
        

    @QtCore.Slot(bool)
    def _press_changed(self, checked : bool):
        self._execute_on_press = checked
        v1 = checked
        v2 = self.execute_on_release
        self.pressChanged.emit(v1)
        self.valueChanged.emit(v1,v2)

        
    @QtCore.Slot(bool)
    def _release_changed(self, checked : bool):
        self._execute_on_release = checked
        v1 = self.execute_on_press
        v2 = checked
        self.releaseChanged.emit(v2)
        self.valueChanged.emit(v1,v2)


    @property
    def execute_on_press(self) -> bool:
        return self._execute_on_press
    
    @execute_on_press.setter
    def execute_on_press(self, value : bool):
        if value != self._execute_on_press:
            self._execute_on_press = value
            with QtCore.QSignalBlocker(self._press_widget):
                self._press_widget.setChecked(True)

    @property
    def execute_on_release(self) -> bool:
        return self._execute_on_release
    
    @execute_on_release.setter
    def execute_on_release(self, value : bool):
        if value != self._execute_on_release:
            self._execute_on_release = value
            with QtCore.QSignalBlocker(self._release_widget):
                self._release_widget.setChecked(True)


# adapted from GitHub example https://github.com/cameel/auto-resizing-text-edit/tree/master
class QAutoResizingTextEdit(QtWidgets.QTextEdit):
    def __init__(self, parent = None):
        super(QAutoResizingTextEdit, self).__init__(parent)

        # This seems to have no effect. I have expected that it will cause self.hasHeightForWidth()
        # to start returning True, but it hasn't - that's why I hardcoded it to True there anyway.
        # I still set it to True in size policy just in case - for consistency.
        size_policy = self.sizePolicy()
        size_policy.setHeightForWidth(True)
        size_policy.setVerticalPolicy(QtWidgets.QSizePolicy.Preferred)
        self.setSizePolicy(size_policy)

        self.textChanged.connect(lambda: self.updateGeometry())

    def setMinimumLines(self, num_lines):
        """ Sets minimum widget height to a value corresponding to specified number of lines
            in the default font. """

        self.setMinimumSize(self.minimumSize().width(), self.lineCountToWidgetHeight(num_lines))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        margins = self.contentsMargins()

        if width >= margins.left() + margins.right():
            document_width = width - margins.left() - margins.right()
        else:
            # If specified width can't even fit the margin, there's no space left for the document
            document_width = 0
        document = self.document().clone()
        document.setTextWidth(document_width)

        return margins.top() + document.size().height() + margins.bottom()

    def sizeHint(self):
        original_hint = super(QAutoResizingTextEdit, self).sizeHint()
        return QSize(original_hint.width(), self.heightForWidth(original_hint.width()))

    def lineCountToWidgetHeight(self, num_lines):
        """ Returns the number of pixels corresponding to the height of specified number of lines
            in the default font. """

        assert num_lines >= 0

        widget_margins  = self.contentsMargins()
        document_margin = self.document().documentMargin()
        font_metrics    = QtGui.QFontMetrics(self.document().defaultFont())

        return (
            widget_margins.top()                      +
            document_margin                           +
            max(num_lines, 1) * font_metrics.height() +
            self.document().documentMargin()          +
            widget_margins.bottom()
        )



class QInfoBox(QtWidgets.QFrame):
    ''' widget for information text '''
    def __init__(self, text, wrap = False, parent = None):
        super().__init__(parent = parent)
        self._label_widget = QAutoResizingTextEdit()
        self._label_widget.setReadOnly(True)
        layout = QtWidgets.QVBoxLayout(self)
        
        layout.addWidget(self._label_widget)
        self.setStyleSheet(Color.cssInfoBox())

        self.setText(text)

    def setText(self, text):
        self._label_widget.setHtml(text)
        
        

class GridClickWidget(QtWidgets.QWidget):
    ''' implements a widget that reponds to a mouse click '''
    pressPos = None
    clicked = Signal()

    def __init__(self, vjoy_device_id, input_type, vjoy_input_id, parent = None):
        super(GridClickWidget, self).__init__(parent=parent)
        self.vjoy_device_id = vjoy_device_id
        self.input_type = input_type
        self.vjoy_input_id = vjoy_input_id


    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton :
            self.pressPos = event.pos()

    def mouseReleaseEvent(self, event):
        # ensure that the left button was pressed *and* released within the
        # geometry of the widget; if so, emit the signal;
        if self.pressPos is not None and event.button() == QtCore.Qt.LeftButton:
            pos = event.pos()
            rect = self.rect()
            if  rect.contains(pos):
                self.clicked.emit()
        self.pressPos = None

# class GridButton(QtWidgets.QPushButton):
#     def __init__(self, action):
#         super(GridButton,self).__init__()
#         self.action = action

#     def _clicked(self):
#         pass

class QButtonGrid(QtWidgets.QWidget):
    ''' button grid - displays joystick button grid and state '''

    def __init__(self, device, parent = None):
        ''' init '''

        super().__init__(parent)
        from dinput import DeviceSummary
        self._state = {} # map of button number to state [id:int] = bool
        self._device : DeviceSummary = device
        self._device_guid = device.device_guid
        self._device_id = device.device_id
        self._button_count = device.button_count
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self._create_input_grid()

    
    def from_device(self):
        ''' sets the state from the current device '''
        if not self._device:
            return
        self._state.clear()
        for id in range(1, self.button_count + 1):
            state = gremlin.joystick_handling.get_button(self._device_guid, id)
            self._state[id] = state
        self._populate_grid()

    def from_profile(self, profile):
        ''' reads the data from the current profile '''
        if not self._device:
            return
        self._state.clear()
        for id in range(1, self._button_count + 1):
            state = profile.getStartButtonState(self._device_id, id)
            if state is None:
                state = False # default
            self._state[id] = state
        self._populate_grid()

    def to_profile(self, profile):
        ''' saves the data to the current profile '''
        if not self._device:
            return
        for id in range(1, self._button_count + 1):
            state = self._state[id]
            profile.setStartButtonState(self._device_id, id, state)

    def all_on(self):
        for id in range(1, self._button_count + 1):
            self._state[id] = True
        self._populate_grid()
            
    def all_off(self):
        for id in range(1, self._button_count + 1):
            self._state[id] = False
        self._populate_grid()
            

    def to_profile(self, profile):
        ''' saves widget data to a profile '''
        for id, state in self._state.items():
            profile.setStartButtonState(self._device_id, id, state)

    def _populate_grid(self):
        gremlin.util.InvokeUiMethod(self._populate_grid_ui)

    def _populate_grid_ui(self):
        ''' updates the usage grid based on current VJOY mappings '''

        self._grid_widgets = {}

        for cb in self.button_group.buttons():
            id = self.button_group.id(cb)
            self._grid_widgets[id] = cb
            with QtCore.QSignalBlocker(cb):
                if id in self._state:
                    value = self._state[id]
                else:
                    value = False # dafault
                    self._state[id] = False
                cb.setChecked(value)


    def _create_input_grid(self):
        ''' create a grid of buttons for easy selection'''
        
        gremlin.util.clear_layout(self.main_layout)


        self.button_grid_widget = QtWidgets.QWidget()

        # link all radio buttons
        self.button_group = QtWidgets.QButtonGroup()
        self.button_group.buttonClicked.connect(self._select_changed)
        self.button_group.setExclusive(False) # allow multiple selections
        self.icon_map = {}

        self.active_id = -1


        
        grid = QtWidgets.QGridLayout(self.button_grid_widget)
        grid.setSpacing(2)
        self.remap_type_layout = grid

        max_col = 16
        col = 0
        row = 0

        
        for id in range(1, self._button_count+1):
            # container for the vertical box
            v_cont = QtWidgets.QWidget()
            #v_cont.setFixedWidth(32)
            v_box = QtWidgets.QVBoxLayout(v_cont)
            v_box.setContentsMargins(0,0,0,5)
            v_box.setAlignment(QtCore.Qt.AlignCenter)

            # line 1
            h_cont = QtWidgets.QWidget()
            h_cont.setFixedWidth(36)
            h_box = QtWidgets.QHBoxLayout(h_cont)
            h_box.setContentsMargins(0,0,0,0)
            h_box.setAlignment(QtCore.Qt.AlignCenter)
            cb = gremlin.ui.ui_common.QDataRadioButton()

            self.button_group.addButton(cb)
            self.button_group.setId(cb, id)
            cb.data = id # data has the button id

            name = str(id)
            h_box.addWidget(cb)
            v_box.addWidget(h_cont)

            # line 2
            line2_cont = GridClickWidget(self._device_guid, InputType.JoystickButton, id)
            line2_cont.setFixedWidth(36)
            h_box = QtWidgets.QHBoxLayout(line2_cont)
            h_box.setContentsMargins(0,0,0,0)
            h_box.setSpacing(0)


            icon_lbl = QtWidgets.QLabel()

            lbl = QtWidgets.QLabel(name)
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)


            self.icon_map[id] = icon_lbl

            h_box.addWidget(icon_lbl)
            h_box.addWidget(lbl)
            v_box.addWidget(line2_cont)

            line2_cont.clicked.connect(self._grid_button_clicked)


            grid.addWidget(v_cont, row, col)
            col+=1
            if col == max_col:
                row+=1
                col=0

        self.main_layout.addWidget(self.button_grid_widget)

    def _select_changed(self, rb):
        # called when a button is toggled
        button_id = self.button_group.checkedId()
        if not button_id in self._state:
            self._state[button_id] = False
        self._state[button_id] = not self._state[button_id]


    @QtCore.Slot()
    def _grid_button_clicked(self):
        sender = self.sender()
        pass
        
        
