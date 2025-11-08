

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
import logging
import fnmatch
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import QModelIndex
import threading
import gremlin.config
import gremlin.event_handler
from gremlin.types import DeviceType
from gremlin.input_types import InputType
import gremlin.shared_state
from gremlin.keyboard import Key
import gremlin.ui.joystick_device
import uuid
from gremlin.singleton_decorator import SingletonDecorator
import collections
import logging
import re
import time
import logging
from typing import Any, Iterator, List, Union
import gremlin.ui.input_item
import os
import gremlin.ui.input_item
import gremlin.ui.ui_common
import gremlin.ui.ui_common
import gremlin.ui.ui_common
import gremlin.ui.ui_common
from gremlin.util import *
from lxml import etree as ElementTree
import enum
import gremlin.util
import gremlin.base_profile
from gremlin.base_classes import AbstractInputItem
import psygnal
from psygnal import Signal

class StateCategory():
    ''' holds a state category '''
    def __init__(self, name : str, id = None):
        assert id is None or isinstance(id, str)
        self._id = gremlin.util.get_guid() if id is None  else id
        self._name = name.casefold().strip() if name else None


    @property
    def name(self) -> str:
        return self._name
    
    @name.setter
    def name(self, value : str):
        if value:
            value = value.casefold().strip()
        if self._name != value:
            self._name = value

            # tell UI of category name change
            el = gremlin.event_handler.EventListener()
            el.state_category_name_change.emit(self)


    @property
    def key(self) -> str:
        if self._name:
            return self._name.casefold().strip()
        return None

    @property
    def id(self) -> str:
        return self._id
    
    @id.setter
    def id(self, value : str):
        assert value and isinstance(value, str), "Invalid value for ID"
        self._id = value

    def text(self) -> str:
        return self._name

    def __eq__(self, value):
        if value is None: return False
        if isinstance(value, str):
            return self._id == value
        elif isinstance(value, StateCategory):
            return self._id == value.id
        return False

    def __hash__(self):
        # make the data unique based on the ID only 
        return hash(self._id)
    
@SingletonDecorator
class CategoryValidator(QtGui.QValidator):
    ''' validator for category selection '''
    def __init__(self):
        super().__init__()
        self._category_names = None
        self._cm = None
        self._cm = StateCategories()
        self._cm.changed.connect(self._update_categories)
        

    def _update_categories(self):
        if self._cm:
            self._category_names = self._cm.getCategoryNames()

        
        
    def validate(self, value, pos):
        if not self._category_names:
            self._update_categories()

        if not self._category_names:
            return QtGui.QValidator.State.Invalid    

        clean_value = value.casefold().strip() if value else None
        if not clean_value or clean_value in self._category_names:
            # blank is ok
            return QtGui.QValidator.State.Acceptable
        # match all values starting with the text given
        try:
            r = re.compile(clean_value + "*")
            for _ in filter(r.match, self._category_names):
                return QtGui.QValidator.State.Intermediate
        except:
            # invalid regex - probably a special char
            pass
        return QtGui.QValidator.State.Invalid

@SingletonDecorator
class StateCategories(QtCore.QObject):
    ''' state categories '''

    changed = Signal() # fires when the list of categories changes

    _default_category_id = "5e54b523700c4a5996bfea85ce1ea75e"
    _default_category = StateCategory("default", _default_category_id)

    def __init__(self):
        super().__init__()
        self.clear()

    def clear(self):
        ''' clears all categories '''
        self._categories = {}
        self._ensure_categories()
        


    def default(self) -> StateCategory:
        ''' returns the default category (hard coded) - states with no categories use this '''
        return self._default_category
        

    def addCategory(self, name : str) -> StateCategory:
        ''' adds a category '''
        if name:
            key = name.casefold().strip()
            if not key in self._categories:
                category = StateCategory(key)
                self._categories[key] = category
                el = gremlin.event_handler.EventListener()
                el.state_category_add.emit(category)
                return category
            
        return None

    def removeCategory(self, category):
        ''' removes a category if it exists '''
        if category:
            if category != self._default_category:
                # only delete if not the default category
                if category.key in self._categories:
                    del self._categories[category.key]
                    el = gremlin.event_handler.EventListener()
                    el.state_category_delete.emit(category)

    def removeCategoryName(self, name : str):
        ''' removes a category by name if it exists '''
        if name:
            key = name.casefold().strip()
            if key in self._categories:
                category = self._categories[key]
                self.removeCategory(category)


        

    def renameCategory(self, old_name : str, new_name :str):
        ''' renames a category '''
        if old_name and new_name:
            n1 = old_name.casefold().strip()
            n2 = new_name.casefold().strip()
            if n1 != n2 and n1 in self._categories:
                category = self._categories[n1]
                if category != self._default_category:
                    category.name = n2
                    el = gremlin.event_handler.EventListener()
                    el.state_category_name_change.emit(category)
            


    def _ensure_categories(self):
        ''' adds the default category if missing '''
        self._categories[self._default_category.name] = self._default_category

    def from_xml(self, root : ElementTree.Element, data = None, extra_data = None):
        ''' reads the category '''
        self._categories = {}
        if root.tag == "categories":
            for node in root:
                if node.tag == "category":
                    name = safe_read(node, "name", str, '')
                    id = safe_read(node, "id", str, '')
                    category = StateCategory(name, id)
                    self._categories[name] = category

        self._ensure_categories()
        self.changed.emit()

    def to_xml(self) -> ElementTree.Element:
        ''' writes the category node'''
        root = ElementTree.Element("categories")
        for category in self._categories.values():
            if category.name:
                node = ElementTree.SubElement(root, "category", name = category.name, id = category.id)
        
        return root
    
    def is_category(self, name: str):
        ''' true if the name is a valid category name '''
        return self.findByName(name) is not None


    def findById(self, id : str, default = None) -> StateCategory:
        ''' finds a category by ID'''
        category = next((cat for cat in self._categories.values() if cat.id == id), None)
        if not category:
            category = default
        return category
    
    def findByName(self, name : str, default = None) -> StateCategory:
        ''' finds a category by name '''
        category = default
        if name:
            name = name.casefold().strip()
            category = next((cat for cat in self._categories.values() if cat.name == name), None)

        if not category:
            category = default
        
        return category
        



    def getCategoryNames(self) -> list:
        ''' gets the list of categories '''
        return [name for name in self._categories]

    def _sort(self):
        ''' sorts the category list '''
        if self._categories:

            keys = list((key for key in self._categories))
            keys.sort()
            new_map = {}
            for key in keys:
                new_map[key] = self._categories[key]

            self._categories = new_map
            self.changed.emit()
    
    def getCategories(self):
        ''' gets all category items '''
        return self._categories
    
    def setCategories(self, categories : list):
        ''' updates the list of category objects - fires appropriate events on changes '''
        id_map = {}
        for category in self._categories.values():
            id_map[category.id] = category
        for category in categories:
            id = category.id
            if id in id_map:
                # look for name changes
                existing_category = id_map[id]
                if category.name != existing_category.name:
                    self.renameCategory(existing_category.name, category.name)
            else:
                self._categories[id] = category
        
        # get list of remove categories
        removed_list = [c for c in self._categories.values() if not c in categories]
        for category in removed_list:
            self.removeCategory(category)

        self._sort()



    def getSelector(self, changed_callback = None, default_category : StateCategory = None, editable = False) -> gremlin.ui.ui_common.QDataComboBox:
        ''' gets a selector combo box for categories '''
        widget = gremlin.ui.ui_common.QDataComboBox()
        widget.setEditable(editable)
        widget.setValidator(CategoryValidator())

        index = 0
        select_index = None
        default_id = default_category.id if default_category else None
        categories = []

        categories = [c for c in self._categories.values()]
        categories.sort(key = lambda x:x.name)
        for category in categories:
            key = category.key
            widget.addItem(category.name, category)
            if select_index is None and default_id and default_id == category.id:
                select_index = index
            index +=1 
            

        # if default_category:
        #     key = default_category.key
        #     if not key in categories:
        #         widget.addItem(default_category.name, default_category)
        #         if select_index is None and default_id and default_id == category.id:
        #             select_index = index
        #         index +=1 

        widget.setMinimumWidth(200)
        if select_index is not None:
            widget.setCurrentIndex(select_index)
        if changed_callback:
            widget.currentIndexChanged.connect(changed_callback)
            
        return widget
    
    def updateSelector(self, widget):
        ''' refresh the selector with the updated data '''
        with QtCore.QSignalBlocker(widget):
            current = widget.currentData()
            widget.clear()
            widget.addItem(self._default_category.name, self._default_category)
            index = 0
            selected_index = None
            # add default category
            for category in self._categories.values():
                widget.addItem(category.name, category)
                if selected_index is None and current == category:
                    selected_index = index
                index +=1

            if selected_index is not None:
                widget.setCurrentIndex(selected_index)
                    


#class StateInputItem(AbstractInputItem):
class StateInputItem(gremlin.base_profile.InputItem):
    ''' holds a single state '''
    changed = Signal(object) # fires when a state changes (state)
    key_changed = Signal(object, str, str) # fires when the key (StateInputItem, old_name, new_name)
    category_changed = Signal(object) # fires when a category changes
    expression_changed = Signal(object) # fires when the expression changes (if the state is an expression state)

    MAX_STACK_SIZE = 100 # maximum number of expressions in a stack (circuit breaker to detect recursion)
    

    def __init__(self, key : str = None,
                 default_value = False,
                 description = None, 
                 is_expression = False, 
                 expression = None, 
                 category = None,
                 autorelease = False,
                 autorelease_delay = 1,
                 autorelease_mode = "toggle", 
                 autorelease_trigger_mode = "on"):
        master_mode = gremlin.shared_state.master_mode


        # get the mode object for this state input
        profile = gremlin.shared_state.current_profile
        device_modes = profile.get_device_modes(
                    gremlin.shared_state.state_tab_guid,
                    DeviceType.State,
                    DeviceType.to_string(DeviceType.State)
                )

        mode_object = device_modes.ensure_mode_exists(master_mode)

        super().__init__(parent = mode_object)
        self._id = gremlin.util.get_guid() # unique ID of this state
        self._key = key
        self._category = category # category (StateCategory)
        self._default_value = default_value
        self._last_value = None
        self._value = default_value
        self._type_cast = type(default_value) if default_value is not None else None
        self.setDescription(description) # parent property
        self._expression = expression # expression to evaluate to derive a state
        self._is_expression = is_expression
        self._expression_stack = [] # expression stack to evaluate
        self._expression_dependencies = [] # reference to state dependencies for expressions
        self._dirty = True # indicates the state is stale and must be recomputed (expressions only)
        self._expression_states = [] # dependent expression states - list of states that need to be evaluated when they change
        self._last_expression_value = False # last computed expression result

        self._autorelease = autorelease # true if autoreleases
        self._autorelease_delay = autorelease_delay # auto toggle timer in seconds
        self._autorelease_mode = autorelease_mode # autorelease behavior when the timer lapses
        self._autorelease_timer = None # timer when triggered for autorelease
        self._autorelease_trigger_mode = autorelease_trigger_mode # trigger mode required to enable the autorelease timer

        
        item = gremlin.base_profile.InputItem(parent = mode_object) #self._custom_name_handler)
        item.input_id = self
        item.input_type = InputType.State
        item.device_name = "State"
        item.device_type = DeviceType.State
        item.device_guid = gremlin.shared_state.state_tab_guid
        item.setOverrideInputType(InputType.JoystickButton)
        self._input_item = item
        self._emit = True # enable events
        self._hooked = False
        self.hook() # hook on creation

    def suppressEvents(self):
        ''' disable events '''
        self._emit = False

    def enableEvents(self):
        ''' enable events'''
        self._emit = True

    def clone(self):
        ''' clones the input item (gives it a new ID)'''

        return StateInputItem(self.key,
                              self.default_value, 
                              self.description, 
                              self.isExpression, 
                              self.expression, 
                              self.category,
                              self.autorelease,
                              self.autorelease_delay,
                              self.autorelease_mode,
                              self.autorelease_trigger_mode)
        
    
    def getOverrideInputType(self):
        ''' override type '''
        return InputType.JoystickButton
    
    def hook(self):
        ''' called when the state is being created - hooks into the event model'''
        if not self._hooked:
            sd = gremlin.ui.state_device.StateData()
            sd.key_changed.connect(self._change_state_name)
            self._hooked = True
            el = gremlin.event_handler.EventListener()
            #el.state_name_change.connect(self._state_name_change)
            el.state_category_delete.connect(self._state_category_delete)
            el.state_category_name_change.connect(self._state_category_name_change)
            el.profile_unloaded.connect(self._handle_profile_unload)
            verbose = gremlin.config.Configuration().verbose_mode_state
            if verbose: syslog.info(f"STATE: hook [{self._key}] id: [{self._id}]")

    def unhook(self):
        ''' called when the state should unhook itself because it is being discarded '''
        if self._hooked:
            sd = gremlin.ui.state_device.StateData()
            sd.key_changed.disconnect(self._change_state_name)
            # clear any dependencies
            for state in self._expression_dependencies:
                state.changed.disconnect(self._dependency_changed)
            self._expression_dependencies.clear()


            el = gremlin.event_handler.EventListener()
            #el.state_name_change.disconnect(self._state_name_change)
            el.state_category_delete.disconnect(self._state_category_delete)
            el.state_category_name_change.disconnect(self._state_category_name_change)
            el.profile_unloaded.disconnect(self._handle_profile_unload)
            self._hooked = False
            verbose = gremlin.config.Configuration().verbose_mode_state
            if verbose: syslog.info(f"STATE: unhook [{self._key}]  id: [{self._id}]")


    def _handle_profile_unload(self):
        ''' occurs on profile unload before a new profile is loaded  '''
        self.unhook()


    
    @property
    def id(self) -> str:
        return self._id
    @id.setter
    def id(self, value : str):
        self._id = value



    @property
    def category(self) -> StateCategory:
        ''' category for the state '''
        if not self._category:
            # use default category
            cm = StateCategories()
            self._category = cm.default()    
        return self._category
    
    def setCategory(self, category : StateCategory):
        if self._category != category:
            self._category = category
    
    @property
    def category_name(self) -> str:
        return self.category.name
    
    @property
    def category_id(self) -> str:
        return self.category.id
        
    @property
    def display_name(self):
        return self._key
    
    @property
    def display_value(self):
        if self.value:
            return "On (true/1)"
        return "Off (false/0)"
    
    @property
    def isExpression(self):
        return self._is_expression
    @isExpression.setter
    def isExpression(self, value : bool):
        self._is_expression = value


    @property
    def value(self) -> bool:
        ''' gets the state value '''
        value = self.evaluate()
        # return False on invalid state value
        return value if value is not None else False
    
    @value.setter
    def value(self, data : bool):
        self.setValue(data)
        
    def setValue(self, data : bool, force = False):
        if data is None or not isinstance(data, bool):
            syslog.warning(f"State setter: state: [{self.key}] id: [{self.id}] attempt to set invalid value [{data}]")
            return
        if self._autorelease_timer:
            self._autorelease_timer.cancel()
            self._autorelease_timer = None

        if force or not self._expression and self._value != data:
            # only set value on non expression states and only if the value has changed
            self._last_value = self._value
            self._value = data
            self._fire_changed(data)

            if self._autorelease and self._autorelease_delay > 0:
                trigger_mode = self._autorelease_trigger_mode
                trigger = False
                match trigger_mode:
                    case "any":
                        trigger = True
                    case "on":
                        trigger = data == True
                    case "off":
                        trigger = data == False
                if trigger:
                    self._autorelease_timer = threading.Timer(self._autorelease_delay, self._handle_autorelease)
                    self._autorelease_timer.start()

    def _handle_autorelease(self):
        ''' called when the auto release timer lapses '''
        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose:
            syslog.info(f"State: autorelease - mode {self._autorelease_mode}")
        match self._autorelease_mode:
            case "toggle":
                value = not self._value
            case "on":
                value = True
            case _:
                value = False
        self.setValue(value)

    @property
    def autorelease(self) -> bool:
        return self._autorelease
    @autorelease.setter
    def autorelease(self, value : bool):
        self._autorelease = value

    @property
    def autorelease_delay(self) -> float:
        return self._autorelease_delay
    @autorelease_delay.setter
    def autorelease_delay(self, value : float):
        if value >= 0:
            self._autorelease_delay = value

    @property
    def autorelease_mode(self) -> str:
        return self._autorelease_mode
    @autorelease_mode.setter
    def autorelease_mode(self, value : str):
        if value in ("toggle","on","off"):
            self._autorelease_mode = value

    @property
    def autorelease_trigger_mode(self) -> str:
        return self._autorelease_trigger_mode
    @autorelease_trigger_mode.setter
    def autorelease_trigger_mode(self, value : str):
        if value in ("any","on","off"):
            self._autorelease_trigger_mode = value
 

    @property
    def lastValue(self) -> bool | None:
        return self._last_value 

    def toggle(self):
        ''' toggles the state '''
        if not self._expression:
            # only toggle non-expression states
            self._value = not self._value
            if self._emit:
                self.changed.emit(self)
            return self._value
        return None

    @property
    def default_value(self):
        ''' default value for the state (set in the state definition)'''
        return self._default_value
    
    @default_value.setter
    def default_value(self, data):
        if self._default_value != data:
            self._default_value = data      
            if data != self._value:
                self._value = data  
                if self._emit:
                    self._fire_changed(data)

    @property
    def key(self)-> str:
        return self._key
    @key.setter
    def key(self, value : str):
        value = value.casefold().strip()
        if self._key != value:
            old_name = self._key
            self._key = value
            if self._emit:
                self.key_changed.emit(self, old_name, value)
                sd = StateData()
                sd.update_key(self, old_name, value)

    @property
    def input_id(self):
        ''' input id for this key '''
        return self._key            
    
    @property
    def type_cast(self):
        return self._type_cast
    
    @property
    def message_key(self):
        return self.key
    
    @property
    def expression(self) -> str:
        return self._expression
    @expression.setter
    def expression(self, value : str):
        if self._expression != value:
            self._expression = value
            self._dirty = True
            self._expression_stack = []
            derived_value = self.evaluate()
            if derived_value != self._value:
                self._value = derived_value
                if self._emit:
                    self.expression_changed.emit(self)
                    self._fire_changed(derived_value)

    def stateInExpression(self, state) -> bool:
        ''' true if the key is found in the expression '''
        if self._is_expression:
            if not self._expression_stack:
                self.evaluate()


            pass
        return False
    
    def _state_name_change(self, old_name, new_name, state):
        self._change_state_name(state, old_name, new_name)

    def _change_state_name(self, state, old_name, new_name):
        ''' called when a state name change happened '''
        if not self._is_expression or state == self:
            # ignore non expression states or self name changes
            return 

        # process the expression
        expression = self._expression

        stack = self._postfix(self.expression)
        if stack:
            # valid expression
            # replace all occurences in the expression
            new_stack = [new_name if item == old_name else item for item in stack]
            if stack != new_stack:
                # convert back to infix if changes were made
                expression = self._infix(new_stack)
                if expression:
                    self.expression = expression

                self.evaluate()
                if self._emit:
                    self.expression_changed.emit(self)
                    sd = StateData()
                    sd.expression_changed.emit(self, old_name, new_name)

    def _state_category_delete(self, category : StateCategory):
        ''' called when a category is deleted '''
        if self._category == category:
            cm = StateCategories()
            default_category = cm.default()
            self._category = default_category  # replace with default category
            if self._emit:
                self.category_changed.emit(self)

    def _state_category_name_change(self, category : StateCategory):
        ''' called when a category is changed '''
        if self._category == category:
            if self._emit:
                self.category_changed.emit(self)
    

    @property
    def input_item(self):
        ''' holds a reference to the mapping data for this input '''
        return self._input_item

    def to_xml(self) -> ElementTree.Element:
        ''' write XML state node '''
        node = ElementTree.Element("state", id = self._id, key = self._key)
        value = self._default_value
        description = self.description
        node.set("id", self._id)

        if description:
            node.set("description", description)
        if isinstance(value, str):
            node.set("value", value)
            node.set("type", "str")
        elif isinstance(value, float):
            node.set("value", safe_format(value, float))
            node.set("type", "float")
        elif isinstance(value, bool):
            node.set("value", safe_format(value, bool))
            node.set("type", "bool")
        else:
            # ignore other types
            return None
        
        if self._category:
            test = self._category.id
            node.set("category_id", self._category.id)
        
        if self._description:
            node.set("description", self._description)

        if self._expression:
            node.set("expression", self._expression)
        node.set("is_expression", safe_format(self._is_expression, bool))

        
        node.set("autorelease",safe_format(self._autorelease, bool))
        node.set("autorelease-delay", safe_format(self._autorelease_delay, float))
        node.set("autorelease-mode", safe_format(self._autorelease_mode, str))
        node.set("autorelease-trigger", safe_format(self._autorelease_trigger_mode, str))

        # write container data
        self._input_item.to_xml(node)
        

        return node
    
    def from_xml(self, node, data = None, extra_data = None):
        ''' read XML state node '''
        self._key = node.get("key")
        if "id" in node.attrib:
            self._id = node.get("id")
        node_type = node.get("type")
        
        description = None
        if "description" in node.attrib:
            description = node.get("description")
        
        self.setDescription(description)

        if "category_id" in node.attrib:
            cat_id = node.get("category_id")
            cm = StateCategories()
            category = cm.findById(cat_id)
            if category:
                self._category = category
            
        value = None

        if node_type == "str":
            value = safe_read(node, "value", str, '')
        elif node_type == "float":
            value = safe_read(node, "value", float, 0.0)
        elif node_type == "int":
            value = safe_read(node, "value", int, 0)
        elif node_type == "bool":
            value = safe_read(node, "value", bool, False)
        if "expression" in node.attrib:
            self._expression = node.get("expression")
            self._is_expression = True
        else:
            if "is_expression" in node.attrib:
                self._is_expression = safe_read(node,"is_expression",bool, False)
            else:
                # suitable default based on existing value
                self._is_expression = bool(self.expression)

        self.autorelease = safe_read(node,"autorelease", bool, False)
        self.autorelease_delay = safe_read(node,"autorelease-delay", float, 1.0)
        self.autorelease_mode = safe_read(node,"autorelease-mode", str, "toggle")
        self.autorelease_trigger_mode = safe_read(node,"autorelease-trigger", str, "on")


        self._default_value = value
        self._value = value
        self._input_item.from_xml(node, data, skip_root=True)


    def evaluate(self, as_tuple = False, force = False) -> bool | tuple:
        ''' evaluates the state 
        
            if the state is an expression, returns the expression result (False if the expression cannot be evaluated)
            If the state is not an expression, returns the current state value

        :param as_tuple: returns the value, error flag, error message if any
        :returns: boolean or tuple (value, error, error message)
        
        '''

       
        if not self._expression:
            # no expression defined, return the curent state value
            return (self._value, False, None) if as_tuple else self._value
        
        if not force and not self._dirty and self._last_expression_value is not None:
            # nothing changed since the expression was last evaluated - use the last value
            return (self._last_expression_value, False, None) if as_tuple else self._last_expression_value
        
        if not self._expression_stack:
            # not converted to postfix yet - get the precomputed evaluation stack
            self._last_expression_value = None
            if as_tuple:
                data = self._postfix(self._expression, as_tuple)
                self._expression_stack = data[0]
                if data[1]: 
                    # error condition
                    return (data, True, "Invalid Expression")
            else:
                self._expression_stack = self._postfix(self._expression)

        if self._expression_stack:
            # update the data 
            data = self._evaluate_stack(self._expression_stack, as_tuple)
            value = data[0] if as_tuple else data
            is_changed =  value != self._last_expression_value
            if is_changed:
                self._value = value
                self._last_expression_value = value
                verbose = gremlin.config.Configuration().verbose_mode_state
                if verbose: syslog.info(f"State: {self.key} new value: {self._last_expression_value}")
                self._fire_changed(value)

        
        return (self._last_expression_value, False, None) if as_tuple else self._last_expression_value
    
    def _fire_changed(self, value: bool):
        ''' called when a state changes '''
        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose: syslog.info(f"STATE CHANGE EMIT: [{self.key}] value: {self.value}")
        self.changed.emit(self)

        # if not gremlin.shared_state.is_running:
        #     return
        
        
        event = gremlin.event_handler.Event(
            event_type= InputType.State,
            device_guid= gremlin.shared_state.state_tab_guid,
            identifier= self,
            value = value,
            curved_value = None,
            raw_value= None,
            is_axis = False,
            is_virtual = True,
            is_pressed = value,
            override_input_type=InputType.JoystickButton # tell actions we're a button
        )
        eh = gremlin.event_handler.EventHandler()
        eh.execute_event(event)



    def _valid_states(self):
        # remove any state named like a boolean or self
        sc = StateData()
        reserved = ['and','or','not','xor', self.key]
        return [state for state in sc.getStateNames() if not state in reserved]


    def _is_operand(self, item):
        ''' true if the item is an operand (vs an operator)'''
        return not item in ['and','or','not','xor']

    def _infix(self, postfix_expression):
        ''' converts a postfix stack to an infix expression '''
        stack = []
    
        for item in postfix_expression:
            if self._is_operand(item):
                stack.append(item)
            else:  # It's an operator
                if len(stack) < 2:
                    syslog.error("Invalid postfix expression")
                    return None
                
                operand2 = stack.pop()
                operand1 = stack.pop()
                
                # Construct the new infix expression with parentheses
                new_infix = f"({operand1} {item} {operand2})"
                stack.append(new_infix)
                
        if len(stack) != 1:
            syslog.error("Invalid postfix expression")
            return None
            
        return stack.pop()


    def _postfix(self, expression, as_tuple = False) -> list | tuple:
        ''' converts the expression to a postfix stack for evaluation 
        
        :returns: list (stack) or tuple (stack, is_error, error_message)

        '''
        verbose = gremlin.config.Configuration().verbose_mode_state

        precedence = {'and': 2, 'or': 1, 'not': 3, 'xor': 1}
        output = []
        stack = []

        expression = expression.replace("("," ( ").replace(")"," ) ")
        expression = expression.strip().casefold()
        

        self._expression_states = []
        
        states = self._valid_states()

        sc = StateData()
        
        if not states:
            # nothing to evaluate if no states exist
            msg = "no valid states available for computation. Ensure the states are not using reserved names or self-reference"
            if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
            if as_tuple:
                return ([],True, msg)
            return []
 
        key = self.key
        tokens = expression.split()
        for token in tokens:
            if token in states:
                # state
                if not token in self._expression_states:
                    # add to the dependent state list
                    self._expression_states.append(token)
                output.append(token)
            elif token == '(':
                stack.append(token)
            elif token == ')':
                if not stack:
                    msg = f"grouping mismatch: [{key}]"
                    if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
                    if as_tuple:
                        return ([],True, msg)
                    return []    
                while stack and stack[-1] != '(':
                    output.append(stack.pop())
                if not stack:
                    msg = f"grouping mismatch: [{key}]"
                    if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
                    if as_tuple:
                        return ([],True, msg)
                    return []    
                stack.pop()
            elif token in precedence:
                while stack and stack[-1] != '(' and precedence[token] <= precedence.get(stack[-1], 0):
                    output.append(stack.pop())
                stack.append(token)
            else:
                # token is not known
                msg = f"Unknown item in expression: [{token}]"
                if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
                if as_tuple:
                    return ([],True, msg)
                return []    
            
        if len(stack) >= StateInputItem.MAX_STACK_SIZE:
            msg = f"Expression too complex"
            if verbose: syslog.error(f"STATE EXPRESSION: {msg}")
            if as_tuple:
                return ([],True, msg)
            return []    



        while stack:
            output.append(stack.pop())

        # clean hooks from any prior dependencies
        for state in self._expression_dependencies:
            state.changed.disconnect(self._dependency_changed)
        self._expression_dependencies.clear()


        # hook the dependent states
        self._expression_states_id = []
        for key in self._expression_states:
            state : StateInputItem
            state = sc.getState(key)
            if state is None:
                msg = f"Invalid state reference: [{key}]"
                if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
                if as_tuple:
                    return ([],True, msg)
                return []
            state.changed.connect(self._dependency_changed)
            state.key_changed.connect(self._state_name_changed)
            # remember the dependencies so we can clean them up later
            if not state in self._expression_dependencies:
                self._expression_dependencies.append(state)


        if as_tuple:
            return (output,False,None)
        return output
    
    def _state_name_changed(self, state: StateInputItem, old_name, new_name):
        ''' called when a dependent state changes its name '''
        self._change_state_name(old_name, new_name)
    
    def _dependency_changed(self, state : StateInputItem):    
        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose: syslog.info(f"STATE: Dependent state change: {state.key}")
        self._dirty = True
        self.evaluate()


    def _evaluate_stack(self, postfix_stack : list, as_tuple = False) -> bool | tuple:
        ''' evaluates the expression if it has changed 
        
        :param stack: the precomputed postfix expression
        :param as_tuple: returns the value, error flag, and any error message
        :returns: boolean, or a tuple (value, error_flag, error_message)
        
        '''

        if not postfix_stack:
            # no stack = False
            return False
        
        stack = []
        
        operators = set(['and', 'or', 'not', 'xor'])

        tokens = postfix_stack.copy() 
        states = self._valid_states()
        verbose = gremlin.config.Configuration().verbose_mode_state
        sc = StateData()
        
        if not states:
            # nothing to evaluate if no states exist
            msg = "Error: No valid states available for computation. Ensure the states are not using reserved names or self-reference"
            if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
            if as_tuple:
                return ([],False,msg)
            return []

        for token in tokens:
            if token not in operators:
                value = sc.value(token)
                if value is None:
                    msg = f"Error: unable to get value for state [{token}]"
                    if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
                    if as_tuple:
                        return (False,True,msg)
                    return False
                if not isinstance(value, bool):
                    msg = f"Error: state [{token}] is not a boolean state."
                    if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
                    if as_tuple:
                        return (False,True,msg)
                    return False
                stack.append(value)
            else:
                opcount = 1 if token == "not" else 2
                if len(stack) < opcount:
                    msg = "Error: Invalid expression: insufficient operands for operator "
                    if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
                    if as_tuple:
                        return (False,True,msg)
                    return False
                result = None
                if token == "not":
                    v1 = stack.pop()
                    result = not v1
                else:
                    v2 = stack.pop()
                    v1 = stack.pop()
                    if token == 'and':
                        result = v1 and v2
                    elif token == 'or':
                        result = v1 or v2
                    elif token == 'xor':
                        result = v1 ^ v2
                if result is None:
                    msg = f"unknown operator: {token}"
                    if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
                    if as_tuple:
                        return (False,True,msg)
                    return False

                stack.append(result)

                if len(stack) >= StateInputItem.MAX_STACK_SIZE:
                    break

        stack_size = len(stack)

        if stack_size >= StateInputItem.MAX_STACK_SIZE:
            # circuit breaker
            msg = "Invalid postfix expression: too complex and/or recursion detected.  Check there are no loops."
            if verbose: syslog.error(f"STATE EXPRESSION: {msg}")
            if as_tuple:
                return (False,True,msg)
            return False

        if stack_size != 1:
            msg = "Invalid postfix expression: too many operands or not enough operators"
            if verbose: syslog.info(f"STATE EXPRESSION: {msg}")
            if as_tuple:
                return (False,True,msg)
            return False

        self._dirty = False # indicate evaluation ok and no errors
        value = stack.pop()
        value_str = "On (true/1)" if value else "Off (false/0)"
        if as_tuple:
            return (value,True,f"Result: {value_str}")
        return value


    def __str__(self):
        return f"State: [{self._key}] id: [{self._id}]"
    
    def __eq__(self, other):
        if other is None:
            return False
        if not isinstance(other, StateInputItem):
            return False
        return self.key == other.key

    def __hash__(self):
        # use ID for hash
        return hash(self._id)

        
    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell

        state = self
        table = ReportTable(cellpadding=4)
        table.addField("State", state.key)

        if self.description:
            table.addField("Description", self.description)

        
        category_name = state.category_name
        if category_name:
            table.addField("Category", category_name)


        expression = state.expression
        if expression:
            table.addField("Expression",expression)
        else:
            table.addField("Default", "on" if state.default_value else "off")

        return table.to_html()    
    
    

@SingletonDecorator
class StateData(QtCore.QObject):
    ''' holds state information '''
    changed  = Signal(object) # fires when the value changes (StateInputItem)
    crud = Signal() # fires when a state is added or removed or changed
    key_changed = Signal(object, str, str) # fires when a state key changes [StateInputItem, old_name, new_name]
    expression_changed = Signal(object) # fires when a state expression changes (if the state is an expression state)

    def __init__(self):
        super().__init__()
        self._data = {}
        self._id_map = {}
        self.changed.connect(self._state_changed)
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._reset)
        el.profile_unloaded.connect(self._handle_profile_unload)

    def _handle_profile_unload(self):
        ''' occurs on profile unload before a new profile is loaded  '''

        self._data = {}
        self._id_map = {}
        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose: syslog.info("STATE: clear data")
        sc = StateCategories()
        sc.clear()


    def _reset(self):
        ''' reset states to default values '''
        to_evaluate = []
        verbose = gremlin.config.Configuration().verbose_mode_state
        for state in self._data.values():
            if state.expression:
                # initial evaluation
                to_evaluate.append(state)
            else:
                state.value = state.default_value
                if verbose: syslog.info(f"STATE: profile start [{state.key}] set initial value to: [{f"ON/PRESSED" if state.value else "OFF/RELEASED"}]")
                

        # evaluate expressions based on initial data values
        if verbose: syslog.info("STATE: profile start expressions:")
        for state in to_evaluate:
            state.evaluate(force=True)
            if verbose: syslog.info(f"\t[{state.key}] expression: {state.value}")


    def _register(self, key : str, value = None, description = None) -> StateInputItem:
        ''' registers a new state '''
        if not key:
            return None
        key = key.casefold().strip()
        if key in self._data:
            # already in the list
            return self._data[key]
        
        state = StateInputItem(key, value, description)    
        self._data[key] = state
        self._id_map[state.id] = state
        self.crud.emit()
        return state
    
    def update_key(self, state, old_name, new_name):
        ''' occurs on a key change'''
        if not state.id in self._id_map:
            self._id_map[state.id] = state
        self._data[new_name] = state
        self.key_changed.emit(state, old_name, new_name)
        # remove the old state AFTER updates or things referencing the old state won't find it
        if old_name in self._data:
            del self._data[old_name]
        self.crud.emit()
        


    def _expression_changed(self, state):
        self.expression_changed.emit(state)
    
    def register(self, key : str, value = None, description = None) -> StateInputItem:
        ''' registers a new state '''
        item = self._register(key, value, description)
        if item:
            self._sort()
        return item

    def unregister(self, key: str):
        ''' removes a state from the list '''
        key = key.casefold().strip()
        if key in self._data:
            state_data = self._data[key]
            state_data.unhook()

            id = state_data.id
            del self._data[key]
            del self._id_map[id]

    def value(self, key : str):
        ''' gets the state value '''
        key = key.casefold().strip()
        if key in self._data:
            return self._data[key].value
        return None

    def toggle(self, key : str):
        ''' toggles a state '''
        key = key.casefold().strip()
        if key in self._data:
            return self._data[key].toggle()
        return None

    
    def add(self, data : StateInputItem, emit = True):
        if data and not data.key in self._data:
            self._data[data.key] = data
            self._id_map[data.id] = data
            self._sort()
            if emit:
                self.crud.emit()



    def _sort(self):
        self._data = dict(sorted(self._data.items()))

    def getStates(self) -> dict:
        ''' gets state map '''
        return self._data
    
    def getStateNames(self):
        ''' gets the list of states currently defined '''
        return list(self._data.keys())
    
    def getInputItems(self):
        ''' gets a dict of input items for each state in the current profile '''
        input_items = {}
        for key, item in self._data.items():
            input_items[key] = item.input_item
        return input_items

    def getState(self, key : str) -> StateInputItem:
        ''' gets a state object for the given state name '''
        if key:
            key = key.casefold().strip()
            if key in self._data:
                return self._data[key]
        return None
    
    def getStateById(self, id : str) -> StateInputItem:
        ''' locates a state by id, None if not found '''
        if id in self._id_map:
            return self._id_map[id]
        return None

    def setValue(self, key : str, value, emit = True, force = False):
        ''' sets state value (and registers if needed) '''
        key = key.casefold().strip()
        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose: syslog.info(f"STATE SET: set state [{key}] -> {value}")
        self._data[key].setValue(value, force)
                                 

    
    def description(self, key : str) -> str:
        ''' gets the description for the state '''
        key = key.casefold().strip()
        if key in self._data:
            return self._data[key].description
        return None
    
    def sorted_keys(self) -> list:
        ''' returns the keys in the state data sorted alphabetically '''
        return list(self._data.keys())
    
    def setDescription(self, key : str, description : str, emit = True):
        ''' sets the description on a state '''
        key = key.casefold().strip()
        if key in self._data:
            if self._data[key].description != description:
                self._data[key].SetDescription(description)
                if self.emit:
                    self.changed.emit(self._data[key])
    
    def exists(self, key: str | StateInputItem):
        ''' true if the key exists in the state data '''
        if isinstance(key, str):
            key = key.casefold().strip()
            return key in self._data
        
        data : StateInputItem = key
        if data.id in self._data.items():
            return True
        if data.key in self._data:
            return True
        return False
        
    
    def clear(self):
        ''' clears all data '''
        if self._data:
            self._data.clear()
            self._id_map.clear()
            self.crud.emit()
        

    def remove(self, key : str):
        key = key.casefold().strip()
        if key in self._data:
            data = self._data[key]
            data.unhook()
            del self._data[key]
            del self._id_map[data.id]
            self.crud.emit()

    def removeId(self, id: str):
        if id in self._id_map:
            data = self._id_map[id]
            data.unhook()
            key = data.key
            del self._data[key]
            del self._id_map[data.id]


    
    def index(self, item):
        ''' gets the index of the item in the current list'''
        if item.key in self._data:
            keys = list(self._data.keys())
            return keys.index(item.key)
        return -1
    
    def createDefault(self, count = 5):
        ''' creates default states '''
        for index in range(count):
            key = f"default_{index+1}"
            self._register(key, False, f"Default state {index+1}")
        self._sort()

    def __iter__(self):
        return self._data.__iter__()
    
    def __next__(self):
        return self._data.__next__()
    
    def __len__(self):
        return len(self._data)

    def __getitem__(self, key):
        if key in self._data:
            return self._data[key]
        return None
        

    def to_xml(self):
        ''' persists the data to XML '''
        root = ElementTree.Element("states")
        for key in self._data:
            item = self._data[key]
            if item:
                node = item.to_xml()
                if node is not None:
                    root.append(node)

        # save defined categories to the state node
        sc = StateCategories()
        node = sc.to_xml()
        root.append(node)
        return root

    def from_xml(self, root, data = None, extra_data = None):
        ''' reads saved data '''

        # read categories first
        nodes = root.xpath("//categories")
        if nodes:
            node = nodes[0]
            sc = StateCategories()
            sc.from_xml(node)

        for node in root:
            if node.tag == "state":
                item = StateInputItem()
                item.from_xml(node)
                self._data[item.key] = item
                self._id_map[item.id] = item
                

    @QtCore.Slot(object)
    def _state_changed(self, data : StateInputItem):
        ''' called when a state changes '''
        if not gremlin.shared_state.is_running:
            return
        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose: syslog.info(f"STATE CHANGE: [{data.key}] value: {data.value}")
        event = gremlin.event_handler.Event(
            event_type= InputType.State,
            device_guid= gremlin.shared_state.state_tab_guid,
            identifier= data,
            value = data.value,
            curved_value = None,
            raw_value= None,
            is_axis = False,
            is_virtual = True,
            is_pressed = data.value,
            override_input_type=InputType.JoystickButton # tell actions we're a button
        )
        eh = gremlin.event_handler.EventHandler()
        eh.execute_event(event)


class CategoryModel(QtCore.QAbstractListModel):
    """
    A custom list model that stores and provides a list of strings to a QListView.
    """

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self._data = {} 
        cb = StateCategories()
        self._source = data
        self._default_category = cb.default()
        self._category_names = []
        if data:
            for index, item in enumerate(data):
                self._data[index] = item
        
        self._update()

    def _update(self):
        self._category_names = []
        for item in self._data.values():
            self._category_names.append(item.name)

    def rowCount(self, parent=QModelIndex()):
        """ Returns the number of rows in the model. """
        return len(self._data) 

    def data(self, index, role=QtCore.Qt.DisplayRole):
        """
        Retrieves the data for a given item and role.
        """
        if not index.isValid() or not (0 <= index.row() < self.rowCount()):
            return None
        
        if role == QtCore.Qt.DisplayRole:
            item = self._data[index.row()]
            return item.text()

        elif role == QtCore.Qt.EditRole:
            return self._data[index.row()]
        elif role == QtCore.Qt.UserRole:
            return len(self._data[index.row()])
        return None

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        """
        Sets the data for a given item and role.
        """
        if not index.isValid() or not (0 <= index.row() < self.rowCount()):
            return False

        if role == QtCore.Qt.EditRole:
            self._data[index.row()].name = value
            self._update()
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    def flags(self, index):
        """
        Returns the item flags for a given index.
        """
        if not index.isValid():
            return QtCore.Qt.NoItemFlags

        # Make items selectable and editable
        return QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable
    
    def addData(self, item, role=QtCore.Qt.EditRole):
        ''' adds an item to the model '''
        if not item.name in self._category_names:
            self.beginResetModel()
            index = len(self._data)
            self._data[index] = item
            self._update()
            self.dataChanged.emit(index, index, [role])
            self.endResetModel()

    def itemAt(self, index):
        if index in self._data:
            return self._data[index]
        return

    @property
    def items(self):
        ''' gets the data in the model'''
        return self._data.values()
    
    def getItems(self):
        return self._data
    
    def getCategoryNames(self):
        ''' gets the list of categories by name '''
        return self._category_names
    
    def clear(self):
        self._data.clear()
        self._update()
    

class StateCategoryEditorDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        cb = StateCategories()
        self._default_category = cb.default()




    def createEditor(self, parent, option, index):
        # Create and return the custom editor widget
        category = index.data(QtCore.Qt.EditRole)
        editor = StateCategoryEditor(category.name, parent)
        return editor
    

    def setModelData(self, editor, model, index):
        value = editor.text()
        if not value or not value.strip():
            gremlin.ui.ui_common.MessageBox(title = "Category Error", prompt = f"Category name cannot be blank.")
            return
        # if value == self._default_category.name:
        #     gremlin.ui.ui_common.MessageBox(title = "Category Error", prompt = f"The default category cannot be renamed.")
        #     return
        model.setData(index, value, QtCore.Qt.EditRole)


class StateCategoryEditor(QtWidgets.QDialog):
    def __init__(self, text = None, parent=None):
        super().__init__(parent)
        self.setModal(True)

        self._widget = QtWidgets.QLineEdit(text)
        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.cancel_widget = QtWidgets.QPushButton("Cancel")

        widget, layout = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True)
        
        self.ok_widget.clicked.connect(self.accept)
        self.cancel_widget.clicked.connect(self.reject)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(self._widget)
        main_layout.addWidget(widget)

        self._widget.setFocus()

    def showEvent(self, event):
        # Show the dialog at the current mouse position
        geom = self.frameGeometry()
        geom.moveCenter(QtGui.QCursor.pos())
        self.setGeometry(geom)
        super().showEvent(event)


    def text(self) -> str:
        return self._widget.text()
    
    def setText(self, text : str):
        self._widget.setText(text)
    


class StateCategoryListView(QtWidgets.QListView):
    edited = Signal() # issued when edited
    lostFocus = Signal() # issued on loss of focus
    def __init__(self, parent=None):
        super().__init__(parent)
        self.delegate = StateCategoryEditorDelegate(self)
        self.setItemDelegate(self.delegate)
        
        self.delegate.closeEditor.connect(self.handle_editor_closed)

    def handle_editor_closed(self, editor, hint):
        self.edited.emit()

    def focusOutEvent(self, event):
        self.lostFocus.emit()
        return super().focusOutEvent(event)

    


class StateCategoryConfigDialog(gremlin.ui.ui_common.QShowAtCursorDialog):
    ''' dialog showing the category configuration options '''

    def __init__(self, parent = None):
        '''
        :param index - the input item index zero based
        :param identifier - the input item identifier 
        '''
        
        super().__init__(self.__class__.__name__,parent = parent)

        main_layout = QtWidgets.QVBoxLayout(self)
        self.setWindowTitle("Category Editor")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._parent = parent # list view

        self._cm = StateCategories()
        self._default_category = self._cm.default()

        categories = [item for item in self._cm.getCategories().values()]
        self._model = CategoryModel(categories)

        self._category_names = self._cm.getCategoryNames()
        self._last_selected_category = None # holds the last category selection

        
        self._list_view = StateCategoryListView()
        self._list_view.setModel(self._model)
        self._list_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._list_view.edited.connect(self._handle_edited)
        self._list_view.selectionModel().selectionChanged.connect(self._selection_changed)
        self._list_view.lostFocus.connect(self._list_lost_focus)
        
       
        main_layout.addWidget(self._list_view)


        # add button
        self._add_button = QtWidgets.QPushButton("Add")
        self._add_button.setToolTip("Adds a new category")
        icon = gremlin.ui.ui_common.Icons.addIcon()
        self._add_button.setIcon(icon)
        self._add_button.clicked.connect(self._add_input_cb)

        self._delete_button = QtWidgets.QPushButton()
        icon = gremlin.ui.ui_common.Icons.trashIcon()
        self._delete_button.setIcon(icon)
        self._delete_button.setMaximumWidth(24)
        self._delete_button.setToolTip("Deletes the selected items")
        self._delete_button.clicked.connect(self._delete_cb)

        self._edit_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._edit_widget.setTriggerOnFocusOnly(False) # trigger on every character
        
        self._edit_widget.valueChanged.connect(self._new_category_changed_cb)

        widget, layout = gremlin.ui.ui_common.getHContainer([self._edit_widget, self._add_button, self._delete_button],"New Category:")
        main_layout.addWidget(widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget, layout = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True)
        
        main_layout.addWidget(widget)

        self._edit_widget.setFocus()
        self._update()

    def _handle_edited(self):
        ''' called when the list view has been edited '''
        pass
        
    def _list_lost_focus(self):
        ''' on focus loss, clear selection '''
        pass

    def category(self) -> StateCategory:
        ''' gets the selected category '''
        category = self._cm.findByName(self._last_selected_category)
        return category

        
    def _selection_changed(self, selected, deselected):
        selected_indexes = self._list_view.selectedIndexes()
        # You can iterate through selected_indexes to get the data of selected items
        enabled = True
        for index in selected_indexes:
            category_name = index.data().casefold().strip()
            self._last_selected_category = category_name
            if category_name == self._default_category.name:
                enabled = False
                break
        self._delete_button.setEnabled(enabled)
        
        
            

    def _update(self):
        name = self._last_selected_category
        add_enabled = False
        if name:
            name = name.casefold().strip()
            if name == self._default_category.name:
                add_enabled = False
            else:
                add_enabled = True
        self._add_button.setEnabled(add_enabled)

        selected_indexes = self._list_view.selectedIndexes()
        self._delete_button.setEnabled(len(selected_indexes) > 0)

    @QtCore.Slot()
    def _delete_cb(self):
        """Callback executed when the delete button is pressed."""

        indices = self._list_view.selectedIndexes()
        if not indices:
            # nothing to do
            return
        
        rows = [idx.row() for idx in indices]
        keep = []
        items = self._model.items

        for index, category in enumerate(items):
            if index in rows:
                if category == self._default_category:
                    gremlin.ui.ui_common.MessageBox(title = "Category Error", prompt = f"The default category cannot be removed.")
                    return
                continue # delete
            keep.append(category) # keep

        deleteCount = len(items)-len(keep)
        if not deleteCount:
            # nothing to delete
            return    

        # confirm box 
        msg = "Delete the selected entries?" if deleteCount > 1 else "Delete the selected entry?"
        msgbox = gremlin.ui.ui_common.ConfirmBox(prompt = msg)
        result = msgbox.show()

        if result == QtWidgets.QMessageBox.StandardButton.Ok:

            self._model.clear()
            for item in keep:
                self._model.addData(item)

            role=QtCore.Qt.EditRole
            self._model.dataChanged.emit(index, index, [role])
            
            # select the first item kept
            if keep:
                index = self._model.index(0)
                self._list_view.setCurrentIndex(index)

    @QtCore.Slot()
    def _new_category_changed_cb(self):
        ''' called on name change '''
        name = self._edit_widget.text()
        enabled = False
        if name:
            # check it's not the default
            name = name.casefold().strip()
            if not name in self._model.getCategoryNames():
                self._last_selected_category = name
                enabled = True

            
        self._add_button.setEnabled(enabled)



    @QtCore.Slot()
    def _add_input_cb(self):
        name = self._last_selected_category
        if name:
            name = name.casefold().strip()
        if name:
            if self._cm.findByName(name):
                gremlin.ui.ui_common.MessageBox(title = "Category Error", prompt = f"Category [{name}] already exists.")
            else:
                item = StateCategory(name)
                self._model.addData(item)
                self._new_category_changed_cb()
                

     
    def _ok_button_cb(self):
        ''' ok button pressed '''

        # update categories 
        category_names = self._model.getCategoryNames()
        for category_name in category_names:
            category = self._cm.findByName(category_name)
            if not category:
                self._cm.addCategory(category_name)
        # remove categories that no longer exist 
        for category_name in self._cm.getCategoryNames():
            if not category_name in category_names:
                self._cm.removeCategoryName(category_name)
        self.accept()   

    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()        
                
    def getCategories(self) -> list:
        ''' gets a list of edited categories '''
        categories = list([item for item in self._model.items])
        return categories

        



    def populate_ui(self):
        self._list_view.items().clear()
        for category in self._cm.getCategories():
            item = QtWidgets.QListWidgetItem()
            item.setText(category.name)
            item.setData(category)
            self._list_view.addItem(item)

    def selectedCategory(self):
        if not self._last_selected_category:
            return self._default_category.name
        return self._last_selected_category


class StateInputConfigDialog(gremlin.ui.ui_common.QShowAtCursorDialog):
    ''' dialog showing the state input configuration options '''

    def __init__(self, state : StateInputItem, ref_state : StateInputItem, parent = None):
        '''
        :param index - the input item index zero based
        :param identifier - the input item identifier 
        '''
        
        super().__init__(self.__class__.__name__,parent = parent)

        gremlin.shared_state.push_suspend_highlighting() # prevent device highlight changes while editing a state 

        # self._sequence = InputKeyboardModel(sequence=sequence)
        self.setWindowTitle("State Editor")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._parent = parent # list view
        self._is_edit = state is not None
    

        el = gremlin.event_handler.EventListener()
        

        main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(main_layout)

        self._config_widget, self._config_layout = gremlin.ui.ui_common.getGridContainer()
        self.data = state
        self.ref_data = ref_state # reference state

        self._name_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._name_widget.setText(state.key)
        self._name_widget.textChanged.connect(self._name_changed)
        
        self._is_expression_widget = QtWidgets.QCheckBox("This state is an expression")
        self._is_expression_widget.setToolTip("If enabled, the state uses an expression to derive its value.  If not set, a default value on start can be set.")
        self._is_expression_widget.setChecked(self.data.isExpression)
        self._is_expression_widget.clicked.connect(self._is_expression_changed)

        self._expression_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._expression_widget.setText(state.expression)
        self._expression_widget.textChanged.connect(self._expression_changed)

        self._test_widget = QtWidgets.QPushButton("Test")
        self._test_widget.setToolTip("Tests the state expression")
        self._test_widget.clicked.connect(self._test_expression)
        self._test_widget.setEnabled(bool(state.expression))


        self._description_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._description_widget.setText(state._description)
        self._description_widget.textChanged.connect(self._description_changed)

        self._autorelease_widget = gremlin.ui.ui_common.QDataCheckbox("Autorelease", value = state.autorelease, callback = self._handle_autorelease_changed)
        self._autorelease_delay_widget = gremlin.ui.ui_common.QFloatLineEdit(min_range = 0, max_range = 1000,step = 0.1,value = state.autorelease_delay, callback = self._handle_autorelease_delay_changed)
        self._autorelease_mode_widget = gremlin.ui.ui_common.QDataComboBox()
        modes = [
            ("Toggle", "toggle"),
            ("On", "on"),
            ("Off", "off"),
        ]
        for mode, data in modes:
            self._autorelease_mode_widget.addItem(mode, data)

        index = self._autorelease_mode_widget.findData(self.data.autorelease_mode)
        if index != -1:
            self._autorelease_mode_widget.setCurrentIndex(index)

        self._autorelease_mode_widget.currentIndexChanged.connect(self._handle_autorelease_mode_changed)


        self._autorelease_trigger_mode_widget = gremlin.ui.ui_common.QDataComboBox()
        modes = [
            ("Any", "any"),
            ("On", "on"),
            ("Off", "off"),
        ]
        for mode, data in modes:
            self._autorelease_trigger_mode_widget.addItem(mode, data)

        index = self._autorelease_trigger_mode_widget.findData(self.data.autorelease_trigger_mode)

        if index != -1:
            self._autorelease_trigger_mode_widget.setCurrentIndex(index)

        self._autorelease_trigger_mode_widget.currentIndexChanged.connect(self._handle_autorelease_trigger_mode_changed)


        widgets = [
            "Delay (s):",
            self._autorelease_delay_widget,
        ]

        r1_widget, _ = gremlin.ui.ui_common.getHContainer(widgets)

        widgets = [
            "Set Value:",
            self._autorelease_mode_widget,
        ]

        r2_widget, _ = gremlin.ui.ui_common.getHContainer(widgets)        

        widgets = [
            "Trigger on:",
            self._autorelease_trigger_mode_widget
        ]

        r3_widget, _ = gremlin.ui.ui_common.getHContainer(widgets)        


        widgets = [
            r1_widget,
            r2_widget,
            r3_widget
            ]
        
        self._autorelease_options_container_widget, _ = gremlin.ui.ui_common.getVContainer(widgets, left_margin=12)

        widgets = [
            self._autorelease_widget,
            self._autorelease_options_container_widget
        ]

        self._autorelease_container_widget, _ = gremlin.ui.ui_common.getVContainer(widgets)

        self._status_widget = gremlin.ui.ui_common.QWarningWidget()


        self._cm = StateCategories()

        selected_index = None
        self._category_selector_widget : QtWidgets.QComboBox = self._cm.getSelector() # self._category_changed_cb)

        # update selector when categories change
        el.state_category_add.connect(self._category_change_cb) 
        el.state_category_delete.connect(self._category_change_cb)
        el.state_category_name_change.connect(self._category_change_cb)

        if self.data.category:
            index = self._category_selector_widget.findData(self.data.category)
            if selected_index is None and index != -1:
                with QtCore.QSignalBlocker(self._category_selector_widget):
                    selected_index = index
                    self._category_selector_widget.setCurrentIndex(index)


        self._category_config_widget = QtWidgets.QPushButton()
        self._category_config_widget.setIcon(gremlin.ui.ui_common.Icons.gearIcon())
        self._category_config_widget.setMaximumWidth(24)
        self._category_config_widget.clicked.connect(self._category_config_cb)
        self._category_config_widget.setToolTip("Edit categories")

        category_widget, _ = gremlin.ui.ui_common.getHContainer([self._category_selector_widget, self._category_config_widget])

        row = 0
        col = 0
        self._config_layout.addWidget(QtWidgets.QLabel("Name:"), row, col)
        self._config_layout.addWidget(self._name_widget, row, col+1)

        row += 1
        self._config_layout.addWidget(QtWidgets.QLabel("Description:"), row, col)
        self._config_layout.addWidget(self._description_widget, row, col+1)

        row += 1
        self._config_layout.addWidget(QtWidgets.QLabel("Category:"), row, col)
        self._config_layout.addWidget(category_widget, row, col+1)

        row += 1
        self._config_layout.addWidget( self._is_expression_widget , row, col, 1, -1)

        row += 1
        self._expression_container_widget, _ = gremlin.ui.ui_common.getHContainer([self._expression_widget, self._test_widget],"Expression:")
        self._config_layout.addWidget(self._expression_container_widget, row, col, 1, -1)

        row += 1
        self._config_layout.addWidget(self._autorelease_container_widget, row, col, 1, -1)

        row += 1
        
        self._default_on_widget = gremlin.ui.ui_common.QDataRadioButton("On", True)
        self._default_on_widget.setToolTip("If checked, the state will default to Active/On/Pressed")
        self._default_off_widget = gremlin.ui.ui_common.QDataRadioButton("Off", False)
        self._default_on_widget.setToolTip("If checked, the state will default to Inactive/Off/Released")
        if state.default_value:
            self._default_on_widget.setChecked(True)
        else:
            self._default_off_widget.setChecked(True)
        self._default_off_widget.clicked.connect(self._default_changed)    
        self._default_on_widget.clicked.connect(self._default_changed)

        self._default_container_widget, _ = gremlin.ui.ui_common.getHContainer([self._default_on_widget, self._default_off_widget],"Default State:")
        self._config_layout.addWidget(self._default_container_widget, row, col, 1, -1)

        main_layout.addWidget(self._config_widget)

        main_layout.addWidget(self._status_widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget, _ = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True)
        
        main_layout.addWidget(widget)
        self._update_ui()

    @QtCore.Slot(bool)
    def _handle_autorelease_changed(self, checked):        
        self.data.autorelease = checked
        self._update_ui()

    @QtCore.Slot()
    def _handle_autorelease_mode_changed(self):
        self.data.autorelease_mode = self._autorelease_mode_widget.currentData()

    @QtCore.Slot()
    def _handle_autorelease_trigger_mode_changed(self):
        self.data.autorelease_trigger_mode = self._autorelease_trigger_mode_widget.currentData()
        
    def _handle_autorelease_delay_changed(self, value):
        self.data.autorelease_delay = value

    def _set_status(self, text : str):
        ''' sets the status text '''
        self._status_widget.setText(text)
        self._update_ui()

    def _clear_status(self):
        ''' clears and hides the status text '''
        self._set_status(None)

        
    def category(self) -> StateCategory:
        ''' gets the current selected category '''
        return self._category_selector_widget.currentData()

    def _category_config_cb(self):
        self._category_dialog = StateCategoryConfigDialog()
        self._category_dialog.accepted.connect(self._category_dialog_ok)
        self._category_dialog.show()

    def _category_dialog_ok(self):
        ''' called when category data changes '''
        selected_category = self._category_dialog.category()
        self._cm.updateSelector(self._category_selector_widget)
        if selected_category:
            index = self._category_selector_widget.findData(selected_category)
            if index != -1:
                self._category_selector_widget.setCurrentIndex(index)


    def _category_change_cb(self, category):
        ''' category was changed '''
        self._cm.updateSelector(self._category_selector_widget)
        index = self._category_selector_widget.findData(category)
        if index == -1:
            # pick the default
            default_category = self._cm.default()
            index = self._category_selector_widget.findData(default_category)
        if index != -1:
            self._category_selector_widget.setCurrentIndex(index)
        

    def _validate(self):
        sd = StateData()
        msg = None
        key = self.data.key

        # blank
        enabled = bool(key)
        if not enabled:
            msg = "Name cannot be blank."
        
        # words
        if re.search(r'\s', key):
            enabled = False
            msg = "Name cannot include spaces"
            
        if enabled:
            state = sd.getState(self.data.key)
            if state and self.ref_data and state != self.ref_data:
                enabled = False
                msg = "Name is not case sensitive and must be unique."

        if enabled:
            # check against reserved keywords
            if key in ("and","or","not","xor"):
                enabled = False
                msg =  "Name cannot be a reserved keyword."

        self.ok_widget.setEnabled(enabled)
        self._set_status(msg)


    @QtCore.Slot()
    def _name_changed(self):
        self.data.key = self._name_widget.text()
        self._validate()

    @QtCore.Slot()
    def _description_changed(self):
        description = self._description_widget.text()
        self.data.setDescription(description)

    @QtCore.Slot(bool)
    def _is_expression_changed(self, checked):
        self.data.isExpression = checked
        self._update_ui()
                 
        
    @QtCore.Slot()
    def _expression_changed(self):
        self.data.expression = self._expression_widget.text()
        self._test_widget.setEnabled(bool(self.data.expression))

    @QtCore.Slot()
    def _test_expression(self):
        value, is_error, error_msg = self.data.evaluate(as_tuple = True, force = True)
        value_str = "On (true/1)" if value else ("Off (false/0)")
        msg = error_msg if is_error else f"Result: {value_str}"
        gremlin.ui.ui_common.MessageBox(title = "Expression Evaluation", prompt= msg, is_warning = is_error)

        

    @QtCore.Slot(bool)
    def _default_changed(self, checked):
        widget = self.sender()
        self.data.default_value = widget.data


    def _ok_button_cb(self):
        ''' ok button pressed '''
        # ensure the item is unique and not already used
        is_expression = False
        if self.data.expression:
            value, is_error, error_msg = self.data.evaluate(as_tuple = True, force = True)
            if is_error:
                gremlin.ui.ui_common.MessageBox(title = "Expression Evaluation Error", prompt= error_msg, is_warning = is_error)
                return
            is_expression = True

        key = self.data.key

        # update category if changed 
        category = self._category_selector_widget.currentData()
        self.data.setCategory(category)

        if key:
            key_low = self.data.key.casefold().strip()
            if key_low:
                if not self._is_edit:
                    # validate if not editing 
                    if not is_expression:
                        id = self.data.id
                        sc = StateData()
                        data = sc.getStates()
                        states = [item.key for item in data.values() if item.id != id and key_low == item.key]
                        if states:
                            gremlin.ui.ui_common.MessageBox(title ="State Error", prompt = f"[{key}] is already defined as a state.\nState names must be unique and are not case sensitive.")
                            return
                        
                gremlin.shared_state.pop_suspend_highlighting()
                self.accept()
        else:
            gremlin.ui.ui_common.MessageBox(title ="State Error", prompt = f"A state name is required.")

        
    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        gremlin.shared_state.pop_suspend_highlighting()
        self.reject()        

    def _update_ui(self):
        ''' updates the dialog controls based on options '''
        expression_visible = self.data.isExpression
        self._expression_container_widget.setVisible(expression_visible)
        self._default_container_widget.setVisible(not expression_visible)
        self._status_widget.setVisible(bool(self._status_widget.text()))

        if expression_visible:
            self._autorelease_container_widget.setVisible(False)
            
        else:
            self._autorelease_container_widget.setVisible(True)
            visible = self.data.autorelease
            self._autorelease_options_container_widget.setVisible(visible)


class  StateFilterWidget(QtWidgets.QWidget):
    ''' displays a filter widget that can be enabled, and a state category selected '''
    changed = Signal(str) # fires when the filter is changed
    categoryChanged = Signal(StateCategory)  # fires when the category is changed
    select = Signal(object) # request to select an item 
    apply = Signal() # called when the widget's apply button is called
    enabledChanged = Signal() # fires when the filter enable/disable is changed
        
    def __init__(self, model = None, parent = None, is_iv = False):
        super().__init__(parent)

        self._config = gremlin.config.Configuration()
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self._model = model
        self._is_iv = is_iv # true if input viewer filter

         # filter widget
        cm = StateCategories()
        category_id = self._config.iv_state_category_filter if is_iv else self._config.state_category_filter
        category = cm.findById(category_id)
        self._category_filter = category

        self.filter_enabled_widget = QtWidgets.QCheckBox("Enable Filtering")
        self.filter_enabled_widget.setToolTip("Enables filtering on the state list by category")
        is_filter = self._config.iv_state_filter_enabled if is_iv else self._config.state_filter_enabled

        self.filter_enabled_widget.setChecked(is_filter)
        self.filter_enabled_widget.clicked.connect(self._filter_enabled_changed)

        self._category_filter_widget = cm.getSelector(self._category_filter_changed, category)
        self._category_filter_widget.setEnabled(is_filter)
        self._category_filter_widget.setEditable(False) # don't allow editing of categories for the main filter


        current_filter = self._config.iv_state_filter if is_iv else self._config.state_filter
        self._filter_widget = gremlin.ui.ui_common.QDataLineEdit(text = current_filter)

        
        self._find_widget = gremlin.ui.ui_common.Buttons.getSearchWidget(callback = self._find_entry)
        self._apply_widget = QtWidgets.QPushButton("Apply")
        self._apply_widget.setToolTip("Apply current filter")
        self._apply_widget.clicked.connect(self._apply_filter)

        self._clear_filter_widget = gremlin.ui.ui_common.Buttons.getClearWidget(callback = self._clear_filter,label=None)
        self._clear_filter_widget.setMaximumWidth(24)

        # text filter
        widget, _ = gremlin.ui.ui_common.getHContainer([self._find_widget,
                                                             "||",
                                                             #self._filter_enabled_widget,
                                                             QtWidgets.QLabel(" Filter:"),
                                                             self._filter_widget,
                                                             "||",
                                                             self._apply_widget,
                                                             self._clear_filter_widget,
                                                             ])
        self.main_layout.addWidget(widget)

        # category filter
        widget, _ = gremlin.ui.ui_common.getHContainer([self.filter_enabled_widget, 
                                                        "||",
                                                        QtWidgets.QLabel(" Category:"), 
                                                        self._category_filter_widget])
        self.main_layout.addWidget(widget)


        # count row
        self._count_widget = QtWidgets.QLabel()
        widget, _ = gremlin.ui.ui_common.getHContainer(self._count_widget)
        self.main_layout.addWidget(widget)
        self.main_layout.setSpacing(2)
        self._update_count()        

    @QtCore.Slot(bool)
    def _filter_enabled_changed(self, is_filter):
        if self._is_iv:
            self._config.iv_state_filter_enabled = is_filter
        else:
            self._config.state_filter_enabled = is_filter
            
        self._category_filter_widget.setEnabled(is_filter) 
        has_categories = self._category_filter_widget.count()
        category = self._category_filter_widget.currentData() if is_filter and has_categories else None
        self.categoryChanged.emit(category)
        self.enabledChanged.emit()


    @QtCore.Slot()
    def _category_filter_changed(self):
        ''' called when the state category filter is changed '''
        category = self._category_filter_widget.currentData()
        self._category_filter = category
        gremlin.config.Configuration().state_category_filter = category.id if category else ""
        self.categoryChanged.emit(category)

    @property
    def category(self) -> StateCategory:
        ''' current category'''
        return self._category_filter
    
    def _update_count(self):
        ''' updates the count of defined inputs '''
        if not self._model:
            self._count_widget.setText(None)
            return
        total = self._model.rows()
        filtered = self._model.filteredRows()

        plural = "s" if total > 1 else ""
        if total == 0:
            msg = f"<i>(no states found)</i>"
        elif filtered != total:
            msg = f"<i>({filtered:,} of {total:,} state{plural})</i>"
        else:
            msg = f"<i>({total:,} state{plural})</i>"
        self._count_widget.setText(msg)

    def updateCounts(self):
        ''' updates the model counts '''
        self._update_count()
    
    def _clear_filter(self):
        value = self._filter_widget.text()
        if value:
            # if there is a filter, clear it
            with QtCore.QSignalBlocker(self._filter_widget):
                self._filter_widget.setText(None)
            self._apply_filter()    

    def _apply_filter(self):
        ''' applies the filter '''
        value = self._filter_widget.text()
        if self._is_iv:
            self._config.iv_state_filter = value
        else:
            self._config.state_filter = value
        self.changed.emit(value)
        self.apply.emit()


    def clearFilter(self):
        ''' clears the filter '''
        self._clear_filter()

    @property
    def filter(self) -> str:
        return self._filter_widget.text()    
    
    def _find_entry(self):
        ''' occurs when the find button is clicked '''
        gremlin.util.InvokeUiMethod(self._find_entry_ui)


    def _find_entry_ui(self):
        ''' displays the find dialog '''
        config = gremlin.config.Configuration()
        current_term = config.state_last_search_term
        self._dialog = gremlin.ui.ui_common.QInputDialog("Find OSC message","Search for:", text = current_term)
        self._dialog.accepted.connect(self._find_entry_accept)
        self._dialog.setModal(True)
        self._dialog.show()

    def _find_entry_accept(self):
        ''' finds the first entry matching the specified search term'''
        config = gremlin.config.Configuration()
        current_term = config.state_last_search_term
        new_term = self._dialog.text()
        if new_term:
            input_item : StateInputItem
            config.state_last_search_term = new_term
            new_term = gremlin.util.decorate_filter(new_term)
            data = self._model.dataModel()
            matches = [(index, item) for index, item in data.items() if fnmatch.fnmatch(item.input_id.key, new_term)]
            if matches:
                index_list = [i for (i, item) in matches]
                index_list.sort()
                index = index_list[0]
                input_item = data[index]
                self.select.emit(input_item)
        
class StateDeviceTabWidget(gremlin.ui.ui_common.QSplitTabWidget):

    """Widget used to configure state change actions """
    
    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS
    device_guid = gremlin.shared_state.state_tab_guid

    def __init__(
            self,
            device_profile,
            current_mode,
            object_name = "State Device",
            parent=None
    ):
        """Creates a new object instance.

        :param device_profile profile data of the entire device
        :param current_mode currently active mode
        :param parent the parent of this widget
        """
        super().__init__(object_name, gremlin.shared_state.state_tab_guid, parent)
        import gremlin.ui.ui_common as ui_common
        import gremlin.ui.input_item as input_item

        # Store parameters
        self.device_profile = device_profile
        self.widget_storage = {}

        button_container_widget = QtWidgets.QWidget()
        button_container_layout = QtWidgets.QHBoxLayout(button_container_widget)

        config = gremlin.config.Configuration()

        
        # lock widget
        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data = self.device_guid)
        widget, _ = gremlin.ui.ui_common.getHContainer(["State Inputs", "||", lock_widget])
        self.addLeftPanelWidget(widget)


        if config.show_container_id:
            device = gremlin.joystick_handling.get_device(self.device_guid)
            width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget, _ = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:")
            self.addLeftPanelWidget(widget)
            w1 = widget

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget, _ = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:")
            self.addLeftPanelWidget(widget)
            w2 = widget

            gremlin.ui.ui_common.synchronize_grids([w1, w2])        
        

        self._filter = gremlin.util.decorate_filter(config.state_filter)
        self._category_filter = config.state_category_filter
        device_data = device_profile.devices[self.device_guid]

        # data model
        self.input_item_list_model = input_item.InputItemListModel(
            device_data,
            current_mode,
            [InputType.State], # only allow Mode inputs for this widget,
            custom_update_handler= self._update_handler,
            custom_remove_handler = self._remove_handler,
            #custom_clear_handler = self._clear_handler,
            custom_filter_handler = self._filter_data
        )        

        self._filter_widget = StateFilterWidget(model = self.input_item_list_model)
        self._filter_widget.changed.connect(self._filter_changed)
        self._filter_widget.categoryChanged.connect(self._category_filter_changed)
        self._filter_widget.select.connect(self._select_input_item_cb)
        self._category_filter = self._filter_widget.category # current category        

        self.addLeftPanelWidget(self._filter_widget)

        # clear and add buttons to add/clear all states
        clear_button = ui_common.ConfirmPushButton("Clear States", show_callback = self._show_clear_cb)
        icon = gremlin.ui.ui_common.Icons.trashIcon()
        clear_button.setIcon(icon)
        clear_button.setToolTip("Deletes all states")
        clear_button.confirmed.connect(self._clear_inputs_cb)
        button_container_layout.addWidget(clear_button)

        # right align
        button_container_layout.addStretch(1)

        # find key button
        # find_button = gremlin.ui.ui_common.Buttons.getSearchWidget(callback = self._find_input_cb)
        # icon = gremlin.ui.ui_common.Icons.findIcon()
        # find_button.setIcon(icon)
        # find_button.setToolTip("Find State")
        # find_button.clicked.connect(self._find_input_cb)
        # button_container_layout.addWidget(find_button)

        # sort states
        sort_button = QtWidgets.QPushButton("Sort State")
        icon = gremlin.ui.ui_common.Icons.sortIcon()
        sort_button.setIcon(icon)
        sort_button.clicked.connect(self._sort_input_cb)
        button_container_layout.addWidget(sort_button)


        # Key add button
        add_button = QtWidgets.QPushButton("Add State")
        add_button.setToolTip("Adds a new state to the profile")
        icon = gremlin.ui.ui_common.Icons.addIcon()
        add_button.setIcon(icon)
        add_button.clicked.connect(self._add_input_cb)

        button_container_layout.addWidget(add_button)




        # update the display names 
        self.input_item_list_view = input_item.InputItemListView(custom_widget_handler=self._custom_widget_handler, device_id = self._device_id)
        self.input_item_list_view.setMinimumWidth(350)

        # Input type specific setups
        self.input_item_list_view.setModel(self.input_item_list_model)
        self.input_item_list_view.redraw()

        # Handle user interaction
        self.input_item_list_view.item_selected.connect(self._select_item_cb)
        self.input_item_list_view.item_edit.connect(self._edit_item_cb)
        self.input_item_list_view.item_closed.connect(self._close_item_cb)
        
        

        self.addLeftPanelWidget(self.input_item_list_view)
        self.addLeftPanelWidget(button_container_widget)
        
        self.input_item_list_model.refresh()
        self.input_item_list_view.redraw()

        
        # refresh on configuration change
        el = gremlin.event_handler.EventListener()
        # lock all inputs
        el.lock_inputs.connect(self._handle_lock_inputs)
        el.unlock_inputs.connect(self._handle_unlock_inputs)

        # last index selected, -1 means none
        self._last_selected_index = -1 


        
        # Select default entry
        selected_index = self.input_item_list_view.current_index
        if selected_index is None:
            selected_index = -1
        self._select_item_cb(selected_index)

    @property
    def inputCount(self) -> int:
        ''' number of inputs in the device '''
        return self.input_item_list_model.rows()
    
    @property
    def inputWidgetCount(self) -> int:
        ''' number of input widgets currently in the device '''
        return self.input_item_list_view.count()        


    def _handle_lock_inputs(self, data):
        ''' lock all inputs event'''
        if not Shiboken.isValid(self):
            return
        if data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.input_item_list_model.getFilteredItems():
                input_item.locked = len(input_item.containers) > 0 # don't lock if not mapped
            self.setUpdatesEnabled(True)
    
    def _handle_unlock_inputs(self, data):
        ''' unlock all inputs event '''
        if data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.input_item_list_model.getFilteredItems():
                input_item.locked = False
            self.setUpdatesEnabled(True)




    def _show_clear_cb(self):
        return self.input_item_list_model.rows() > 0

    def _config_changed_cb(self):
        ''' called when configuraition has changed '''
        self.refresh()      



    @QtCore.Slot(bool)
    def _filter_enabled_changed(self, is_filter):
        config = gremlin.config.Configuration()
        config.state_filter_enabled = is_filter
        self._filter_widget.setEnabled(is_filter)
        self.refresh()

    @QtCore.Slot(StateCategory)
    def _category_filter_changed(self, category):
        ''' called when the state category filter is changed '''
        self._category_filter = category
        self.refresh()


    def _filter_data(self, input_item) -> bool:
        ''' custom filter handler - true if the data is included in the filter, false otherwise '''
        import fnmatch
        if not self._filter:
            return True # ok
        item : StateInputItem = input_item.input_id
        key = item.key
        if not key:
            # no key = match
            return True
        
        key = item.key.casefold().strip()
        if self._filter in key:
            return True
        return fnmatch.fnmatch(key, self._filter)
        


    def _filter_changed(self, filter):
        ''' called when the filter changes '''
        self._filter = gremlin.util.decorate_filter(filter)
        self.input_item_list_model.refresh(emit = False)
        self.input_item_list_model.applyFilter()
        self.input_item_list_view.redraw()
        self._filter_widget.updateCounts()

    @QtCore.Slot()
    def _find_input_cb(self):
        ''' finds a state '''
        name, ok = QtWidgets.QInputDialog.getText(self, "State Lookup", "Search for:")
        if ok:
            sc = StateData()
            if sc.exists(name):
                data = sc.getState(name)
                index = self._index_for_key(data)
                self.input_item_list_view.select_item(index,True)
            else:
                gremlin.ui.ui_common.MessageBox(prompt=f"State [{name}] not found.")


    @QtCore.Slot()
    def _add_input_cb(self):
        """Adds a new state to the inputs list ADD STATE """
        input_id = StateInputItem()
        input_id.suppressEvents()
        index = self.input_item_list_model.add(input_id)
        self._edit_dialog = StateInputConfigDialog(input_id, None, self)
        self._edit_dialog.accepted.connect(self._dialog_ok_new_cb)
        gremlin.util.centerDialog(self._edit_dialog)
        self._edit_dialog.showNormal()
        self._edit_item = input_id
        self._edit_item_index = index
        self._is_edit = True
        self._index = index

    def _edit_item_cb(self, widget, index, input_id):
        ''' edit the state  '''
        tmp_input_id = input_id.clone()
        tmp_input_id.suppressEvents()
        self._edit_dialog = StateInputConfigDialog(tmp_input_id, input_id, self)
        self._edit_dialog.accepted.connect(self._dialog_ok_edit_cb)
        gremlin.util.centerDialog(self._edit_dialog)
        self._edit_dialog.showNormal()
        self._edit_item = input_id
        self._edit_item_index = index
        self._is_edit = True
        self._index = index

    def _sort_input_cb(self):
        ''' sorts states by key name '''

        if not self.input_item_list_model.rows():
            # nothing to sort
            return 

        # current selection (so we can select the item that was selected if the order changes)
        index = self._last_selected_index
        current_selection = None
        if index != -1:
            current_selection = self.input_item_list_model.data(index)

        self.input_item_list_model.sort(self._sort_callback)

        if current_selection:
            # reselect the saved item - because the inputs were likely recreated - we can't compare the old with the new
            # so we need to find the matching data packet
            items = self.input_item_list_model.getItems()
            state = current_selection.input_id
            for index, item in enumerate(items):
                if item.input_id == state:
                    self._select_item_cb(index)
                    return


    def _sort_callback(self, items : list):
        ''' callback for sorting '''
        items.sort(key = lambda x: x.input_id.key)
        return items

    def _close_item_cb(self, widget, index, data):
        ''' called when the close button is clicked '''
        key = self.getRegisteredKeyIndex(index)
        self.unregisterWidget(key)
        if not self.input_item_list_model.rows():
            # display blank page if no item left
            self._blank_input()

    def _dialog_ok_new_cb(self):        
        ''' called when edit dialog closes with ok on a new state '''
        data = self._edit_dialog.data
        sd = StateData()
        if sd.exists(data.key):
            syslog.warning(f"STATE: [{data.key}] already exists, ignoring edit")
            return 
        

        sd.add(data)
        self.input_item_list_model.refresh()
        self._filter_widget.updateCounts()
        index = self.input_item_list_model.indexOf(data)
        
        syslog.info(f"adding id: [{data.id}]  key: [{data.key}] at index [{index}]")
        

        identifier = self.input_item_list_model.data(index)
        input_item : StateInputItem = identifier.input_id
        input_item.enableEvents()
        category = self._edit_dialog.category()
        input_item.setCategory(category)
        input_item.key = data.key
        input_item.setDescription(data.description)
        input_item.default_value = data.default_value
        input_item.isExpression = data.isExpression
        input_item.expression = data.expression
        
        input_item.autorelease = data.autorelease
        input_item.autorelease_delay = data.autorelease_delay
        input_item.autorelease_mode = data.autorelease_mode
        input_item.autorelease_trigger_mode = data.autorelease_trigger_mode
        


        
        self.input_item_list_view.redraw()
        self._select_item_cb(index)

        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_id)            

    def _dialog_ok_edit_cb(self):        
        ''' called when edit dialog closes with ok on an edited state '''
        data = self._edit_dialog.data
        sd = StateData()
        trigger = False
        if self._edit_item._key != data.key:
            # name change?
            old_name = self._edit_item._key
            new_name = data.key
            self._edit_item._key = data.key # change the key and don't fire the event
            trigger = True

        self._edit_item.enableEvents()


        self._edit_item.description = data.description
        self._edit_item.setCategory(data.category)
        self._edit_item.default_value = data.default_value
        self._edit_item.isExpression = data.isExpression    
        self._edit_item.expression = data.expression    

        self._edit_item.autorelease = data.autorelease
        self._edit_item.autorelease_delay = data.autorelease_delay
        self._edit_item.autorelease_mode = data.autorelease_mode
        self._edit_item.autorelease_trigger_mode = data.autorelease_trigger_mode
        
        self.input_item_list_model.refresh()
        index = sd.index(self._edit_item)
        self.refresh()
        
        if trigger:
            sd.update_key(self._edit_item, old_name, new_name)

        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_id)

        # redraw for any updates
        self.input_item_list_view.redraw()
        self._select_item_cb(index)


    def _clear_inputs_cb(self):
        ''' clears all input keys '''
        sd = StateData()
        sd.clear()
        profile = gremlin.shared_state.current_profile
        profile.state.clear()
        self.input_item_list_model.reset()
        self.input_item_list_view.redraw()
        self._filter_widget.updateCounts()

        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_id)

        # add a blank input configuration if nothing is selected - the configuration widget is always the second widget of the main layout
        self._blank_input()
            
    def _update_handler(self, model, emit_change = True):
        ''' called when the data model for the input list needs to be updated - refreshes the model view '''
        state = self.device_profile.state
        self._input_items = {}

        keys = [key for key in state]
        keys.sort()

        model._index_map = {}
        model._item_map = {}
        model._source_item_map = {}
        model._source_index_map = {}

        config = gremlin.config.Configuration()
        is_filter = config.state_filter_enabled


        cm = StateCategories()
        default_category = cm.default()
        category = None
        if is_filter:
            category_id = self._category_filter
            category = cm.findById(category_id)
            if not category:
                category = default_category

 
        changed = False
        index = 0
        for key in keys:
            data = state[key]
            if category:
                # apply filter
                item_category = data.category if data.category else default_category
                if item_category != category:
                    continue # filter out
                
            item = data.input_item
            self._input_items[key] = item
            changed = True
            model._index_map[index] = item
            model._item_map[key] = index 

            model._source_index_map[index] = item
            model._source_item_map[item] = index
            index += 1
            
        model._update_filter()


        if changed and emit_change:
            model.data_changed.emit()

    def _remove_handler(self, model, index, emit_change = True):
        ''' clears a single index '''
    
        if index in model._index_map:
            del model._index_map[index]
            item = next((key for key, data in model._item_map.items() if data == index), None)
            if item:
                del model._item_map[item]
            
            # source items
            source_index = next((i for i, data in model._source_index_map.items() if data.input_id == item), -1)
            if source_index != -1:
                del model._source_index_map[source_index]
                item = next((key for key, data in model._source_item_map.items() if data == source_index), None)
                if item:
                    del model._source_item_map[item]
            
            model._update_filter()

            key = item.key
            sd = StateData()
            sd.remove(key)
            self._update_handler(model, emit_change)
            self._filter_widget.updateCounts()
            

    # def _clear_handler(self, model, emit_change = True):
    #     ''' clears all state data '''
    #     sd = StateData()
    #     sd.clear()
        

    
    def itemAt(self, index):
        ''' returns the input widget at the given index '''
        return self.input_item_list_view.itemAt(index)

    def display_name(self, input_id):
        ''' returns the name for the given input ID '''
        return input_id.display_name


    def _index_for_key(self, input_id):
        ''' returns the index of the selected input id'''
        current_mode = gremlin.shared_state.edit_mode
        mode = self.device_profile.modes[current_mode]
        sorted_keys = list(mode.config[InputType.State].keys())
        return sorted_keys.index(input_id)
    
     
    def getWidgetKey(self, input_type, input_id):
        ''' gets the content widget compound key for the item / input combination'''
        return (self._device_guid, input_type, input_id)

    def refresh(self, emit = True):
        """Refreshes the current selection, ensuring proper synchronization."""
        #self.set_mode(gremlin.shared_state.edit_mode) # force a model and reload
        self.input_item_list_model.refresh()
        self.input_item_list_view.redraw()
        self._filter_widget.updateCounts()
        self._select_item_cb(self.input_item_list_view.current_index, emit)

    def _select_input_item_cb(self, input_item, emit = True):
        ''' select by input '''
        input_id = input_item.input_id
        index = self.input_item_list_model.indexOf(input_id)
        if index == -1:
            self.clearFilter()
            index = self.input_item_list_model.indexOf(input_id)
        if index != -1:
            self._select_item_cb(index)

    def clearFilter(self):
        ''' clears the current data filter '''
        self._filter_widget.clearFilter()
        self.input_item_list_view.redraw()

    def _select_item_cb(self, index, emit = True):
        """Handles the selection of an input item.

        :param index the index of the selected item
        """
        import gremlin.ui.input_item

        if not Shiboken.isValid(self.input_item_list_view):
            return

        if index == -1:
            index = self._last_selected_index

        if index == -1:
            # select the first item
            if self.input_item_list_model.rows():
                index = 0
            else:
                return 
        
        with QtCore.QSignalBlocker(self.input_item_list_view):
            self.input_item_list_view.select_item(index, False)
        
        
        item_data : gremlin.base_profile.InputItem = self.input_item_list_model.data(index)
        if not item_data:
            # not in the model yet
            return
        
        input_type = InputType.State
        input_id = item_data.input_id
        key = self.getWidgetKey(input_type, input_id)
        widget = self.getRegisteredWidget(key)
        if not widget:
            widget = gremlin.ui.input_item.InputItemMappingWidget(item_data, object_name=f"STATE: {item_data.input_id.key}")
            self.registerWidget(key, widget)

        self._item_data = item_data
        

        # remember the last input
        config = gremlin.config.Configuration()
        device_guid = self.device_guid
        input_type = InputType.State
        input_id = item_data.input_id if item_data else None
        

        config.set_last_input(device_guid, input_type, input_id)

        # Create new configuration widget
        item_data.is_axis = False
        change_cb = self._create_change_cb(index)
        widget.action_model.data_changed.connect(change_cb)
        widget.description_changed.connect(change_cb)

        self.input_item_list_view.select_item(index,False)


        self._last_selected_index = index
        self.selectRegisteredWidget(key)
        self.input_item_list_view.scrollToIndex(index)
        
        # el = gremlin.event_handler.EventListener()
        # el.input_selection_changed.emit(device_guid, input_type, input_id)

    def _custom_filter_handler(self, data) -> bool:
        ''' evaluates if the item should be included or not based on current input filters '''
        return True

    def _custom_widget_handler(self, list_view, index : int, identifier, data, parent = None):
        ''' creates a widget for the input 
        
        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item
        
        '''
        import gremlin.ui.input_item

        widget = gremlin.ui.input_item.InputItemWidget(identifier = identifier, populate_ui_callback = self._populate_input_widget_ui, update_callback = self._update_input_widget, config_external=True, parent = parent, data = data)
        widget.data = data
        widget.create_action_icons(data)
        input_id : StateInputItem = data.input_id

        sd = StateData()

        
        title = f"State: [{input_id.key}] [{input_id.id}]" if gremlin.config.Configuration().show_container_id else f"State: [{input_id.key}]"
        widget.setTitle(title)
        widget.enable_edit()
        widget.enable_close()
        widget.clearWidgets()

        if input_id.description:
            widget.addWidget(QtWidgets.QLabel(f"{input_id.description}"))

        category_name =input_id.category_name
        if category_name:
            widget.addWidget(QtWidgets.QLabel(f"Category: [{category_name}]"))

        if input_id.expression:
            icon = gremlin.ui.ui_common.Icons.calculateIcon(gremlin.ui.ui_common.Color.expressionColor())
            expression_widget = gremlin.ui.ui_common.QIconLabel(icon, input_id.expression, data = data)
            widget.addWidget(expression_widget)
            # cause the widget to update if the state expression changes
            sd.expression_changed.connect(self._create_expression_update_callback(input_id, expression_widget))
        else:
            widget.addWidget(QtWidgets.QLabel(f"Default: {input_id.display_value}"))


            
        # widget.disable_close()
        # widget.disable_edit()
        widget.setIcon("mdi.state-machine")



        # remember what widget is at what index
        widget.index = index
        return widget

    def _create_expression_update_callback(self, state, widget):
        return lambda: self._change_expression_callback(state, widget)
        
    def _change_expression_callback(self, state, widget):
        if Shiboken.isValid(widget):
            if widget.data.input_id == state:
                widget.setText(state.expression)
    
    def _set_status(self, widget, icon = None, status = None, use_qta = True, color = None):
        ''' sets the status of an input widget '''
        status_widget = widget.findChild(gremlin.ui.ui_common.QIconLabel, "status")
        if color:
            status_widget.setIcon(icon, use_qta = use_qta, color = color)
        else:
            status_widget.setIcon(icon, use_qta = use_qta)
        
        status_widget.setText(status)
        status_widget.setVisible(status is not None)    


    


    def _update_input_widget(self, input_widget, container_widget):
        ''' called when the widget has to update itself on a data change '''
        pass
 

    def _populate_input_widget_ui(self, input_widget, container_widget, data):
        ''' called when a button is created for custom content '''
        layout = QtWidgets.QVBoxLayout(container_widget)
        status_widget = gremlin.ui.ui_common.QIconLabel()
        status_widget.setObjectName("status")
        layout.addWidget(status_widget)
        self._update_input_widget(input_widget, container_widget)





    def _index_for_key(self, input_id):
        ''' returns the index of the selected input id'''
        sd = StateData()
        return sd.index(input_id)
        

    def _create_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.input_item_list_view.redraw_index(index)

    def set_mode(self, mode):
        ''' changes the mode of the tab '''        
        self.current_mode = mode
        
        self.input_item_list_model.mode = mode
        
        #self.input_item_list_view.select_item(-1)
        if gremlin.shared_state.isDeviceTabActive(self.device_guid):
            self.input_item_list_model.refresh()
            self.input_item_list_view.redraw()        
            self._select_item_cb(self._last_selected_index)

 




_state_categories = StateCategories()
_state_data = StateData()
_category_validator = CategoryValidator()