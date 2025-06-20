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


from collections.abc import MutableSequence
from abc import abstractmethod, ABCMeta
from PySide6 import QtCore

import gremlin.shared_state




class TraceableList(MutableSequence):
    ''' implements a custom list that can be traced when it changes  '''

    def __init__(self, initlist=None, callback = None):
        MutableSequence.__init__(self)
        
        self.data = []
        self._callbacks = []
        if callback:
            self._callbacks.append(callback)
        if initlist is not None:
            if isinstance(initlist, list):
                self.data[:] = initlist

            elif isinstance(initlist, TraceableList):
                self.data[:] = initlist.data[:]

            else:
                self.data = list(initlist)

    def add_callback(self, value):
        ''' adds a callback - signature (action: str, index: int, value [optional object])'''
        if not value in self._callbacks:
            self._callbacks.append(value)

    def remove_callback(self, value):
        ''' removes a callback '''
        if value in self._callbacks:
            self._callbacks.remove(value)

    def clear_callbacks(self):
        ''' removes all callbacks '''
        self._callbacks.clear()

    def _trigger(self, action, index = None, value = None):
        for callback in self._callbacks:
            callback(self, action, index, value)


    def __repr__(self):
        return """<{} data: {}>""".format(self.__class__.__name__, repr(self.data))

    def __lt__(self, other):
        return self.data < self.__cast(other)

    def __le__(self, other):
        return self.data <= self.__cast(other)

    def __eq__(self, other):
        return self.data == self.__cast(other)

    def __gt__(self, other):
        return self.data > self.__cast(other)

    def __ge__(self, other):
        return self.data >= self.__cast(other)

    def __cast(self, other):
        return other.data if isinstance(other, TraceableList) else other

    def __contains__(self, value):
        return value in self.data

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            return self.__class__(self.data[idx])
        return self.data[idx]
        
    def __iter__(self):
        return self.data.__iter__()
    
    def __next__(self):
        return self.data.__next__()

    def __setitem__(self, idx, value):
        # optional: self._acl_check(val)
        self.data[idx] = value
        self._trigger("setitem", idx, value)

    def __delitem__(self, idx):
        self._trigger("delitem", idx)
        del self.data[idx]

    def __add__(self, other):
        if isinstance(other, TraceableList):
            return self.__class__(self.data + other.data)

        elif isinstance(other, type(self.data)):
            return self.__class__(self.data + other)

        return self.__class__(self.data + list(other))

    def __radd__(self, other):
        if isinstance(other, TraceableList):
            return self.__class__(other.data + self.data)

        elif isinstance(other, type(self.data)):
            return self.__class__(other + self.data)

        return self.__class__(list(other) + self.data)

    def __iadd__(self, other):
        if isinstance(other, TraceableList):
            self.data += other.data

        elif isinstance(other, type(self.data)):
            self.data += other

        else:
            self.data += list(other)

        return self

    def __mul__(self, nn):
        return self.__class__(self.data * nn)

    __rmul__ = __mul__

    def __imul__(self, nn):
        self.data *= nn
        return self

    def __copy__(self):
        inst = self.__class__.__new__(self.__class__)
        inst.__dict__.update(self.__dict__)

        # Create a copy and avoid triggering descriptors
        inst.__dict__["data"] = self.__dict__["data"][:]

        return inst

    def append(self, value):
        self.data.append(value)
        if self._callbacks:
            self._trigger("append",value)
        

    def insert(self, idx, value):
        if self._callbacks:
            self._trigger("insert",value)
        self.data.insert(idx, value)

    def pop(self, idx=-1):
        if self._callbacks:
            self._trigger("pop",idx)
        return self.data.pop(idx)

    def remove(self, value):
        self.data.remove(value)

    def clear(self):
        if self._callbacks:
            self._trigger("clear")
        self.data.clear()

    def copy(self):
        if self._callbacks:
            self._trigger("copy")
        return self.__class__(self)

    def count(self, value):
        return self.data.count(value)

    def index(self, idx, *args):
        return self.data.index(idx, *args)

    def reverse(self):
        self.data.reverse()

    def sort(self, /, *args, **kwds):
        self.data.sort(*args, **kwds)

    def extend(self, other):
        data = other.data if isinstance(other, TraceableList) else other
        self.data.extend(data)
        self._trigger("extend", value = data)

    def to_list(self):
        return self.data
    
def empty_copy(obj):
    class Empty(obj.__class__):
        def __init__(self): pass
    newcopy = Empty(  )
    newcopy.__class__ = obj.__class__
    return newcopy      

class ABCMetaQObject(ABCMeta, type(QtCore.QObject)):
    pass


class AbstractInputItem(QtCore.QObject, metaclass=ABCMetaQObject):
    ''' base class for input items for MIDI, OSC, KEYBOARD and STATE items '''

    def __init__(self):
        
        super().__init__()
        import uuid
        self._id =  uuid.uuid4() # GUID (unique) if loaded from XML - will reload that one
        self._guid = str(self.id).replace("-","")
        self._display_name = None
        self._description = None
        self._input_description = None
        self._axis_value = None
        self._button_value = False # true if the equivalent of "pressed"

    @property
    def guid(self):
        ''' id in string format '''
        return self._guid
    
    @property
    def id(self):
        return self._id
    
    @id.setter
    def id(self, value):
        self._id = value
        self._guid = str(value).replace("-","")

    @property
    def display_name(self):
        ''' display name for this input '''
        return self._display_name
    
    def setDisplayName(self, value : str):
        self._display_name = value
    
    @property
    def description(self) -> str:
        return self._description
    
    @description.setter
    def description(self, value) -> str:
        self._description = value
    
    def setDescription(self, value : str):
        self._description = value
    

    @property
    def input_description(self) -> str:
        return self._input_description
    
    def setInputDescription(self, value : str):
        self._input_description = value

            
    @property
    def axis_value(self) -> float:
        ''' gets the current axis value '''
        return self.getAxisValue()
    
    def getAxisValue(self):
        if self._axis_value is None:
            return 0.0
        return self._axis_value
    
    def setAxisValue(self, value : float):
        ''' sets the axis value and triggers a joystick input event 
        
        :param value: the floating point value to set (-1 to +1)
        :param emit: flag to trigger a joystick event if the value is set
        
        '''
        if self.axis_value is None or value != self._axis_value:
            self._axis_value = value


    def getOverrideInputType(self):
        # override input type            
        return None

    @property
    def button_value(self) -> bool:
        return self._button_value
    
    def setButtonValue(self, value: bool):
        self._button_value = value


    @property
    def message_key(self):
        assert False,"message_key property must be implemented by subclasses"

    @abstractmethod
    def to_xml(self):
        ''' must implement '''
        pass

    @abstractmethod
    def parse_xml(self):
        ''' must implement '''
        pass

    def __getstate__(self):
        ''' manual pickle to XML '''
        return self.to_xml()
    
    def __setstate__(self, data):
        ''' manual unpickle '''
        self.parse_xml(data)


class SpecialInputItem(AbstractInputItem):
    ''' specialized input item '''
    def __init__(self, name):
        super().__init__()
        self._display_name = name
        self._description = "Special Virtual Input"

    @property
    def message_key(self):
        return self.display_name
    
    def __str__(self):
        return "special"
    

pickle_targets = {}

class PickleTarget():
    ''' helper class to pickle objects that don't want to be pickled
     
    The way this works is we store the object to pickle in a local cache, give it a unique ID, and use that as the pickled value because the ID does pickle.
    When the object is unpickled, we retrieve the object from the cache, remove it from the cache and return the original.

    Pickling is automatic and occurs when cloning objects for example.

    '''

    def __init__(self, item):
        self._item = item

    def __getstate__(self):
        ''' pickle '''
        from gremlin.util import get_guid
        id = get_guid()
        pickle_targets[id] = self.item
        self.id = id
        #print (f"pickled to id: {id}")
        return self.id
    
    def __setstate__(self, id):
        ''' unpickle '''
        #print (f"pickled from id: {id}")
        if id in pickle_targets:
            #print ("target found")
            self.item = pickle_targets[id]
            del pickle_targets[id]
        return self
    
    @property
    def item(self):
        return self._item
    
    @item.setter
    def item(self, value):
        self._item = value


from gremlin.input_types import InputType
import gremlin.joystick_handling
import gremlin.event_handler
            
class JoystickHook:
    ''' base class for hooking joysticks 
    
        provides update hooks for axis inputs using the hookDevice() and unhookDevice()
        inputs are suspended while a profile is running

        when hooked, the current device value is read and updated via the callback
    
    '''

    def __init__(self):
        ''' 
        
        :param callback: the callback, signature (float) - passes the axis or button value back
        :param device_guid: optional, id of the device to hook - if not set, use hookDevice() later
        :param input_type: optional, input type of the device
        :param input_id: optional, input id (usually a number)
        
        '''
        self._hooked = False
        self._hook_connected = False
        self._hook_enabled = True # hook updates by default
        self._hook_value = 0.0 # current value
        self._hook_calibrated_value = 0.0 # current calibrated value
        el = gremlin.event_handler.EventListener()
        el.ui_ready.connect(self._hook_ui_ready)
        self._input_id = None
        self._device_guid = None
        self._input_type = None
        self._calibrate = True # calibrate the data by default, false = do not apply calibration


    


    @property
    def input_id(self) -> object:
        return self._input_id
    @property
    def device_guid(self) -> str:
        return self._device_guid
    @property
    def input_type(self) -> InputType:
        return self._input_type

    def getEnabled(self) -> bool:
        return self._hook_enabled
    
    def setEnabled(self, value: bool):
        if value != self._hook_enabled:
            self._hook_enabled = value
            if value:
                self._hook_enable()
            else:
                self._hook_disable()

    def getCalibrated(self)-> bool:
        ''' gets the calibration flag '''
        return self._calibrate
    def setCalibrated(self, value: bool):
        if self._calibrate != value:
            self._calibrate = value
            self._hook_update_value()
        
    def _cleanup_ui(self):
        ''' item is being deleted '''
        self.unhookDevice()

    def getValue(self) -> float:
        return self._hook_value
    def getCalibratedValue(self) -> float:
        return self._hook_calibrated_value
    

    @QtCore.Slot()
    def _hook_ui_ready(self):
        ''' called when UI is ready '''
        el = gremlin.event_handler.EventListener()
        el.ui_ready.disconnect(self._hook_ui_ready)
        self._hook_profile_stop() # enable hook  

    @QtCore.Slot()
    def _hook_profile_start(self):
        # de-attach when profile stops
        self._hook_disable()
            
    def _hook_disable(self):
        if self._hooked and self._hook_connected:
            el = gremlin.event_handler.EventListener()
            el.joystick_event.disconnect(self._hook_joystick_event)
            self._hook_connected = False
    
    @QtCore.Slot()
    def _hook_profile_stop(self):
        # re-attach when profile stops
        self._hook_enable()

    def _hook_enable(self):
        # re-attach when profile stops
        if self._hooked and not self._hook_connected:
            el = gremlin.event_handler.EventListener()
            el.joystick_event.connect(self._hook_joystick_event)
            self._hook_connected = True
            self._hook_update_value()

    @QtCore.Slot(object)
    def _hook_joystick_event(self, event):
        if self._callback:
            if not event.is_axis:
                return 
            if self._device_guid != event.device_guid:
                return
            if self._input_type != event.event_type:
                return
            if self._input_id != event.identifier:
                return
            

            self._hook_value = event.value
            should_process = True
            
            if self._calibrate:
                # get calibrated value
                calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self._device_guid, self._input_id)
                value, should_process = calibration.getValue(event.value, normalize = False, filter = True) # input is already normalized
                self._hook_calibrated_value = value
            else:
                self._hook_calibrated_value = self._hook_value

            if should_process:
                self._callback(self._hook_value, self._hook_calibrated_value)
            


    def unhookDevice(self):
        ''' unhooks the device '''
        
        if self._hooked:
            el = gremlin.event_handler.EventListener()
            el.profile_start.disconnect(self._hook_profile_start)
            el.profile_stop.disconnect(self._hook_profile_stop)
            if self._hook_connected:
                
                el.joystick_event.disconnect(self._hook_joystick_event)
                self._hook_connected = False
            self._hooked = False

    def hookDevice(self, device_guid, input_type, input_id):
        assert False,"Abstract method must be implemented by derived class"


    def _hookDevice(self, device_guid, input_type, input_id, callback):
        ''' 
        Hooks the device
        :param device_guid: id of the device to hook
        :param input_type: input type of the device
        :param input_id: input id (usually a number)
        :param callback: the callback, signature (float) - passes the axis or button value back
        '''


        if self._hooked:
            self.unhookDevice()
        
        assert device_guid is not None,"Device GUID must be specified"

        self._callback = callback
        self._device_guid = device_guid
        self._input_id = input_id
        self._input_type = input_type
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._hook_profile_start)
        el.profile_stop.connect(self._hook_profile_stop)

        if gremlin.shared_state.ui_ready:
            # only hook after UI is loaded to prevent updates while UI is not setup yet
            el.joystick_event.connect(self._hook_joystick_event)
            self._hook_connected = True
        
        self._hook_value = self._hook_update_value() # grab current value
        self._hooked = True

        # calibration data
        calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self._device_guid, self._input_id)
        self._calibrate = calibration.hasData

    def setHookCallback(self, callback):
        ''' updates the callback on value change '''
        self._callback = callback
        if callback:
            # update the current value
            callback(self._hook_value) 

    def getHookCallback(self):
        ''' gets the callback used for value change'''
        return self._callback
        

    def _hook_update_value(self):
        if self._hooked:
            self._is_hardware_input = gremlin.joystick_handling.is_hardware_device(self.device_guid)
            if self._input_type in (InputType.OpenSoundControl, InputType.Midi):
                self._hook_value = self.input_id.axis_value
            elif self._is_hardware_input:
                self._hook_value = gremlin.joystick_handling.get_axis(self.device_guid, self.input_id)
            
            if self._calibrate:
                # apply calibration
                calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self._device_guid, self._input_id)
                self._hook_value = calibration.getValue(self._hook_value)

            if self._callback:
                self._callback(self._hook_value, self._hook_calibrated_value)

class BaseCallbacks(QtCore.QObject):
    ''' base class implementing callback functionality'''

    def __init__(self):
        super().__init__()
        self._callbacks = []

    def registerCallback(self, callback):
        if not callback in self._callbacks:
            self._callbacks.append(callback)

    def unregisterCallback(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def clearCallbacks(self):
        self._callbacks.clear()

    def DoCallbacks(self):
        ''' runs the callbacks '''
        for callback in self._callbacks:
            callback(self)                