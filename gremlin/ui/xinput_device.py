''' xinput device '''

import logging

from PySide6 import QtWidgets, QtCore
from gremlin.threading import AbortableThread
from gremlin.input_types import InputType
import gremlin.shared_state
from gremlin.util import *
from lxml import etree as ElementTree
import enum

import uuid
import mido
from gremlin.singleton_decorator import SingletonDecorator

from gremlin.util import parse_guid, byte_list_to_string
import gremlin.event_handler
import gremlin.config
from gremlin.ui.qdatawidget import QDataWidget
from dinput.xinput import XInputAxisType, XInputButtonType, XInputTriggerType, XInputEventType
from gremlin.ui import ui_common

class XInputAxisWidget(QtWidgets.QGroupBox):
    def __init__(self, input_type : XInputAxisType, device, parent = None):
        super().__init__(parent)

        if input_type == XInputAxisType.Left:
            header_text = "Left Stick"
        elif input_type == XInputAxisType.Right:
            header_text = "Right Stick"

        # left stick
        box = QtWidgets.QGroupBox()
        widget = QtWidgets.QLabel(header_text)
        layout = box.layout()
        layout.addWidget(widget)

        self.axis_widget = ui_common.AxisStateWidget(orientation = QtCore.Qt.Orientation.Horizontal, show_percentage=False)
        layout.addWidget(self.axis_widget)

        self.device = device

class XInputTriggerWidget(QtWidgets.QGroupBox):
    def __init__(self, input_type : XInputTriggerType, device, parent = None):
        super().__init__(parent)

        if input_type == XInputTriggerType.Left:
            header_text = "Left Trigger"
        elif input_type == XInputTriggerType.Right:
            header_text = "Right Trigger"

        # left stick
        box = QtWidgets.QGroupBox()
        widget = QtWidgets.QLabel(header_text)
        layout = box.layout()
        layout.addWidget(widget)

        self.axis_widget = ui_common.AxisStateWidget(orientation = QtCore.Qt.Orientation.Horizontal, show_percentage=False)
        layout.addWidget(self.axis_widget)

        self.device = device


class XInputButtonWidget(QtWidgets.QGroupBox):
    def __init__(self, input_type : XInputButtonType, device, parent = None):
        super().__init__(parent)

        if input_type == XInputButtonType.Back:
            header_text = "Back"
        elif input_type == XInputButtonType.Start:
            header_text = "Start"
        elif input_type == XInputButtonType.Stop:
            header_text = "Stop"
        elif input_type == XInputButtonType.ShoulderLeft:
            header_text = "Left Shoulder"
        elif input_type == XInputButtonType.ShoulderRight:
            header_text = "Right Shoulder"
        elif input_type == XInputButtonType.A:
            header_text = "A"
        elif input_type == XInputButtonType.B:
            header_text = "B"
        elif input_type == XInputButtonType.X:
            header_text = "X"
        elif input_type == XInputButtonType.Y:
            header_text = "Y"
        
        # left stick
        box = QtWidgets.QGroupBox()
        widget = QtWidgets.QLabel(header_text)
        layout = box.layout()
        layout.addWidget(widget)

        self.device = device




class XInputTabWidget(QDataWidget):
    # device guids (up to 4 devices supported )
    device_guids = [parse_guid('60c8a277-325f-4cff-8835-c9e9441a1b1b'),
                   parse_guid('8a3ebd9a-9c05-4186-90b9-65fc343400ff'),
                   parse_guid('5d209cff-405a-487b-8776-0e61a6d6d18c'),
                   parse_guid('c1bd9746-58c9-4da3-8479-68be2e51bcb4')
    ]
    
    def __init__(
            self,
            xinput_index, # input of the controller 0 to 3
            device_profile,
            current_mode,
            parent=None
    ):
        """Creates a new object instance.

        :param device_profile profile data of the entire device
        :param current_mode currently active mode
        :param parent the parent of this widget
        """
        super().__init__(parent)

        import gremlin.ui.input_item as input_item
        import gremlin.ui.ui_common as ui_common

       

        # Store parameters
        self.device_profile = device_profile
        self.current_mode = current_mode

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.left_panel_layout = QtWidgets.QVBoxLayout()
        self.device_profile.ensure_mode_exists(self.current_mode)

        # widgets
        for _, axis in enumerate(XInputAxisType):
            widget = XInputAxisWidget(axis)






        self.layout


