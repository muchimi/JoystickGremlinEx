# implements a custom multi-gate slider widget

import enum
import time
import threading
import os
from typing import Optional
import logging
from PySide6 import QtWidgets, QtCore, QtGui
import PySide6.QtGui
import PySide6.QtWidgets
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
import gremlin.util
from  PySide6.QtCore import (
    Qt, QSize, QPoint, QPointF, QRectF, QRect,
    QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup,
    Slot, Property)

from PySide6.QtWidgets import QCheckBox
from PySide6.QtGui import QColor, QBrush, QPaintEvent, QPen, QPainter, QFont, QMouseEvent


class Direction:
    Up = 0
    Down = 1

class QSliderWidget(QtWidgets.QWidget):
    ''' custom slider object '''

    handleLeftClicked = QtCore.Signal(int) # called when a gate is left clicked
    handleRightClicked = QtCore.Signal(int) # called when a gate is right clicked
    handleGrooveClicked = QtCore.Signal(float) # called when a groove is clicked (between gates) - sends the value of the slider where clicked
    valueChanged = QtCore.Signal() # called when a gate value changes via dragging

    
    # QOVERFLOW = 2**31 - 1
    # MAX_DISPLAY = 5000

    class PixmapData():
        ''' holds a pixmap definition '''
        def __init__(self, pixmap : QtGui.QPixmap = None, offset_x = None, offset_y = None):
            self.pixmap = pixmap
            self.offset_x = offset_x
            self.offset_y = offset_y
            if pixmap is not None:
                self.width = pixmap.width()
                self.height = pixmap.height()
            else:
                self.width = 0
                self.height = 0    

    def __init__(self, parent = None):
        super().__init__(parent)

        self._values = [-1.0, 1.0]
        self._minimum = -1.0
        self._maximum = 1.0

        self.finishedNumberColor = QColor(255, 255, 255)
        self.finishedBackgroundColor = QColor(228, 231, 237)
        self.unfinishedBackgroundColor = QColor(138, 231, 237)

        self.pointerDirection = Direction.Up

        self._finishedProgressLength = 0
        self._gate_rects = [] # rects of clickable spots
        self._gate_positions = [] # computed gate position offset indexed by gate index
        self._marker_pos = [] # computed marker positions

        self._readOnly = False
        self._range_width = 0 # range width, pixels
        self._range_left = 0 # left range start position, pixel
        self._range_right = 0 # right range start position, pixel
        self._marker_size = 16 # size of the marker icons in pixels

        self._range_gate_left = 0 # position of the first gate in pixels
        self._range_gate_right = 0 # position of the last gate in pixels
        self._range_gate_width = 0 # width of the bar between min gate and max gate in pixels
        self._range_gate_height = 0 # height of the gate range bar
        self._range_gate_top = 0 # top offset for the gate range bar

        
        #self.sizePolicy().setHorizontalPolicy(QtWidgets.QSizePolicy.Expanding)

        self.setSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding,
            QtWidgets.QSizePolicy.Fixed
        )

        self._pixmaps = [] # list of pixmap data marker definition objects

        self.adjustSize()

        self._update_pixmaps()
        self._update_targets()
        self.setMarkerValue(0)
        
    def sizeHint(self):
        return QtCore.QSize(400,32)
    
    @property
    def values(self) -> list:
        return self._values
    
    @values.setter
    def values(self, value : int | float | list | tuple):
        self.setValue(value)
        
    def setValue(self, value : int | float | list | tuple):
        ''' input values expected to be -1 to +1 floating point '''
        values = None
        if isinstance(value, float): 
            values = [value]
        elif isinstance(value, int):
            values = [float(value)]
        elif isinstance(value, list):
            values = value
        elif isinstance(value, tuple):
            values = list(value)
        if values:
            values.sort() # sort by value so the values are always in smallest to greatest
            self._values = values # [max(min(1.0, n), -1.0) for n in values]
            self._update_offsets()
            self.update()

    def value(self) -> list:
        ''' gets the list of values in the slider - a single value is returned as a list of one'''
        return self._values

    @property
    def marker_size(self):
        return self._marker_size
    
    @marker_size.setter
    def marker_size(self, value):
        if value > 0:
            self.marker_size = value
            self._update_pixmaps()
            self._update_marker_offsets()
            self.update()

    def setReadonly(self, value : bool):
        self._readOnly = value
    
    def isReadonly(self) -> bool:
        return self._readOnly
    
        

    def _update_offsets(self):
        ''' recomputes pixel offsets based on gate values '''
        size = self.size()
        widget_width = size.width()
        widget_height = size.height()
        usable_width = int(widget_width * 0.9)

        gate_positions = []

        if len(self._values) == 0:
            return
        

        # compute the max range geometry boundaries (horizontal only)
        self._range_width = usable_width
        self._range_margin = (widget_width - usable_width) // 2
        self._range_left = self._range_margin
        self._range_right = widget_width - self._range_margin
        self._range_gate_height = widget_height * 0.5
        self._range_gate_top = (widget_height - self._range_gate_height) // 2

        print (f"Range width: {self._range_width} range left: {self._range_left} range right: {self._range_right}  range width: {self._range_width}  widget width: {widget_width}  height {widget_height}")

        for value in self._values:
            x = gremlin.util.scale_to_range(value, target_min = self._range_left, target_max = self._range_right)
            gate_positions.append(x)
            print(f"Gate offset: {x}")

        # leftmost position of the first gate
        if len(gate_positions) == 1:
            # single gate - use the whole range
            self._range_gate_left = self._range_left
            self._range_gate_right = self._range_right
        else:
            # two or more gates 
            self._range_gate_left = gate_positions[0]
            self._range_gate_right = gate_positions[-1]
        self._range_gate_width = self._range_gate_right - self._range_gate_left
        self._gate_positions = gate_positions
        print (f"Gate left: {self._range_gate_left}  right: {self._range_gate_right}  width: {self._range_gate_width} height: {self._range_gate_height} top margin: {self._range_gate_top}")
        



        self._update_marker_offsets()

    def _update_marker_offsets(self):

        # compute marker positions
        source_min = self._minimum
        source_max = self._maximum
        target_min = self._range_left # self._to_qinteger_space(self._range_left)
        target_max = self._range_right # self._to_qinteger_space(self._range_right)
        self._int_marker_pos = [((v - source_min) * (target_max - target_min)) / (source_max - source_min) + target_min for v in self._marker_pos]
        print (f"marker: {[v for v in self._int_marker_pos]}")
        

    def _update_targets(self):
        ''' update target positions '''
        self._target_min = self._minimum # self._to_qinteger_space(self._minimum)
        self._target_max = self._maximum # self._to_qinteger_space(self._maximum)

    # def _to_qinteger_space(self, val, _max=None):
    #     """Converts a value to the internal integer space."""
        
    #     _max = _max or self.MAX_DISPLAY
    #     range_ = self._maximum - self._minimum
    #     if range_ == 0:
    #         return self._minimum
    #     return int(min(self.QOVERFLOW, val / range_ * _max))        


    def setMarkerValue(self, value):
        ''' sets the marker(s) value - single float is one marker, passing a tuple creates multiple markers'''
        if isinstance(value, float) or isinstance(value, int):
            list_value = [value]
        else:
            list_value = value
        self._marker_pos = list_value

        # update geometry + repaint
        self._update_offsets() 
        self.update()

    def minimum(self) -> float:  # type: ignore
        ''' gets the slider's minimum value '''
        return self._minimum

    def setMinimum(self, value: float) -> None:
        ''' sets the slider's minimum value '''
        self._minimum = value
        if self._maximum < self._minimum:
            self._maximum, self._minimum = self._minimum, self._maximum
        self._update_targets()
        self._update_offsets()

    def maximum(self) -> float:  # type: ignore
        ''' gets the slider's maximum value '''
        return self._maximum

    def setMaximum(self, value: float) -> None:
        ''' sets the slider's maximum value '''
        self._maximum = value
        if self._maximum < self._minimum:
            self._maximum, self._minimum = self._minimum, self._maximum
        self._update_targets()
        self._update_offsets()

    def setRange(self, range_min : float, range_max : float):
        ''' sets the slider's min/max values
        
        :param range_min: min range (float)
        :param range_max: max range (float)
        
        '''
        if range_min > range_max:
            # swap
            range_max, range_min = range_min, range_max
        self._minimum = range_min
        self._maximum = range_max
        self._update_targets()
        self._update_offsets()


    def paintEvent(self, event : QPaintEvent):
        ''' paint event
                
        :param event: QPaintEvent object
        
        '''
        # draw the widget
        # https://github.com/KhamisiKibet/QT-PyQt-PySide-Custom-Widgets/blob/main/Custom_Widgets/QFlowProgressBar.py

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        self._draw_widget(painter)
        self._draw_markers(painter)

    def getBackgroundColor(self) -> QColor:
        """
        Get the background color of the progress bar.

        :return: QColor object representing the background color.
        """
        return self.unfinishedBackgroundColor       

    def getFinishedBackgroundColor(self) -> QColor:
        """
        Get the color for finished progress bar segments.

        :return: QColor object representing the finished segment color.
        """
        return self.finishedBackgroundColor

    def getFinishedNumberColor(self) -> QColor:
        """
        Get the color for finished numbers in the progress bar.

        :return: QColor object representing the finished number color.
        """
        return self.finishedNumberColor
         


    def _draw_widget(self, painter: QPainter):
        """
        Draw the progress bar with Circular or Square style.

        :param painter: QPainter object.
        """
        gate_count = len(self._gate_positions)
        sliderBarLength = self.size().width()
        sliderBarHeight = int(self.size().height() * 0.5)
        totalRangeLength = int(sliderBarLength * 0.88)
        iconSize = int((totalRangeLength / (gate_count - 1)) * 0.15)
        iconStep = totalRangeLength // (gate_count - 1)
        iconStartY = 0



        iconBorderPen = QPen(QBrush(self.getBackgroundColor()), iconSize * 0.1)
        whiteBrush = QBrush(Qt.white)
        
        maxIconSize = int(self.size().height() * 2 / 3)
        iconSize = min(iconSize, maxIconSize)
        
        startX = 0 # self._to_qinteger_space(0)
        startY = (iconSize / 2) - (sliderBarHeight / 2)

        backgroundBrush = QBrush(self.getBackgroundColor())
        finishedBrush = QBrush(self.getFinishedBackgroundColor())
        emptyPen = QPen(Qt.NoPen)

        # slider background
        painter.setPen(emptyPen)
        painter.setBrush(backgroundBrush)
        painter.drawRoundedRect(startX, startY, sliderBarLength, sliderBarHeight,
                                 sliderBarHeight, sliderBarHeight)

        # slider range
        startX = self._range_gate_left #  self._to_qinteger_space(self._range_left)
        painter.setBrush(finishedBrush)
        painter.drawRoundedRect(startX, startY, self._range_gate_width, self._range_gate_height,
                                 self._range_gate_height, self._range_gate_height)

        painter.save()
        painter.translate(startX + sliderBarLength * 0.05, iconStartY)

        # draw gates
        for i in range(gate_count):
            painter.setBrush(whiteBrush)

            currentXOffset = self._gate_positions[i]
            painter.setPen(iconBorderPen)

            # Store the bounding rectangle of each gate
            iconRect = QRect(currentXOffset, 1, iconSize, iconSize)
            clickableRect = QRect(currentXOffset + (iconStep - iconSize) // 2 - (iconSize/2), 1, iconSize, iconSize)
            self._gate_rects.append(clickableRect)

            #if self.barStyle == self.Styles.Circular:
            painter.drawEllipse(iconRect)
            # else:
            #     painter.drawRect(iconRect)

        painter.restore()

    def _draw_markers(self, painter: QPainter):
        ''' draws the markers on the widget '''
        positions = self._int_marker_pos
        center = self.height() / 2
        
        pixmaps = self._get_pixmaps()
        p_count = len(pixmaps)
        for index, value in enumerate(positions):
            if index < p_count:
                pd = pixmaps[index]
                painter.drawPixmap(value + pd.offset_x, center + pd.offset_y, pd.pixmap)
    
    def resizeEvent(self, event):
        ''' called on resize '''
        super().resizeEvent(event)
        self._update_offsets()
        
        self.adjustSize()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        ''' mouse press event handler 
        :param event: QMouseEvent object.

        '''
        if self._readOnly:
            # don't fire events in readonly mode
            return 
        point = event.pos()
        for index, rect in enumerate(self._gate_rects):
            if rect.contains(point):
                # gate clicked
                self._drag_active = True
                self._drag_gate_index = index
                self.setMouseTracking(True) # track mouse movements

    def mouseMoveEvent(self, event : QMouseEvent):
        if event.buttons() == QtCore.Qt.LeftButton:
            # left mouse drag operation
            if self._drag_active:
                point = event.pos()
                width = self._range_width()




                

    def mouseReleaseEvent(self, event: QMouseEvent):
        """
        Mouse release event handler.

        :param event: QMouseEvent object.
        """
        if self._readOnly:
            # don't fire events in readonly mode
            return 
        if self._drag_active:
            # stop drag
            self._drag_active = False
            self._drag_gate_index = None
            self.setMouseTracking(False)
            return
        
        self._drag_gate_index = index
        point = event.pos()
        # print("Mouse click coordinates:", point)  # Debug print
        for index, rect in enumerate(self._gate_rects):
            if rect.contains(point):
                # print("Step", index + 1, "clicked")  # Debug print
                #self.changeCurrentStep(index + 1)
                button = event.button()
                if button == Qt.MouseButton.LeftButton:
                    self.handleLeftClicked.emit(index)
                elif button == Qt.MouseButton.RightButton:
                    self.handleRightClicked.emit(index)
                break


    class PixmapData():
        ''' holds a pixmap definition '''
        def __init__(self, pixmap : QtGui.QPixmap = None, offset_x = None, offset_y = None):
            self.pixmap = pixmap
            self.offset_x = offset_x
            self.offset_y = offset_y
            if pixmap is not None:
                self.width = pixmap.width()
                self.height = pixmap.height()
            else:
                self.width = 0
                self.height = 0



        # self.setStyleSheet(self.css)

    def _get_pixmaps(self):
        if self._pixmaps: return self._pixmaps
        return self._internal_pixmaps
    
    def _update_pixmaps(self):
        icon = gremlin.util.load_icon("ei.chevron-up")
        pixmap = icon.pixmap(self.marker_size)
        center = self.height() / 2
        if pixmap.height() > center:
            pixmap = pixmap.scaledToHeight(center)
        pd = QSliderWidget.PixmapData(pixmap = pixmap, offset_x = -pixmap.width()/2, offset_y=0)
        self._internal_pixmaps = [pd]