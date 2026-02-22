# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026 
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
import sys
import enum
import time
import threading
import anytree
import os

import logging
from PySide6 import QtWidgets, QtCore, QtGui


import gremlin.config
import gremlin.error
import qtawesome as qta

from gremlin.input_types import InputType
from shiboken6 import Shiboken
import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.shared_state
import gremlin.types
from gremlin.types import SyncMode
from lxml import etree
from PySide6.QtCore import (
    Qt, QSize, QPoint, QPointF, QRectF,
    QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup,
    Slot, Property,
    QEasingCurve,
    QEvent,
    QMargins,
    QObject,
    QPropertyAnimation,
    QRect,
    )

from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap,QColor, QBrush, QPaintEvent, QPen, QPainter, QStandardItemModel, QStandardItem, QLinearGradient
from PySide6.QtWidgets import QFrame, QPushButton, QSizePolicy, QVBoxLayout, QWidget, QCheckBox, QHBoxLayout



from gremlin.util import load_pixmap, load_icon, safe_format, safe_read
import gremlin.util
import gremlin.ui.ui_common
from gremlin.singleton_decorator import SingletonDecorator
from gremlin.types import HatDirection
import gremlin.remote
from dinput import DeviceSummary
import psygnal
from psygnal import Signal
import gremlin.event_handler

syslog = logging.getLogger("system")

    
       

class Color():
    ''' general UI color and stylesheet handling '''
    @staticmethod
    def activeColor():
        return "#51f56f" if gremlin.shared_state.is_dark_theme else "#3BAC41"
    @staticmethod
    def inactiveColor():
        return "#686a6e" if gremlin.shared_state.is_dark_theme else "#8c8c8c"
    @staticmethod
    def onColor():
        return "#93f551" if gremlin.shared_state.is_dark_theme else "#3BAC41"
    @staticmethod
    def offColor():
        return "#08420B" if gremlin.shared_state.is_dark_theme else "#8c8c8c"
    @staticmethod
    def normalColor():
        return "#AAAAAA" if gremlin.shared_state.is_dark_theme else "#111111"
    def disabledColor():
        return "#2E2E2E" if gremlin.shared_state.is_dark_theme else "#9C9C9C"
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
        return "#A7A7A7" if gremlin.shared_state.is_dark_theme else "#CCCCCC"
    @staticmethod
    def backgroundColor():
        return "#212121" if gremlin.shared_state.is_dark_theme else "#EEEEEE"
    @staticmethod
    def tabBackgroundColor():
        return "#212121" if gremlin.shared_state.is_dark_theme else "#EEEEEE"
    @staticmethod
    def tabForegroundColor():
        return "#B6B6B6" if gremlin.shared_state.is_dark_theme else "#303030"
    @staticmethod
    def tabMissingForegroundColor():
        return "#8a761c" if gremlin.shared_state.is_dark_theme else "#725919"
    @staticmethod
    def tabUsedForegroundColor():
        return "#FFFFFF" if gremlin.shared_state.is_dark_theme else "#000000"
    @staticmethod
    def tabUsedOtherForegroundColor():
        return "#B9B9B9" if gremlin.shared_state.is_dark_theme else "#777777"
    @staticmethod
    def blueColor():
        return "#34b7eb" if gremlin.shared_state.is_dark_theme else "#0B15AA"
    @staticmethod
    def grayColor():
        return "#6e6e6e" if gremlin.shared_state.is_dark_theme else "#B1B1B1"
    @staticmethod
    def orangeColor():
        return "#ebd034" if gremlin.shared_state.is_dark_theme else "#968215"
    @staticmethod
    def greenColor():
        return "#2abd38" if gremlin.shared_state.is_dark_theme else "#088814"
    @staticmethod
    def yellowColor():
        return "#d9eb34" if gremlin.shared_state.is_dark_theme else "#818b20"
    @staticmethod
    def grayColor():
        return "#949494" if gremlin.shared_state.is_dark_theme else "#585858"
    @staticmethod
    def buttonGradientStartColor():
        return "#757575" if gremlin.shared_state.is_dark_theme else "#E2E2E2"
    @staticmethod
    def buttonGradientEndColor():
        return "#5A5A5A" if gremlin.shared_state.is_dark_theme else "#BDBDBD"
    
    @staticmethod
    def selectedBackgroundColor():
        return Color.selectColor()
    @staticmethod
    def highlightBackgroundColor():
        return "#66612f" if gremlin.shared_state.is_dark_theme else "#FFF4B0"
    @staticmethod
    def borderColor():
        return "#585858" if gremlin.shared_state.is_dark_theme else "#111111"
    @staticmethod
    def menuSeparatorColor():
        return "#CACACA" if gremlin.shared_state.is_dark_theme else "#111111"

    @staticmethod
    def titleBackgroundColor():
        return "#222222" if gremlin.shared_state.is_dark_theme else "#AAAAAA"
    @staticmethod
    def warningColor():
        return Color.orangeColor()
    @staticmethod
    def selectColor():
        return "#658265" if gremlin.shared_state.is_dark_theme else "#8FBC8F"
    @staticmethod
    def alternateSelectColor():
        return "#8a761c" if gremlin.shared_state.is_dark_theme else "#bcaf8f"
    @staticmethod
    def selectGradientColor():
        return "#448044"
    @staticmethod
    def selectEndGradientColor():
        return "#61BB61"
    @staticmethod
    def alternateSelectGradientColor():
        return "#677517"
    @staticmethod
    def alternateSelectEndGradientColor():
        return "#ACC425"
    @staticmethod
    def ChannelColors():
        ''' pairs of channel colors'''
        if gremlin.shared_state.is_dark_theme:
            return [
                ("#448044","#61BB61"),
                ("#677517","#ACC425"),
                ("#177533","#25C4B7"),
                ("#5F1775","#B725C4"),
                ("#174875","#504EC0"),
                ("#A7A7A7","#E4E4E4"),
            ]
        else:
            return [
                ("#448044","#61BB61"),
                ("#7A8B14","#8DA311"),
                ("#177533","#25C4B7"),
                ("#5F1775","#B725C4"),
                ("#174875","#504EC0"),
                ("#494949","#858585"),
            ]
    
    @staticmethod
    def extraChannelC1Color():
        return "#ACC425"
    
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
        return "#414141" if gremlin.shared_state.is_dark_theme else "#9B9B9B"
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
        return Color.blueColor()
    @staticmethod
    def infoBackgroundColor(): # color used for information boxes
        return "#92882b"  if gremlin.shared_state.is_dark_theme else "#dbd496"
    def infoColor(): # color used for information boxes
        return "#f1f1f1"  if gremlin.shared_state.is_dark_theme else "#3d3d3d"
    @staticmethod
    def frameColor(): # color used for frame boxes
        return "#8a8a8a"  if gremlin.shared_state.is_dark_theme else "#dddddd"
    @staticmethod
    def inputTitleColor(): # color for the input title bar
        return "#5A725A" if gremlin.shared_state.is_dark_theme else "#678867"
    @staticmethod
    def inputTitleUnselectedColor(): # color for the input title bar
        return "#3A3A3A" if gremlin.shared_state.is_dark_theme else "#C9C9C9"
    @staticmethod
    def repeaterColor(): # color for repeaters
        return "#0C8D12"
    def repeaterBackgroundColor(): # color for repeaters
        return "#374438" if gremlin.shared_state.is_dark_theme else "#829784"
    
    @staticmethod
    def ansiRed(): 
        return '\033[91m'
    @staticmethod
    def ansiGreen(): 
        return '\033[92m'
    @staticmethod
    def ansiBlue(): 
        return '\033[94m'
    @staticmethod
    def ansiYellow(): 
        return '\033[93m'
    @staticmethod
    def ansiMagenta(): 
        return '\033[95m'
    @staticmethod
    def ansiCyan(): 
        return '\033[96m'
    @staticmethod
    def ansiWhite():     
        return '\033[97m'
    @staticmethod
    def ansiReset(): 
        return '\033[0m'


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
        background_color = Color.infoBackgroundColor()
        foreground_color = Color.infoColor()
        css = f'''
            background: {background_color};
            color: {foreground_color};
            QFrame {{
                border: 0px solid {border_color};
                
            }}
            QLabel {{
                border: none;
            }}
            
            '''
        return css
    
    @staticmethod
    def cssFrameBox(): 
        border_color = Color.borderColor()
        background_color = Color.frameColor()
        css = f'''
            QFrame {{
                border: 2px solid {border_color};
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

          

            QGroupBox::indicator:checked {{
                image: url({relative_path}{checkbox_checked});
            }}
            QGroupBox::indicator:unchecked {{
                image: url({relative_path}{checkbox_unchecked}); 
                width: 18px;
                height: 18px;
            }}
            QGroupBox  {{
                border: 1px solid {border_color};
                margin-top: 27px;
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
        gradient_start = Color.buttonGradientStartColor()
        gradient_end = Color.buttonGradientEndColor()
        css = f'''
        QPushButton {{
            border: 2px solid #8f8f91;
            border-radius: 15px;
            background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {gradient_start}, stop: 1 {gradient_end});
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
                        background_start_color,
                        background_end_color,
                        foreground_color,
                        selected_border_color,
                        selected_color,
                        selected_gradient_color,
                        foreground_disabled):
        min_size = font_size * 2
        radius = font_size 
        css = f'''
        QPushButton {{
            border: 2px solid #8f8f91;
            border-radius: {radius}px;
            background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {background_start_color}, stop: 1 {background_end_color});
            color: {foreground_color};
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
             color: {foreground_disabled};
        }}
        '''
        return css
    

    @staticmethod
    def cssStateButton(font_size = 16):
        ''' gets a pushbutton state for the input viewer '''

        normal_color = Color.normalColor()
        background_start_color = Color.buttonGradientStartColor()
        background_end_color = Color.buttonGradientEndColor()
        selected_border_color = Color.selectBorderColor()
        selected_color = Color.selectColor()
        selected_gradient_color = Color.selectGradientColor()
        disabled_color = Color.disabledColor()
        return Color._cssStateButton(font_size, 
                                    background_start_color,
                                    background_end_color,
                                    normal_color,
                                    selected_border_color,
                                    selected_color,
                                    selected_gradient_color,
                                    disabled_color)

    
    @staticmethod
    def cssStateExpressionButton(font_size = 16):
        ''' gets a pushbutton state for the input viewer '''

        background_start_color = Color.buttonGradientStartColor()
        background_end_color = Color.buttonGradientEndColor()
        normal_color = Color.normalColor()
        selected_border_color = Color.alternateSelectBorderColor()
        selected_color = Color.alternateSelectColor()
        selected_gradient_color = Color.alternateSelectGradientColor()
        disabled_color = Color.disabledColor()
        return Color._cssStateButton(font_size, 
                                background_start_color,
                                background_end_color,
                                normal_color,
                                selected_border_color,
                                selected_color,
                                selected_gradient_color,
                                disabled_color)
 
    
    
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
    def trashIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("ei.trash", qta_color)
    @staticmethod
    def eraserIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("fa6s.eraser", qta_color)
    @staticmethod
    def folderIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.yellowColor()
        return Icons._icon("fa5s.folder-open", qta_color)
    @staticmethod
    def saveIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.yellowColor()
        return Icons._icon("fa5s.save", qta_color)
    @staticmethod
    def keyboardIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("fa6s.keyboard", qta_color)
    @staticmethod
    def addIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("msc.diff-added", qta_color)
    @staticmethod
    def sortIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("fa5s.sort-amount-down-alt", qta_color)
    @staticmethod
    def removeIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("fa6s.minus", qta_color)
    @staticmethod
    def gearIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("fa6s.gear", qta_color)
    @staticmethod
    def findIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("ei.search", qta_color)
    @staticmethod
    def sortUpIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("mdi.sort-ascending", qta_color)
    @staticmethod
    def sortDownIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("mdi.sort-descending", qta_color)
    @staticmethod
    def questionIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("fa5s.question-circle", qta_color)
    @staticmethod
    def refreshIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("ei.refresh", qta_color)
    @staticmethod
    def resizeIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("ph.frame-corners", qta_color)
    @staticmethod
    def copyIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("fa6.copy", qta_color)
    @staticmethod
    def pasteIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("fa6.paste", qta_color)
    @staticmethod
    def configureIcon(qta_color = None) -> QtGui.QIcon:
        return Icons._icon("fa6s.gear", qta_color)
    @staticmethod
    def editIcon(qta_color = None) -> QtGui.QIcon:
        if not qta_color: qta_color = Color.blueColor()
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
    def disconnectedIcon(qta_color = Color.tabMissingForegroundColor()):
        return Icons._icon("mdi.power-plug-off", qta_color = qta_color)
    @staticmethod
    def usedIcon(qta_color = Color.tabUsedForegroundColor()):
        return Icons._icon("fa6s.sitemap", qta_color = qta_color)

    @staticmethod
    def warningIcon():
        return Icons._icon("ph.shield-warning-fill",qta_color=QtGui.QColor(Color.warningColor()))
    @staticmethod
    def infoIcon(qta_color = "#34b7eb"):
        return Icons._icon("fa5s.info-circle",qta_color=qta_color)
    @staticmethod
    def mappedIcon(qta_color = None):
        if not qta_color: qta_color = Color.normalColor()
        return Icons._icon("ph.tree-structure-fill", qta_color = qta_color)
    @staticmethod
    def mappedOtherIcon(qta_color = None):
        if not qta_color: qta_color = Color.normalColor()
        return Icons._icon("ph.tree-structure-thin", qta_color = qta_color)
    
    @staticmethod
    def aircraftIcon():
        return Icons._icon("mdi.airplane")
    @staticmethod
    def lockIcon(qta_color = None):
        if not qta_color: qta_color = Color.orangeColor()
        return Icons._icon("fa5s.lock", qta_color = qta_color)
    @staticmethod
    def unlockIcon(qta_color = None):
        if not qta_color: qta_color = Color.greenColor()
        return Icons._icon("fa5s.lock-open", qta_color = qta_color)
    @staticmethod
    def filterIcon(qta_color = None):
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("mdi.filter", qta_color = qta_color)
    @staticmethod
    def noFilterIcon():
        return Icons._icon("mdi.filter-off")
    @staticmethod
    def mappedIcon(qta_color = None):
        if not qta_color: qta_color = Color.blueColor()
        return Icons._icon("ri.organization-chart", qta_color = qta_color)
    @staticmethod
    def noMappedIcon(qta_color = None):
        if not qta_color: qta_color = Color.grayColor()
        return Icons._icon("ri.organization-chart", qta_color = qta_color)
    @staticmethod
    def treeIcon(qta_color = None):
        if not qta_color: qta_color = Color.yellowColor()
        return Icons._icon("ph.tree-structure-thin", qta_color = qta_color)
    @staticmethod
    def chevronIcon(qta_color = None):
        if not qta_color: qta_color = Color.grayColor()
        return Icons._icon("ph.tag-chevron-fill", qta_color = qta_color)
    
    
    @staticmethod
    def collapseAllIcon():
        return Icons._icon("mdi6.arrow-collapse-vertical")
    @staticmethod
    def expandAllIcon():
        return Icons._icon("mdi6.arrow-expand-vertical")
    @staticmethod
    def syncIcon():
        return Icons._icon("mdi6.format-horizontal-align-left")
    @staticmethod
    def remoteControlIcon():
        return Icons._icon("mdi.remote")
    

    def _icon(value : str, qta_color = None):
        if qta_color and isinstance(qta_color, str):
            qta_color = QtGui.QColor(qta_color)
        return load_icon(value, qta_color = qta_color) if qta_color is not None else load_icon(value)
    
    def to_pixmap(icon : QtGui.QIcon, pixels = 24):
        ''' convers an icon to a pixmap'''
        #icon : QtGui.QIcon = Icons.warningIcon()
        return icon.pixmap(QtCore.QSize(pixels, pixels))
@SingletonDecorator
class Pixmaps():
    ''' holds common pixmaps '''
    def __init__(self):
        self._icon_size = QtCore.QSize(16,16)
        on_icon = load_icon("mdi.checkbox-blank-circle",use_qta=True,qta_color=Color.onColor())
        self.onIconPixmap = on_icon.pixmap(self._icon_size)
        off_icon = load_icon("mdi.checkbox-blank-circle",use_qta=True,qta_color=Color.offColor())
        self.offIconPixmap = off_icon.pixmap(self._icon_size)
        self.warningIconPixmap =  Icons.to_pixmap(Icons.warningIcon(), pixels = 24)
        icon = Icons.horizontalSeparatorIcon()
        self.horizontalSeparatorPixmap = icon.pixmap(QtCore.QSize(24,24))


class Buttons():
    ''' common UI button widgets '''

    maxHeight = 24 # max height in pixels

    @staticmethod
    def _template(label = "", icon_source : str = "", tooltip = None, callback = None, no_keyboard = True, data = None, width : int = None, height : int = None):
        
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
        if height is not None:
            widget.setMaximumHeight(height)
        return widget
    
    @staticmethod
    def getDeleteWidget(label = None, tooltip = "Delete", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, "mdi6.delete", tooltip, callback, no_keyboard, data)
        
    
    @staticmethod
    def getAddWidget(label = "Add", tooltip = "Add", callback = None, no_keyboard = True, data = None):
        button =  Buttons._template(label, "ri.add-line", tooltip, callback, no_keyboard, data)
        button.setMinimumHeight(24)
        #button.setFixedWidth(get_text_width(label)*1.3)
        # button.setStyleSheet(f" QPushButton {{margin-left: none;}}")
        return button
    
    @staticmethod
    def getRemoveWidget(label = "Remove", tooltip = "Remove", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, "mdi.close-box-outline", tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getEditWidget(label = None, tooltip = "Edit", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, "msc.edit", tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getSearchWidget(label = None, tooltip = "Search", callback = None, no_keyboard = True, data = None):
        icon = Icons.findIcon()
        return Buttons._template(label, icon, tooltip, callback, no_keyboard, data)
    
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
    def getEraserWidget(label = None, tooltip = "Clear", callback = None, no_keyboard = True, data = None, width = 24, height = 24):
        return Buttons._template(label, Icons.eraserIcon(), tooltip, callback, no_keyboard, data, width=width, height=height)
    
    @staticmethod
    def getFolderWidget(label = None, tooltip = None, callback = None, no_keyboard = True, data = None, width = 24, height = 24):
        return Buttons._template(label, Icons.folderIcon(), tooltip, callback, no_keyboard, data, width = width, height = height)

    @staticmethod
    def getSaveWidget(label = None, tooltip = None, callback = None, no_keyboard = True, data = None, width = 24, height = 24):
        return Buttons._template(label, Icons.saveIcon(), tooltip, callback, no_keyboard, data, width = width, height = height)


    @staticmethod
    def getOkWidget(label = "Ok", tooltip = "Accept", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, None, tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getCancelWidget(label = "Cancel", tooltip = "Cancel", callback = None, no_keyboard = True, data = None):
        return Buttons._template(label, None, tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getSortUpWidget(label = None, tooltip = "Sort up", callback = None, no_keyboard = True, data = None):
        icon = Icons.sortUpIcon()
        return Buttons._template(label, icon, tooltip, callback, no_keyboard, data)
    @staticmethod
    def getSortDownWidget(label = None, tooltip = "Sort Down", callback = None, no_keyboard = True, data = None):
        icon = Icons.sortDownIcon()
        return Buttons._template(label, icon, tooltip, callback, no_keyboard, data)
    
    @staticmethod
    def getRefreshWidget(label = None, tooltip = "Refresh", callback = None, no_keyboard = True, data = None):
        icon = Icons.refreshIcon()
        return Buttons._template(label, icon, tooltip, callback, no_keyboard, data)

    @staticmethod
    def getResizeWidget(label = None, tooltip = "AutoSize", callback = None, no_keyboard = True, data = None):
        icon = Icons.resizeIcon()
        return Buttons._template(label, icon, tooltip, callback, no_keyboard, data)
                
    @staticmethod
    def getListSyncWidget(label = None, tooltip = "Find In List", callback = None, no_keyboard = True, data = None):
        icon = Icons.syncIcon()
        return Buttons._template(label, icon, tooltip, callback, no_keyboard, data)

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
        
    @staticmethod
    def getCollapseAllWidget(tooltip = "Collapse All", callback = None, width = 24, height = 24):
        return Buttons._template(None, Icons.collapseAllIcon(), tooltip, callback, width=width, height=height)
    
    @staticmethod
    def getExpandAllWidget(tooltip = "Collapse All", callback = None, width = 24, height = 24):
        return Buttons._template(None, Icons.expandAllIcon(), tooltip, callback, width=width, height=height)
    
    @staticmethod
    def getRecordWidget(tooltip = "Record", callback = None, width = 24, height = 24):
        return Buttons._template(None, Icons.recordIcon(), tooltip, callback, width=width, height=height)
    
    
    

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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self._button_cache:
            if input_type in self._button_cache[device_guid]:
                key = self._key(input_id)
                if key in self._button_cache[device_guid][input_type]:
                    widget = self._button_cache[device_guid][input_type][key]
                    return widget
                
        return None
    
    def getAxisWidget(self, device_guid, input_type, input_id):
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
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
            device_guid = gremlin.util.normalize_guid(device_guid)
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


class AbstractModel(QtCore.QAbstractItemModel):

    """Base class for MVC models."""

    data_changed = Signal()

    def __init__(self, parent=None):
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
            if value:
                self._model.data_changed.connect(self._model_changed)

            self._model_changed()                

    def _model_changed(self):
        syslog.info("model changed")
        self.redraw()


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

    def __init__(self, label = None, parent=None):
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





class QLineEdit(QtWidgets.QLineEdit):

    focusOut = QtCore.Signal()

    def __init__(self, text = None, callback = None, parent = None, tooltip = None):
        super().__init__(text = text, parent = parent)
        self._callback = callback
        self.focusOut.connect(self._handle_text_changed)
        if tooltip:
            self.setToolTip(tooltip)

    def _handle_text_changed(self, value : str):
        if self._callback:
            self._callback(value)

    def focusOutEvent(self, event):
        self.focusOut.emit()
        return super().focusOutEvent(event)


class QFloatLineEdit(QtWidgets.QWidget):
    ''' double input validator with optional range limits for input axis

        this line edit behaves like a spin box so it's interchangeable

    '''

    valueChanged = QtCore.Signal(float) # fires when the value changes
    doubleClick = QtCore.Signal() # fires when the input is double clicked

    def __init__(self, data = None, min_range = -1.0, max_range = 1.0, decimals = 3,  step = 0.01, value = 0.0, chars = 8, callback = None, tooltip = None, parent = None):
        super().__init__(parent)
        self._min_range = min_range
        self._max_range = max_range
        self._step = step
        self._decimals = decimals
        self._value = None
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self._widget = QLineEdit()
        self._widget.focusOut.connect(self._focus_out)
          
        # validate on field lost focus only
        #self._widget.textChanged.connect(self._validate)

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

        if tooltip:
            self.setToolTip(tooltip)
        if callback:
            self.valueChanged.connect(callback)

    def _focus_out(self):
        # syslog.info("focus loss")
        value = self._widget.text()
        try:
            value = float(value)
        except:
            value = self.value()
        self.setValue(value)
        

    def setReadOnly(self, value : bool):
        ''' sets or clears readonly state '''
        if not Shiboken.isValid(self):
            return
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
                el = gremlin.event_handler.EventListener()
                is_shifted = el.get_shifted_state()
                factor = 0.1 if is_shifted else 1.0
                if event.angleDelta().y() > 0:
                    # up
                    v += self._step * factor
                else:
                    # down
                    v -= self._step * factor
                if v < self._min_range:
                    v = self._min_range
                elif v > self._max_range:
                    v = self._max_range
                #v = gremlin.util.clamp(v, self._min_range, self._max_range)
                self.setValue(v)
                
            return True # filter the wheel event
        elif t == QtCore.QEvent.Type.FocusAboutToChange:
            syslog.info("focus about to change")
            value = self._to_value()
            if value is None:
                return True # skip the event
        elif t == QtCore.QEvent.Type.FocusOut:
            # format the input to the correct decimals
            # syslog.info("focus loss")
            self.setValue(self.value())
        elif t == QtCore.QEvent.Type.MouseButtonDblClick:
            self.doubleClick.emit()
        

        return super().eventFilter(widget, event)
    
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


    def _update_value(self, value, emit : bool = True, format : bool = True):
        gremlin.util.assert_ui_thread()
        if not Shiboken.isValid(self):
            return
        if value is None:
            return
        current_value = self._value

        if self._decimals > 0:
            s_value = f"{float(value):0.{self._decimals}f}"
        else:
            s_value = f"{int(value)}"
        with QtCore.QSignalBlocker(self):
            self._widget.setText(s_value)
        if current_value is None or current_value != value:
            self._value = value
            if emit:
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
        

    def setValue(self, value : float, emit : bool = True):
        ''' sets the value '''
        #if not gremlin.util.is_close(self._value, value):
        gremlin.util.InvokeUiMethod(self._update_value, value, emit)
            

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


    def __init__(self, data = None, min_range = -1.0, max_range = 1.0, decimals = 3, step = 0.01, value = 0.0, chars = 8, callback = None, parent = None):
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

        if callback:
            self.valueChanged.connect(callback)
        


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
        if not Shiboken.isValid(self):
            return
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


class IntValidator(QtGui.QValidator):
    def __init__(self, min_range = None, max_range = None, parent=None):
        super().__init__(parent)
        self._min_range = min_range
        self._max_range = max_range

    def setBottom(self, value : int):
        self._min_range = value

    def setTop(self, value : int):
        self._max_range = value

    def validate(self, input_str, pos):
        # Implement your custom validation logic here
        # Return a tuple: (state, validated_string, cursor_position)
        # States: QValidator.Invalid, QValidator.Intermediate, QValidator.Acceptable

        if not input_str:
            return (QtGui.QValidator.Intermediate, input_str, pos)
        
        # invalid characters?
        if not gremlin.util.valid_integer_string(input_str):
            return (QtGui.QValidator.Invalid, input_str, pos)
        
        # convert

        try:
            value = int(input_str)
        except:
            return (QtGui.QValidator.Invalid, input_str, pos)
        
        return (QtGui.QValidator.Acceptable, input_str, pos)

        
class QIntLineEdit(QtWidgets.QLineEdit):
    ''' integer input validator with optional range limits for input axis

        this line edit behaves like a spin box so it's interchangeable

    '''

    valueChanged = QtCore.Signal(int) # fires when the value changes
    doubleClick = QtCore.Signal() # fires when the input is double clicked
    invalid = QtCore.Signal() # fires when there is an invalid value entered

    def __init__(self, data = None, min_range = None, max_range = None, step = 1, value = 0, chars = 8, callback = None, tooltip = None, parent = None):
        super().__init__(parent)
        if min_range is not None and max_range is not None:
            if min_range > max_range:
                max_range, min_range = min_range, max_range
        self._min_range = min_range 
        self._max_range = max_range 
        self._step = step

        self._supressed = False # true if events are suppressed

        # self._validator = QtGui.QIntValidator(min_range, max_range) 
    
        self._validator = IntValidator(min_range, max_range) 
        self._validator.setLocale(self.locale()) # handle correct floating point separator
        #self.textChanged.connect(self._validate)
        self.setValidator(self._validator)
        self.installEventFilter(self)
        self.setValue(value)
        self._data = data
        if chars > 0:
            self._chars = chars
            self._update_width(chars)
        else:
            self.chars = 0

        if tooltip:
            self.setToolTip(tooltip)

        if callback:
            self.valueChanged.connect(callback)

    def setSuppressed(self, value : bool):
        self._supressed = value

    def unhook(self):
        ''' called on widget delete '''
        self._supressed = True

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
        if self._supressed:
            return True
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
            # check the range
            value = self.value()
            
            if self._min_range is not None and value < self._min_range:
                self.setValue(self._min_range)
            if self._max_range is not None and value > self._max_range:
                self.setValue(self._max_range)
        elif t == QtCore.QEvent.Type.FocusOut:
            if not self.hasAcceptableInput():
                return True # skip the event
            # format the input to the correct decimals
            self.setValue(self.value())
        elif t == QtCore.QEvent.Type.MouseButtonDblClick:
            if not self._supressed:
                self.doubleClick.emit()
        return False


    def _update_value(self, value : int):
        if not Shiboken.isValid(self):
            return
        other = self.value()
        v1 = int(value)
        if value is None and other is None:
            return
        s_value = str(v1)
        if s_value != self.text():
            with QtCore.QSignalBlocker(self):
                self.setText(s_value)
        if not self._supressed and other is not None and other != value:
            self.valueChanged.emit(v1)

    @QtCore.Slot()
    def _validate(self):
        ''' called whenever the text changes '''
        if self.hasAcceptableInput():
            value = self.value()
            if not self._supressed:
                self.valueChanged.emit(value)
        else:
            if not self._supressed:
                self.invalid.emit()

    def setValue(self, value : int):
        ''' sets the value '''
        v1 = int(value)
        self._update_value(v1)
        if not self._supressed:
            self.valueChanged.emit(v1)

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
        if bottom is not None and top is not None and top < bottom:
            bottom, top = top, bottom
        self._min_range = bottom
        self._max_range = top
        self._validator.setBottom(bottom)
        self._validator.setTop(top)
        value = int(self.text())
        v1 = int(gremlin.util.clamp(value, bottom, top))
        if v1 != value:
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

    def __init__(self,
                  activate_callback = None,
                  selected_callback = None,
                  valid_types = [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
                  parent=None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.grid_layout = QtWidgets.QGridLayout()
        self.main_layout.addLayout(self.grid_layout)

        self.grid_layout.addWidget(QtWidgets.QWidget(),0,2)
        self.grid_layout.setColumnStretch(2,2)

        self._callback = activate_callback
        self._selected_callback = selected_callback
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

        if not self.input_item_dropdowns:
            return None

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

    def set_selection(self, input_type, device_id, input_id, emit = False):
        if isinstance(device_id, str):
            device_id = gremlin.util.parse_guid(device_id) # ensure a GUID
        if device_id not in self._device_id_registry:
            syslog.error(f"INPUT SELECTOR: device not found: {device_id}")
            syslog.info("Valid values are:")
            for value in self._device_id_registry:
                syslog.info(f"\t{value}")

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

        if emit:
            self.input_changed.emit(self.get_selection())


    def _update_device(self, index):

        for entry in self.input_item_dropdowns:
            with QtCore.QSignalBlocker(entry):
                entry.setVisible(False)

        # Show correct dropdown
        entry = self.input_item_dropdowns[index]
        with QtCore.QSignalBlocker(entry):
            entry.setVisible(True)
            entry.setCurrentIndex(0)
        self._execute_callback()
        self._execute_selected_callback()
        


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
        self.device_dropdown = QDataComboBox(self)
        for device in self.device_list:
            self.device_dropdown.addItem(self._format_device_name(device))
            self._device_id_registry.append(self._device_identifier(device))
        self.grid_layout.addWidget(QtWidgets.QLabel("Device:"),0,0)
        self.grid_layout.addWidget(self.device_dropdown,0,1)
        #self.device_dropdown.activated.connect(self._update_device)
        self.device_dropdown.currentIndexChanged.connect(self._update_device)



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
            selection_widget = QDataComboBox(self)
            # limit drop down size
            selection_widget.setMaxVisibleItems(20)
            selection_widget.setStyleSheet("QComboBox { combobox-popup: 0; }")
            self._input_type_registry.append([])
            self.selection_widget = selection_widget
            selection_widget.currentIndexChanged.connect(self._input_changed)

            # Add items based on the input type
            max_col = 32

            with QtCore.QSignalBlocker(selection_widget):
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
        self._execute_selected_callback()



    def _execute_callback(self):
        data = self.get_selection()
        if data and self._callback:
            self._callback(data)

    def _execute_selected_callback(self):
        data = self.get_selection()
        if data:
            if self._selected_callback:
                self._selected_callback(data)
            self.input_changed.emit()

    def sync(self):
        ''' forces the change cb to be called to update dependents based on values '''
        self._execute_callback()




class JoystickSelector(AbstractInputSelector):

    """Widget allowing the selection of input items on a physical joystick."""


    def __init__(self, callback = None,
                 valid_types = [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
                 parent=None):
        """Creates a new JoystickSelector instance.

        :param change_cb function to call when changes occur
        :param valid_types valid input types for selection
        :param parent the parent of this widget
        """
        super().__init__(selected_callback = callback,
                         valid_types = valid_types,
                         parent = parent)


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
        super().__init__(selected_callback = change_cb,
                         valid_types = valid_types,
                         parent = parent)

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
        :param input_item: the mapped input type
        :param parent the parent of this widget
        """
        super().__init__(parent)
        import gremlin.base_profile
        

        # if not input_type in (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat):
        #     pass

        assert isinstance(input_item, gremlin.base_profile.InputItem), "expected an input item, wrong type passed"
        self._input_item = input_item
        self._input_item.lockedChanged.connect(self._handle_lock_changed)
        self._input_type = input_type if input_type else self._input_item.getInputType()

        self.action_dropdown = QDataComboBox()
        self.action_dropdown.currentIndexChanged.connect(self._action_changed)
        self.refresh()
        
        self.add_button = Buttons.getAddWidget(callback = self._add_action, tooltip = "Adds the selected action")
       
        

        # self.help_widget = Buttons.getHelpWidget(callback = self._handle_help)

        # clipboard
        self.paste_button = Buttons.getPasteWidget(callback=self._paste_action)
        self.paste_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Minimum)
        self.paste_button.setToolTip("Paste Action")

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.action_label = QtWidgets.QLabel("Actions")

        widget, _ = getHContainer([self.action_label, 
                                   self.action_dropdown,
                                   self.add_button,
                                  # self.help_widget,
                                   self.paste_button,
                                   ])

        self.main_layout.addWidget(widget)
        eh = gremlin.event_handler.EventHandler()
        eh.last_action_changed.connect(self._last_action_changed)
        self._container = None


        self._handle_lock_changed_ui(self._input_item) # initial lock state

    def _handle_lock_changed(self, input_item):
        gremlin.util.InvokeUiMethod(self._handle_lock_changed_ui, input_item) # ensure on UI thread

    def _handle_lock_changed_ui(self, input_item):
        if Shiboken.isValid(self):
            unlocked = not input_item.locked
            self.add_button.setEnabled(unlocked)
            self.paste_button.setEnabled(unlocked)
        
    def refresh(self):
        ''' reloads the selector based on the input '''
        with QtCore.QSignalBlocker(self.action_dropdown):
            self.action_dropdown.clear()
            action_list = self._valid_action_list(self._input_type)
            for name in action_list:
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
            # if entry.tag == "gremlin-control":
            #     pass
            if not entry.input_types or input_type in entry.input_types:
                if convert_vjoy and entry.name == "Remap":
                    continue
                elif convert_curve and entry.name == "Response Curve":
                    continue
                # if entry.name == "Control" and not control_enabled:
                #     continue
                action_list.append(entry.name)
        return sorted(action_list)


    def _handle_help(self):
        ''' handles the help box on an action '''
        action_name = self.action_dropdown.currentText()
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action = plugin_manager.get_class(action_name)(self._input_item)
        if hasattr(action,"hint"):
            hint = action.hint
        else:
            hint = gremlin.hints.hint.get(action.tag, "")  
        if hint:
            MessageBox(title = f"About the {action_name} action:", prompt = hint, width = 300, is_warning=False)




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
        

        valid_actions = self._valid_action_list(self._input_type)
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


def get_mode_list(profile):
    ''' gets a pairs (display_name, mode) '''
    
    profile = gremlin.shared_state.current_profile
    return profile.get_mode_display_list()

    
class ModeSelectorWidget(QtWidgets.QWidget):
    ''' displays a mode selector drop down for the current profile modes '''
    modeChanged = QtCore.Signal(str) # occurs whena mode is selected
    
    def __init__(self, 
                 parent=None):
        super().__init__(parent)


        self._selector_widget = QDataComboBox()
        self._selector_widget.currentIndexChanged.connect(self._handle_mode_changed)

        widgets = [self._selector_widget]
        widget, layout = getHContainer(widgets,"Mode:")

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(widget)

        self._refresh_modes()

    def _handle_mode_changed(self):
        mode = self._selector_widget.currentData()
        self.modeChanged.emit(mode)

    def setMode(self, mode : str) -> bool:
        ''' selects a mode, mode must exist, true if selected '''
        index = self._selector_widget.findData(mode)
        if index != -1:
            self._selector_widget.setCurrentIndex(index)
            return True
        return False

    def mode(self) -> str:
        ''' gets the selected mode'''
        return self._selector_widget.currentData()
    
    def refresh(self, mode_to_select : str = None):
        ''' refresh '''
        gremlin.util.InvokeUiMethod(self._refresh_modes(mode_to_select))
        

    def _refresh_modes(self, mode_to_select : str = None):
       
        profile = gremlin.shared_state.current_profile

        with QtCore.QSignalBlocker(self._selector_widget):
            #modes = gremlin.shared_state.current_profile.get_modes()
            while self._selector_widget.count() > 0:
                    self._selector_widget.removeItem(0)

            mode_list_pairs = get_mode_list(profile)
            self.mode_list = [x[1] for x in mode_list_pairs]
            
            # Add properly arranged mode names to the drop down list
            index = 0
            select_index = None

            master_mode = gremlin.shared_state.master_mode
            for display_name, mode_name in mode_list_pairs:
                if mode_name == master_mode:
                    continue
                self._selector_widget.addItem(display_name, mode_name)
                # self.mode_list.append(mode_name)
                if mode_to_select and select_index is None and mode_to_select == mode_name:
                    select_index = index
                index += 1

            if select_index is None:
                # select the default mode
                default_mode = gremlin.shared_state.current_profile.get_default_mode()
                index = self._selector_widget.findData(default_mode)
                if index != -1:
                    self._selector_widget.setCurrentIndex(index)



class ModeWidget(QtWidgets.QWidget):

    """Displays the ui for mode selection and management of a device."""

    # Signal emitted when the mode changes
    edit_mode_changed = QtCore.Signal(str) # when the edit mode changes


    def __init__(self, 
                 label = "Profile Edit Mode",
                 tooltip = "Selects the active profile mode being edited",
                 parent=None):
        """Creates a new instance.

        :param parent the parent widget
        """
        
        QtWidgets.QWidget.__init__(self, parent)

        self.mode_list = []

        self.profile = None
        self._label = label
        self._tooltip = tooltip
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self._create_widget()

        el = gremlin.event_handler.EventListener()
        el.mode_list_update.connect(self._mode_list_update)
        el.profile_modes_changed.connect(self._mode_list_update)
        


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


    def _mode_list_update(self):
        gremlin.util.InvokeUiMethod(self._mode_list_update_ui) # ensure on UI thread
    
    def _mode_list_update_ui(self):
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
            hide_default_mode = gremlin.config.Configuration().hide_default_mode

            modes = gremlin.shared_state.current_profile.get_modes()
            while self.edit_mode_selector.count() > 0:
                    self.edit_mode_selector.removeItem(0)

            mode_list_pairs = get_mode_list(profile)
            self.mode_list = [x[1] for x in mode_list_pairs]
            
            # Add properly arranged mode names to the drop down list
            index = 0
            current_index = 0
            select_index = None
            last_edit_mode = gremlin.config.Configuration().get_profile_last_edit_mode()

            if not last_edit_mode in modes:
                last_edit_mode = profile.get_default_mode()
                #hide_default_mode = False # show default mode

            default_mode = profile.get_default_mode() # profile.get_root_modes()

            master_mode = gremlin.shared_state.master_mode
            for display_name, mode_name in mode_list_pairs:
                if mode_name == master_mode:
                    continue
                if mode_name == "Default" and hide_default_mode:
                    continue
                self.edit_mode_selector.addItem(display_name, mode_name)
                # self.mode_list.append(mode_name)
                if mode_to_select and select_index is None and mode_to_select == mode_name:
                    select_index = index
                if mode_name == last_edit_mode:
                    current_index = index
                index += 1

            if default_mode:
                select_index = self.edit_mode_selector.findData(default_mode)

            if select_index != -1:
                self.edit_mode_selector.setCurrentIndex(select_index)    
                current_index = select_index
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
        new_mode = self.edit_mode_selector.currentData()
        #new_mode = self.mode_list[idx]
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
        self.profile_options_button_widget.setIcon(Icons.gearIcon())
        self.profile_options_button_widget.setToolTip("Profile Options")
        self.profile_options_button_widget.clicked.connect(self._profile_options_cb)



        # Create mode selector and related widgets
        self.edit_label = QtWidgets.QLabel(self._label)
        self.edit_label.setSizePolicy(min_min_sp)
        self.edit_mode_selector = QDataComboBox()
        self.edit_mode_selector.setSizePolicy(exp_min_sp)
        self.edit_mode_selector.setMinimumContentsLength(20)
        self.edit_mode_selector.setToolTip(self._tooltip)


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
            MessageBox(prompt = "Please save the profile before setting options.")
            return

        dialog = gremlin.ui.dialogs.ProfileOptionsUi()
        dialog.exec()

    def currentIndex(self) -> int:
        ''' current selector index '''
        return self.edit_mode_selector.currentIndex()

    def currentMode(self):
        ''' gets the current mode object '''
        return self.edit_mode_selector.currentData()
    
    def currentModeName(self) -> str:
        ''' gets the current mode name '''
        return self.edit_mode_selector.currentText()


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
    keyInput = QtCore.Signal(list) # called when a keyboard input is made - the parameter will be a key if mouse/keyboard input
    closed = QtCore.Signal(bool) # closed - passes the accepted flag

    def __init__(
            self,
            event_types = [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
            return_kb_event=False,
            multi_keys=False,
            filter_func=None,
            callback = None, 
            virtual_only = False,
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
        self._virtual_only = virtual_only # only listen to virtual devices if set
        self.selection = None # holds whatever was selecteed
        self._mouse_x = None # mouse x coord for mouse move
        self._mouse_y = None # mouse y coord for mouse move
        
        self._listen_mouse = InputType.Keyboard in event_types or InputType.KeyboardLatched in event_types or InputType.Mouse in event_types

        self._close_on_key = not (InputType.Keyboard in event_types or InputType.KeyboardLatched in event_types)
        self._esc_key = key_from_name("esc")

        # Create and configure the ui overlay
        self.main_layout = QtWidgets.QVBoxLayout(self)


        if self._multi_keys:
            self.main_layout.addWidget(QtWidgets.QLabel("<center>Multi-Key/Mouse Listen Mode</center>"))
            self.repeater_container_widget, self.repeater_container_layout = getHContainer()
            self.repeater_container_widget.setMinimumHeight(32)
            self.repeater_container_layout.addWidget(QtWidgets.QLabel("<i>waiting for input...</i>",alignment= QtCore.Qt.AlignmentFlag.AlignHCenter))
            self.main_layout.addWidget(self.repeater_container_widget)

        
        label = QtWidgets.QLabel()
        self.main_layout.addWidget(label)

        if self._multi_keys:
            
            self.cancel_widget = Buttons.getCancelWidget(callback = self._cancel)
            self.ok_widget = Buttons.getOkWidget(callback = self._accept)
            widget = getHContainer([self.ok_widget, self.cancel_widget], widget_only = True)
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
        el = gremlin.event_handler.EventListener()
        el.keyboard_event.connect(self._kb_event_cb)
        #if InputType.JoystickAxis in self._event_types or InputType.JoystickButton in self._event_types or InputType.JoystickHat in self._event_types:
        el.joystick_event_ui.connect(self._joy_event_cb)
        
        if self._listen_mouse:
            # hook the mouse
            mh = gremlin.windows_event_hook.MouseHook()
            mh.registerMouseMove(self._mouse_move_cb)
            mh.register(self._mouse_event_cb) # trap clicks



    def unhook(self):
        ''' called on widget destruction '''
        
        el = gremlin.event_handler.EventListener()
        el.keyboard_event.disconnect(self._kb_event_cb)
        el.joystick_event_ui.disconnect(self._joy_event_cb)

        if self._listen_mouse:
            # unhook mouse callbacks
            mh = gremlin.windows_event_hook.MouseHook()
            mh.unregisterMouseMove(self._mouse_move_cb)
            mh.unregister(self._mouse_event_cb)
            
            

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
        if event.is_axis:
            process_event = True # gremlin.input_devices.JoystickInputSignificant().should_process(event)
        elif event.event_type == InputType.JoystickButton:
            process_event = event.is_pressed
        elif event.event_type == InputType.JoystickHat:
            process_event = event.value != (0,0)

        if process_event:
            gremlin.input_devices.JoystickInputSignificant().reset()
            gremlin.util.InvokeUiMethod(self._selected_ui, event)
        

    def _selected_ui(self, event):
        ''' input selected - runs on UI thread'''
        if self._virtual_only:
            dev = gremlin.joystick_handling.device_info_from_guid(event.device_guid)
            if not dev.is_virtual:
                return
        
        if self._callback:
            self._callback(event)
        self.item_selected.emit(event)
        self.selection = event
        self.unhook()
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

                self.selection = [key]
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
                    self.keyInput.emit(self._multi_key_storage) # notify a key was pressed
                    self._echo_key(key)
                    self.selection = self._multi_key_storage
                   

    def _mouse_event_ui(self, event):
        ''' process mouse events on UI thread '''
        verbose = gremlin.config.Configuration().verbose_mode_mouse_input
        if verbose: syslog.info(f"mouse event ui: {event}")
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
                self.keyInput.emit(self._multi_key_storage) # notify a key was pressed
                self.selection = self._multi_key_storage
                self._echo_key(key)
            else:
                # not listening to multiple keys
                self.keyInput.emit([key]) # notify a key was pressed
                self.item_selected.emit([key])
                self.selection = [key]
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

    def _mouse_move_cb(self, x, y):
        self._mouse_x = x
        self._mouse_y = y

    def getMousePosition(self):
        ''' gets the recorded mouse position '''
        return (self._mouse_x, self._mouse_y)
  

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

        self.unhook()
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
    def __init__(self, parent = None, width = None, maxItems = 20,):
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
            # AUTOSIZE
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
            self.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)

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
        pixmap = Icons.to_pixmap(Icons.warningIcon())
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

def ConfirmBox(prompt = "Are you sure", informative_text = None, parent = None) -> bool:

    result = False
    def set_result(value):
        nonlocal result
        result = value == QtWidgets.QMessageBox.StandardButton.Yes


    MessageBoxYesNo(prompt = prompt, informative_text = informative_text, callback = set_result)
    return result


def MessageBoxWarning(title = "Warning", prompt = "Operation", informative_text = None,  parent = None, width = 200):
    gremlin.util.InvokeUiMethod(_message_box_ui, title, prompt, informative_text, "warning", None, parent)

def MessageBoxInfo(title = "Notice", prompt = "Operation", informative_text = None, parent = None, width = 200):
    gremlin.util.InvokeUiMethod(_message_box_ui, title, prompt,  informative_text,"info", None, parent)

def MessageBoxYesNo(title = "Notice", prompt = "Operation", informative_text = None, callback = None,  parent = None, width = 200):
    gremlin.util.InvokeUiMethod(_message_box_ui, title, prompt,  informative_text,"yesno", callback, parent)    

def MessageBoxOkCancel(title = "Notice", prompt = "Operation", informative_text = None, callback = None, parent = None, width = 200):
    gremlin.util.InvokeUiMethod(_message_box_ui, title, prompt, informative_text, "okcancel", callback, parent)    

def MessageBox(title = "Notice", prompt = "Operation", informative_text = None, is_warning = True, callback = None, parent = None, width = 200):
    mode = "warning" if is_warning else "info"
    gremlin.util.InvokeUiMethod(_message_box_ui, title, prompt, informative_text, mode, callback, parent)


def _message_box_ui(title = "Notice", prompt = "Operation", informative_text = None, mode : str = "info", callback = None, parent = None):
    buttons = QtWidgets.QMessageBox.StandardButton.Ok
    if parent is None:
        parent = gremlin.shared_state.ui
    match mode:
        case "warning":
            # warning icon
            icon = Icons.warningIcon()
        case "question" | "yesno":
            icon = Icons.questionIcon()
            buttons = QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        case "okcancel":
            icon = Icons.questionIcon()
            buttons = QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel
        case _:
            icon = Icons.infoIcon()

        
    pixmap = icon.pixmap(48)
    msgbox = QtWidgets.QMessageBox(parent=parent)
    msgbox.setWindowTitle(title)
    msgbox.setIconPixmap(pixmap)
    msgbox.setText(prompt)
    if informative_text:
        msgbox.setInformativeText(informative_text)
    msgbox.setStandardButtons(buttons)

    result = msgbox.exec()
    if callback:
        callback(result)



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

    def __init__(self, icon_path = None, text = None, stretch=True, use_qta = False, icon_color = None, use_wrap = False, icon_size = 16, data = None, tooltip = None, parent = None):
        super().__init__(parent)

        self.data = data

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

        if tooltip:
            self.setToolTip(tooltip)



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
    def __init__(self, label : str = None, data = None, callback = None, callbackEx = None, value : bool = None, tooltip = None, parent = None):
        '''
        :param text: the label (optional, recommended)
        :param data: the data tracked by this control (optional)
        :param callback: the callback to call (checked)
        :param callbackEx: the extended callback to call (widget, checked)
        :param value: default value (optional)
        :param tooltip: tooltip to display (optional)
        :param parent: parent widget (optional)
        '''

        super().__init__(label, parent)
        self._data = data
        self._ignore_keyboard = False
        self.installEventFilter(self)
        self._callback = callback
        self._callbackEx = callbackEx
        if value is not None:
            self.setChecked(value)
        self.stateChanged.connect(self._handle_clicked)
        if tooltip:
            self.setToolTip(tooltip)


    def _handle_clicked(self):
        checked = self.isChecked()
        if self._callback:
            self._callback(checked)
        if self._callbackEx:
            self._callbackEx(self, checked)
        

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
    def __init__(self, label : str = None, data = None, callback = None, callbackEx = None, value : bool = None, tooltip = None, parent = None):
        ''' data enabled checkbox 
        :param text: the label (optional, recommended)
        :param data: the data tracked by this control (optional)
        :param value: default value (optional)
        :param callback: the callback to execute when the radio button state is changed, passes the checked (bool) value [bool] if provided
        :param callbackEx: the callback to execute when the radio button state is changed, passes the widget itself, and checked (bool) value  [widget, checked] if provided
        :param tooltip: tooltip to display (optional)
        :param parent: parent widget (optional)
        
        '''
        super().__init__(label, parent)
        self._data = data

        if value:
            self.setChecked(value)
        self._callback = callback
        self._callback_ex = callbackEx
        self.clicked.connect(self._handle_callback)
        if tooltip:
            self.setToolTip(tooltip)

    def _handle_callback(self):
        if self._callback:
            self._callback(self.isChecked())
        if self._callback_ex:
            self._callback_ex(self, self.isChecked())


    def unhook(self):
        self.clicked.disconnect(self._handle_callback)



    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

class QDataPushButton(QtWidgets.QPushButton):
    ''' custom push button with data field and right click context events '''

    _clicked = QtCore.Signal(object) # click internal (widget)
    clickedEx = QtCore.Signal(object, bool, bool, bool, bool) # fires on control click (widget, ctrl, shft, right)


    ''' a checkbox that has a data property to track an object associated with the checkbox '''
    def __init__(self, text = None, data = None, parent = None, tooltip = None, callback = None, callbackEx = None, clicked = None, enabled = None):
        ''' custom push button 
        
        :param text: label for the button (optiona)
        :param data: data object tracked with the button (optional)
        :param parent: parent widget (optional)
        :param tooltip: tooltip (optional)
        :param callback: click callback(widget) (optional) 
        :param callback_ex: click callback (ctrl, shft, right) as boolean flags as parameters to the event (optional)
        :param clicked: click callback() 
        :param enabled: default enabled state (optional) - button is enabled by default

        
        '''
        # if callback_ex:
        #     import inspect
        #     sig = inspect.signature(callback_ex)
        #     if len(sig.parameters) != 5:
        #         pass
        super().__init__(text, parent)
        self._data = data
        if tooltip:
            self.setToolTip(tooltip)
    
        self._clicked.connect(self._handle_callback)
        self.clickedEx.connect(self._handle_callback_ex)

        self._callback = callback
        self._callback_ex = callbackEx
        if enabled is not None:
            self.setEnabled(enabled)
        if clicked:
            self.clicked.connect(clicked)

        self.installEventFilter(self)

    

    def _handle_callback(self):
        if self._callback:
            self._callback(self)

    def _handle_callback_ex(self, widget, is_ctrl : bool, is_shft : bool, is_alt : bool, is_right : bool):
        if self._callback_ex:
            self._callback_ex(widget, is_ctrl, is_shft, is_alt, is_right)

    def setCallback(self, callback):
        self._callback = callback

    def setCallbackEx(self, callback):
        self._callback_ex = callback



    def eventFilter(self, watched, event):
        if self.isEnabled():
            t = event.type()
            if t == QtCore.QEvent.Type.MouseButtonPress:
                button = event.buttons()
                # Check if Control modifier is active
                is_ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                is_shft = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                is_alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
                if button == QtCore.Qt.RightButton:
                    self.clickedEx.emit(self, is_ctrl, is_shft, is_alt, True) # extended click
                    return True # handled
                elif button == QtCore.Qt.LeftButton:
                    if self.isCheckable():
                        self.setChecked(not self.isChecked())

                    self.clickedEx.emit(self, is_ctrl, is_shft, is_alt, False) # extended click
                    self._clicked.emit(self )
                    self.clicked.emit()
                    return True
                    
                    
            elif t == QtCore.QEvent.Type.MouseButtonRelease:
                return True
            elif t == QtCore.QEvent.Type.MouseButtonDblClick:
                return True
                
        return super().eventFilter(watched, event)

    def unhook(self):
        self._callback = None
        self._callback_ex = None
        self._clicked.disconnect(self._handle_callback)
        self.clickedEx.disconnect(self._handle_callback_ex)

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

class NoKeyboardPushButton(QDataPushButton):

    """Standard PushButton which does not react to keyboard input."""

    def __init__(self, *args, **kwargs):
        """Creates a new instance."""
        super().__init__(*args, **kwargs)
        

    def keyPressEvent(self, event):
        """Handles key press events by ignoring them.

        :param event the key event to handle
        """
        pass


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

        self.up_widget = QIconButton(data = "up", icon = "ph.caret-circle-up-light", tooltip="Move up")
        self.up_widget.clicked.connect(self._move)
        
        self.down_widget = QIconButton(data = "down", icon = "ph.caret-circle-down-light", tooltip = "Move down")
        self.down_widget.clicked.connect(self._move)

        self.top_widget = QIconButton(data = "top", icon = "ph.caret-circle-double-up-light", tooltip = "Move top")
        self.top_widget.clicked.connect(self._move)

        self.bottom_widget = QIconButton(data = "bottom", icon = "ph.caret-circle-double-down-light",  tooltip = "Move bottom")
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
    valueChanged = QtCore.Signal() # fires when the text has changed AND we lost the focus if that option is selected
    lostFocus = QtCore.Signal() # fires when the input looses focus
    enterPressed = QtCore.Signal() # indicates the enter key was pressed
    escPressed = QtCore.Signal() # indicates the esc key was pressed

    def __init__(self, text = None, data = None, parent = None, width = 200, callbackEx = None):
        super().__init__(parent = parent)
        self.setText(text)
        self._data = data
        self._text_changed = True
        self.setAlignment(Qt.AlignLeft)
        #self.setStyleSheet("QLineEdit{border: #8FBC8F;}")
        super().textChanged.connect(self._text_changed_cb)
        self.setMinimumWidth(width)
        self._trigger_on_focus_loss = True

        
        self.callback_ex = callbackEx

        self.installEventFilter(self)

    def eventFilter(self, watched, event):
        t = event.type()
        if t == QtCore.QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
                self.enterPressed.emit()
                return True # eat it
            if event.key() == Qt.Key.Key_Escape:
                self.escPressed.emit()
                return True # eat it
             
        return super().eventFilter(watched, event)

    def setTriggerOnFocusOnly(self, value : bool):
        self._trigger_on_focus_loss = value

    def triggerOnFocusOnly(self) -> bool:
        ''' true if the widget triggers value changed only on focus loss '''
        return self._trigger_on_focus_loss


    def _text_changed_cb(self):
        self._text_changed = True
        if not self._trigger_on_focus_loss:
            # trigger on any text change
            self.valueChanged.emit()
        if self.callback_ex:
            self.callback_ex(self, self.text())


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
    def __init__(self, data = None, callback = None, parent = None, wheel_enabled : bool = None, auto_adjust : bool = False, source = None, value = None, tooltip : str = None, max_items = 20):
        ''' creates a combo box 
        
        :param data: data object the widget carries
        :callback: callback handler when the index changes (optional) - callback(data) - returns the data for the selected row
        :wheel_enabled: true if mouse wheel is enabled on the combo box 
        :auto_adjust: true if the combo box autosizes to contents
        :source: optional, list of tuples (display, data) to populate the combo box with
        :value: optional, if source is provided, the default display value to select
        
        '''
        super().__init__(parent)
        self._data = data
        self._wheel_enabled = gremlin.config.Configuration().dropdown_use_mouse_wheel if wheel_enabled is None else wheel_enabled
        self.installEventFilter(self)
        if auto_adjust:
            self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        # self.setStyleSheet("QComboBox { padding: 5px; margin: 10px; }") 
        self.setStyleSheet("QComboBox { padding: 5px; }") 
        self._callback = callback

        self.setMaxVisibleItems(max_items)
        self.setStyleSheet("QComboBox { combobox-popup: 0; }")


        if source:
            # source is expected to be a list of tuples of display/data
            for display, item in source:
                self.addItem(display, item)

            if value is not None:
                index = self.findData(value)
                if index != -1:
                    self.setCurrentIndex(index)

        self.currentIndexChanged.connect(self._handle_callback)

        if tooltip:
            self.setToolTip(tooltip)

    def setSource(self, source, value = None):
        ''' sets the source of the combo box as a list of (name, data)'''
        self.clear()
        if source:
            for display, item in source:
                self.addItem(display, item)
        if value:
            index = self.findData(value)
            if index != -1:
                self.setCurrentIndex(index)


    def _handle_callback(self):
        if self._callback:
            with QtCore.QSignalBlocker(self):
                self._callback(self.currentData())

    def setCallback(self, callback):
        self._callback = callback

    
    def eventFilter(self, widget, event):
        
        if not self._wheel_enabled:
            t = event.type()
            if t == QtCore.QEvent.Type.Wheel:
                # check for shift state
                if not gremlin.event_handler.EventListener().get_shifted_state():
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

    def setWidthToContent(self):
        ''' updates the width of the combo box to its contents '''
        count = 0
        for i in range(self.count()):
            item_text = self.itemText(i)
            count = max(count, len(item_text))

        width = get_char_width(count + 4)
        self.setMaximumWidth(width)
    

class QLimitedComboBox(QDataComboBox):
    ''' a row limited combo box '''
    def __init__(self, data = None, parent = None):
        super().__init__(data, parent)
        self.setMaxVisibleItems(20)
        self.setStyleSheet("QComboBox { combobox-popup: 0; }")

class QHatSelectorComboBox(QDataComboBox):
    ''' a combo box for hat directions '''

    valueChanged = QtCore.Signal(HatDirection) # fires when a value is selected 

    def __init__(self, value : HatDirection = HatDirection.Center, callback = None, tooltip = None, data = None, parent = None):
        import vjoy.vjoy
        super().__init__(data, callback = callback, parent = parent)

        self._direction = HatDirection.Center
        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
        
        
        for position in HatDirection:
            icon = load_icon(vjoy.vjoy.Hat.direction_to_icon[position.value])
            # match position:
            #     case HatDirection.Center:
            #         png = f"{prefix}hat_ctr.png"
            #     case HatDirection.North:
            #         png = f"{prefix}hat_n.png"
            #     case HatDirection.NorthEast:
            #         png = f"{prefix}hat_ne.png"
            #     case HatDirection.NorthWest:
            #         png = f"{prefix}hat_nw.png"
            #     case HatDirection.East:
            #         png = f"{prefix}hat_e.png"
            #     case HatDirection.South:
            #         png = f"{prefix}hat_s.png"
            #     case HatDirection.SouthEast:
            #         png = f"{prefix}hat_se.png"
            #     case HatDirection.SouthWest:
            #         png = f"{prefix}hat_sw.png"      
            #     case HatDirection.West:
            #         png = f"{prefix}hat_w.png"  
            # icon = load_icon(png)   
            #icon_active = load_icon(png_active)        
            
            self.addItem(icon, HatDirection.to_display_name(position), HatDirection.to_enum(position))
            

        if value:
            index = self.findData(value)
            if index != -1:
                self.setCurrentIndex(index)


        if tooltip:
            self.setToolTip(tooltip)

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

    def __init__(self, header = None, text = None, data = None, dir_mode = False, parent = None, open_tooltip_text = "Browse", callback = None, callback_open = None, button_label = "..."):
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
        self._open_button = None
        if button_label:
            self._open_button = QtWidgets.QPushButton(button_label)
            if button_label == "...":
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
        if self._open_button:
            self._layout.addWidget(self._open_button)
        self._layout.setContentsMargins(0,0,0,0)

        self._data = data
        self._callback = callback
        self._callback_open = callback_open
        self.pathChanged.connect(self._handle_path_changed)
        self.open.connect(self._handle_open)
        

        self._file_changed()
        
        
        self.setLayout(self._layout)

    @property
    def header_width(self):
        return self._header_widget.frameGeometry().width()
    
    @header_width.setter
    def header_width(self, value):
        self._header_widget.setMaximumWidth(value)
        self._header_widget.setMinimumWidth(value)

    def _handle_path_changed(self, value : str):
        if self._callback:
            self._callback(self, self.text())

    def _handle_open(self):
        if self._callback_open:
            self._callback_open(self)

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
    ''' visualizes a vertical or horizontal progress bar
     
    supports multiple values if the value is an iterating type like tuple or list.
    colors are also multiple values and will round robin if the number of colors is less than the number of values.

    values can be assigned as single float, or a list of values, displayed in sequence on the progress bar.
    if the value is None, the progress bar adds a blank bar.  The number of bars always matches however may values are entered

    Colors are assigned in roundrobin fashion for the next bar if the number of colors given is less than the numbers of bars to display
      
    '''

    valueChanged = QtCore.Signal() # fires when the value changes (and widget is not in readonly mode)
    sizeChanged = QtCore.Signal() # fires when the number of rows in the progress bar changes

    def __init__(self, orientation : Qt.Orientation = Qt.Orientation.Vertical, value : float = 0, min : float = -1.0, max : float = 1.0, readonly : bool = True, step : float = 0.1, data = None, parent = None):
        super().__init__()
        self.parent = parent
        self.config = gremlin.config.Configuration()
        if orientation == Qt.Orientation.Vertical:
            self._desired_width = 10
            self._desired_height = 100
        else:
            self._desired_width = 100
            self._desired_height = 10

        self._valid = True # true until the widget is no longer valid from Shibokent due to QT GC
        self._value = None
        self._orientation = orientation
        self._step = step
        self._readOnly = readonly
        self._data = data
        self._percent = {} # percent valuess of the progress bar by value index
        self._colors = {} # color gradient assigned to a specific channel
        self._row_count = 1 # display rows by default

        self._start_color = {} # color for each value band (start gradient)
        self._end_color = {} # color for each value band (end gradient)
        

        # self.setMinimumSize(self.sizeHint())
        # self.setMaximumSize(self.sizeHint())

        self._background_color = Color.actionBackgroundColor()
        self._border_color = Color.selectBorderColor()

        index = 0
        pairs = Color.ChannelColors()
        for (c1,c2) in pairs:
            # channel gradients
            self._start_color[index] = c1
            self._end_color[index] = c2
            index += 1
        
        self._sub_color_start = c1
        self._sub_color_end = c2

        
        self.setRange(min, max)
        self.installEventFilter(self)

        if value is not None:
            self._set_value_ui(value)

    @property
    def valid(self) -> bool:
        return self._valid

    def _update_tooltip(self, value):
        ''' updates the tooltip for the repeater '''
        
        stub = None
        if isinstance(value, gremlin.event_handler.AxisValues):
            # calibration data
            stub = f"Value: {value.actual:0.3f} [{self._to_percent(value.actual):0.2f}%]"
            if value.raw is not None and value.actual != value.raw:
                stub += f"\nRaw: {value.raw:0.3f} [{self._to_percent(value.raw):0.2f}%]"
            if value.calibrated is not None:
                stub += f"\nCalibrated: {value.calibrated:0.3f} [{self._to_percent(value.calibrated):0.2f}%]"
            if value.curved is not None:
                stub += f"\nCurved: {value.curved:0.3f} [{self._to_percent(value.curved):0.2f}%]"
        else:
            if value is not None:
                if isinstance(value, list):
                    stub = f"Value: {value[0]:0.3f} [{self._to_percent(value[0]):0.2f}%]"
                else:
                    stub = f"Value: {value:0.3f} [{self._to_percent(value):0.2f}%]"
        
        self.setToolTip(stub)

    def _to_percent(self, value):
        return gremlin.util.scale_to_range(value, target_min = 0, target_max = 100)



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
        
        if self._readOnly:
            # ignore
            return super().eventFilter(widget, event)

        t = event.type()
        if t == QtCore.QEvent.Type.Wheel:
            # handle wheel up/down change
            # syslog.info("PB: wheel!")
            if self._readOnly:
                return True # cannot change the value if readonly
            v = self._value
            if v is not None:
                # keyboard shifted state
                eh = gremlin.event_handler.EventListener()
                is_shifted = eh.get_shifted_state()
                is_control = eh.get_control_state()
                if is_control and is_shifted:
                    # double slow
                    factor = 0.01
                elif is_control:
                    # fast
                    factor = 1.5
                elif is_shifted:
                    # slow
                    factor = 0.1
                else:
                    # normal
                    factor = 1.0
                
                if event.angleDelta().y() > 0:
                    # up
                    v += self._step * factor
                else:
                    # down
                    v -= self._step * factor
                
                v = gremlin.util.clamp(v, self._min_range, self._max_range)
                self.setValue(v)
                self.valueChanged.emit()
                return True # indicate handled
        elif t == QtCore.QEvent.Type.MouseButtonDblClick:
            # set to 0 on double click
            if self._value != 0:
                self.setValue(0.0)
                self.valueChanged.emit()
            return True # indicate handled
        return super().eventFilter(widget, event)

    @property
    def channels(self) -> int:
        ''' returns the number of channels based on the last data set '''
        if self._percent:
            return len(self._percent)
        return 1
    
    @property
    def channelHeight(self) -> int:
        ''' height in pixels of a single channel '''
        return self._desired_height if self._orientation == Qt.Orientation.Horizontal else self._desired_width

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
        if len(self._start_color) > 1:
            return [c for c in self._start_color.values()]
        return self._start_color[0]
        
    @gradientStartColor.setter
    def gradientStartColor(self, value):
        self._start_color.clear()
        if hasattr(value,"__iter__"):
            for index, color in enumerate(value):
                self._start_color[index] = QtGui.QColor(color)
        else:
            self._start_color[0] = QtGui.QColor(value)

        if Shiboken.isValid(self):
            self.update()

    @property
    def isMulti(self) -> bool:
        ''' true if the input has multiple values to display '''
        return hasattr(self._value,"__iter__") 

        
    @property
    def gradientEndColor(self):
        if len(self._end_color) > 1:
            return [c for c in self._end_color.values()]
        return self._end_color[0]
        
    @gradientEndColor.setter
    def gradientEndColor(self, value):
        self._gradient_end_color = value
        self._end_color.clear()
        if hasattr(value,"__iter__"):
            for index, color in enumerate(value):
                self._end_color[index] = QtGui.QColor(color)
        else:
            self._end_color[0] = QtGui.QColor(value)

        if Shiboken.isValid(self):
            self.update() # repaint


    @property
    def gradientSubStartColor(self):
        return self._sub_color_start
    
    @gradientSubStartColor.setter
    def gradientSubStartColor(self, value : str):
        self._sub_color_start = value
        if Shiboken.isValid(self):
            self.update()

    @property
    def gradientSubEndColor(self):
        return self._sub_color_start
    
    @gradientSubEndColor.setter
    def gradientSubEndColor(self, value : str):
        self._sub_color_end = value
        if Shiboken.isValid(self):
            self.update()
        


    def sizeHint(self) -> QtCore.QSize:
        ''' desired widget size '''
        count = self._row_count
        size = super().sizeHint()
        
        if count:
            if self._orientation == Qt.Orientation.Vertical:
                w = self._desired_width * count
                h = self._desired_height
            else:
                w = self._desired_width
                h = self._desired_height * count 
        size = QtCore.QSize(w, h)    
        return size


    def setRange(self, min : float, max : float):
        if min > max:
            min, max = max, min
        self._min_range = min
        self._max_range = max
        self._update_value()

    def setValue(self, value : float | list, emit = True):
        if value is not None:
            gremlin.util.InvokeUiMethod(self._set_value_ui, value, emit)

    def _set_value_ui(self, value, emit : bool = True):

        if not Shiboken.isValid(self):
            self._valid = False
            return
        
        # if self.config.showJoystickRepeaterTooltip:
        #     self._update_tooltip(value) # tooltip
        # else:
        #     self.setToolTip(None)
        
        if hasattr(value,"toList"):
            if not self.config.splitJoystickRepeater:
                # hide split data
                value = value.actual
                
            else:
                # show split data
                value = value.toList()
        if hasattr(value,"__iter__"):
            # count non null entries
            #syslog.info(f"ProgressBar: {value}")
            if value[0] is not None:
                count = sum(1 for item in value if item is not None)
                if count == 1:
                    self._value = value[0] # use the first value only
                else:
                    values = value
                    # remove the last values if NULL
                    while values and values[-1] is None:
                        values.pop()
                    self._value = values # use all values
            else:
                self._value = value # use the whole list
        else:
            self._value = value
        self._update_value_ui()

    def Value(self) -> float:
        return self._value
    
    def _update_value(self):
        gremlin.util.InvokeUiMethod(self._update_value_ui)
    
    def _update_value_ui(self):
        if not Shiboken.isValid(self):
            return

        if hasattr(self._value,"__iter__"):
            # count how many are not None
            values = self._value
        else:
            values = [self._value]
        self._percent.clear()
        self._colors.clear()
        start_index = 0
        end_index = 0
        index = 0
        for value in values:
            bump_start = True
            bump_end = True
            c1 = self._start_color[start_index]
            c2 = self._end_color[end_index] 
            if value is None:
                self._percent[index] = None
            else:
                if hasattr(value,"__iter__"):
                    # sublist of values, like merged data
                    subvalues = value
                    if self._sub_color_start:
                        c1 = self._sub_color_start
                        bump_start = False
                    if self._sub_color_end:
                        c2 = self._sub_color_end
                        bump_end = False
                else:
                    subvalues = [value]
                for value in subvalues:
                    self._percent[index] = gremlin.util.scale_to_range(value, 
                                    source_min= self._min_range, 
                                    source_max = self._max_range,
                                    target_min = 0.0,
                                    target_max = 1.0)
                    self._colors[index] = (c1,c2)
                    
                    # round robin the colors
                    if bump_start:
                        start_index += 1
                        if not start_index in self._start_color:
                            start_index = 0

                    if bump_end:
                        end_index += 1
                        if not end_index in self._end_color:
                            end_index = 0

                    # next channel
                    index += 1

        self.updateGeometry() # indicate desired size changed 
        
        
        count = len(self._percent)
        if count != self._row_count:
            self._row_count = count
            self.sizeChanged.emit()                    

        self.update() # repaint

    
    def paintEvent(self, event):

        # syslog.info("progress paint start")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        count = len(self._percent) # how many bars to display
        if count:
            # something to paint
            x = 0
            y = 0
            r = 0 # radius
            w = self._desired_width # width of one bar
            h = self._desired_height # height of one bar
            

            is_vertical = self._orientation == Qt.Orientation.Vertical
            
            mw = w * count if is_vertical else w
            mh = h if is_vertical else h * count
            

            backgroundBrush = QBrush(self._background_color)
            borderPen = QtGui.QPen(QtGui.QColor(self._border_color))
            borderPen.setWidth(1)

            # draw bar background
            painter.setPen(borderPen)
            painter.setBrush(backgroundBrush)


            painter.drawRoundedRect(x, y, mw, mh, r, r)

            index = 0
            for percent in self._percent.values():
                c1,c2 = self._colors[index]
                if is_vertical:
                    gradient = QLinearGradient(QPoint(x, y), QPoint(w,h))
                    
                    gradient.setColorAt(0, c1)
                    gradient.setColorAt(1, c2)
                    painter.setBrush(gradient)
                    if percent is None:
                        v = 0
                    else:
                        v = int(h * (1.0 - percent)) # start from the bottom
                    
                    painter.drawRoundedRect(x, y + v, w, h, r, r)
                    x += w # next band
                else:
                    # horizontal
                    gradient = QLinearGradient(QPoint(x, y), QPoint(w,h))
                    gradient.setColorAt(0, c1)
                    gradient.setColorAt(1, c2)
                    painter.setBrush(gradient)
                    if percent is None:
                        v = 0
                    else:
                        v = int(w * percent)
                    painter.drawRoundedRect(x, y, x + v, h, r, r)
                    y += h # next band
               
                index += 1

        painter.end()

        #syslog.info("progress paint end")

        #syslog.info(f"X: {x} y: {y} w: {w} h: {h} v:{v} value: {self._percent:0.3f}")

_hook_registry = {} # registers hook list [hook_id]

class QHookedProgressBar(QProgressBar, gremlin.event_handler.JoystickHook):
    ''' hooked progress bar to a hardware input '''

    unhooked = QtCore.Signal() # fires on unhook

    def __init__(self, orientation : Qt.Orientation = Qt.Orientation.Vertical,
                 value : float | list = 0,
                 min : float = -1.0,
                 max : float = 1.0,
                 readonly : bool = True,
                 step : float = 0.1,
                 data = None,
                 parent = None):
       
        super().__init__(orientation, value, min, max, readonly, step, data, parent)
        self._description = None
        self._hook_requested = False # true if the hook was requested via a call to hookevent
        self._persist = False
        self._value_change_callback = None

    def getDescription(self) -> str:
        return self._description
    
    def setValueChangeCallback(self, callback):
        self._value_change_callback = callback
    
    def event(self, event):
        if event.type() == QEvent.Show:
            if self._hook_requested:
                self._do_hook()
        elif event.type() == QEvent.Hide:
            self.unhook()
        return super().event(event)    

    def hookDevice(self, hook_id, device_guid, input_type, input_id, ui_only = True, persist = False, description = None, ui_thread = True):    
        ''' hooks the device '''    

        
        changed = False
        des = description or f"repeater (axis): [{gremlin.joystick_handling.getDeviceName(self.device_guid)}] input id: [{self.input_id}]{' +ui' if ui_only else ''}{' +uit' if ui_thread else ''}"
        if des != self._description:
            changed = True
            self._description = des
        if hook_id != self._hook_id:
            self._hook_id = hook_id
            changed = True
        if self._device_guid != device_guid:
            self._device_guid = device_guid
            changed = True
        if input_type != self._input_type:
            self._input_type = input_type   
            changed = True
        if input_id != self._input_id:
            changed = True
            self._input_id = input_id
        if ui_only != self._ui_only:
            self._ui_only = ui_only
            changed = True
        if ui_thread != self._ui_thread:
            self._ui_thread = ui_thread
            changed = True
        
        self._persist = persist
        self._hook_requested = True
        


        if self.isVisible():
            if not self._hooked:
                # first time hook
                self._do_hook()
            elif changed:
                # remove old hook
                self.unhook()

                # set new hook
                self._do_hook()


         
    def _do_hook(self):
        global _hook_registry
        if self._hook_requested and not self._hooked:
         
            verbose = gremlin.config.Configuration().verbose_mode_hooks
            
            if self._hook_id and self._device_guid and self._input_type and self._input_id:
                if self._hook_id in _hook_registry:
                    # already registered
                    return
                if verbose:
                    syslog.info(f"DEV: hook (axis): [{len(_hook_registry)}] [{self._hook_id}] {self._description}")
                super().hookDevice(
                        self._hook_id,
                        self.process_events,
                        device_guid = self._device_guid,
                        input_type = self._input_type,
                        input_id = self._input_id,
                        ui_only = self._ui_only,
                        persist = self._persist,
                        ui_thread=True # update on UI thread
                        )
                
                _hook_registry[self._hook_id] = True
                self._hooked = True
            
    def unhook(self):
        ''' called when object is removed '''
        global _hook_registry
        if self._hook_id in _hook_registry:
            super().unhookDevice()
            verbose = gremlin.config.Configuration().verbose_mode_hooks
            del _hook_registry[self._hook_id]
            if verbose: syslog.info(f"DEV: unhook (axis): [{len(_hook_registry)}] [{self._hook_id}] {self._description}")
            self._hooked = False
            

    def process_events(self, event, values = None):
        ''' joystick value changed '''
        
        if not self.valid:
            # self unregister on QT GC garbage collection
            verbose = gremlin.config.Configuration().verbose_mode_hooks
            if verbose: syslog.info(f"DEV: auto unhook (axis): [{self._hook_id}] {self._description}")
            self.unhook()
            return
        if __debug__ and self._ui_thread and gremlin.util.assert_ui_thread():
            # ensure on ui thread
            pass
        self._set_local_value_ui(values)
        #gremlin.util.InvokeUiMethod(self._set_local_value_ui, values)

    def _set_local_value_ui(self, values):
        ''' set value on UI thread '''    
        self._set_value_ui(values)
        if self._value_change_callback:
            self._value_change_callback(self._device_guid, self._input_type, self.input_id, values)



class ButtonStateWidget(QtWidgets.QWidget):
    ''' visualizes the state of a button '''

    deleted = QtCore.Signal() # triggers on delete
    unhooked = QtCore.Signal() # triggers when unhooked
    
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
        self._input_type = InputType.JoystickButton # default to a button
        self._button_widget = QtWidgets.QLabel()
        self._button_widget.setContentsMargins(0,0,0,0)
        height = self._icon_size.height()+2
        self._button_widget.setMinimumHeight(height)
        self._button_widget.setMaximumHeight(height)

        self._last_state_value = None # not set

        self._button_widget.setStyleSheet("")
        self._valid = True # assume ok

        self._hat_icons = {} # icon hats, keyed by position
        
        self.main_layout.addWidget(self._button_widget)

        self._handler_connected = False
        el = gremlin.event_handler.EventListener()
        el.tab_selected.connect(self._tab_selected)
        el.tab_unselected.connect(self._tab_unselected)

        self._hooked = False
        self._suspended = False
        self._hook_requested = False # true if the hook was requested via a call to hookevent
        self._hook_id = None
        

        config = gremlin.config.Configuration()
        config.changed.connect(self._config_changed)

    def event(self, event):
        if event.type() == QEvent.Show:
            if self._hook_requested:
                self._do_hook()
        elif event.type() == QEvent.Hide:
            self.unhook()
        return super().event(event)    


    def desiredHeight(self):
        return self.sizeHint().height()
        
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


    def hookDevice(self, hook_id : str, device_guid, input_type, input_id, description : str = None):
        self._description = description or f"repeater (button): [{gremlin.joystick_handling.getDeviceName(self.device_guid)}] input id: [{self.input_id}]"
        changed = False
        if self._hook_id != hook_id:
            self._hook_id = hook_id
            changed = True
        if self._device_guid != device_guid:
            self._device_guid = device_guid
            changed = True
        if self._input_type != input_type:
            self._input_type = input_type
            changed = True
        if self._input_id != input_id:
            self._input_id = input_id
            changed = True

        self._hook_requested = True
        if self.isVisible():
            if not self._hooked:
                self._do_hook()
            elif changed:
                # data changed 
                self.unhook()
                self._do_hook()


    def _do_hook(self):
        ''' hooks the input  '''
        if self._hook_requested and not self._hooked:
            global _hook_registry
            verbose = gremlin.config.Configuration().verbose_mode_hooks
            if self._hook_id and self._device_guid and self._input_type and self._input_id:
                _hook_registry[self._hook_id] = True
                if verbose:
                    syslog.info(f"DEV: hook (button): [{len(_hook_registry)}] [{self._hook_id}] {self._description}")                
                self._hooked = True
                self._last_state_value = None # reset state
                self.updateState()
                self._tab_selected(self._device_guid)
                el = gremlin.event_handler.EventListener()
                el.button_state_change.connect(self.process_event)


    def unhook(self):
        self.unhookDevice()

    def unhookDevice(self):
        if not self._hooked:
            return
        global _hook_registry
        verbose = gremlin.config.Configuration().verbose_mode_hooks
        if self._hook_id in _hook_registry:
            del _hook_registry[self._hook_id]
            if verbose:
                syslog.info(f"DEV: unhook (button): [{len(_hook_registry)}] [{self._hook_id}] {self._description}")

            self._hooked = False
            el = gremlin.event_handler.EventListener()
            el.button_state_change.disconnect(self.process_event)

    def process_event(self, event):
        ''' joystick event handler '''
        if not self._valid: 
            verbose = gremlin.config.Configuration().verbose_mode_hooks
            if verbose: syslog.info(f"DEV: (button) auto unhook: [{self._hook_id}] {self._description}")
            self.unhook()
            return
            
        if self._suspended:
            return
        if event.is_axis:
            # not a button
            return
        if not gremlin.util.compare_guid(event.device_guid, self._device_guid):
            return
        if event.event_type != self._input_type:
            return
        if event.identifier != self._input_id:
            return
        state = event.is_pressed

        # if self._last_state_value is None or self._last_state_value != state:
        #     # changed
        gremlin.util.InvokeUiMethod(self._update_value, state)

    
        
    def updateState(self):
        ''' updates the widget state with the cached state  '''
        if self._input_type == InputType.JoystickAxis:
            # not a button device
            return
        state = gremlin.joystick_handling.get_button(self._device_guid, self._input_id)
        if state is not None:
            self._update_value(state)
            

  
        
 

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
        if not Shiboken.isValid(self):
            self._value = False
            return
        if self._last_state_value is None or self._last_state_value != is_pressed:
            # syslog.info(f"update button state: {is_pressed}")
            gremlin.util.InvokeUiMethod(self._update_pixmap_ui, is_pressed)
            self._last_state_value = is_pressed
              

    def _update_pixmap_ui(self, state):
        # updates the visual, on UI thread
        if not Shiboken.isValid(self._button_widget):
            return
        if state:
            self._button_widget.setPixmap(Pixmaps().onIconPixmap)
        else:
            self._button_widget.setPixmap(Pixmaps().offIconPixmap)

    def _update_hat(self, position):
        ''' updates a hat position '''
        if not Shiboken.isValid(self._button_widget):
            return
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
            self._button_widget.setPixmap(Pixmaps().onIconPixmap)
        else:
            self._button_widget.setPixmap(Pixmaps().offIconPixmap)


    def setValue(self, is_pressed):
        ''' value '''
        self._update_value(is_pressed)

class QOnOffStatusfWidget(QtWidgets.QWidget):
    ''' on/off widget '''
    def __init__(self, state : bool = False, on_icon : str = None, off_icon : str = None, tooltip : str = None, parent=None):
        super().__init__(parent)
        self._button_widget = QtWidgets.QLabel()
        self._button_widget.setContentsMargins(0,0,0,0)
        self._button_widget.setFixedWidth(20)
        self.setFixedWidth(22)
        icon_size = QtCore.QSize(16,16)
        if on_icon:
            icon = load_icon(on_icon,use_qta=True,qta_color=Color.onColor())
            self._on_pixmap = icon.pixmap(icon_size)
        else:
            self._on_pixmap = Pixmaps().onIconPixmap

        if off_icon:
            icon = load_icon(off_icon,use_qta=True,qta_color=Color.offColor())
            self._off_pixmap = icon.pixmap(icon_size)
        else:
            self._off_pixmap = Pixmaps().offIconPixmap

        layout = QtWidgets.QHBoxLayout(self)
        layout.addWidget(self._button_widget)
        self._set_state_ui(state)

        if tooltip:
            self.setToolTip(tooltip)
        

    def setState(self, state : bool):
        gremlin.util.InvokeUiMethod(self._set_state_ui, state)

    def _set_state_ui(self, state : bool):
        if state:
            self._button_widget.setPixmap(self._on_pixmap)
        else:
            self._button_widget.setPixmap(self._off_pixmap) 



# class AxisStateWidget(QtWidgets.QWidget, gremlin.event_handler.JoystickHook):
#     ''' input axis visualizer '''

#     valueChanged = QtCore.Signal(float, float) # (input_value, curved_value)
#     deleted = QtCore.Signal(object) # indicates the item is being deleted

#     def __init__(self, 
#                 device_guid = None,
#                 input_type = None,
#                 axis_id = None,
#                 show_calibrated = False, show_percentage = False, show_value = False,
#                 show_label = False, show_curve = False, orientation = QtCore.Qt.Orientation.Horizontal,
#                 min_range : float = -1.0,
#                 max_range : float = 1.0, 
#                 comment = None, 
#                 decimals = 3, 
#                 callback = None, 
#                 parent=None,
#                 ui_only = True):
#         """Creates a new instance.

#         :param axis_id: id of the axis, used in the label
#         :param show_calibrated: show calibrated data 
#         :param show_percentage: show percent label
#         :param show_value : show value label 
#         :param show_curve : show curve value label
#         :param orientation: horizontal or vertical
#         :param min_range: min range (-1)
#         :param max_range: max range (+1)
#         :param comment: comment label
#         :param device : device to use
#         :param decimals: decimals to use for value data (3)
#         :param callback: update callback when the widget changes values (optional)
#         :param parent the parent of this widget

#         """
#         super().__init__(parent)

#         self._scale_factor = 1000
#         self.main_layout = QtWidgets.QVBoxLayout(self)
#         self.device = gremlin.joystick_handling.getDevice(device_guid)
#         self._device_guid = self.device.device_guid
#         self._input_id = axis_id
#         self._input_type = input_type
#         self.setObjectName("state_repeater")
#         self._is_state = True # indicate this is a state widget
#         self.show_raw = True # true if the raw value should be displayed
#         self._callback = callback

#         self.hookDevice(self.process_event, self._device_guid, self._input_type, self._input_id, ui_only)
        

#         self.container_widget = QtWidgets.QWidget()
#         if orientation == QtCore.Qt.Orientation.Vertical:
#             self.container_layout = QtWidgets.QVBoxLayout(self.container_widget)
            
#         else:
#             # horizontal
#             self.container_layout = QtWidgets.QHBoxLayout(self.container_widget)

#         self.container_layout.setSpacing(4)
            

#         # container for the progress bars (regular + calibrated)
#         self.progress_container_widget = None
#         self.progress_container_layout = None

#         self._orientation = orientation
#         self._show_percentage = show_percentage
#         self._show_value = show_value
#         self._show_label = show_label
#         self._show_curve = show_curve
#         self._show_calibrated = show_calibrated
#         self._decimals = decimals if decimals is not None else 3

#         # widget references 
#         self._progress_widget = None
#         self._progress_raw_widget = None
#         self._progress_calibrated_widget = None
#         self._display_curve_widget = None
#         self._display_label_widget = None
#         self._display_percent_widget = None
#         self._display_value_widget = None
        
#         self._data = None
#         self._comment = comment

#         self._label_text = ""
#         self._label_value = ""
#         self._label_percentage = ""
#         self._label_curve = ""

#         self._display_value = 0.0
#         self._calibrated_value = 0.0
        
#         if axis_id:
#             self._label_text = f"Axis {axis_id}"

#         min = min_range
#         max = max_range
#         if min > max:
#             min, max = max, min
#         self._min_range = min_range
#         self._max_range = max_range

        
#         self._value = 0
#         self._raw_value = 0
#         self._reverse = False
#         self._decimals = 3
#         self._width = 10

#         # hook tab events
#         el = gremlin.event_handler.EventListener()
#         el.tab_selected.connect(self._tab_selected)
#         el.tab_unselected.connect(self._tab_unselected)
#         el.calibration_changed.connect(self._calibration_changed)
#         el.calibration_options_changed.connect(self._calibration_options_changed)

#         self.main_layout.addWidget(self.container_widget)

#         el = gremlin.event_handler.EventListener()
#         el.ui_ready.connect(self._ui_ready)

#         self._set_value_ui(self._value)


#         css = Color.cssRepeater()
#         self.setStyleSheet(css)
#         self.installEventFilter(self)

#     def unhook(self):
#         self.unhookDevice(self.process_event)

#     def process_event(self, event):
#         ''' handles joystick updates '''
#         astate = gremlin.event_handler.AxisState()
#         values = astate.getAxisValues(self._device_guid, self._input_type, self._axis_id)
#         self.setValue(values)

#     def sizeHint(self):
#         if self._orientation == QtCore.Qt.Orientation.Vertical:
#             w = 20
#             h = -1
#         else:
#             w = -1
#             h = 20

#         return QtCore.QSize(w, h)


#     def eventFilter(self, widget, event):
#         ''' grab mouse wheel events to avoid random scrolling '''
#         t = event.type()
#         if t == QtCore.QEvent.Type.Wheel:
#             return True
#         return False


#     @QtCore.Slot(object)
#     def _calibration_changed(self, calibration):
#         ''' occurs when calibration data is changed '''
#         if not Shiboken.isValid(self):
#             return
#         if self.device_guid == calibration.device_guid and self.input_id == calibration.input_id:
#             # one of ours
#             isCalibrated = calibration.hasData
#             syslog.info(f"Device calibration changed to: {isCalibrated}")
#             self.setCalibrated(isCalibrated)
#             self.show_calibrated = isCalibrated
#             self._clear_widgets()
#             self._update_widgets()

#     @QtCore.Slot()
#     def _calibration_options_changed(self):
#         ''' refresh when calibration options change '''
#         self._clear_widgets()
#         self._update_widgets()
            
    

#     def _clear_widgets(self):
#         ''' removes all the widgets for a clean slate '''
#         if not Shiboken.isValid(self):
#             return
#         try:
#             clear_layout(self.container_layout)
#             self._display_curve_widget = None
#             self._display_label_widget = None
#             self._display_percent_widget = None
#             self._display_value_widget = None
#             self._progress_widget = None
#             self._progress_calibrated_widget = None
#             self.progress_container_widget = None
#             self.progress_container_widget = None
#         except:
#             pass

#     def _update_widgets(self):
#         ''' loads widgets into the control based on preferences
        
#         Because QT (as of this writing) does not issue events when it deletes C++ underlying objects, and because the wiring may lead to automatic garbage collection without 
#         Python being aware - we go through special handling to catch these situations and re-create garbage collected elements for this UI widget
        
#         '''

#         # gremlin.util.assert_ui_thread()

#         if not Shiboken.isValid(self):
#             return

#         # clear_layout(self.container_layout)
#         alignment = QtCore.Qt.AlignmentFlag.AlignCenter if self._orientation == QtCore.Qt.Orientation.Vertical else QtCore.Qt.AlignmentFlag.AlignLeft
#         clear_layout(self.container_layout)
        
#         # progress bar label
#         if self._show_label:
#             self._display_label_widget = QtWidgets.QLabel(self._label_text)
#             self.container_layout.addWidget(self._display_label_widget, alignment = alignment)
        
#         # progress bar widget
#         self._progress_widget = QProgressBar(orientation= self._orientation, min = self._min_range, max = self._max_range, data = self._input_id)
#         #widget, layout = getVContainer(self._progress_widget)
#         self.container_layout.addWidget(self._progress_widget, alignment = alignment)

#         if self.device and self.device.is_virtual:
#             self._progress_widget.setReadOnly(False)
#             self._progress_widget.valueChanged.connect(self._value_changed)

#         if self._hooked:
#             # automatic value
#             astate = gremlin.event_handler.AxisState()
#             values = astate.getAxisValues(self._device_guid, self._input_id)
#             if values:
#                 # progress bar widget
#                 self._progress_widget.setValue(values)        
#         else:
#             # manual value
#             self._progress_widget.setValue(self._value)        

#         if self._show_calibrated:
#             config = gremlin.config.Configuration()
#             if config.splitJoystickRepeater:
#                 self._progress_calibrated_widget = QProgressBar(orientation= self._orientation, min = self._min_range, max = self._max_range, data = self.input_id)
#                 self._progress_calibrated_widget.gradientStartColor = Color.selectGradientAltColor()
#                 self._progress_calibrated_widget.gradientEndColor = Color.selectEndGradientAltColor()
#                 self._progress_calibrated_widget.setFixedSize(self._progress_calibrated_widget.sizeHint())
#                 self.container_layout.addWidget(self._progress_calibrated_widget, alignment = alignment)
#                 if self._orientation == QtCore.Qt.Orientation.Vertical:
#                     w = 4 + self._progress_widget.width() + self._progress_calibrated_widget.width() 
#                     self.progress_container_widget.setFixedWidth(w)
#                 else:
#                     h = 4 + self._progress_widget.height() + self._progress_calibrated_widget.height()
#                     self.progress_container_widget.setFixedHeight(h)
                
#                 self._progress_calibrated_widget.setValue(self._calibrated_value)
#                 if self.device and self.device.is_virtual:
#                     self._progress_calibrated_widget.setReadOnly(False)
#                     self._progress_calibrated_widget.valueChanged.connect(self._value_changed)


#         # progress bar value
#         if self._show_value:
#             if self.device and self.device.is_virtual:
#                 self._display_value_widget = QFloatLineEdit(value = self._value)
#                 self._display_value_widget.valueChanged.connect(self._value_changed)
#             else:
#                 self._display_value_widget = QtWidgets.QLabel(self._label_value)
#             self.container_layout.addWidget(self._display_value_widget, alignment = alignment)


#         # progress bar percentage
#         if self._show_percentage:
#             self._display_percent_widget = QtWidgets.QLabel(self._label_percentage)
#             self.container_layout.addWidget(self._display_percent_widget, alignment = alignment)

#         # progress curve 
#         if self._show_curve: 
#             self._display_curve_widget = QtWidgets.QLabel(self._label_curve)
#             self.container_layout.addWidget(self._display_curve_widget, alignment = alignment)

#         self.container_layout.addStretch()

#     @QtCore.Slot()
#     def _value_changed(self):
#         if not Shiboken.isValid(self):
#             return
#         widget = self.sender()        
#         value = widget.value()
#         input_id = widget.data
#         device_guid = self.device.device_guid
#         gremlin.joystick_handling.set_axis(device_guid, input_id, value)



    
#     @QtCore.Slot()
#     def _ui_ready(self):
#         ''' fires when the UI is ready '''
#         self._value = self._hook_value

#     def _cleanup_ui(self):
#         ''' item is being deleted '''
#         if Shiboken.isValid(self):
#             self.unhookDevice()
#             self.deleted.emit(self)

#     @property
#     def data(self):
#         return self._data
#     @data.setter
#     def data(self, value):
#         self._data = value        

#     @property
#     def show_curved(self) -> bool:
#         ''' true if repeater shows curved data '''
#         return self._show_curve
#     @show_curved.setter
#     def show_curved(self, value: bool):
#         if not Shiboken.isValid(self):
#             return
#         if value != self._show_curve:
#             self._show_curve = value
#             self._setValue(self._value, self._curve_value)
#             if value:
#                 self._update_widgets()
#             else:
#                 try:
#                     self.container_layout.removeWidget(self._display_curve_widget)
#                     self._display_curve_widget = None
#                 except:
#                     pass

#     @property
#     def show_percent(self) -> bool:
#         ''' true if repeater shows percentd data '''
#         return self._show_percentage
#     @show_percent.setter
#     def show_percent(self, value: bool):
#         if not Shiboken.isValid(self):
#             return
#         if value != self._show_percentage:
#             self._show_percentage = value
#             if value:
#                 self._update_widgets()
#             else:
#                 try:
#                     self.container_layout.removeWidget(self._display_percent_widget)
#                     self._display_percent_widget = None
#                 except:
#                     pass

#     @property
#     def show_value(self) -> bool:
#         ''' true if repeater shows percentd data '''
#         return self._show_value
#     @show_value.setter
#     def show_value(self, value: bool):
#         if not Shiboken.isValid(self):
#             return
#         if value != self._show_value:
#             self._show_value = value
#             if value:
#                 self._update_widgets()
#             else:
#                 try:
#                     self.container_layout.removeWidget(self._display_value_widget)
#                     self._display_value_widget = None                
#                 except:
#                     pass

#     @property
#     def show_label(self) -> bool:
#         ''' true if repeater shows percentd data '''
#         return self._show_label
#     @show_label.setter
#     def show_label(self, value: bool):
#         if value != self._show_label:
#             self._show_label = value
#             if value:
#                 self._update_widgets()
#             else:
#                 try:
#                     self.container_layout.removeWidget(self._display_label_widget)
#                     self._display_label_widget = None                
#                 except:
#                     pass      

#     @property
#     def show_calibrated(self) -> bool:
#         ''' true if repeater shows percentd data '''
#         return self._show_calibrated
#     @show_calibrated.setter
#     def show_calibrated(self, value: bool):
#         if value != self._show_calibrated:
#             self.setCalibrated(value)
#             self._show_calibrated = value
#             self._clear_widgets()
#             self._update_widgets()

#     def setPercentageVisible(self, value: bool):
#         ''' shows or hides the percentage value on the axis '''
#         if not Shiboken.isValid(self):
#             return
#         self.show_percent(value)

#     def setValueVisible(self, value: bool):
#         self.show_value(value)

#     def setLabel(self, value : str):
#         ''' sets the label for the axis '''
#         if not Shiboken.isValid(self):
#             return
#         self._label_text = value
#         self._update_widgets()
        
#     def setLabelVisible(self, value: bool):
#         if not Shiboken.isValid(self):
#             return
#         self.show_label(value)
        
        

#     def setWidth(self, value):
#         if value > 0:
#             self._width = value
#             #self._update_css()

#     def value(self):
#         return self._value

#     def setValue(self, value, curve_value = None, percent_value = None, other_value = None):
#         """Sets the value shown by the widget.
#         :param value new value to show
#         """
#         gremlin.util.InvokeUiMethod(self._set_value_ui, value, curve_value, percent_value, other_value)
    

#     def _set_value_ui(self, value, calibrated_value = None, curve_value = None, percent_value = None, other_value = None):
#         ''' internal set value '''

#         if not Shiboken.isValid(self):
#             return
        
#         if self._callback:
#             self._callback(value)
        
#         if value is None:
#             return
        
#         if hasattr(value,"__iter__"):
#             # value is [actual, raw, calibrated, curved]
#             display_value = value[0]
#             if calibrated_value is not None and curve_value is not None:
#                 value = value[0] # use the first vlaue only if we have other data passed
            
#             if calibrated_value is None:
#                 calibrated_value = value[2]
#             if curve_value is None:
#                 curve_value = value[3]
#         else:
#             # single value
#             if calibrated_value is None:
#                 calibrated_value = value
        
#             if value < self._min_range:
#                 value = self._min_range
#             if value > self._max_range:
#                 value = self._max_range
#             value += 0   # avoid negative 0 (WHY?)

#             if curve_value is not None:
#                 self._curve_value = curve_value
#                 display_value = curve_value
#             else:
#                 display_value = value
#                 self._curve_value = value

#             if self._reverse:
#                 display_value = gremlin.util.scale_to_range(display_value, invert=True)
#                 calibrated_value = gremlin.util.scale_to_range(calibrated_value, invert=True)
                      
#             self._display_value = display_value
#             self._calibrated_value = calibrated_value

#         if value is None:
#             display_value = None
       
#         self._value = value

        
#         if display_value is not None:
#             self._label_value = f"{display_value:+0.{self._decimals}f}"
#         else:
#             self._label_value = "n/a"
            

#         if self._show_curve and curve_value is not None:
#             self._label_curve = f"C{curve_value:+0.{self._decimals}f}"
            
#         if self._show_percentage:
#             if percent_value is None:
#                 if curve_value is None:
#                     percent = gremlin.util.scale_to_range(display_value, target_min=0, target_max = 100)
#                 else:
#                     percent = gremlin.util.scale_to_range(curve_value, target_min=0, target_max = 100)
#             else:
#                 percent = percent_value
#             self._label_percentage = f"{percent:0.1f} %"

        
#         try:
#             if self._progress_widget and Shiboken.isValid(self._progress_widget):
#                 self._progress_widget.setValue(self._value)
#             else:
#                 self._update_widgets()
#                 return

#             if self._show_curve:
#                 if self._display_curve_widget and Shiboken.isValid(self._display_curve_widget):
#                     self._display_curve_widget.setText(self._label_curve)
#                 else:
#                     self._update_widgets()
#                     return

#             if self._show_label:
#                 if self._display_label_widget and Shiboken.isValid(self._display_label_widget):
#                     self._display_label_widget.setText(self._label_text)
#                 else:
#                     self._update_widgets()
#                     return

            
#             if self._show_value:
#                 if self._display_value_widget and Shiboken.isValid(self._display_value_widget):
#                     self._display_value_widget.setText(self._label_value)
#                 else:
#                     self._update_widgets()
#                     return

#             if self._show_percentage:
#                 if self._display_percent_widget and Shiboken.isValid(self._display_percent_widget):
#                     self._display_percent_widget.setText(self._label_percentage)
#                 else:
#                     self._update_widgets()
#                     return
#         finally:
#             self.valueChanged.emit(self._value, self._curve_value)

           


#     def value(self):
#         ''' gets the current value '''
#         if Shiboken.isValid(self):
#             return self._value
#         return 0

#     def setRange(self, min = -1.0, max = 1.0, decimals = 3):
#         ''' sets the range of the widget '''
#         if not Shiboken.isValid(self):
#             return
#         if min > max:
#             max, min = min, max
#         self._min_range = min
#         self._max_range = max
#         self._decimals = decimals
#         self._update_range()

#     def _update_range(self):
#         if self._progress_widget:
#             self._progress_widget = None
#         self._setValue(self._value)

#     def setMaximum(self, value):
#         ''' sets the upper range value '''
#         self.setRange(self._min_range, value)

#     def setMinimum(self, value):
#         ''' sets the lower range value'''
#         self.setRange(value, self._max_range)

#     def setReverse(self, value):
#         self._reverse = value
#         self._setValue(self._value)

#     def reverse(self):
#         ''' reverse flag '''
#         if not Shiboken.isValid(self):
#             return
#         return self._reverse

#     @property
#     def enabled(self) -> bool:
#         return self.getEnabled()

#     @QtCore.Slot(str)
#     def _tab_selected(self, device_guid):
#         ''' triggered when a tab is selected 
        
#         :param device_guid: the device selected
        
#         '''
#         if not Shiboken.isValid(self):
#             return
#         if self.getEnabled():
#             # already connected
#             return
        
#         device_name = gremlin.shared_state.get_device_name(device_guid)
#         if isinstance(device_guid, str):
#             device_guid = gremlin.util.parse_guid(device_guid)
        
#         if self._device_guid == device_guid:
#             # connect the handler
#             input_id = self._input_id
#             verbose = gremlin.config.Configuration().verbose_mode_inputs
#             if verbose: 
#                 # syslog = logging.getLogger("system")
#                 syslog.info(f"AxisState: {device_name} axis {str(input_id)} connect")
#             _state_tracker.registerAxisState(self, self._device_guid, self._input_type, self._input_id)
#             self.setEnabled(True)


    
#     @QtCore.Slot(str)
#     def _tab_unselected(self, device_guid):
#         ''' triggered when a device tab is deselected, also used to force a disconnect
         
#         :param device_guid: the device to deselect - if None - deselect all
          
#         '''
#         if not Shiboken.isValid(self):
#             return
#         if not self.getEnabled():
#             # not connected 
#             return
#         # syslog = logging.getLogger("system")
#         el = gremlin.event_handler.EventListener()
#         if device_guid:
#             if isinstance(device_guid, str):
#                 device_guid = gremlin.util.parse_guid(device_guid)
#             disconnect = self._device_guid == device_guid
#             device_name = gremlin.shared_state.get_device_name(device_guid)
#         else:
#             disconnect = True
#             device_name = "reset"
            
#         if disconnect:
#             # disconnect the handler
#             input_id = self._input_id
#             # syslog.info(f"AxisState: (unselect) {device_name} axis {input_id} disconnect")
#             _state_tracker.unregisterAxisState(self._device_guid, self._input_type, self._input_id)
#             self.setEnabled(False)
        


#     def _update_value(self, value):
#         # invert the input if needed
#         if not Shiboken.isValid(self):
#             return
#         if self._is_hardware_input:
#             self._setValue(value)
#         else:
#             self._setValue(value)



class AxesCurrentState(QtWidgets.QGroupBox):

    """Displays the current state of all axes on a device (input viewer)"""

    def __init__(self, device : DeviceSummary, step = 0.01, ui_only = False, parent=None):
        """Creates a new instance.

        :param device the device of which to display the axes sate
        :param parent the parent of this widget
        """
        super().__init__(parent)

        
        self._manual_lock = False # semaphore for manual updates
        self.device = device
        self._readonly = True
        self._min_range = -1.0
        self._max_range = 1.0
        self._step = step

        self.main_layout = QtWidgets.QVBoxLayout(self)
        
        
        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Axes")
            self._readonly = False
        else:
            self.setTitle(f"{device.name} - Axes")

        self.show_raw = True # show raw value
        self.axis_widgets = {}
        self.value_label_widgets = {}
        self.percent_widgets = {}
        self.index_map = {}
        axes_layout = QtWidgets.QGridLayout()
        axes_layout.setSpacing(0)
        #axis_list = device.axis_index_list() 
        name_index = 0

        
        verbose = gremlin.config.Configuration().verbose_mode_hooks
        if device.axis_count:
            for i in range(device.axis_count): 
                linear_id = i + 1
                axis_id = device.linear_id_map[linear_id] # map linear -> axis ID for non sequential axes
                
                widget,layout = getVContainer()
                # widget.setStyleSheet("border: 1px solid;")
                widget.setFixedWidth(80)
                widget.setFixedHeight(150)
                sd = gremlin.event_handler.AxisState()
                
                            
                axis_name = device.axis_names[name_index]
                name_index +=1
                axis_label = QtWidgets.QLabel(f"Axis {axis_name} L{linear_id}")
                self.index_map[axis_id] = linear_id
                values = sd.getAxisValues(device.device_guid, linear_id, linear = True)
                if values is None:
                    syslog.error(f"AxisCurrentState: unregistered axis [{device.name}] id: [{device.device_guid}] axis: A{axis_id} L{linear_id}]") 
                    continue

                
                # get initial data
                astate = gremlin.event_handler.AxisState()
                values = astate.getAxisValues(device.device_guid, axis_id)


                axis_widget = QProgressBar(data = axis_id, value = values)
                el = gremlin.event_handler.EventListener()
                el.joystick_event.connect(self.process_event)

                
                if not self._readonly:
                    axis_widget.valueChanged.connect(self._manual_bar_changed) # axis set by the user
                axis_widget.setReadOnly(self._readonly)
                
                
                value = values[0]
                #value = gremlin.joystick_handling.get_axis(device.device_guid, index)
                value_widget = QFloatLineEdit(data = axis_id)
                if self.device.is_virtual:
                    value_widget.setReadOnly(self._readonly)
                    if not self._readonly:
                        value_widget.valueChanged.connect(self._manual_input_changed)
                else:
                    value_widget.setReadOnly(True)

                #axis.setValue(value)
                self.axis_widgets[axis_id] = axis_widget
                self.value_label_widgets[axis_id] = value_widget
                percent = gremlin.util.scale_to_range(value,target_min=0, target_max=100)
                
                percent_label = QtWidgets.QLabel(f"{percent:0.1f} %")
                self.percent_widgets[axis_id] = percent_label
                axis_widget.setValue(values)

                bar_container, _ = getHContainer(["||",axis_widget,"||"]) # centered horizontally
                layout.addWidget(bar_container)

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

            
            axes_layout.setColumnStretch(i+1,2)
        
        self.main_layout.addLayout(axes_layout)

    def unhook(self):
        ''' called when widget is being removed '''

        # disconnect joystick handler
        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self.process_event)

        # disconnect widgets if needed
        if not self._readonly:
            for widget in self.axis_widgets.values():
                # remove data hook
                widget.valueChanged.disconnect(self._manual_bar_changed)
            for widget in self.value_label_widgets.values():
                widget.valueChanged.disconnect(self._manual_input_changed)
             # widget.unhook()

        # cleanup for GC
        self.axis_widgets.clear()
        self.value_label_widgets.clear()
        gremlin.util.clear_layout(self.main_layout)
        


    def process_event(self, event):
        if not event.is_axis:
            return
        if event.device_guid != self.device.device_guid:
            return
        astate = gremlin.event_handler.AxisState()
        input_id = event.identifier
        values = astate.getAxisValues(event.device_guid, input_id, event.value)
        if input_id in self.axis_widgets:
            self.axis_widgets[input_id].setValue(values)
        if input_id in self.value_label_widgets:
            self.value_label_widgets[input_id].setValue(values.actual)
        


  
    def _handle_axis_value_changed(self, device_guid, input_type, input_id, values):
        ''' called by axis handler when axis value changes '''
        w1 = self.percent_widgets[input_id]
        w2 = self.value_label_widgets[input_id]
        if Shiboken.isValid(self) and Shiboken.isValid(w1) and Shiboken.isValid(w2):
            value = values.actual
            percent = gremlin.util.scale_to_range(value, target_min=0, target_max = 100)
            w1.setText(f"{percent:0.1f} %")
            w2.setValue(value)
        


    def isReadOnly(self) -> bool:
        return self._readonly
    
    @QtCore.Slot()
    def _manual_bar_changed(self):
        ''' called when the axis is manually set '''
        if self._manual_lock:
            return 
        
        if Shiboken.isValid(self):
            try:
                self._manual_lock = True    
                widget = self.sender()
                axis_id = widget.data
                value = widget.value()
                gremlin.joystick_handling.set_axis(self.device.device_guid, axis_id, value)
            finally:
                self._manual_lock = False
    
                

    @QtCore.Slot()
    def _manual_input_changed(self):
        ''' called when the axis is manually set '''
        if self._manual_lock:
            return 
        
        if Shiboken.isValid(self):
            self._manual_lock = True    
            widget = self.sender()
            axis_id = widget.data
            value = widget.value()
            gremlin.joystick_handling.set_axis(self.device.device_guid, axis_id, value)
            
                


    def _set_value(self, axis_id : int, value : float | list):
        if not Shiboken.isValid(self):
            return
        if not axis_id in self.axis_widgets:
            syslog.error(f"AXIS STATE: set value {value:0.3f} for axis {axis_id} - axis not found")
            return
        
        self.axis_widgets[axis_id].setValue(value)
        widget = self.value_label_widgets[axis_id]
        
        if hasattr(value,"__iter__"):
            value = value[0]
        if hasattr(widget, "setValue"):
            widget.setValue(value, emit = False)
        else:
            widget.setText(f"{value:+0.3f}")
        percent = gremlin.util.scale_to_range(value,target_min=0, target_max=100)
        self.percent_widgets[axis_id].setText(f"{percent:0.1f} %")


      

    


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
        if not Shiboken.isValid(self):
            return
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
        hat_layout = QFlowLayout()
        for i in range(device.hat_count):
            hat = HatWidget(data = i+1) # data is the hat #
            if device.is_virtual:
                hat.clicked.connect(self._hat_clicked)
            self.hats.append(hat)
            hat_layout.addWidget(hat)

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
        layout = self.layout()
        font = QtGui.QFont("Arial", 8)
        self.scale_widget, _ = getVContainer(['+1',"||","0","||","-1"], font = font)
        self.scale_widget.setMaximumWidth(20)
        self.plot_widget = TimeLinePlotWidget()
        self.legend_layout = QtWidgets.QHBoxLayout()
        
        colors = Color.PenColors()
        for i in range(device.axis_count):
            index = device.axismap_list[i].axis_index
            axis_name = device.axis_names[i]
            label = QtWidgets.QLabel(f"Axis {axis_name}")
            css = f"QLabel {{ color: {colors.get(index,"#000000")}; font-weight: bold }}"
            label.setStyleSheet(css)
            self.legend_layout.addWidget(label)

        self.legend_layout.addStretch()


        self.timeline_container, _ = getHContainer([self.scale_widget, self.plot_widget])
        self.scale_widget.setMinimumHeight(150)
        layout.addWidget(self.timeline_container)
        layout.addLayout(self.legend_layout)

        self.device_guid = device.device_guid
        self.input_id_list = device.getAxisInputIdList()
        self.interval = 1/60
        self._is_running = True
        self._thread = threading.Thread(target = self._update_thread)
        self._thread.name="Timeline"
        self._thread.start()

    def _update_thread(self):
        astate = gremlin.event_handler.AxisState()
        while self._is_running:
            for input_id in self.input_id_list:
                values = astate.getAxisValues(self.device_guid, input_id)
                if values:
                    self.add_point(values.actual, input_id)
            time.sleep(self.interval)

    def unhook(self):
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join()
            self._thread = None
        gremlin.util.clear_layout(self.layout())

    def add_point(self, value, series_id):
        """Adds a new point to the timline.

        :param value the value to add
        :param series_id id of the axes to which to add the value
        """
        # invert the point
        value *= -1.0
        self.plot_widget.add_point(value, series_id)






class TimeLinePlotWidget(QtWidgets.QWidget):

    """Visualizes temporal joystick data as a line graph."""



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

        # update m76T123 - remove all instances of QTimer to avoid mixing and matching QT threading model from Python threading model
        # syncing with QT is manually handled to guard against pitfalls

        self._interval = 1/60 # in seconds
        self._is_running = True # run flag for the update thread
        self._thread = threading.Thread(target = self._update_runner)
        self._thread.name = "TimeLinePlotRunner"
        self._thread.start()
    


    def _update_runner(self):
        ''' update thread for the visualization '''
        while self._is_running:
            gremlin.util.InvokeUiMethod(self._handle_update_ui)
            time.sleep(self._interval)

    def _handle_update_ui(self):
        if Shiboken.isValid(self):
            self._update_pixmap()
            self.update()


    def unhook(self):
        ''' occurs on cleanup '''
        self._is_running = False
        if self._thread.is_alive():
            self._thread.join()
            self._thread = None
    

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
        
        p.setRenderHint(self._render_flags)

        self._pixmap.scroll(-self._step_size, 0, QtCore.QRect(0, 0, self._pixmap.width(), self._pixmap.height()))
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
        match vis_type:
            case gremlin.types.VisualizationType.AxisCurrent:
                el.joystick_event.disconnect(self._current_axis_update)
            case gremlin.types.VisualizationType.AxisTemporal:
                el.joystick_event.disconnect(self._temporal_axis_update)
            case gremlin.types.VisualizationType.ButtonHat:
                el.joystick_event.disconnect(self._button_hat_update)
            case gremlin.types.VisualizationType.Button:
                el.joystick_event.disconnect(self._button_update)
            case gremlin.types.VisualizationType.Hat:
                el.joystick_event.disconnect(self._hat_update)

        self._hooked = False

    def _cleanup_ui(self):
        self.unhook()   




class JoystickDeviceWidget(QtWidgets.QWidget):

    """ joystick visualization widget in the input viewer """

    def __init__(self, device : DeviceSummary, vis_type : gremlin.types.VisualizationType, parent=None):
        """Creates a new instance.

        :param device_data information about the device itself
        :param vis_type the visualization type to use
        :param parent the parent of this widget
        """
        super().__init__(parent)
        assert device is not None, "Device must be provided"

        self._device = device
        self.hook_id = gremlin.util.get_guid()
        self.vis_type = vis_type
        self.widgets = []
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        self.setLayout(layout)
        self.vis_type = vis_type
        self._hooked = False
        self.show_raw = True # true if raw value is displayed
        self._as = gremlin.event_handler.AxisState()

        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self._handle_shutdown)

    def _handle_shutdown(self):
        self.unhook()

    @property
    def device_id(self):
        return self._device.device_id
    
    @property
    def device_guid(self):
        return self._device.device_guid
    


    def process_event(self, event):
        if not gremlin.util.compare_guid(self.device_guid,event.device_guid):
            # wrong device
            return
        vis_type = self.vis_type
        if vis_type == gremlin.types.VisualizationType.AxisCurrent:
            self._current_axis_update(event)
            
        elif vis_type == gremlin.types.VisualizationType.AxisTemporal:
            pass # automatic
            # self._temporal_axis_update(event)
            # for widget in self.widgets:
            #     for input_id in self._device.axis_index_list():
            #         values = self._as.getAxisValues(self.device_guid, input_id)
            #         value= values[0]
            #         # syslog.info(f"input: {input_id} value: {value:0.3f}")
            #         #value = gremlin.joystick_handling.get_axis(self.device_guid, input_id)
            #         widget.add_point(value, input_id)
        elif vis_type in (gremlin.types.VisualizationType.ButtonHat, gremlin.types.VisualizationType.Button, gremlin.types.VisualizationType.Hat):
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
        if not Shiboken.isValid(self):
            return
        if self._hooked:
            return
        vis_type = self.vis_type
        el = gremlin.event_handler.EventListener()

        match vis_type:
            case gremlin.types.VisualizationType.AxisCurrent:
                self._create_current_axis()
                # el.joystick_event.connect(self._current_axis_update) # hook runtime event so it works at runtime or edit time
                el.vjoy_output_event.connect(self._vjoy_current_axis_update) # hook vjoy separately
                    
            case gremlin.types.VisualizationType.AxisTemporal:
                self._create_temporal_axis()

            case gremlin.types.VisualizationType.ButtonHat:
                self._create_button_hat()
                el.joystick_event.connect(self._button_hat_update)
                el.vjoy_output_event.connect(self._vjoy_button_hat_update) # hook vjoy separately

            case gremlin.types.VisualizationType.Button:
                self._create_button()
                el.joystick_event.connect(self._button_update)
                el.vjoy_output_event.connect(self._vjoy_button_update) # hook vjoy separately 

            case gremlin.types.VisualizationType.Hat:
                self._create_hat()
                el.joystick_event.connect(self._hat_update)
                el.vjoy_output_event.connect(self._vjoy_hat_update) # hook vjoy separately
 
        self._hooked = True

    def unhook(self):
        ''' unhooks events '''
        if not Shiboken.isValid(self):
            return
        if not self._hooked:
            return
        vis_type = self.vis_type
        el = gremlin.event_handler.EventListener()
        if vis_type == gremlin.types.VisualizationType.AxisCurrent:
            el.joystick_event.disconnect(self._current_axis_update)

        elif vis_type == gremlin.types.VisualizationType.AxisTemporal:
            pass
            # jep = gremlin.event_handler.JoystickEventProcessor()
            # jep.unregisterCallback(self.hook_id) # this unregisters ALL hooks to this callback

        elif vis_type == gremlin.types.VisualizationType.ButtonHat:
            self._unhook_buttons()
            el.joystick_event.disconnect(self._button_hat_update)
            #el.vjoy_event.connect(self._vjoy_button_hat_update)
            el.vjoy_output_event.connect(self._vjoy_button_hat_update)
            # if self._device.is_virtual:
            #     el.unregisterVjoyCallback(self._vjoy_button_hat_update)
        self._hooked = False

    def _cleanup_ui(self):
        if self.widgets:
            for widget in self.widgets:
                gremlin.util.delete_widget(widget)
            self.widgets.clear()

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
        self.widgets = []
        if self._device.button_count:
            widget = ButtonState(self._device)
            self.widgets.append(widget)
        if self._device.hat_count:
            self.widgets.append(HatState(self._device))
        if self.widgets:
            if len(self.widgets) > 1:
                widget = getHContainer(self.widgets, widget_only=True, alignment= QtCore.Qt.AlignmentFlag.AlignTop,right_stretch=False)
                self.layout().addWidget(widget)
            else:
                self.layout().addWidget(self.widgets[0])

    def _create_hat(self):
        """Creates display for button and hat data."""
        self.widgets = []
        if self._device.hat_count:
            widget = HatState(self._device)
            self.layout().addWidget(widget)
            self.widgets = [widget]

    def _create_button(self):
        """Creates display for button and hat data."""
        self.widgets = []
        if self._device.button_count:
            widget = ButtonState(self._device)
            self.layout().addWidget(widget)
            self.widgets = [widget]
            

    def _unhook_buttons(self):
        pass
        # if self._device.is_virtual:
        #     widgets = [widget for widget in self.widgets if isinstance(widget, ButtonState)]
        #     for widget in widgets:
        #         widget.unhook()

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


    # --------------

    def _button_hat_update(self, event : gremlin.event_handler.Event):
        """Updates the button and hat display.

        :param event the event to use in the update
        """
        if not gremlin.util.compare_guid(self.device_guid,event.device_guid):
            return
        if event.event_type in (InputType.JoystickButton, InputType.JoystickHat):
            gremlin.util.InvokeUiMethod(self._button_hat_update_ui, event) # on ui thread

    def _button_hat_update_ui(self, event : gremlin.event_handler.Event):
        for widget in self.widgets:
            widget.process_event(event)

    def _vjoy_button_hat_update(self, event: gremlin.event_handler.VjoyEvent):
        if self._device.vjoy_id != event.vjoy_id:
            return
        if event.input_type in (InputType.JoystickButton, InputType.JoystickHat):
            
            event = gremlin.event_handler.Event(event_type = event.input_type,
                                                identifier = event.input_id,
                                                is_pressed = event.value,
                                                is_virtual= True,
                                                device_guid= self.device_guid,
                                                value = event.value,
                                                )
            gremlin.util.InvokeUiMethod(self._vjoy_button_hat_update_ui, event) # on ui thread

    def _vjoy_button_hat_update_ui(self, event : gremlin.event_handler.VjoyEvent):
        for widget in self.widgets:
            widget.process_event(event)

    # --------------

    def _button_update(self, event : gremlin.event_handler.Event):
        """Updates the button and hat display.

        :param event the event to use in the update
        """
        if not gremlin.util.compare_guid(self.device_guid,event.device_guid):
            return
        if event.event_type == InputType.JoystickButton:
            gremlin.util.InvokeUiMethod(self._button_update_ui, event) # on ui thread

    def _button_update_ui(self, event : gremlin.event_handler.Event):
        for widget in self.widgets:
            widget.process_event(event)

    def _vjoy_button_update(self, event: gremlin.event_handler.VjoyEvent):
        if self._device.vjoy_id != event.vjoy_id:
            return
        if event.input_type == InputType.JoystickButton:
            
            event = gremlin.event_handler.Event(event_type = event.input_type,
                                                identifier = event.input_id,
                                                is_pressed = event.value,
                                                is_virtual= True,
                                                device_guid= self.device_guid,
                                                value = event.value,
                                                )
            gremlin.util.InvokeUiMethod(self._vjoy_button_update_ui, event) # on ui thread

    def _vjoy_button_update_ui(self, event : gremlin.event_handler.VjoyEvent):
        for widget in self.widgets:
            widget.process_event(event)

    # --------------

    def _hat_update(self, event : gremlin.event_handler.Event):
        """Updates the button and hat display.

        :param event the event to use in the update
        """
        if not gremlin.util.compare_guid(self.device_guid,event.device_guid):
            return
        if event.event_type == InputType.JoystickHat:
            gremlin.util.InvokeUiMethod(self._hat_update_ui, event) # on ui thread

    def _hat_update_ui(self, event : gremlin.event_handler.Event):
        for widget in self.widgets:
            widget.process_event(event)

    def _vjoy_hat_update(self, event: gremlin.event_handler.VjoyEvent):
        if self._device.vjoy_id != event.vjoy_id:
            return
        if event.input_type == InputType.JoystickHat:
            
            event = gremlin.event_handler.Event(event_type = event.input_type,
                                                identifier = event.input_id,
                                                is_pressed = event.value,
                                                is_virtual= True,
                                                device_guid= self.device_guid,
                                                value = event.value,
                                                )
            gremlin.util.InvokeUiMethod(self._vjoy_hat_update_ui, event) # on ui thread

    def _vjoy_hat_update_ui(self, event : gremlin.event_handler.VjoyEvent):
        for widget in self.widgets:
            widget.process_event(event)

    # --------------



    def _current_axis_update(self, event : gremlin.event_handler.Event):
        if self.device_guid != event.device_guid:
            return
        if event.event_type == InputType.JoystickAxis:
            gremlin.util.InvokeUiMethod(self._current_axis_update_ui, event)

    def _current_axis_update_ui(self, event : gremlin.event_handler.Event):
        
        for widget in self.widgets:
            widget.show_raw = self.show_raw
            widget.process_event(event)

    def _vjoy_current_axis_update(self, event : gremlin.event_handler.VjoyEvent):
        if self._device.vjoy_id != event.vjoy_id:
            return
        if event.input_type == InputType.JoystickAxis:
            verbose = gremlin.config.Configuration().verbose_mode_vjoy
            if verbose: syslog.info(f"vjoy event: device: [{event.vjoy_id}] input:[{event.input_id}] value: {event.value:0.3f}")
            event = gremlin.event_handler.Event(event_type = event.input_type,
                                                is_virtual=True,
                                                identifier = event.input_id,
                                                device_guid = self.device_guid,
                                                value=event.value,
                                                is_axis = True,
                                                )
            gremlin.util.InvokeUiMethod(self._vjoy_current_axis_update_ui, event) # on ui thread


    def _vjoy_current_axis_update_ui(self, event : gremlin.event_handler.VjoyEvent):
        for widget in self.widgets:
            widget.process_event(event)
       

    def _temporal_axis_update(self, event : gremlin.event_handler.Event, values = None):
        # if self.device_guid != event.device_guid:
        #     return
        # if event.event_type == InputType.JoystickAxis:
        gremlin.util.InvokeUiMethod(self._temporal_axis_update_ui, event, values) # on ui thread

    def _temporal_axis_update_ui(self, event : gremlin.event_handler.Event, values = None):
        """Updates the temporal axes display.

        :param event the event to use in the update
        """
        for widget in self.widgets:
            widget.add_point(event.value, event.identifier)

    def _vjoy_temporal_axis_update(self, event : gremlin.event_handler.VjoyEvent):
        if self._device.vjoy_id != event.vjoy_id:
            return            
        if event.input_type == InputType.JoystickAxis:
            gremlin.util.InvokeUiMethod(self._vjoy_temporal_axis_update_ui, event) # on ui thread

    def _vjoy_temporal_axis_update_ui(self, event : gremlin.event_handler.VjoyEvent):
        for widget in self.widgets:
            widget.add_point(event.value, event.input_id)

class QUsedPushButton(QDataPushButton):
    ''' custom paint used button with a marker for used/unused '''
    def __init__(self, text = None, data = None, parent = None, tooltip = None,
                 callback = None, callbackEx = None,
                 used = False,
                 used_device_guid = None, used_input_type = None, used_input_id = None, checkable = False, checked = None):
        super().__init__(text, data, parent, tooltip, callback = callback, callbackEx = callbackEx )
        self._used = used
        self._device_guid = used_device_guid
        self._input_type= used_input_type
        self._input_id = used_input_id
        self._highlight = False
        self._pulse_timer = None

        if checkable is not None:
            self.setCheckable(checkable)
        if checked is not None:
            self.setChecked(checked)

        self._hook_requested = False

        if used_device_guid:
            # hook the callback 
            self._hook_requested = True
            self._do_hook()
            
        

    def event(self, event):
        if event.type() == QEvent.Show:
            if self._hook_requested:
                self._do_hook()
        elif event.type() == QEvent.Hide:
            self.unhook()
        return super().event(event)
    
    def _do_hook(self):
        if self._hook_requested:
            el = gremlin.event_handler.EventListener()
            el.input_used_changed.connect(self._handle_used_changed)

    def unhook(self):
        if self._hook_requested:
            el = gremlin.event_handler.EventListener()
            el.input_used_changed.disconnect(self._handle_used_changed)


    def _handle_used_changed(self, device_guid, input_type, input_id, value : bool):
        # see if it's ours
        if device_guid != self._device_guid:
            return
        if input_type != self._input_type:
            return
        if input_id != self._input_id:
            return
        gremlin.util.InvokeUiMethod(self.setUsed, value) # update on UI thread
        
        
    def setUsed(self, value : bool):
        ''' marks the button as used/unused '''
        if Shiboken.isValid(self):
            self._used = value
            self.update()

    def setHighlight(self, value : bool):
        ''' sets the button highlight effect on/off'''
        self._highlight = value
        if self._pulse_timer:
            self._pulse_timer.cancel()
            self._pulse_timer = None
        gremlin.util.InvokeUiMethod(self._repaint)

    def pulseHighlight(self, interval = 0.25):
        ''' pulses the highlight effect on the button for a given duration '''
        if self._pulse_timer:
            self._pulse_timer.cancel()
            
        self._pulse_timer = threading.Timer(interval, self._stopHighlight)
        self._pulse_timer.start()
        self._highlight = True
        gremlin.util.InvokeUiMethod(self._repaint)


    def _stopHighlight(self):
        ''' stops the highlight effect for pulsed highlights'''
        self._highlight = False
        gremlin.util.InvokeUiMethod(self._repaint)


    def _repaint(self):
        if Shiboken.isValid(self):
            self.update()

    
    def paintEvent(self, event):
        super().paintEvent(event)

        # Create a QPainter object
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # --- Perform your custom drawing operations here ---
        # Example: Draw a red rectangle
        color = Color.greenColor() if self._used else Color.grayColor()
            
        painter.setPen(QColor(color))
        painter.setBrush(QColor(color))

        painter.drawEllipse(QPoint(9,9), 3,3)

        # highlight
        if self._highlight:
            
            c1 = QtGui.QColor(0, 255, 0, 32)
            c2 = QtGui.QColor(0, 255, 0, 64)
            w = self.width()
            h = self.height()
            w2 = w/2
            h2 = h/2

            gradient = QtGui.QRadialGradient(
                QPointF(w2, h2),
                min(w, h) / 2,         
                QPointF(w2, h2))

            gradient.setColorAt(0.0, c1) 
            gradient.setColorAt(0.0, c2) 


            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(gradient)
            rect = QtCore.QRect(0, 0, w, h)
            painter.drawEllipse(rect)
        

        painter.end()

class StateRepeaterButton(QDataPushButton):
    ''' state repeater - hooks the state '''

    def __init__(self, state, callback = None, parent = None):
        super().__init__(state.key, parent = parent, data = state)

        font_size = gremlin.config.Configuration().input_viewer_button_size
        self.setCheckable(True)
        css = Color.cssStateButton(font_size)
        cssAlternate = Color.cssStateExpressionButton(font_size)
        self.data = state
  
        if state.expression:
            self.setEnabled(False)    
            self.setStyleSheet(cssAlternate)
        else:
            self.setStyleSheet(css)

        self.setChecked(state.value)
        self.setCallback(callback)

    def toggle(self, emit = False):
        ''' toggle the repeater state'''
        self.setState(not self.isChecked(), emit)

    def setState(self, value : bool, emit = False):
        ''' sets the state of the repeater '''
        if emit:
            # fire the signal when checked
            self.setChecked(value)
        else:
            # block the signal
            with QtCore.QSignalBlocker(self):
                self.setChecked(value)




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

        is_disabled =  True
        if device.is_virtual:
            self.setTitle(f"{device.name} #{device.vjoy_id:d} - Buttons")
            is_disabled = False
            usage_state = gremlin.joystick_handling.VJoyUsageState()
        else:
            self.setTitle(f"{device.name} - Buttons")

        css = Color.cssRepeater()
        self.setStyleSheet(css)

        css = Color.cssButtonState()
        self.buttons = [None]
        flow_layout = QFlowLayout()
        #button_layout = QtWidgets.QGridLayout()
        profile = gremlin.shared_state.current_profile
        for i in range(device.button_count):
            input_id = i+1
            is_used = profile.isInputMapped(device.device_guid, InputType.JoystickButton, input_id)
            if not is_used and device.is_virtual:
                # vjoy device
                is_used = usage_state.get_usage_state(device.vjoy_id, input_id)
                used_device_guid = device.vjoy_id
            else:
                used_device_guid = device.device_guid


            btn = QUsedPushButton(str(input_id),
                                  input_id,
                                  used = is_used,
                                  used_device_guid = used_device_guid,
                                  used_input_type = InputType.JoystickButton,
                                  used_input_id = input_id,
                                  callback = self._button_clicked
                                  )
            btn.setStyleSheet(css)
            
            

            btn.setDisabled(is_disabled)
            if not is_disabled:
                btn.setCheckable(True) # set checkable for state retention

            # read the current state
            is_pressed = gremlin.joystick_handling.get_button(device.device_guid, input_id)
            btn.setDown(is_pressed)
            self.buttons.append(btn)
            #button_layout.addWidget(btn, int(i / 10), int(i % 10))
            flow_layout.addWidget(btn)
        #button_layout.setColumnStretch(10, 1)
        #self.setLayout(button_layout)
        self.setLayout(flow_layout)

        
    @QtCore.Slot()
    def _button_clicked(self, btn):
        ''' called when the button is clicked'''
        input_id = btn.data
        device_guid = self._device.device_guid
        # set the button
        is_pressed = btn.isChecked()
        # is_pressed = not gremlin.joystick_handling.get_button(device_guid, input_id)
        
        # update the remote clients if needed
        gremlin.joystick_handling.set_button(device_guid, input_id, is_pressed, update_remote = True)

    def process_event(self, event):
        """Updates state visualization based on the given event.

        :param event the event with which to update the state display
        """
        if not Shiboken.isValid(self):
            return
        if self._device.device_guid != event.device_guid:
            # not ours
            return
        input_type = event.getInputType()
        if input_type == InputType.JoystickButton:
            #is_pressed = event.is_pressed if event.is_pressed is not None else event.current
            state = event.is_pressed if event.is_pressed is not None else False
            btn = self.buttons[event.identifier]
            btn.setHighlight(state)
            #btn.setChecked(state)
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


class QIconCheckbox(QCheckBox):
    ''' custom checkbox icons for checked/unchecked '''
    def __init__(self,
                checked_icon,
                unchecked_icon,
                size = 24,
                parent=None,
                ):
        ''' :param checked_icon: QIcon for the checked state 
            :param unchecked_icon: QIcon for the unchecked state
            :param size: size in pixels (height and width)
            :param parent: owner widget 
            '''

        super().__init__(parent)
        self._checked_pixmap =  Icons.to_pixmap(checked_icon, pixels = size) if checked_icon else None
        self._unchecked_pixmap =  Icons.to_pixmap(unchecked_icon, pixels = size) if unchecked_icon else None
        self._size = size
        

    def sizeHint(self):
        return QSize(self._size, self._size)
        
    def paintEvent(self, e: QPaintEvent):
        
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        pixmap = self._checked_pixmap if self.isChecked() else self._unchecked_pixmap
        p.drawPixmap(0, 0, pixmap)
        p.end()




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

class QLockToggle(QtWidgets.QWidget):
    ''' toggle for a lock '''

    def __init__(self, parent = None):
        super().__init__(parent)

        main_layout = QtWidgets.QVBoxLayout(self)
        self._toggle_widget = QToggle()
        label = QtWidgets.QLabel()
        label.setPixmap(Pixmaps().warningIconPixmap)
        main_layout.addWidget(label)

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
    def value(self, checked : bool):
        self._button.setChecked(checked)


class QDelayWidget(QtWidgets.QWidget):
    ''' widget to collect a delay time in milliseconds '''

    valueChanged = QtCore.Signal(int) # fired when the value changes
    invalid = QtCore.Signal() # fires when the input is invalid

    def __init__(self, 
                 value = 250, 
                 min_value_seconds = 0,
                 max_value_seconds = 60,
                 is_seconds = False, 
                 callback = None, 
                 invalid_callback = None, 
                 validation_callback = None, 
                 show_shortcuts = True, 
                 parent = None, 
                 label = None,
                 tooltip = None):
        '''

        :params value: default delay in milliseconds '''
        super().__init__(parent)
        self._value = value
        self._supressed = False
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self._callback = callback # callback when value change 
        self._invalid_callback = invalid_callback # callback on invalid input
        self._validation_callback = validation_callback # callback that accepts a value and returns True if the value can be used

        self._is_seconds = is_seconds
        self._max_value = max_value_seconds * 1000 # max value possible
        self._min_value = min_value_seconds * 1000 # min value

        width = get_char_width(8)
        self.delay_label = QtWidgets.QLabel(label) if label else None
        self._delay_widget = QIntLineEdit()
        self._delay_widget.invalid.connect(self._handle_invalid_input)
        # self._delay_widget.setRange(0, self._max_value) 
        self._delay_widget.setMaximumWidth(width)
        self._delay_widget.setMinimum(self._min_value)
        self._delay_widget.setMaximum(self._max_value)
        self._delay_widget.setValue(value) # default
        self._delay_widget.valueChanged.connect(self._value_changed)

        if label:
            widgets = [self.delay_label, self._delay_widget]
        else:
            widgets = [self._delay_widget]

        self.main_layout.addWidget(getHContainer(widgets, widget_only = True))

        if show_shortcuts:
            widgets = []
            shortcuts = {
                "1/10s" : 100,
                "1/4s" : 250,
                "1/2s" : 500,
                "3/4s" : 750,
                "1s": 1000
            }

            for label, value in shortcuts.items():
                widgets.append( QDataPushButton(label, data = value, callback = self._handle_shortcut))

            self.main_layout.addWidget(getHContainer(widgets, widget_only = True))


        if tooltip:
            self.setToolTip(tooltip)

    def _handle_shortcut(self, widget):
        value = widget.data
        self.setValue(value)


    def setSuppressed(self, value : bool):
        ''' supresses events when on '''
        self._supressed = value
            
    def unhook(self):
        self._supressed = True

    def isValid(self) -> bool:
        ''' true if the delay value is valid '''
        return self._delay_widget.isValid()

    def _handle_invalid_input(self):
        if not self._supressed:
            if self._invalid_callback:
                self._invalid_callback()

            self.invalid.emit()

    def setSecondsMode(self, enabled : bool):
        self._is_seconds = enabled

    def value(self):
        ''' gets the delay in milliseconds '''
        value = self._value
        if self._is_seconds:
            value /= 1000 # to seconds
        return value

    def setValue(self, value : float, emit = True):
        ''' sets the widget value 
        :param value: value in ms or in seconds if the widget mode is set to seconds
        '''
        milliseconds = milliseconds = value * 1000 if self._is_seconds else value
        if self._validation_callback:
            if not self._validation_callback(milliseconds):
                return
        if milliseconds >= 0 and milliseconds != self._value:
            self._value = milliseconds
            self._delay_widget.setSuppressed(True)
            self._delay_widget.setValue(milliseconds)
            self._delay_widget.setSuppressed(False)
            if emit and not self._supressed:
                if self._callback:
                    self._callback(milliseconds)
                self.valueChanged.emit(milliseconds)

    
    def setLabel(self, text : str):
        if self.delay_label:
            self.delay_label.setText(text)

    @QtCore.Slot()
    def _value_changed(self):
        value = self._delay_widget.value()
        if self._validation_callback:
            if not self._validation_callback(value):
                self._delay_widget.setSuppressed(True)
                self._delay_widget.setValue(self._value)
                self._delay_widget.setSuppressed(False)
                return
        self._value = value
        if not self._supressed:
            if self._callback:
                self._callback(value)
            self.valueChanged.emit(value)



@SingletonDecorator
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
    ''' flow layout '''
    def __init__(self, parent=None):
        super().__init__(parent)

        if parent is not None:
            self.setContentsMargins(QMargins(0, 0, 0, 0))

        self._item_list = []

    def __del__(self):
        self.clear()

    def clear(self):
        ''' removes all widgets '''
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
        height = self._do_layout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super(QFlowLayout, self).setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()

        lineHeight = 0
        for item in self._item_list:
            item_size = item.minimumSize()
            size = size.expandedTo(item_size)
            lineHeight = max(lineHeight, item_size.height())



        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top() + lineHeight / 2)
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._item_list:
            style = item.widget().style()
            layout_spacing_x = style.layoutSpacing(
                QSizePolicy.ControlType.PushButton, QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Horizontal
            )
            layout_spacing_y = style.layoutSpacing(
                QSizePolicy.ControlType.PushButton, QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Vertical
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
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y()


class QFlowWidget(QtWidgets.QWidget):
    ''' flow layout widget '''
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QFlowLayout(self)
        

    def addWidget(self, widget):
        ''' adds widget to the flow layout'''
        self.main_layout.addWidget(widget)

    def clear(self):
        ''' removes all widgets from the contents '''
        self.main_layout.clear()

    def getWidgets(self) -> list:
        ''' gets a list of widgets in the flow widget'''
        return gremlin.util.get_layout_widgets(self.main_layout)




# class QFlowLayout(QtWidgets.QLayout):
#     def __init__(self, parent=None, margin=-1, hspacing=-1, vspacing=-1):
#         '''
#         :params:
#         parent = parent of the object
#         margin = margin, -1 for auto
#         hspacing = horizontal spacing, -1 for auto
#         vspacing = vertical spacing, -1 for auto
#         sort_property = name of the index member of the item to set the display order, None to disable
#         '''
#         super().__init__(parent)
#         self._hspacing = hspacing
#         self._vspacing = vspacing
#         self._items = []
#         self.setContentsMargins(margin, margin, margin, margin)
#         self._grid_layout = True
#         self._row = 0
#         self._col = 0
#         self._lineHeight = 0

#     def rowCount(self) -> int:
#         return self._row

#     def __del__(self):
#         del self._items[:]

#     def addItem(self, item):
#         self._items.append(item)

#     def sortItems(self, callback):
#         ''' sorts the items based on the given sort property '''
#         self._items.sort(key = lambda item: callback(item))

#     def horizontalSpacing(self):
#         if self._hspacing >= 0:
#             return self._hspacing
#         else:
#             return self.smartSpacing(
#                 QtWidgets.QStyle.PM_LayoutHorizontalSpacing)

#     def verticalSpacing(self):
#         if self._vspacing >= 0:
#             return self._vspacing
#         else:
#             return self.smartSpacing(
#                 QtWidgets.QStyle.PM_LayoutVerticalSpacing)

#     def count(self):
#         return len(self._items)

#     def itemAt(self, index):
#         if 0 <= index < len(self._items):
#             return self._items[index]

#     def takeAt(self, index):
#         if 0 <= index < len(self._items):
#             return self._items.pop(index)

#     def expandingDirections(self):
#         return QtCore.Qt.Orientations(0)

#     def hasHeightForWidth(self):
#         return True

#     def heightForWidth(self, width):
#         return self.doLayout(QtCore.QRect(0, 0, width, 0), True)

#     def setGeometry(self, rect):
#         super().setGeometry(rect)
#         self.doLayout(rect, False)

#     def sizeHint(self):
#         return self.minimumSize()

#     def minimumSize(self):
#         size = QtCore.QSize()
#         lineheight = 0
#         for item in self._items:
#             lineheight = max(lineheight, item.sizeHint().height())
#         for item in self._items:
#             size = size.expandedTo(item.minimumSize())
#             #size = size.expandedTo(item.sizeHint()) + QSize(item.geometry().x(), item.geometry().y())
#         left, top, right, bottom = self.getContentsMargins()
#         size += QtCore.QSize(left + right, top + bottom)
#         size += QSize(0, lineheight * self._row)
#         return size

#     def doLayout(self, rect, testonly):
#         left, top, right, bottom = self.getContentsMargins()
#         effective = rect.adjusted(+left, +top, -right, -bottom)
#         x = effective.x()
#         y = effective.y()
#         lineheight = 0


#         # visible_count = len(self._items)
#         # invisible_count = 0

        
#         if self._grid_layout:
#             # compute max width
#             max_w = 0
#             pos_x = {}
#             pos_x[0] = x

#             for item in self._items:
#                 widget = item.widget()
#                 if not widget.isVisible():
#                     #invisible_count+=1
#                     continue
#                 # if hasattr(widget,"display_name"):
#                 #     print (f"layout: {str(widget.display_name())}")
#                 hspace = self.horizontalSpacing()
#                 if hspace == -1:
#                     hspace = widget.style().layoutSpacing(
#                         QtWidgets.QSizePolicy.PushButton,
#                         QtWidgets.QSizePolicy.PushButton, QtCore.Qt.Horizontal)
#                 vspace = self.verticalSpacing()
#                 if vspace == -1:
#                     vspace = widget.style().layoutSpacing(
#                         QtWidgets.QSizePolicy.PushButton,
#                         QtWidgets.QSizePolicy.PushButton, QtCore.Qt.Vertical)
#                 item_w = item.sizeHint().width() + hspace
#                 max_w = max(max_w,item_w)
#                 lineheight = max(lineheight, item.sizeHint().height())
#             # compute columns

#             self._lineHeight = lineheight

#             usable_width = effective.right() - x
#             if max_w == 0:
#                 max_w = usable_width
#             max_col = max(1, usable_width // max_w)

#             # print (f"available width {usable_width} max widget {max_w} columns: {max_col}")
#             for col in range(max_col):
#                 pos_x[col] = col * max_w
#                 # print(f"\tcol {col} position {pos_x[col]}")

#             col = 0
#             row = 0
#             index = 0
#             for item in self._items:
#                 widget = item.widget()
#                 if not widget.isVisible():
#                     continue
#                 x = pos_x[col]

#                 if not testonly:
#                     item.setGeometry(
#                         QtCore.QRect(QtCore.QPoint(x, y), item.sizeHint()))
#                     # print (f"flow [{index}] position {x} {y}")
#                     index+=1

#                 col += 1
#                 if col == max_col:
#                     col = 0
#                     row += 1
#                     y += lineheight + vspace

#             self._row = row
#             self._col = max_col


#             #print (f"layout visible: {visible_count} invisible: {invisible_count}")

#             return y + lineheight - rect.y() + bottom

#         else:
#             item : QtWidgets.QWidgetItem
#             for item in self._items:
#                 widget = item.widget()
#                 hspace = self.horizontalSpacing()
#                 if hspace == -1:
#                     hspace = widget.style().layoutSpacing(
#                         QtWidgets.QSizePolicy.PushButton,
#                         QtWidgets.QSizePolicy.PushButton, QtCore.Qt.Horizontal)
#                 vspace = self.verticalSpacing()
#                 if vspace == -1:
#                     vspace = widget.style().layoutSpacing(
#                         QtWidgets.QSizePolicy.PushButton,
#                         QtWidgets.QSizePolicy.PushButton, QtCore.Qt.Vertical)
#                 nextX = x + item.sizeHint().width() + hspace

#                 if nextX - hspace > effective.right() and lineheight > 0:
#                     x = effective.x()
#                     y = y + lineheight + vspace
#                     nextX = x + item.sizeHint().width() + hspace
#                     lineheight = 0

#                 if not testonly:
#                     item.setGeometry(
#                         QtCore.QRect(QtCore.QPoint(x, y), item.sizeHint()))
#                 x = nextX

#                 lineheight = max(lineheight, item.sizeHint().height())

#         return y + lineheight - rect.y() + bottom

#     def smartSpacing(self, pm):
#         parent = self.parent()
#         if parent is None:
#             return -1
#         elif parent.isWidgetType():
#             return parent.style().pixelMetric(pm, None, parent)
#         else:
#             return parent.spacing()
        


class QBubble(QtWidgets.QLabel):
    def __init__(self, text):
        super(QBubble, self).__init__(text)
        self.word = text
        self.setContentsMargins(5, 5, 5, 5)

    def paintEvent(self, event):

        # syslog.info("bubble paint start")
        p = QtGui.QPainter(self)
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


class QVContentWidget(QContentWidget):
    def __init__(self, parent = None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)

    def addWidget(self, widget):
        self.main_layout.addWidget(widget)
    def insertWidget(self, index, widget):
        self.main_layout.insertWidget(index, widget)
    def addLayout(self, layout):
        self.main_layout.addLayout(layout)
    def removeWidget(self, widget):
        self.main_layout.removeWidget(widget)
    def clearLayout(self):
        gremlin.util.clear_layout(self.main_layout)
    def getWidgets(self):
        return gremlin.util.get_layout_widgets(self.main_layout)
    def getLayout(self):
        return self.main_layout
        


class QSplitTabWidget(QDataWidget):
    ''' tab content widget split '''
    def __init__(self, object_name, device_guid, parent = None):
        '''
        Creates a device split tab widget with inputs on the left and contents on the right 
        
        :param object_name: device name
        :param device_guid: guid of the device 
        :param parent: parent widget (optional)
        
        '''
        super().__init__(parent)
        self.setObjectName(object_name)

        self._id = gremlin.util.get_guid() # unique ID
        self._blank_input_id = "blank_c9a484aedbab4f518e5bab7ec402df65"  # input ID to use for the blank pages
        self._device_guid = device_guid
        self._device_id = gremlin.util.normalize_guid(device_guid)
        self._filtered = False # filter state for inputs
        

        self._lock = False
        self._tab_data = None

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.setContentsMargins(0,0,0,0)

        self._content_widget = QContentWidget()
        self._content_widget.resized.connect(self._content_resized)
        self._content_widget.setContentsMargins(0,0,0,0)

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self._content_widget)
        self._splitter.splitterMoved.connect(self._splitter_moved)
        self._splitter.setChildrenCollapsible(False)
        self._last_sizes = None


        self._left_panel_widget, self._left_panel_layout = getVContainer()
        #self._left_panel_widget.setMinimumWidth(200)

        self._right_panel_widget, self._right_panel_layout = getVContainer()

        # left panel, list view on top, buttons on bottom
        self._left_container_widget, self._left_container_layout = getVContainer()
        #self._left_container_widget.setMinimumWidth(200)

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
        self._splitter.setStretchFactor(1,4)

        self.main_layout.addWidget(self._content_widget)

        self._blank_input()

    def _handle_used_filter_changed(self, device_id, value):
        if self._device_id == device_id and self._filtered != value:
            self._filtered = value
            self.update_used_filter(value)

    
    @property
    def inputCount(self) -> int:
        ''' number of inputs in the device '''
        assert False,"Must be implemented by derived class"
    
    @property
    def inputWidgetCount(self) -> int:
        ''' number of input widgets currently in the device '''
        assert False,"Must be implemented by derived class"


    @property 
    def tabData(self):
        return self._tab_data
    @tabData.setter
    def tabData(self, value):
        if value != self._tab_data:
            if self._tab_data:
                self._tab_data.filteredChanged.disconnect(self._handle_used_filter_changed)
                self._tab_data.lockedChanged.disconnect(self._handle_locked_changed)
            self._tab_data = value
            self._tab_data.filteredChanged.connect(self._handle_used_filter_changed)
            self._tab_data.lockedChanged.connect(self._handle_locked_changed)

    def _handle_used_filter_changed(self, value : bool):
        assert False, "Abstract member must be implemented in derived class"

    def _handle_locked_changed(self, value : bool):
        assert False, "Abstract member must be implemented in derived class"


    @QtCore.Slot(int, int)
    def _splitter_moved(self, pos, index):
        sizes = self._splitter.sizes()
        if pos < 0:
            # QT bug - position should never be negative
            if self._last_sizes:
                sizes = self._last_sizes
            else:
                width = self._content_widget.frameGeometry().width()
                sizes = [200, width - 200]
            self._splitter.setSizes(sizes)        
        self._last_sizes = sizes
        
    @QtCore.Slot(QtCore.QSize)
    def _content_resized(self, size : QtCore.QSize):
        ''' called when the container object is resized '''

        # resize the splitter to the container's size as it doesn't happen by itself for some reason
        width = self._content_widget.frameGeometry().width()
        height = self._content_widget.frameGeometry().height()
        if width > 400:
            self._splitter.setFixedWidth(width)
        self._splitter.setFixedHeight(height)

    @property
    def rightPanelLocked(self) -> bool:
        ''' true if right panel is locked '''
        unlocked = self._right_panel_widget.isEnabled()
        return not unlocked
    @rightPanelLocked.setter
    def rightPanelLocked(self, locked : bool):
        self._right_panel_widget.setEnabled(not locked)


    def _cleanup_ui(self):
        ''' remove '''
        self.unregisterAllWidgets()
        gremlin.util.clear_layout(self._left_container_layout)
        gremlin.util.clear_layout(self._right_container_layout)
        

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
    
    def unload(self):
        ''' unloads UI resources used by a particular tab widget '''
        pass

    
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

    def ensureLoaded(self):        
        ts = gremlin.tabstate.TabState()
        data = ts.getData(self._device_id)
        if not data.populateEnabled:
            data.populateEnabled = True # enable data loading
            verbose = gremlin.config.Configuration().verbose_mode_ui    
            if verbose: 
                device_name = gremlin.joystick_handling.device_name_from_guid(self._device_id)
                syslog.info(f"UI: enable device data population [{device_name}] [{self._device_id}]")

            # verify this is a device tab
            if hasattr(self, "input_item_list_model"):
                # data needs to be populated - do this on the UI thread
                gremlin.util.InvokeUiMethod(self._ensureLoaded_ui)

    def _ensureLoaded_ui(self):
        ''' ensures the data is loaded into the widget - runs on UI thread '''
        if self.input_item_list_model.rows() == 0:
            self.input_item_list_model.refresh()
        self.input_item_list_view.redraw()   


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

        self.active_screen = QtWidgets.QApplication.screenAt(self.pos())
        self._apply_window_settings()
        



    def _apply_window_settings(self):
        """Restores the stored window geometry settings."""
        config = gremlin.config.Configuration()
        window_size = config.getWindowSize(self._window_key)
        window_location = config.getWindowLocation(self._window_key)
        if window_size:
            self.resize(window_size[0], window_size[1])
        if window_location:
            self.move(window_location[0], window_location[1])
        else:
            self.active_screen = QtWidgets.QApplication.screenAt(self.pos())


    def moveEvent(self, evt):
        """Handle changing the position of the window.

        :param evt event information
        """
        config = gremlin.config.Configuration()
        pos = evt.pos()
        config.setWindowLocation(self._window_key, pos.x(), pos.y())

        # track the screen the application is on (used for cursor positioning)
        self.active_screen = QtWidgets.QApplication.screenAt(pos)

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

def get_main_window():
    """Finds and returns the main QMainWindow instance."""
    for widget in QtWidgets.QApplication.instance():
        if isinstance(widget, QtWidgets.QMainWindow):
            return widget
    return None

class QShowAtCursorDialog(QtWidgets.QDialog):
    ''' a dialog that pops up near the cursor '''
    dialog_closed = QtCore.Signal(object)

    def __init__(self, key = None, parent = None):
        super().__init__(parent)

    def showEvent(self, event):
        # Show the dialog at the current mouse position
        geom = self.frameGeometry()
        geom.moveCenter(QtGui.QCursor.pos())

        # which screen is the main window on
        main_window = gremlin.shared_state.ui
        screen = main_window.active_screen
        if not screen:
            screen = QtWidgets.QApplication.primaryScreen()

        # stay in bounds if the screen 
        
        screen_geometry = screen.availableGeometry()
        a = geom.bottom()
        b = screen_geometry.bottom()
        if a > b :
            geom.moveBottom(b)
        a = geom.top()
        b = screen_geometry.top()
        if a < b:
            geom.moveTop(b)
        a = geom.left()
        b = screen_geometry.left()
        if a < b:
            geom.moveLeft(b)
        a = geom.right()
        b = screen_geometry.right()
        if a > b:
            geom.moveRight(b)
            
        

        self.setGeometry(geom)

        super().showEvent(event)

    def closeEvent(self, arg__1):
        self.dialog_closed.emit(self)
        return super().closeEvent(arg__1)
    
    


class QRememberDialog(QtWidgets.QDialog):
    ''' a dialog window that remembers its size and location '''

    dialog_closed = QtCore.Signal(object)

    def __init__(self, key: str, width : int = 300, height : int = 200 , parent = None):
        super().__init__(parent)

        self._resize_count = 0
        assert key,"unique key must be provided"
        self.window_key = key
        self._moving = False
        self._resizable = True
        self._move_stack = []
        self._move_lock = False
        self._visible = False
        self._default_width = width
        self._default_height = height




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
        else:
            self.resize(self._default_width, self._default_height)
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
        self.dialog_closed.emit(self)
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
        self.closed.emit()
        super().closeEvent(event)

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
        self.setPixmap(Pixmaps().horizontalSeparatorPixmap)

class QHorizontalLine(QtWidgets.QFrame):
    def __init__(self, size = 1, parent = None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setLineWidth(size)

def get_layout_widgets(layout : QtWidgets.QLayout) -> list:
    ''' returns a list of layout widgets '''
    widgets = []
    if layout:
        index = layout.count()
        while index >= 0:
            child = layout.itemAt(index)
            if child is not None:
                if child.layout():
                    widgets.extend(get_layout_widgets(child.layout()))
                elif child.widget():
                    widgets.append(child.widget())
            index -= 1

    return widgets        
        
def getLayoutWidgetHeight(layout, max_height = None):
    ''' gets the maximum height of all the widgets in a layout - assume a horizontal layout up to maximum height if provided  '''
    h = max(w.height() for w in get_layout_widgets(layout))
    if max_height:
        h = min(h, max_height)
    return h 


   
def getHContainer(widget_or_list = None, 
                  label : str = None, 
                  parent = None, 
                  left_stretch : bool= False, 
                  right_stretch  : bool= True, 
                  alignment = None, 
                  set_alignment : bool = True, 
                  min_height = None, 
                  use_vcontainers = False,
                  font : str = None,
                  left_margin : int = 0,
                  right_margin : int  = 0,
                  top_margin : int  = 0,
                  bottom_margin : int = 0,
                  no_stretch : bool = False,
                  widget_only : bool = False,
                  align_top : bool = False,
                  tooltip : str = None):
    ''' gets a qt H container widget 
    
    :param widget_or_list: list of widgets, or a single widget to add to the container - can contain strings that will be converted to a label automatically, use "|" for separator, "||" to insert a stretch
    :param label: label to add to the container (appears first if provided)
    :param parent: parent widget if any
    :param left_stretch: adds the stretch at the start of the container to right align it on the row
    :param use_vcontainers: individual items are wrapped in a vertical container to align top
    :param widget_only: returns just the widget, instead of a (widget, layout) tuple
    :param font: the font to use (optional)
    :param use_vcontainers: flag to place the horizontal container inside a vertical container (for vertical alignment)
    :param min_height: min height in pixels (optional)
    :param alignment: alignment 
    :param set_alignment: if set, forces the alignment set with the alignment parameter
    
    '''
    widget = QtWidgets.QWidget(parent=parent)
    layout = QtWidgets.QHBoxLayout(widget)
    widget.setContentsMargins(0,0,0,0)
    layout.setContentsMargins(left_margin, top_margin, right_margin, bottom_margin)
    

    stretch = False if no_stretch else left_stretch

    if min_height is not None:
        widget.setMinimumHeight(min_height)

    if align_top:
        alignment = QtCore.Qt.AlignmentFlag.AlignTop
    elif alignment is None and set_alignment:
        alignment = QtCore.Qt.AlignmentFlag.AlignVCenter

    if label:
        layout.addWidget(QtWidgets.QLabel(label))
        if not no_stretch:
            stretch = True
    if widget_or_list:
        if isinstance(widget_or_list, list) or isinstance(widget_or_list, tuple):
            for item in widget_or_list:
                if item is None:
                    continue # skip blanks
                if isinstance(item, str):
                    if item == "|": 
                        # separator
                        item = QHorizontalSeparator()
                    elif item == "||":
                        layout.addStretch(1)
                        continue
                    else:
                        item = QtWidgets.QLabel(item)
                        if font:
                            item.setFont(font)
                if use_vcontainers:

                    item, _ = getVContainer(item)
                    
                if alignment:
                    layout.addWidget(item, alignment = alignment)
                else:
                    layout.addWidget(item)
        else:
            if isinstance(widget_or_list, str):
                widget_or_list = QtWidgets.QLabel(widget_or_list)

            if use_vcontainers:
                widget_or_list, _ = getVContainer(widget_or_list)

            if alignment:
                layout.addWidget(widget_or_list, alignment= alignment)
            else:
                layout.addWidget(widget_or_list)
        stretch = True
    if stretch:
        if left_stretch:
            layout.insertStretch(0)
        else:
            if right_stretch:
                layout.addStretch()

    if tooltip:
        widget.setToolTip(tooltip)

    if widget_only:
        return widget
    
    
    return (widget, layout)
    




def getVContainer(widget_or_list = None, label = None, alignment = None, font = None,  parent = None, no_stretch = False, bottom_stretch = False, top_stretch = False, left_margin = 0, widget_only = False):
    ''' gets a qt H container widget '''
    widget = QtWidgets.QWidget(parent=parent)
    layout = QtWidgets.QVBoxLayout(widget)
    widget.setContentsMargins(0,0,0,0)
    layout.setContentsMargins(left_margin,0,0,0)
    if alignment is None:
        alignment = QtCore.Qt.AlignmentFlag.AlignTop
    layout.setAlignment(widget, alignment)
    if top_stretch:
        layout.addStretch()

    stretch = False
    if label:
        layout.addWidget(QtWidgets.QLabel(label))
        stretch = True
    if widget_or_list:
        if isinstance(widget_or_list, list)  or isinstance(widget_or_list, tuple):
            for item in widget_or_list:
                if item is None:
                    continue
                if isinstance(item, str):
                    if item == "|": 
                        # separator
                        item = QHorizontalSeparator()
                    elif item == "||":
                        layout.addStretch(1)
                        continue
                    else:
                        item = QtWidgets.QLabel(item)
                        if font:
                            item.setFont(font)
                    layout.addWidget(item)    
                else:
                    layout.addWidget(item)
        else:
            layout.addWidget(widget_or_list)
        stretch = True
    if (not no_stretch and stretch) or bottom_stretch:
        layout.addStretch()
    
    if widget_only:
        return widget
    return (widget, layout)


def getFlowContainer(widget_or_list = None, label = None, widget_only = False):
    ''' gets a QT custom flow container '''

    widget = QtWidgets.QWidget()
    layout = QFlowLayout(widget)
    widget.setContentsMargins(0,0,0,0)
    layout.setContentsMargins(0,0,0,0)
    
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
            layout.addWidget(item)
        
    if widget_only:
        return widget
    return (widget, layout)


def getGridContainer(widget_or_list = None,
                     label = None,
                     alignment = QtCore.Qt.AlignmentFlag.AlignLeft,
                     start_col = 0,
                     start_row = None,
                     stretch_col = None,
                     add_to_widget = None,
                     widget_only = False,
                     left_margin = 0,
                     bottom_margin = 0):
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
        widget.setContentsMargins(left_margin,0,0,bottom_margin)
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
    if widget_only:
        return widget
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
    layouts = [l for l in layouts if isinstance(l, QtWidgets.QGridLayout)]
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

        w = gremlin.shared_state.char_width * 12 # get_text_width("0000000.0000")

        output_data_entry_widget= QtWidgets.QWidget()
        output_data_entry_layout = QtWidgets.QGridLayout(output_data_entry_widget)


         # output range                 
        border_color = Color.warningColor()
        css = f'''
            QLineEdit {{
                border: 1px solid {border_color};
            }}
            '''
        self._command_min_widget = QFloatLineEdit()
        self._command_min_widget.setRange(min_range, max_range)
        self._command_min_widget.setStyleSheet(css)


        self._command_min_widget.setValue(min_cmd)
        self._command_min_widget.valueChanged.connect(self._update_command_min_range)
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
        self._command_max_widget.valueChanged.connect(self._update_command_max_range)
        self._command_max_widget.setStyleSheet(css)
        

        # output min
        self._data_min_widget = QFloatLineEdit()
        self._data_min_widget.setRange(min_range, max_range)
        if min_range < -1 or max_range > 1:
            self._data_min_widget.setDecimals(0)
        self._data_min_widget.setValue(min_output)
        self._data_min_widget.setMinimumWidth(w)
        self._data_min_widget.valueChanged.connect(self._update_data_min_range)

        # output max
        self._data_max_widget = QFloatLineEdit()
        self._data_max_widget.setRange(min_range, max_range)
        if min_range < -1 or max_range > 1:
            self._data_max_widget.setDecimals(0)
        self._data_max_widget.setValue(max_output)
        self._data_max_widget.setMinimumWidth(w)
        self._data_max_widget.valueChanged.connect(self._update_data_max_range)

        
        

        # normalized is -1 to + 1
        self._normalized_min_widget = QFloatLineEdit()
        self._normalized_min_widget.setRange(-1,1)
        self._normalized_min_widget.setValue(min_norm)
        self._normalized_min_widget.setMinimumWidth(w)
        self._normalized_min_widget.valueChanged.connect(self._update_from_normalized)
        
        
        
        self._normalized_max_widget = QFloatLineEdit()
        self._normalized_max_widget.setRange(-1,1)
        self._normalized_max_widget.setValue(max_norm)
        self._normalized_max_widget.setMinimumWidth(w)
        
        self._normalized_max_widget.valueChanged.connect(self._update_from_normalized)

        self._percent_min_widget = QFloatLineEdit(decimals=2)
        #self._output_min_percent_range_widget.setReadOnly(True)
        self._percent_min_widget.setRange(0,100)
        self._percent_min_widget.setValue(min_percent)
        self._percent_min_widget.setMinimumWidth(w)
        self._percent_min_widget.valueChanged.connect(self._update_from_percent)

        self._percent_max_widget = QFloatLineEdit(decimals=2)
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
                ""
            ]
        )

        grids.append(self.grid_data)

        self.grid_normalized, _ = getGridContainer(
            [   
                QtWidgets.QLabel("Normalized:"),
                self._normalized_min_widget,
                self._normalized_max_widget,
                ""
            ]
        )

        grids.append(self.grid_normalized)

        self.grid_percent, _ = getGridContainer(
            [   
                QtWidgets.QLabel("Percent:"),
                self._percent_min_widget,
                self._percent_max_widget,
                ""
            ]
        )

        grids.append(self.grid_percent)


        
        self.grid_command, _ = getGridContainer(
            [   
                QtWidgets.QLabel("Command Range:"),
                self._command_min_widget,
                self._command_max_widget,
                "(output is scaled to this range)"
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

        self._update_decimals()

    def _update_command_min_range(self, value):
        ''' called when min command value changes '''
        self._update_widget_decimals(self._command_min_widget)
        self._update_from_command(value)

    def _update_command_max_range(self, value):
        ''' called when max command value changes '''
        self._update_widget_decimals(self._command_max_widget)
        self._update_from_command(value)        

    def _update_data_min_range(self, value):
        ''' called when min data value changes '''
        self._update_widget_decimals(self._data_min_widget)
        self._update_from_output(value)

    def _update_data_max_range(self, value):
        ''' called when max data value changes'''
        self._update_widget_decimals(self._data_max_widget)
        self._update_from_output(value)        

    def _update_decimals(self):
        ''' updates decimal range based on the range values of each component '''
        widgets = [self._command_min_widget,
                   self._command_max_widget,
                   self._data_min_widget,
                   self._data_max_widget]
        for widget in widgets:
            self._update_widget_decimals(widget)
        

    def _update_widget_decimals(self, widget):
        ''' updates decimal display for a given float line widget '''
        v1 = widget.minimum()
        v2 = widget.maximum()
        if v1 < -1 or v2 > 1:
            widget.setDecimals(0)
        else:
            widget.setDecimals(3)


    @QtCore.Slot(bool)
    def _inverted_changed(self, checked : bool):
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
    pass


        

class QGroupBoxV(QtWidgets.QGroupBox):
    def __init__(self, title : str = None, value : bool = None, callback = None, parent = None):
        super().__init__(parent)
        self.setContentsMargins(0,0,0,0)

        if title:
            self.setTitle(title)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self._callback = None
        if value is not None:
            self.setCheckable(True)
            self._callback = callback
            self.toggled.connect(self._handle_toggled)

        if title is None:
            # push the margin up
            self.setStyleSheet("QGroupBox{padding-top:0px; margin-top: 0px; }")



    def _handle_toggled(self, checked : bool):
        if self._callback:
            self._callback(checked)

    def addWidget(self, widget):
        self.main_layout.addWidget(widget)


    def clear(self):
        gremlin.util.clear_layout(self.main_layout)


class QHatDirectionSelector(QHatSelectorComboBox):
    pass
    

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
        verbose = gremlin.config.Configuration().verbose_mode_osc
        widget = self.sender()
        value = widget.data
        if verbose: syslog.info(f"OSC: data type changed to: {value}")
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
    
    def setValue(self, value : bool, emit = True):
        if value != self._value:
            self._value = value
            with QtCore.QSignalBlocker(self._on_widget):
                self._on_widget.setChecked(value)
            with QtCore.QSignalBlocker(self._off_widget):
                self._off_widget.setChecked(not value)
            if emit:
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


        self._min_widget = QFloatLineEdit(min_value, min_range = min_range, max_range = max_range)
        self._min_widget.valueChanged.connect(self._min_changed)
        self._max_widget = QFloatLineEdit(max_value, min_range = min_range, max_range = max_range)
        self._min_widget.valueChanged.connect(self._max_changed)


        self._scale_widget, self._scale_layout = getHContainer([QtWidgets.QLabel(f"{label + ' ' if label else ''}Min:"),
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
    def __init__(self,
                 execute_on_press : bool = True,
                 execute_on_release : bool = True,
                 press_callback = None,
                 release_callback = None,
                 label = None,
                 parent = None):
        super().__init__(parent)

        self._execute_on_press = execute_on_press
        self._execute_on_release = execute_on_release

        self._press_widget = QDataCheckbox("Execute on press",
                                           value = execute_on_press,
                                           callback = self._press_changed,
                                           tooltip = "If checked, commands sends on a press event")
        
        self._release_widget = QDataCheckbox("Release on press",
                                           value = execute_on_release,
                                           callback = self._release_changed,
                                           tooltip = "If checked, commands sends on a release event")

        self._press_callback = press_callback
        self._release_callback = release_callback

        self.main_layout = QtWidgets.QVBoxLayout(self)

        widget = getHContainer([self._press_widget, self._release_widget], label = label, widget_only= True)
        self.main_layout.addWidget(widget)
        
        

    @QtCore.Slot(bool)
    def _press_changed(self, checked : bool):
        self._execute_on_press = checked
        v1 = checked
        v2 = self.execute_on_release
        if self._press_callback:
            self._press_callback(v1)
        self.pressChanged.emit(v1)
        self.valueChanged.emit(v1,v2)

        
    @QtCore.Slot(bool)
    def _release_changed(self, checked : bool):
        self._execute_on_release = checked
        v1 = self.execute_on_press
        v2 = checked
        if self._release_callback:
            self._release_callback(v2)
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

class QFrameBox(QtWidgets.QFrame):
    ''' widget for information text '''
    def __init__(self, text = None, wrap = False, parent = None):
        super().__init__(parent = parent)
        self._label_widget = QtWidgets.QLabel(text)
        layout = QtWidgets.QVBoxLayout(self)
        
        layout.addWidget(self._label_widget)
        self.setStyleSheet(Color.cssFrameBox())

        # size to the text
        # width = get_text_width(text)
        # margins = 8
        # self.setFixedWidth(width + margins * 2)

    def setText(self, text):
        if not Shiboken.isValid(self):
            return
        self._label_widget.setHtml(text)


class QInfoBox(QtWidgets.QFrame):
    ''' widget for information text '''
    def __init__(self, text = None, wrap = False, hide_key = None, parent = None):
        super().__init__(parent = parent)

        
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self._label_widget = QAutoResizingTextEdit()
        self._label_widget.setReadOnly(True)
        self._hide_key = hide_key
        css = Color.cssInfoBox()
        if hide_key:
            
            config = gremlin.config.Configuration()
            hidden = config.visualHidden(hide_key)
            if hidden:
                return
            
            widget = QDataCheckbox("Do not show again", callback=self._handle_hide_visual)
            wcss = f"font-weight:bold;"
            widget.setStyleSheet(wcss)
            self.main_layout.addWidget(getHContainer(widget, widget_only=True))
            self._hide_key = hide_key
 
        self.main_layout.addWidget(self._label_widget)
        self.setStyleSheet(css)

        if text:
            self.setText(text)

    def _handle_hide_visual(self, checked : bool):
        config = gremlin.config.Configuration()
        config.setVisualHidden(self._hide_key, True)
        self.setStyleSheet("")
        gremlin.util.clear_layout(self.main_layout)
        self._label_widget = None




    def setText(self, text):
        if not Shiboken.isValid(self):
            return
        if self._label_widget:
            self._label_widget.setHtml(text)
        
        

class GridClickWidget(QtWidgets.QWidget):
    ''' implements a widget that reponds to a mouse click '''
    pressPos = None
    clicked = QtCore.Signal()

    def __init__(self, vjoy_id, input_type, vjoy_input_id, parent = None):
        super(GridClickWidget, self).__init__(parent=parent)
        self.vjoy_id = vjoy_id
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
            cb = QDataRadioButton()

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

           # line2_cont.clicked.connect(self._grid_button_clicked)


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


    # @QtCore.Slot()
    # def _grid_button_clicked(self):
    #     sender = self.sender()
    #     pass
        
        


class QModeSelector(QtWidgets.QWidget):

    """Allows selecting the mode in which Gremlin starts."""
    modeChanged = QtCore.Signal(str) # profile selected (mode:str)


    def __init__(self, profile = None, title = None, parent=None):
        import gremlin.shared_state
        super().__init__(parent)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.dropdown = QDataComboBox()
        if not profile:
            profile = gremlin.shared_state.current_profile

        for mode in profile.mode_list():
            self.dropdown.addItem(mode, mode)
        self.dropdown.currentIndexChanged.connect(self._update_cb)

        if title:
            widget,_ = getHContainer(self.dropdown, title)
            self.main_layout.addWidget(widget)
        else:
            self.main_layout.addWidget(self.dropdown)
        self.main_layout.addStretch()

    def _update_cb(self, index):
        """Handles changes in the mode selection drop down.

        :param index the index of the entry selected
        """
        mode = self.dropdown.currentData()
        self.modeChanged.emit(mode)
        
    def setMode(self, mode):
        index = self.dropdown.findData(mode)
        if index != -1:
            with QtCore.QSignalBlocker(self.dropdown):
                self.dropdown.setCurrentIndex(index)
        else:
            syslog.error(f"MODE SELECTOR: invalid mode: [{mode}]")

    def setCurrentIndex(self, index):
        try:
            with QtCore.QSignalBlocker(self.dropdown):
                self.dropdown.setCurrentIndex(index)
        except:
            syslog.error(f"MODE SELECTOR: invalid index: [{index}]")
            pass # bad index



class QInputDialog(QRememberDialog):
    ''' grabs user input, adds enter key accept - we use our own here to avoid focus issues and have control over the enter key to accept on enter'''
    def __init__(self, title = "Input Dialog", label = None, text=None,parent = None):
        super().__init__(self.__class__.__name__, parent = parent)

        
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.setWindowTitle(title)

        if label:
            self.main_layout.addWidget(QtWidgets.QLabel(label))    

        # edit box
        self._widget = QDataLineEdit(text)
        self._widget.enterPressed.connect(self._accept)
        self._widget.escPressed.connect(self._cancel)
        self.main_layout.addWidget(self._widget)


        self.cancel_widget = Buttons.getCancelWidget(callback = self._cancel)
        self.ok_widget = Buttons.getOkWidget(callback = self._accept)
        widget = getHContainer([self.ok_widget, self.cancel_widget], widget_only = True)
        self.main_layout.addWidget(widget, alignment= QtCore.Qt.AlignmentFlag.AlignHCenter)

    def text(self) -> str:
        return self._widget.text()
    
    def setText(self, text :str) :
        self._widget.setText(text)

    def _cancel(self):
        self.close()

    def _accept(self):
        self.accept()
        self.close()
    

class QWarningWidget(QtWidgets.QWidget):
    ''' warning widget'''
    def __init__(self, text = None, split : bool = False, parent = None):
        super().__init__(parent)
        
        
        self._label_widget = QtWidgets.QLabel(text if split else None)
        main_layout = QtWidgets.QVBoxLayout(self)
        self.setContentsMargins(0,0,0,0)
        main_layout.setContentsMargins(0,0,0,0)
        
        icon = Icons.warningIcon()
        self._icon_widget = QIconLabel(icon_path = icon, text = text if not split else None)
        left_panel, _ = getVContainer(self._icon_widget)
        right_panel, _ = getVContainer(self._label_widget)

        self._split = split
        widget, _ = getHContainer([left_panel, right_panel],alignment = QtCore.Qt.AlignmentFlag.AlignTop)
        main_layout.addWidget(widget)
        self._text = text

    def text(self) -> str:
        return self._text
        
    
    def setText(self, text : str):
        if self._split:
            self._label_widget.setText(text)
        else:
            self._icon_widget.setText(text)
        self._text = text

    def hasText(self) -> bool:
        return bool(self._text)


class QJoystickInputWidget(QtWidgets.QWidget):
    ''' widget to display joystick axis, button and hat counts '''
    def __init__(self, device_guid, parent = None):
        super().__init__(parent = parent)
        
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.device_guid = device_guid
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum,
            QtWidgets.QSizePolicy.Expanding
        )
        self._update_ui()



    def _update_ui(self, filtered_axis = None, filtered_button = None, filtered_hat = None, visible_count = None):
        if not Shiboken.isValid(self):
            return
        widgets = []
        fcolor = Color.blueColor()
        gremlin.util.clear_layout(self.main_layout)
        device = gremlin.joystick_handling.getDevice(self.device_guid)
        if device:
            if device.axis_count:
                
                if filtered_axis is not None and filtered_axis != device.axis_count:
                    icon = Icons.axisIcon(fcolor)
                    tooltip = f"Showing {filtered_axis} out of {device.axis_count} axis inputs"
                    label = QIconLabel(icon, f"<span style='color: {fcolor}; font-weight: bold;'>{filtered_axis}</span>/{device.axis_count}", tooltip=tooltip)    
                else:
                    icon = Icons.axisIcon()
                    tooltip = f"Showing {device.axis_count} axis inputs"
                    label = QIconLabel(icon, f"{device.axis_count}",tooltip=tooltip)
                widgets.append(label)

            if device.button_count:
                
                if filtered_button is not None and filtered_button != device.button_count:
                    icon = Icons.buttonIcon(fcolor)
                    tooltip = f"Showing {filtered_button} out of {device.button_count} button inputs"
                    label = QIconLabel(icon, f"<span style='color: {fcolor}; font-weight: bold;'>{filtered_button}</span>/{device.button_count}",tooltip=tooltip)    
                else:
                    icon = Icons.buttonIcon()
                    tooltip = f"Showing {device.button_count} button inputs"
                    label = QIconLabel(icon, f"{device.button_count}",tooltip=tooltip)
                widgets.append(label)

            if device.hat_count:
                
                if filtered_hat is not None and filtered_hat != device.hat_count:
                    icon = Icons.hatIcon(fcolor)
                    tooltip = f"Showing {filtered_hat} out of {device.hat_count} hat inputs"
                    label = QIconLabel(icon, f"<span style='color: {fcolor}; font-weight: bold;'>{filtered_hat}</span>/{device.hat_count}", tooltip=tooltip)    
                else:
                    icon = Icons.hatIcon()
                    tooltip = f"Showing {device.hat_count} hat inputs"
                    label = QIconLabel(icon, f"{device.hat_count}",tooltip=tooltip)
                widgets.append(label)

            if visible_count is not None:
                total_count = device.axis_count + device.button_count + device.hat_count
                tooltip = f"Showing {visible_count} out of {total_count} inputs"
                label = QtWidgets.QLabel(f"<span style='color: {fcolor}; font-weight: bold;'>{visible_count}</span>/{total_count}")
                label.setToolTip(tooltip)
                widgets.append(label)
                

            if widgets:
                widget = getHContainer(widgets, widget_only=True)
                self.main_layout.addWidget(widget)
        else:
            widget = QtWidgets.QLabel(f"Device not found: {gremlin.util.normalize_guid(self.device_guid)}")
            self.main_layout.addWidget(widget)

    def setStats(self, stats):
        ''' sets the stats from a JoystickInputStats object '''
        f_axis = stats.visible_axis_count
        f_button = stats.visible_button_count
        f_hat = stats.visible_hat_count
        f_visible = f_axis + f_button + f_hat
        gremlin.util.InvokeUiMethod(self._update_ui, f_axis, f_button, f_hat, f_visible)

        


        
        
class QInputLockWidget(QtWidgets.QWidget):
    ''' displays the global lock/unlock buttons '''

    filterChanged = QtCore.Signal(bool) # fires when the filter is toggled
    mappedChanged = QtCore.Signal(bool) # fires when the mapped filter is toggled

    def __init__(self, data = None, filter : bool = False, filter_enabled = False, parent = None):
        super().__init__(parent)
        
        self.data = data # holds anything
        main_layout = QtWidgets.QVBoxLayout(self)
        self._filter = filter
        

        lock_widget = QtWidgets.QPushButton()
        lock_widget.setIcon(Icons.lockIcon())
        lock_widget.clicked.connect(self._handle_lock)
        lock_widget.setToolTip("Lock all inputs")

        unlock_widget = QtWidgets.QPushButton()
        unlock_widget.setIcon(Icons.unlockIcon())
        lock_widget.setToolTip("Unlock all inputs")
        unlock_widget.clicked.connect(self._handle_unlock)

        widgets = [
            lock_widget,
            unlock_widget
        ]

        if filter_enabled:

            self._filter_widget = QDataPushButton()
            self._filter_widget.setIcon(Icons.filterIcon() if filter else Icons.noFilterIcon())
            self._filter_widget.setToolTip(self._get_filter_tooltip(filter))
            self._filter_widget.clicked.connect(self._handle_used)
            self._filter_widget.clickedEx.connect(self._handle_context)
            widgets.insert(0, self._filter_widget)

        else:
            self._filter_widget = None
        

        widget, _ = getHContainer(widgets, left_stretch=True)
        main_layout.addWidget(widget)

    @property
    def filter(self) -> bool:
        return self._filter
    @filter.setter
    def filter(self, value: bool):
        if value != self._filter and self._filter_widget:
            self._filter = value
            self._filter_widget.setIcon(Icons.filterIcon() if value else Icons.noFilterIcon())
            self._filter_widget.setToolTip(self._get_filter_tooltip(value))
            self.filterChanged.emit(value)


    def _get_filter_tooltip(self, value : bool) -> str:
        return "Input Filter Options"
            

    def _handle_used(self):
        # toggle filter
        self.filterChanged.emit(self.filter)
        # self.filter = not self.filter


    def _handle_context(self, widget, is_control : bool, is_shift : bool, is_alt : bool, is_right: bool):
        ''' right click of filter button '''
        if is_right:
            
            el = gremlin.event_handler.EventListener()
            el.jump_to_mapped_input.emit() # request jump to first mapped input 

    def _handle_lock(self):
        
        el = gremlin.event_handler.EventListener()
        el.lock_inputs.emit(self.data)

    def _handle_unlock(self):
        
        el = gremlin.event_handler.EventListener()
        el.unlock_inputs.emit(self.data)


class QHeaderLabel(QtWidgets.QWidget):
    ''' header label widget'''
    def __init__(self, label = None, icon = None, icon_size = 24, size = 3, data = None, parent = None):
        super().__init__(parent)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(QHorizontalLine(size))
        if icon:
            self.main_layout.addWidget(QIconLabel(icon, label, icon_size= icon_size or 24))
        else:
            self.main_layout.addWidget(QtWidgets.QLabel(label))
        self.data = data



class QCollapsible(QFrame):
    """A collapsible widget to hide and unhide child widgets.

    A signal is emitted when the widget is expanded (True) or collapsed (False).

    Based on https://stackoverflow.com/a/68141638 and borrowed from SuperQT

    """

    toggled = QtCore.Signal(bool)
    contentHeightChanged = QtCore.Signal(int) # size to change to



    def __init__(
        self,
        title: str = "", # title bar label
        title_widget: QWidget | None = None, # title bar widget if any
        collapsed = False, # initial state
        parent: QWidget | None = None,
        expandedIcon: QIcon | str | None = "▼",
        collapsedIcon: QIcon | str | None = "▲",
    ):
        super().__init__(parent)
        self._locked = False
        self._is_animating = False
        self._text = title

        self._toggle_btn = QPushButton(title)
        self._toggle_btn.setCheckable(True)

        self.setCollapsedIcon(icon=collapsedIcon)
        self.setExpandedIcon(icon=expandedIcon)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self._toggle_btn.setStyleSheet("text-align: left; border: none; outline: none;")
        self._toggle_btn.toggled.connect(self._toggle)

        # frame layout

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # title layout
        
        if title_widget:
            h_layout = QHBoxLayout()
            h_layout.addWidget(self._toggle_btn)
            h_layout.addWidget(title_widget, stretch = 2)
            layout.addLayout(h_layout)
        else:
            layout.addWidget(self._toggle_btn)

        self.content_widget, self.content_layout = getVContainer()
        layout.addWidget(self.content_widget)

        self._content_height = 0 # height of the content
        

        # Create animators
        self._animation = QPropertyAnimation(self, b"contentHeight")
        #self._animation.setPropertyName(b"maximumHeight")
        self._animation.setStartValue(0)
        self._animation.finished.connect(self._on_animation_done)
        self._animation.setTargetObject(self)
        self.setDuration(300)
        self.setEasingCurve(QEasingCurve.Type.InOutCubic)




        # default content widget
        self._content = None
        
        if collapsed:
            self.collapse(False)
        else:
            self.expand(False)


    def _getContentHeight(self) -> int:
        return self._content_height

    def _setContentHeight(self, value : int):
        ''' called when content height should change'''
        self.contentHeightChanged.emit(value)
        self._content_height = value
        if self._content:
            self._content.setMaximumHeight(value)
        self.contentHeightChanged.emit(value)

    # custom property target for the animation
    contentHeight = QtCore.Property(int, _getContentHeight, _setContentHeight)    

    def toggleButton(self) -> QPushButton:
        """Return the toggle button."""
        return self._toggle_btn

    def setText(self, text: str) -> None:
        """Set the text of the toggle button."""
        self._toggle_btn.setText(text)

    def text(self) -> str:
        """Return the text of the toggle button."""
        return self._toggle_btn.text()

    def setContent(self, content: QWidget, own = True) -> None:
        """Replace central widget (the widget that gets expanded/collapsed)."""
        self._content = content
        
        if own:
            gremlin.util.clear_layout(self.content_layout)
            self.content_layout.addWidget(self._content)
        




    def content(self) -> QWidget:
        """Return the current content widget."""
        return self._content

    def _convert_string_to_icon(self, symbol: str) -> QIcon:
        """Create a QIcon from a string."""
        size = self._toggle_btn.font().pointSize()
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        color = self._toggle_btn.palette().color(QPalette.ColorRole.WindowText)
        painter.setPen(color)
        painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, symbol)
        painter.end()
        return QIcon(pixmap)

    def expandedIcon(self) -> QIcon:
        """Returns the icon used when the widget is expanded."""
        return self._expanded_icon

    def setExpandedIcon(self, icon: QIcon | str | None = None) -> None:
        """Set the icon on the toggle button when the widget is expanded."""
        if icon and isinstance(icon, QIcon):
            self._expanded_icon = icon
        elif icon and isinstance(icon, str):
            self._expanded_icon = self._convert_string_to_icon(icon)

        if self.isExpanded():
            self._toggle_btn.setIcon(self._expanded_icon)

    def collapsedIcon(self) -> QIcon:
        """Returns the icon used when the widget is collapsed."""
        return self._collapsed_icon

    def setCollapsedIcon(self, icon: QIcon | str | None = None) -> None:
        """Set the icon on the toggle button when the widget is collapsed."""
        if icon and isinstance(icon, QIcon):
            self._collapsed_icon = icon
        elif icon and isinstance(icon, str):
            self._collapsed_icon = self._convert_string_to_icon(icon)

        if not self.isExpanded():
            self._toggle_btn.setIcon(self._collapsed_icon)

    def setDuration(self, msecs: int) -> None:
        """Set duration of the collapse/expand animation."""
        self._animation.setDuration(msecs)

    def setEasingCurve(self, easing: QEasingCurve | QEasingCurve.Type) -> None:
        """Set the easing curve for the collapse/expand animation."""
        self._animation.setEasingCurve(easing)

    def addWidget(self, widget: QWidget) -> None:
        """Add a widget to the central content widget's layout."""
        widget.installEventFilter(self)
        self._content.layout().addWidget(widget)

    def removeWidget(self, widget: QWidget) -> None:
        """Remove widget from the central content widget's layout."""
        self._content.layout().removeWidget(widget)
        widget.removeEventFilter(self)

    def expand(self, animate: bool = True) -> None:
        """Expand (show) the collapsible section."""
        self._expand_collapse(QPropertyAnimation.Direction.Forward, animate)

    def collapse(self, animate: bool = True) -> None:
        """Collapse (hide) the collapsible section."""
        self._expand_collapse(QPropertyAnimation.Direction.Backward, animate)

    def isExpanded(self) -> bool:
        """Return whether the collapsible section is visible (expanded) """
        return self._toggle_btn.isChecked()
    
    def isCollapsed(self) -> bool:
        ''' true if the collapsible section is collapsed (not visible)'''
        return not self._toggle_btn.isChecked()

    def setLocked(self, locked: bool = True) -> None:
        """Set whether collapse/expand is disabled."""
        if not Shiboken.isValid(self):
            return
        self._locked = locked
        self._toggle_btn.setCheckable(not locked)

    def locked(self) -> bool:
        """Return True if collapse/expand is disabled."""
        return self._locked

    def _expand_collapse(
        self,
        direction: QPropertyAnimation.Direction,
        animate: bool = True,
        emit: bool = True,
    ) -> None:
        """Set values for the widget based on whether it is expanding or collapsing.

        An emit flag is included so that the toggle signal is only called once (it
        was being emitted a few times via eventFilter when the widget was expanding
        previously).
        """
        if self._locked:
            return
        
        if not Shiboken.isValid(self):
            return

        forward = direction == QPropertyAnimation.Direction.Forward
        icon = self._expanded_icon if forward else self._collapsed_icon
        self._toggle_btn.setIcon(icon)
        self._toggle_btn.setChecked(forward)

        if self._content:
            _content_height = self._content.sizeHint().height() + 10
            if animate:
                self._animation.setDirection(direction)
                self._animation.setEndValue(_content_height)
                self._is_animating = True
                self._animation.start()
            else:
                self._content_height = _content_height
                if self._content:
                    self._content.setMaximumHeight(_content_height if forward else 0)
                self.contentHeightChanged.emit(_content_height)
        if emit:
            self.toggled.emit(direction == QPropertyAnimation.Direction.Forward)

    def _toggle(self) -> None:
        self.expand() if self.isExpanded() else self.collapse()

    def eventFilter(self, a0: QObject, a1: QEvent) -> bool:
        """If a child widget resizes, we need to update our expanded height."""
        if (
            a1.type() == QEvent.Type.Resize
            and self.isExpanded()
            and not self._is_animating
        ):
            self._expand_collapse(
                QPropertyAnimation.Direction.Forward, animate=False, emit=False
            )
        return False

    def _on_animation_done(self) -> None:
        self._is_animating = False



class QSyncModeWidget(QtWidgets.QWidget):
    ''' control used to set the synchronize mode for some actions '''
    changed = QtCore.Signal(gremlin.types.SyncMode) # called when a mode changes
    valueChanged = QtCore.Signal(object) # called when the value is changed 
    def __init__(self, mode = gremlin.types.SyncMode.Default, label = None, callback = None, input_type = None, default_value = None, sync_modes = None, parent = None):
        super().__init__(parent = parent)
        self._callback = callback # change callback
        self._mode = mode
        self._default_value = default_value
        self._input_type = input_type
        self._value = None

        main_layout = QtWidgets.QVBoxLayout(self)
    
        self._selector_widget = QDataComboBox(auto_adjust=True)
        modes = sync_modes if sync_modes else [mode for mode in gremlin.types.SyncMode]
        
        for data in modes:
            self._selector_widget.addItem(data.name, data)

        index = self._selector_widget.findData(mode)
        if index != -1:
            self._selector_widget.setCurrentIndex(index)
        else:
            self._mode = self._selector_widget.currentData()
        

        widgets = [self._selector_widget]
        default_widgets = []


        # default value
        if input_type is not None:
            
            # show default values
            if input_type == InputType.JoystickAxis:
                if default_value is None:
                    default_value = 0.0
                self._default_widget = QFloatLineEdit()
                if default_value is not None:
                    self._default_widget.setValue(default_value)
                self._value = default_value
                self._default_widget.valueChanged.connect(self._axis_value_changed)


                
                default_widgets.append(self._default_widget)

            else:
                # button
                self.rb_start_released = QtWidgets.QRadioButton("Released")
                self.rb_start_pressed = QtWidgets.QRadioButton("Pressed")
                default_widgets.append(self.rb_start_pressed)
                default_widgets.append(self.rb_start_released)
                if default_value == True:
                    self._value = True
                    self.rb_start_pressed.setChecked(True)
                else:
                    self._value = False
                    self.rb_start_released.setChecked(True)
                self.rb_start_pressed.clicked.connect(self._pressed_changed)
                self.rb_start_released.clicked.connect(self._released_changed)
               
        if default_widgets:
            self._default_container_widget, _ = getHContainer(default_widgets)
            widgets.append(self._default_container_widget)
        else: 
            self._default_container_widget = None
        self._description_widget = QtWidgets.QLabel()

        widgets.append(self._description_widget)

        widget, _ = getHContainer(widgets, label if label else "Start Sync Mode:")
        
        main_layout.addWidget(widget)

        self._selector_widget.currentIndexChanged.connect(self._mode_changed)

        self._mode_changed(emit = False)
        main_layout.setContentsMargins(0,0,0,0)


    def _pressed_changed(self):
        self._value = True
        self.valueChanged.emit(self._value)

    def _released_changed(self):
        self._value = False
        self.valueChanged.emit(self._value)        

    def _axis_value_changed(self):
        ''' called when the value is changed (axis) '''
        self._value = self._default_widget.value()
        self.valueChanged.emit(self._value)

    
    @property
    def value(self) -> float | bool:
        ''' gets the selected start value '''
        return self._value
    



    def _mode_changed(self, emit = True):
        ''' called when mode changes'''
        self._mode = self._selector_widget.currentData()
        description = gremlin.types.SyncMode.to_description(self._mode)
        self._description_widget.setText(f"({description})")
        if self._default_container_widget:
            visible = self._mode in (SyncMode.Default, SyncMode.LastOrDefault)
            self._default_container_widget.setVisible(visible)
        if emit:
            if self._callback:
                self._callback(self._mode)
            self.changed.emit(self._mode)

    @property
    def mode(self) -> SyncMode:
        return self._mode
    
    def setMode(self, value : SyncMode):
        gremlin.util.InvokeUiMethod(self._set_mode_ui, value) # ensure on UI thread

    def _set_mode_ui(self, value : SyncMode):
        index = self._selector_widget.findData(value)
        if index != -1:
            with QtCore.QSignalBlocker(self._selector_widget):
                self._selector_widget.setCurrentIndex(index)

        

class QCurveWidget(QtWidgets.QWidget):
    ''' curve button / clear / set '''

    curveChanged = QtCore.Signal(object) # fires when the curve data changes (curve_data)

    def __init__(self, parent = None):
        super().__init__(parent = parent)
        import gremlin.curve_handler

        main_layout = QtWidgets.QVBoxLayout(self)

        self.curve_button_widget = QtWidgets.QPushButton("Output Curve")

        active_color = Color.activeColor()
        normal_color = Color.normalColor()
        self.curve_icon_inactive = load_icon("mdi.chart-bell-curve",qta_color=normal_color)
        self.curve_icon_active = load_icon("mdi.chart-bell-curve",qta_color=active_color)
        self.curve_button_widget.setToolTip("Curve output")
        self.curve_button_widget.clicked.connect(self._curve_button_cb)

        self.curve_clear_widget = QtWidgets.QPushButton("Clear curve")
        delete_icon = load_icon("mdi.delete")
        self.curve_clear_widget.setIcon(delete_icon)
        self.curve_clear_widget.setToolTip("Removes the curve output")
        self.curve_clear_widget.clicked.connect(self._curve_delete_button_cb)

        self.curve_data = gremlin.curve_handler.AxisCurveData()

        widgets = [self.curve_button_widget, self.curve_clear_widget]

        widget,_ = getHContainer(widgets)
        main_layout.addWidget(widget)
        self.curve_update_handler = None

    def setValue(self, value : float):
        ''' update the axis position in the dialog '''
        if self.curve_update_handler:
            self.curve_update_handler(value)

    QtCore.Slot()
    def _curve_button_cb(self):
        import gremlin.curve_handler
        if not self.curve_data:
            curve_data = gremlin.curve_handler.AxisCurveData()
            curve_data.curve_update()
            self.curve_data = curve_data

        syslog.info(f"Before curve update: {self.curve_data}")

        dialog = gremlin.curve_handler.AxisCurveDialog(self.curve_data)
        gremlin.util.centerDialog(dialog, dialog.width(), dialog.height())
        # setup the update handler for value inputs into the curve
        self.curve_update_handler = dialog.curve_update_handler
        #self._update_axis_widget()

        # disable highlighting
        gremlin.shared_state.push_suspend_highlighting()
        dialog.exec()
        gremlin.shared_state.pop_suspend_highlighting()
        self.curve_update_handler = None
        self.curve_data = dialog.getCurveData()
        self.curve_data.curve_update() # update any changes to the curve

        syslog.info(f"After curve update: {self.curve_data}")

        self._update_curve_icon()
        self.curveChanged.emit(self.curve_data)

    QtCore.Slot()
    def _curve_delete_button_cb(self):
        ''' removes the curve data '''
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Confirmation")
        message_box.setInformativeText("Delete curve data for this output?")
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
        )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        is_cursor = gremlin.util.isCursorActive()
        if is_cursor:
            gremlin.util.popCursor()
        response = message_box.exec()
        if is_cursor:
            gremlin.util.pushCursor()
        if response == QtWidgets.QMessageBox.StandardButton.Ok:
            self.curve_data = None
            self._update_curve_icon()
            self.curveChanged.emit(self.curve_data)

    
    def _update_curve_icon(self):
        if self.curve_data:
            self.curve_button_widget.setIcon(self.curve_icon_active)
            self.curve_clear_widget.setEnabled(True)
        else:
            self.curve_button_widget.setIcon(self.curve_icon_inactive)
            self.curve_clear_widget.setEnabled(False)


    
class QScrollableWidget(QtWidgets.QWidget):
    ''' implements a scrollable widget '''

    def __init__(self, widget = None, stretch = True, vertical_scroll = True, horizontal_scroll = True, parent = None):
        super().__init__(parent = parent)

        self._scroll_area = QtWidgets.QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        main_layout = QtWidgets.QVBoxLayout(self)
        self._content_widget = QtWidgets.QWidget()
        self._content_layout = QtWidgets.QVBoxLayout(self._content_widget)
        self._scroll_area.setWidget(self._content_widget)
        main_layout.addWidget(self._scroll_area)

        if widget is not None:
            # add content if provided either as a single widget or a list of widgets
            if hasattr(widget, "__iter__"):
                # list
                for w in widget:
                    self._content_layout.addWidget(w)
            else:
                self._content_layout.addWidget(widget)
            if stretch:
                self._content_layout.addStretch()

        self.setVerticalScroll(vertical_scroll)
        self.setHorizontalScroll(horizontal_scroll)
            

    def addWidget(self, widget):
        ''' adds a widget '''
        self._content_layout.addWidget(widget)
    def insertWidget(self, index, widget):
        self._content_layout.insertWidget(index, widget)
    def addLayout(self, layout):
        self._content_layout.addLayout(layout)
    def removeWidget(self, widget):
        self._content_layout.removeWidget(widget)
    def clearLayout(self):
        gremlin.util.clear_layout(self._content_layout)        

    def clear(self):
        ''' removes all widgets from the layout '''
        gremlin.util.clear_layout(self._content_layout)

    def getLayout(self):
        ''' returns the scrollable layout'''
        return self._content_layout
    

    def setVerticalScroll(self, enabled : bool):
        ''' enable or disable vertical scroll bar '''
        if enabled:
            self._scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self._scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def setHorizontalScroll(self, enabled : bool):
        ''' enable or disable horizontal scroll bar '''
        if enabled:
            self._scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self._scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


class QJoystickSelectorWidget(QtWidgets.QWidget):
    ''' selector widget for a joystick axis, button or hat '''
    selectionChanged = QtCore.Signal(tuple) # when data is selected, returns (dev : DeviceSummary, inputType, inputId)
    def __init__(self,
                    input_types = [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
                    default_device = None,
                    default_input_type = None,
                    default_input_id = None,
                    virtual_only = False,
                    parent = None):
        ''' 
        :param input_types: list of selectable inputs 
        
        '''
        import gremlin.joystick_handling
        super().__init__(parent)
        main_layout = QtWidgets.QVBoxLayout(self)

        self._input_types = input_types
        self._selected_device = default_device
        self._selected_input_type = default_input_type
        self._selected_input_id = default_input_id
        self._last_key = None # last event data 
        self._key_map = {} # map of input keys to input index
        self._virtual_only = virtual_only

        self._devices = sorted(gremlin.joystick_handling.filtered_input_devices(self._input_types, virtual_only),key=lambda x: x.name)

        container_selector_widget = QtWidgets.QWidget()
        main_layout.addWidget(container_selector_widget)
        grid = QtWidgets.QGridLayout(container_selector_widget)
        grid.setColumnStretch(3,1)


        row = 0

        self.lbl_vjoy_device_selector = QtWidgets.QLabel("Device:")
        grid.addWidget(self.lbl_vjoy_device_selector,row,0)
        self.device_selector_widget = QDataComboBox()
        grid.addWidget(self.device_selector_widget,row,1)



        row += 1
        self.input_selector_widget = QDataComboBox()
        self.lbl_vjoy_input_selector = QtWidgets.QLabel("Input:")
        grid.addWidget(self.lbl_vjoy_input_selector,row,0)
        grid.addWidget(self.input_selector_widget,row,1)

    
        self._update_devices()
        self._update_inputs(self.device_selector_widget.currentData())

        

        self.device_selector_widget.currentIndexChanged.connect(self._handle_device_changed)
        self.input_selector_widget.currentIndexChanged.connect(self._handle_input_changed)

    def select(self, device, input_type, input_id):
        ''' selects the specified entries if they exist  '''
        with QtCore.QSignalBlocker(self.device_selector_widget):
            index = self.device_selector_widget.findData(self._selected_device)
            if index != -1:
                self.device_selector_widget.setCurrentIndex(index)
                self._selected_device = device
                self._update_inputs(device)
                with QtCore.QSignalBlocker(self.input_selector_widget):
                    key = (input_type, input_id)
                    if key in self._key_map:
                        index = self._key_map[key]
                    else: 
                        index = -1
                    if index != -1:
                        self.input_selector_widget.setCurrentIndex(index)
                        self._selected_input_type = input_type
                        self._selected_input_id = input_id
                    else:
                        self._selected_input_type, self._selected_input_id = self.input_selector_widget.currentData()
                
            else:
                self._selected_device = self.device_selector_widget.currentData()
                self._selected_input_type, self._selected_input_id = self.input_selector_widget.currentData()
        


    def _update_devices(self):
        ''' updates the device list '''
        with QtCore.QSignalBlocker(self.device_selector_widget):
            self.device_selector_widget.clear()
            for dev in self._devices:
                self.device_selector_widget.addItem(dev.name, dev)

            # select the current entry
            if self._selected_device:
                index = self.device_selector_widget.findData(self._selected_device)
                if index != -1:
                    self.device_selector_widget.setCurrentIndex(index)
                else:
                    self._selected_device = None 

            if not self._selected_device:
                self._selected_device = self.device_selector_widget.currentData() # new default

            self._emit() # send update if needed

    def _update_inputs(self, dev):
        ''' updates the input list for a given device '''
        with QtCore.QSignalBlocker(self.input_selector_widget):
            self.input_selector_widget.clear()
            self._key_map.clear()
            index = 0
            for input_type in self._input_types:
                
                match input_type:
                    case InputType.JoystickAxis:
                        # add axes
                        if dev.axis_count:
                            for am in dev.axismap_list:
                                input_id = am.axis_index
                                if not input_id:
                                    continue # does not exist
                                axis_name = dev.get_axis_name(input_id)
                                key = (input_type, input_id)
                                axis_name = gremlin.joystick_handling.get_axis_name(input_id)
                                self.input_selector_widget.addItem(f"Axis {input_id} ({axis_name})", key)
                                self._key_map[key] = index
                                index += 1
                    case InputType.JoystickButton:
                        # add buttons
                        if dev.button_count:
                            for input_id in range(1, dev.button_count+1):
                                key = (input_type, input_id)
                                self.input_selector_widget.addItem(f"Button {input_id}",  key)
                                self._key_map[key] = index
                                index += 1
                    case InputType.JoystickHat:
                        # add hats
                        if dev.hat_count:
                            for input_id in range(1, dev.hat_count+1):
                                key = (input_type, input_id)
                                self.input_selector_widget.addItem(f"Hat {input_id}",  key)
                                self._key_map[key] = index
                                index += 1

            # default selection
            key = (self._selected_input_type, self._selected_input_id)
            if key in self._key_map:
                index = self._key_map[key]
                self.input_selector_widget.setCurrentIndex(index)
            else:
                # not found, new default
                self._selected_input_type, self._selected_input_id = self.input_selector_widget.currentData()

            self._emit() # send update if needed


    @QtCore.Slot()
    def _handle_device_changed(self):
        import dinput
        dev : dinput.DeviceSummary = self.device_selector_widget.currentData()
        if dev:
            
            if self._selected_device != dev:
                self._update_inputs(dev)
                self._selected_device = dev
                if self.input_selector_widget.count:
                    self._selected_input_type, self._selected_input_id = self.input_selector_widget.currentData()
                    return
                else:                
                    self._selected_input_type = self._selected_input_id = None
                self._selected_device = dev
        else:
            self._selected_device = None

        self._emit()

    @QtCore.Slot()
    def _handle_input_changed(self):
        if self.input_selector_widget.count:
            self._selected_input_type, self._selected_input_id = self.input_selector_widget.currentData()
            self._emit()

    def _emit(self):
        ''' fire the change event if the data is valid '''
        new_key = (self._selected_device, self._selected_input_type, self._selected_input_id)
        if new_key != self._last_key and None not in new_key:
            self.selectionChanged.emit(new_key)
            self._last_key = new_key


class QJoystickSelectorDialog(QShowAtCursorDialog):
    def __init__(self,
                input_types = [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
                default_device = None,
                default_input_type = None,
                default_input_id = None,
                virtual_only : bool = False,
                parent = None):
        
        super().__init__(self.__class__.__name__,parent = parent)


        self._selected_data = (default_device, default_input_type, default_input_id)
        self._input_types = input_types
        self._selected_device = default_device
        self._selected_input_type = default_input_type
        self._selected_input_id = default_input_id
        self._virtual_only = virtual_only

        # self._sequence = InputKeyboardModel(sequence=sequence)
        self.setWindowTitle("Select Joystick Input")
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(main_layout)

        self.selector_widget = QJoystickSelectorWidget(input_types, default_device, default_input_type, default_input_id, virtual_only = virtual_only)
        self.selector_widget.selectionChanged.connect(self._handle_selection_changed)
        main_layout.addWidget(self.selector_widget)

        listen_widget = Buttons.getListenWidget(callback = self._handle_listen_request)

        ok_button_widget =  QtWidgets.QPushButton("Ok")
        ok_button_widget.clicked.connect(self._execute_cb)
        cancel_button_widget = QtWidgets.QPushButton("Cancel")
        cancel_button_widget.clicked.connect(self._close_cb)
        button_container_widget, _ = getHContainer(
            [listen_widget, 
             "||",
             ok_button_widget,
             cancel_button_widget])
        
        main_layout.addWidget(button_container_widget)

        
    @QtCore.Slot(tuple)
    def _handle_selection_changed(self, data):
        self._selected_device, self._selected_input_type, self._selected_input_id = data 
        self._selected_data = data

    def _handle_listen_request(self):
        ''' calls up a listen box to select the input '''
        dialog = InputListenerWidget(
                event_types = self._input_types,
                return_kb_event=True,
                callback = self._handle_listen_selection,
                virtual_only = self._virtual_only
            )
        
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()
    
        dialog.setGeometry(
                int(geom.x() + geom.width() / 2 - 150),
                int(geom.y() + geom.height() / 2 - 75),
                300,
                150
            )
        
        dialog.show()

    def _handle_listen_selection(self, event):
        gremlin.util.InvokeUiMethod(self._handle_listen_selection_ui, event)

    def _handle_listen_selection_ui(self, event):
    
        dev = gremlin.joystick_handling.device_info_from_guid(event.device_guid)
        if self._virtual_only and not dev.is_virtual:
            return
        if event.event_type:
            self._selected_device =  dev
            self._selected_input_type = event.event_type
            self._selected_input_id = event.identifier
            self.selector_widget.select(self._selected_device, self._selected_input_type, self._selected_input_id)
        else:
            syslog.warning(f"INPUT SELECTION: received an invalid event with no input type: {str(event)}")



    @QtCore.Slot()
    def _close_cb(self):
        ''' cancel button pressed '''
        self._selected_data = None
        self.close()

    @QtCore.Slot()
    def _execute_cb(self):
        ''' ok button pressed'''
        import gremlin.input_types
        if self._selected_device is None or self._selected_input_type is None or self._selected_input_id is None:
            syslog.warn("INPUT SELECTION: invalid selection - missing device, type or input id")
            self._selected_data = None
        else:
            self._selected_data = (self._selected_device, gremlin.input_types.InputType(self._selected_input_type), self._selected_input_id)
        self.close()


    @property
    def selectedData(self) -> tuple:
        ''' dialog selection'''
        return self._selected_data



 

class QBorderWidget(QtWidgets.QFrame):
    def __init__(self, parent = None):
        super().__init__(parent = parent)

        is_dark = gremlin.shared_state.is_dark_theme
        border_color = Color.borderColor()

        css = f"# frame {{border: 1px solid {border_color};}}')"
        self.setStyleSheet(css) 
        self.setFrameShape(QtWidgets.QFrame.Box)

        self.main_layout = QtWidgets.QVBoxLayout(self)

    def addWidget(self, widget):
        self.main_layout.addWidget(widget)
    def insertWidget(self, index, widget):
        self.main_layout.insertWidget(index, widget)
    def addLayout(self, layout):
        self.main_layout.addLayout(layout)
    def removeWidget(self, widget):
        self.main_layout.removeWidget(widget)
    def clearLayout(self):
        gremlin.util.clear_layout(self.main_layout)
    def getWidgets(self):
        return gremlin.util.get_layout_widgets(self.main_layout)
    def getLayout(self):
        return self.main_layout
    def setBackgroundColor(self, color : str):
        ''' sets the background color of the title bar '''
        border_color = Color.borderColor()
        if color:
            css = f"# frame {{border: 1px solid {border_color}; background-color: {color}}}')"
        else:
            css = f"# frame {{border: 1px solid {border_color};}}')"
        self.setStyleSheet(css) 
        
               

class QTimedLabel(QtWidgets.QWidget):
    ''' timed label - shows text and makes it go away after a period of time '''
    def __init__(self, delay = 2, parent=None):
        super().__init__(parent)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self._label_widget = QtWidgets.QLabel()
        self._interval = delay
        self._timer = None
        self.main_layout.addWidget(self._label_widget)

    def setText(self, text : str = None):
        gremlin.util.InvokeUiMethod(self._set_text_ui, text)

    def _set_text_ui(self, text : str):
        if Shiboken.isValid(self) and Shiboken.isValid(self._label_widget):
            self._label_widget.setText(text)
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self._interval, self._handle_timer)
            self._timer.start()

    def closeEvent(self, event):
        if self._timer:
            self._timer.cancel()
        return super().closeEvent(event)

    def _handle_timer(self):
        gremlin.util.InvokeUiMethod(self._handle_timer_ui)

    def _handle_timer_ui(self):
        if Shiboken.isValid(self) and Shiboken.isValid(self._label_widget):
            self._label_widget.setText("")
        self._timer = None


        
        
        

class QUrlLabel(QtWidgets.QLabel):
    ''' URL label '''
    def __init__(self, url : str, caption : str = None, parent = None):
        super().__init__(parent = parent)
        self.setText(f"<a href='{url}'>{caption if caption else url}</a>")
        self.setOpenExternalLinks(True)
        


class FindWindowDialog(BaseDialogUi):
    def __init__(self, parent = None):
        super().__init__(self.__class__.__name__, parent)
        self.setWindowTitle("Find Process Window")
        self.setModal(True)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.data = [] # tuples of (class : str, title : str)
        self.selected_index = None # nothing selected
        
        refresh_widget = Buttons.getRefreshWidget("Refresh", callback = self._update_data)

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()
        self.table = QtWidgets.QTableWidget()
        self.table.setSortingEnabled(True)

        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        # Configure the scroll area
        self.scroll_area.setMinimumWidth(400)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        self.scroll_layout.addWidget(self.table)

        self.main_layout.addWidget(self.scroll_area)

        headers = [
                "Process",
                "Window Title",
                "Process Path",
        ]

        self.table.setColumnCount(len(headers))
        self.table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows) # select the entire row
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection) # select a single row at a time
        self.table.currentItemChanged.connect(self._handle_row_changed)
        
        # self.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        # self.table.customContextMenuRequested.connect(self._context_menu_cb)
        # self.table.viewport().installEventFilter(self)


        self.ok_button = QtWidgets.QPushButton("Ok")
        self.ok_button.clicked.connect(self._handle_ok)

        close_button = QtWidgets.QPushButton("Cancel")
        close_button.clicked.connect(self._handle_cancel)

        widgets = [
            refresh_widget,
            "||",
            self.ok_button,
            close_button
            ]
        
        widget = getHContainer(widgets, widget_only = True)
        self.main_layout.addWidget(widget)


        self._update_data()

    def _handle_row_changed(self, current, previous):
        if current is not None:
            self.selected_index = current.row()
        self.ok_button.setEnabled(self.selected_index is not None)

    def getSelectedRow(table_widget):
        row = table_widget.currentRow()
        if row > -1:  # Check if a row is actually selected
            row_data = []
            for column in range(table_widget.columnCount()):
                item = table_widget.item(row, column)
                if item is not None:
                    row_data.append(item.text())
                else:
                    row_data.append("") # Handle empty cells
            return row_data
        return None        


   

    def _update_data(self):
        ''' updates the list of windows '''
        import gremlin.process
        pm = gremlin.process.ProcessHelper()
        self.data = pm.getWindows()
        self.selected_index = None

        self.table.clearContents()
        self.table.setRowCount(len(self.data))
        for i, item in enumerate(self.data):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(item["process_name"]))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(item["window_title"]))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(item["process_path"]))
                               

        # resize
        self.table.resizeColumnsToContents()

        # ok button
        self.ok_button.setEnabled(self.selected_index is not None)

    def _handle_ok(self):
        self.selected = self.data[self.selected_index]
        self.close()

    def _handle_cancel(self):
        self.selected = None
        self.close()

class QProcessSelectorWidget(QtWidgets.QWidget):
    ''' process selection widget by window or by exe file '''
    process_changed = QtCore.Signal(str)
    args_changed = QtCore.Signal(str)
    autostart_changed = QtCore.Signal(bool)
    timeout_changed = QtCore.Signal(float)

    def __init__(self, path : str,
                 args : str = None,
                 enable_autostart : bool = False, 
                 autostart : bool = False,
                 timeout : float = 5,
                 label : str = "Target Process:",
                 callback_path = None,
                 callback_args = None,
                 callback_autostart = None,
                 callback_timeout = None,
                parent = None):
        '''
        Docstring for __init__
        
        
        :param path: path to the exe, can be None
        :param args: process start arguments, optional
        :param enable_autostart: true if autostart checkbox and timeout can be used
        :param autostart: start process flag, optional
        :param timeout: start timeout flag, time in second to wait for a process to autostart
        :param label: widget caption, optional
        :param parent: parent widget, optional
        '''
        super().__init__(parent = parent)

        self._path = path
        self._args = args
        self._autostart = autostart
        self._timeout = timeout
        self._callback_path = callback_path
        self._callback_args = callback_args
        self._callback_timeout = callback_timeout
        self._callback_autostart = callback_autostart
        self._autostart_enabled = enable_autostart
        
    

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.process_path_widget = QPathLineItem(text = self._path,
                                                callback = self._handle_process_path_changed,
                                                callback_open= self._handle_find_window,
                                                button_label = "Select Window...")
        self.process_path_widget.setMaximumWidth(300)

        select_process = QDataPushButton("Select Executable...", callback=self._handle_select_executable)

        container_process = getHContainer([self.process_path_widget, select_process], widget_only = True)

        if enable_autostart:

            start_widget = QDataCheckbox("Auto-start process if not running",
                                                        value = self._autostart,
                                                        callback = self._handle_autostart_changed,
                                                        tooltip = "Attemps to start the process if not running.")
            
            self.timeout_widget = QFloatLineEdit(value = self._timeout,
                                                            min_range=1,
                                                            max_range = 1000,
                                                            step = 1.0,
                                                            callback = self._handle_timeout_changed
                                                            )
                
   
        self.args_widget = QLineEdit(self._args,
                                                    callback = self._handle_args_changed,
                                                    tooltip = "Command line arguments to pass to the process (optional)")
        
        margin = 12
        self.container_timeout = getHContainer(self.timeout_widget,"Process start timeout (s):", widget_only = True, left_margin = margin)
        self.container_args = getHContainer(self.args_widget,"Process command line arguments:", widget_only = True, left_margin = margin)
        widgets = []
        
        if label:
            widgets.append(label)
        
        widgets.append(container_process)
        if enable_autostart:
            widgets.append(start_widget)
            widgets.append(self.container_timeout)

        widgets.append(self.container_args)
        
        self.container = getVContainer(widgets, widget_only = True)
        self.main_layout.addWidget(self.container)


    @property
    def process(self) -> str:
        return self._path
    def setProcess(self, path:str):
        import gremlin.util
        gremlin.util.InvokeUiMethod(self._set_process_ui, path)

    @property
    def args(self) -> str:
        return self._args
    
    def setArgs(self, args : str):
        import gremlin.util
        gremlin.util.InvokeUiMethod(self._set_args, args)

    def _set_process_ui(self, path: str):
        self.process_path_widget.setText(path)

    def _set_args_ui(self, args : str):
        self.args_widget.setText(args)

    def _handle_process_path_changed(self, widget, path : str):
        if path != self._path:
            self._path = path
            self.process_changed.emit(path)
            if self._callback_path:
                self._callback_path(path)
   
    def _handle_select_executable(self, widget):
        ''' opens the process executable '''
        import gremlin.ui.dialogs
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Process",
            self.action_data.process_name,
            "Executable files (*.exe)"
        )
        if fname and os.path.isfile(fname):
            self.process_name = fname
            with QtCore.QSignalBlocker(self.process_path_widget):
                self.process_path_widget.setText(fname)
            self._update_ui()


    @QtCore.Slot(bool)
    def _handle_autostart_changed(self, checked : bool):
        if checked != self._autostart:
            self._autostart = checked
            self._update_ui()
            self.autostart_changed.emit(checked)
            if self._callback_autostart:
                self._callback_autostart(checked)

    @QtCore.Slot(float)
    def _handle_timeout_changed(self, value : float):
        if value != self._timeout:
            self._timeout = value
            self.timeout_changed.emit(value)
            if self._callback_timeout:
                self._callback_timeout(value)

    @QtCore.Slot(str)
    def _handle_args_changed(self, value : str):
        if self._args != value:
            self._args = value if value else None
            self.args_changed.emit(self._args)
            if self._callback_args:
                self._callback_args(self._args)
        
    @QtCore.Slot(object)
    def _handle_find_window(self, widget):
        ''' show find window dialog '''
        self.dialog = FindWindowDialog()
        self.dialog.closed.connect(self._handle_dialog_closed)
        self.dialog.exec()

    @QtCore.Slot()
    def _handle_dialog_closed(self):
        selected = self.dialog.selected
        if selected:
            path = selected["process_path"]
            if path != self._path:
                with QtCore.QSignalBlocker(self.process_path_widget):
                    self.process_path_widget.setText(path)
                    self._path = path
                    self.process_changed.emit(path)
                    if self._callback_path:
                        self._callback_path(path)

        

    def _update_ui(self):
        enabled = self._autostart
        self.container_args.setEnabled(enabled)
        if self._autostart_enabled:
            self.container_timeout.setEnabled(enabled)


class QSendModeSelector(QtWidgets.QWidget):
    ''' send mode selector for actions '''
    def __init__(self, value = gremlin.types.SendType.Normal, callback = None, tooltip = None, parent = None):
        super().__init__(parent = parent)

        if value is None:
            value = gremlin.types.SendType.Normal
        self.mode = value
        self._callback = callback

        main_layout = QtWidgets.QVBoxLayout(self)
        items = [
            ("Normal", gremlin.types.SendType.Normal),
            ("Local Only", gremlin.types.SendType.LocalOnly),
            ("Remote Only", gremlin.types.SendType.RemoteOnly),
            ("Local & Remote", gremlin.types.SendType.LocalAndRemote),
        ]
        self._selector_widget = QDataComboBox(source = items,
                                              value = value,
                                              callback = self._handle_mode_changed
                                              )
        
        icon = Icons.remoteControlIcon()
        widgets = [
            QIconLabel(icon, "Send:"),
            self._selector_widget,
            " "
        ]
        widget = getGridContainer(widgets, widget_only = True)
        widget = getVContainer(widget, widget_only = True)
        self._tooltip = tooltip
        main_layout.addWidget(widget)
        self._update_tooltip()


    def _handle_mode_changed(self, value):
        self.mode = value
        self._update_tooltip()
        if self._callback:
            self._callback(value)

    def _update_tooltip(self):
        if not self._tooltip:
            self.setToolTip(f"Send mode: {gremlin.types.SendType.to_description(self.mode)}")


class QNoWheelPainTextEdit(QtWidgets.QPlainTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.installEventFilter(self)
        self._hover = False
 
 
    def eventFilter(self, object, event):
        t = event.type()
        if t == QtCore.QEvent.Type.Leave:
            self._hover = False
        elif t == QtCore.QEvent.Type.Enter:
            self._hover = True
        elif t == QtCore.QEvent.Type.Wheel:
            if self._hover:
                # blitz wheel
                return True
            
        return False




class RemoteClientWidget(QtWidgets.QWidget):
    ''' UI element that shows the list of available network clients '''
    def __init__(self, config, parent = None):
        
        super().__init__(parent = parent)

        self.config : gremlin.remote.RemoteConfig = config
        self.config.client_changed.connect(self._handle_client_changed)
   
        self.main_layout = QtWidgets.QVBoxLayout(self)
   
 
        self.custom_widget = QDataCheckbox("Custom output configuration",
                                       value = self.config.isCustom,
                                       callback = self._handle_custom_changed,
                                       tooltip = "Enable custom send targets",
                                       )
     
        self.group_widget = QGroupBoxV()
        widget = QtWidgets.QLabel("List of clients:")

        self.any_widget = QDataCheckbox("Any",
                                        value = self.config.anySelected(),
                                        callbackEx= self._handle_client_selected,
                                        tooltip = "Sends to all remote clients when selected",
                                        data = 0,
                                        )


        self.send_local_widget = QDataCheckbox("Local", 
                                        value = self.config.local,
                                        callback = self._handle_local_changed,
                                        tooltip="Send to local instance")
        
        self.send_remote_widget = QDataCheckbox("Remote", 
                                        value = self.config.remote,
                                        callback = self._handle_remote_changed,
                                        tooltip="Send to ore or more remote instances")
        
        self.warning_remote_widget = QWarningWidget("<i>Remote control is currently disabled</i>")
        self.warning_no_output_widget = QWarningWidget("No output mode selected")
        
        

        widgets = [
            self.send_local_widget,
            self.send_remote_widget,
            self.warning_remote_widget,
            self.warning_no_output_widget,
        ]

        widget = getHContainer(widgets, widget_only=True)
        self.group_widget.addWidget(widget)

         
        self.refresh_widget = Buttons.getRefreshWidget("Refresh",callback = self._trigger_identify, tooltip = "This will refresh the list of available network instances.\nClients must be running and allowed to communicate with the current instance to be detected.")
        self.select_all_widget = QDataPushButton("All", callback=self._handle_select_all)
        self.select_none_widget = QDataPushButton("Clear", callback=self._handle_select_none)

        widgets = [
            self.refresh_widget,
            self.select_all_widget,
            self.select_none_widget,
        ]
        

        self.container_buttons = getHContainer(widgets, widget_only=True)

     

        
        widget = getHContainer(widget, widget_only=True)
        self.group_widget.addWidget(widget)

        self.flow_container_widget, self.flow_container_layout = getVContainer()

        self.client_count_widget = QtWidgets.QLabel()

        icon = Icons.remoteControlIcon()
        client_widget = getHContainer([QIconLabel(icon, "Target Client(s):"),
                                       self.client_count_widget
                                       ],
                                       widget_only = True)
  

        # any client
        widgets = [
            client_widget,
            self.any_widget,
            self.flow_container_widget,
            QHorizontalLine(),
            self.container_buttons
        ]
        
        self.container_client = getVContainer(widgets, widget_only = True, left_margin = 12)
        self.group_widget.addWidget(self.container_client)


        self.main_layout.addWidget(self.custom_widget)
        widget = getVContainer(self.group_widget, widget_only = True)
        self.main_layout.addWidget(widget)
        self.main_layout.addStretch()
        

        self.refreshClients()
        
        self._update_ui()
  
    def _update_ui(self):
        
        config = self.config

        if not config.isCustom:
            # custom output disabled - only show the checkbox 
            self.group_widget.setVisible(False)
            return
        
        self.group_widget.setVisible(True)

        enabled = config.enabled


        # remote control only visible if remote control is allowed
        self.send_remote_widget.setEnabled(enabled)

        self.warning_remote_widget.setVisible(not enabled)

        self.warning_no_output_widget.setVisible(not(config.local or config.remote))

        visible = enabled and config.remote
        self.container_buttons.setVisible(visible)
        self.container_client.setVisible(visible)
        
        if visible:
            count = config.getClientCount()
            self.client_count_widget.setText(f"({count-1} found)" if count-1 else "(none detected)")
            selected_count = config.getSelectedCount()
            self.select_all_widget.setEnabled(count > 0 and selected_count < count)
            self.select_none_widget.setEnabled(selected_count > 0)

            # disable individual client selection if "any" is selected
            enabled = not config.anySelected()
            self.flow_container_widget.setEnabled(enabled)

        count = config.getClientCount()
        self.select_all_widget.setEnabled(count > 0)
        selected_count = config.getSelectedCount()
        self.select_none_widget.setEnabled(selected_count > 0)            



    def _handle_client_changed(self):
        ''' update on client change '''
        # syslog.info("remote config client change")
        if Shiboken.isValid(self):
            self.refreshClients()
        else:
            # unregister if called and we're deleted already
            self.config.unregisterClientChangeCallback(self._handle_client_changed)


    def _handle_custom_changed(self, checked : bool):
        self.config.isCustom = checked
        self._update_ui()


    def _handle_identify(self, widget):
        gremlin.remote.remote_client.requestIdentify()


    def _handle_client_response(self, data: gremlin.remote.PacketData ):
        syslog.info(f"REMOTE: received client response:")
        syslog.info(f"client [{data.client_id}]")
        syslog.info(f"Status: [{data.status.name}]")

    def _handle_remote_control_changed(self, enabled : bool):
        ''' called when GEX remote control state changes '''

        gremlin.util.InvokeUiMethod(self._handle_remote_control_ui, enabled)

    def _handle_remote_control_ui(self, enabled : bool):
        if Shiboken.isValid(self):
            self._update_ui()

    def _handle_local_changed(self, checked):
        self.config.local = checked
        self._update_ui()

    def _handle_remote_changed(self, checked):
        self.config.remote = checked
        if checked:
            # ensure at least one client is selected
            count = self.config.getSelectedCount()
            if not count:
                self.any_widget.setChecked(True)
            
        self._update_ui()
        
    def _handle_client_selected(self, widget, checked):
        client_id = widget.data
        client = self.config.getClient(client_id)
        if client:
            client.selected = checked
            self._refresh_clients_ui()
            self._update_ui()

    def _getClientWidgets(self) -> list:
        widgets = [self.any_widget]
        widgets.extend(self.flow_widget.getWidgets())
        return widgets

    def _handle_singleton_changed(self, checked):
        self.config.singleton = checked
        if checked:
            # ensure only one client is selected
            count = self.config.getSelectedCount()
            if count > 1:
                # pick the first one that is selected, clear the others
                selected = True
                for widget in self._getClientWidgets():
                    client : gremlin.remote.RemoteClientData = widget.data
                    if selected and client.selected:
                        selected = False
                        continue
                    widget.setChecked(selected)

    def _trigger_identify(self):
        ''' refreshes the list of network clients '''
        el = gremlin.event_handler.EventListener()
        el.remote_control_identify.emit()

    def _handle_select_all(self, widget):
        ''' selects all widgets '''
        self.config.selectAll()
        self._refresh_clients_ui()
        self._update_ui()

    def _handle_select_none(self, widget):
        ''' clears selection'''
        self.config.selectNone()
        self._refresh_clients_ui()
        self._update_ui()
        

    def _handle_select_any(self):
        ''' only selects the ANY '''
        self.any_widget.setChecked(True)
        self._update_ui()

    
    def refreshClients(self):
        self._refresh_clients()
        self._update_ui()

    def _refresh_clients(self):
        gremlin.util.InvokeUiMethod(self._refresh_clients_ui) # ensure on UI thread


    def _refresh_clients_ui(self):


        if not Shiboken.isValid(self):
            # already deleted
            return
        
        verbose = gremlin.config.Configuration().verbose_mode_remote
        
        config = self.config
        client = config.getClient(0)

        self.send_local_widget.setEnabled(config.localEnabled)
        self.send_remote_widget.setEnabled(config.remoteEnabled)

        with QtCore.QSignalBlocker(self.send_local_widget):
            self.send_local_widget.setChecked(config.local)
        with QtCore.QSignalBlocker(self.send_remote_widget):
            self.send_remote_widget.setChecked(config.remote)
        with QtCore.QSignalBlocker(self.any_widget):            
            self.any_widget.setChecked(client.selected)
        

        gremlin.util.clear_layout(self.flow_container_layout)

        flow_layout = QFlowLayout()
        self.flow_container_layout.addLayout(flow_layout)


        # ANY client is not selected, show the distinct list of clients
        clients = config.getClients()
        client_id = config.getLocalClientId() # local client ID

        any_selected = config.anySelected()

        for client in clients:
            #if verbose: syslog.info(f"got client: [{client.client_name}]")
            if client.client_id != 0:
                # only add the specific connected clients
                # if verbose: syslog.info(f"adding client: {client.client_name}")
                if client.client_id == client_id:
                    # local
                    client_name = f"{client.client_name} (self)"
                    enabled = False # cannot send to self but display the data
                else:
                    client_name = client.client_name
                    enabled = not any_selected
                widget = QDataCheckbox(client_name,
                                        data = client.client_id,
                                        value = client.selected,
                                        callbackEx= self._handle_client_selected,
                                        tooltip = str(client))

                widget.setEnabled(enabled)
                
                
                flow_layout.addWidget(widget)

        self._update_ui()

    
    def setClientId(self, client_id):
        ''' sets the client id '''
        index = self.client_selector.findData(client_id)
        if index != -1:
            self.client_selector.setCurrentIndex(index)
