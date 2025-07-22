

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


class ModeInputModeType(enum.IntEnum):
    ''' possible input modes '''
    ModeEnter = 0  # executes on mode enter
    ModeExit = 1 # executes on mode exit
    ModeGlobalEnter = 2 # executes on any mode change (activate)
    ModeGlobalExit = 3 # executes on any mode change (deactivate)

    @staticmethod
    def to_display_name(value):
        match value:
            case ModeInputModeType.ModeEnter:
                return "Mode Activate"
            case ModeInputModeType.ModeExit:
                return "Mode Deactivate"
            case ModeInputModeType.ModeGlobalEnter:
                return "Mode Activate (any)"
            case ModeInputModeType.ModeGlobalExit:
                return "Mode Deactivate (any)"
        
        return f"Unknown mode: {value}"
    

class StateCategory():
    ''' holds a state category '''
    def __init__(self, name : str, id = None):
        self._id = gremlin.util.get_guid() if id is None else id
        self._name = name.casefold().strip() if name else None


    @property
    def name(self) -> str:
        return self._name
    
    @name.setter
    def name(self, value : str):
        if value:
            value = value.casefold().strip()
        self._name = value

    @property
    def id(self) -> str:
        return self._id
    @id.setter
    def id(self, value : str):
        self._id = value

    def __eq__(self, value : StateCategory):
        if value is None: return False
        return self._id == value.id

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

    def _update_categories(self):
        if not self._cm:
            self._cm = StateCategories()
            self._cm.changed.connect(self._update_categories)
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
        self._categories = {}
        self._ensure_categories()
        


    def default(self) -> StateCategory:
        ''' returns the default category (hard coded) - states with no categories use this '''
        return self._default_category
        

    def _ensure_categories(self):
        ''' adds the default category if missing '''
        self._categories[self._default_category.name] = self._default_category

    def from_xml(self, root : ElementTree.Element):
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
        return [name for name in self._categories.keys()]

    def _sort(self):
        ''' sorts the category list '''
        if self._categories:

            keys = [key for key in self._categories.keys()]
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
        ''' updates the list of category objects '''
        new_map = {}
        for category in categories:
            new_map[category.name] = category
        self._categories = new_map
        self._sort()



    def getSelector(self, changed_callback = None, default_category : StateCategory = None, editable = False) -> gremlin.ui.ui_common.QDataComboBox:
        ''' gets a selector combo box for categories '''
        widget = gremlin.ui.ui_common.QDataComboBox()
        widget.setEditable(editable)
        widget.setValidator(CategoryValidator())
        widget.addItem(self._default_category.name, self._default_category)
        index = 0
        select_index = None
        default_id = default_category.id if default_category else None
        for category in self._categories.values():
            widget.addItem(category.name, category)
            if default_id and default_id == category.id:
                select_index = index
            index +=1 
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
                    


class StateInputItem(AbstractInputItem):
    ''' holds a single state '''
    changed = Signal(object) # fires when a state changes (state)
    key_changed = Signal() # fires when the key changes

    MAX_STACK_SIZE = 100 # maximum number of expressions in a stack (circuit breaker to detect recursion)
    

    def __init__(self, key : str = None, default_value = False, description = None, is_expression = False, expression = None):
        super().__init__()
        self._id = gremlin.util.get_guid()
        self._key = key
        self._category = None # category (StateCategory)
        self._default_value = default_value
        self._value = default_value
        self._type_cast = type(default_value) if default_value is not None else None
        self.setDescription(description) # parent property
        self._expression = expression # expression to evaluate to derive a state
        self._is_expression = is_expression
        self._expression_stack = [] # expression stack to evaluate
        self._dirty = True # indicates the state is stale and must be recomputed (expressions only)
        self._expression_states = [] # dependent expression states - list of states that need to be evaluated when they change
        self._last_expression_value = False # last computed expression result
        
        item = gremlin.base_profile.InputItem() #self._custom_name_handler)
        item.input_id = self
        item.input_type = InputType.State
        item.device_name = "State"
        item.device_type = DeviceType.State
        item.device_guid = gremlin.shared_state.state_tab_guid
        item.setOverrideInputType(InputType.JoystickButton)

        self._input_item = item

    def clone(self):
        ''' clones the input item (gives it a new ID)'''
        return StateInputItem(self.key, self.default_value, self.description, self.isExpression, self.expression)
        
    
    def getOverrideInputType(self):
        ''' override type '''
        return InputType.JoystickButton
    
    @property
    def id(self) -> str:
        return self._id
    @id.setter
    def id(self, value : str):
        self._id = value



    @property
    def category(self) -> StateCategory:
        ''' category for the state '''
        return self._category
    
    def setCategory(self, category : StateCategory):
        if self._category != category:
            self._category = category
    
    @property
    def category_name(self) -> str:
        if self._category:
            return self._category.name
        # return default category name
        cm = StateCategories()
        return cm.default().name
    
    @property
    def category_id(self) -> str:
        if self._category:
            return self._category.id
        # return default category ID
        cm = StateCategories()
        return cm.default().id 
        
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
    def value(self):
        return self.evaluate()
    
    @value.setter
    def value(self, data):
        if not self._expression and self._value != data:
            # only set value on non expression states and only if the value has changed
            self._value = data
            self._fire_changed(data)

    def toggle(self):
        ''' toggles the state '''
        if not self._expression:
            # only toggle non-expression states
            self._value = not self._value
            self.changed.emit(self)
            return self._value
        return None

    @property
    def default_value(self):
        return self._default_value
    
    @default_value.setter
    def default_value(self, data):
        if self._default_value != data:
            self._default_value = data      
            if data != self._value:
                self._value = data  
                self._fire_changed(data)

    @property
    def key(self)-> str:
        return self._key
    @key.setter
    def key(self, value : str):
        value = value.casefold().strip()
        if self._key != value:
            self._key = value
            self.key_changed.emit()
    
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
                self._fire_changed(derived_value)
    

    @property
    def input_item(self):
        ''' holds a reference to the mapping data for this input '''
        return self._input_item
    # @input_item.setter
    # def input_item(self, value):
    #     self._input_item = value

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
            node.set("category_id", self._category.id)
        
        if self._description:
            node.set("description", self._description)

        if self._expression:
            node.set("expression", self._expression)
        node.set("is_expression", safe_format(self._is_expression, bool))

        # write container data
        self._input_item.to_xml(node)
        

        return node
    
    def from_xml(self, node, data = None):
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
        if "is_expression" in node.attrib:
            self._is_expression = safe_read(node,"is_expression",bool, False)
        else:
            # suitable default based on existing value
            self._is_expression = bool(self.expression)

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


        # hook the dependent states
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

        if as_tuple:
            return (output,False,None)
        return output
    
    
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
        return f"State: [{self._key}]"

    def __hash__(self):
        return hash(self._key)

        

    
    

@SingletonDecorator
class StateData(QtCore.QObject):
    ''' holds state information '''
    changed  = Signal(object) # fires when the value changes (StateItem)
    crud = Signal() # fires when a state is added or removed or changed

    def __init__(self):
        super().__init__()
        self._data = {}
        self._id_map = {}
        self.changed.connect(self._state_changed)
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._reset)

    def _reset(self):
        ''' reset states to default values '''
        to_evaluate = []
        for data in self._data.values():
            if data.expression:
                # initial evaluation
                to_evaluate.append(data)
            else:
                data.value = data.default_value

        # evaluate expressions based on initial data values
        for data in to_evaluate:
            data.evaluate(force=True)

    def _register(self, key : str, value = None, description = None) -> StateInputItem:
        ''' registers a new state '''
        if not key:
            return None
        key = key.casefold().strip()
        if key in self._data:
            # already in the list
            return self._data[key]
        
        item = StateInputItem(key, value, description)    
        self._data[key] = item
        self._id_map[item.id] = item
        self.crud.emit()
        item.key_changed.connect(self._key_changed)
        return item
    
    @QtCore.Slot()
    def _key_changed(self):
        ''' occurs on a key change'''
        self.crud.emit()
    
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
            id = self._data[key].id
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
            data.key_changed.connect(self._key_changed)
            if emit:
                self.crud.emit()
    

    def _sort(self):
        self._data = dict(sorted(self._data.items()))

    def getStates(self):
        ''' gets all input items '''
        return self._data
    
    def getStateNames(self):
        ''' gets the list of states currently defined '''
        return list(self._data.keys())
    
    def getInputItems(self):
        ''' gets a dict of input items for each state'''
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

    def setValue(self, key : str, value, emit = True):
        ''' sets state value (and registers if needed) '''
        if not key:
            return
        
        key = key.casefold().strip()
        trigger = not key in self._data or self._data[key].value != value
        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose: syslog.info(f"STATE: [{key}] -> {value}")
        self._data[key].value = value
        if emit and trigger:
            self.changed.emit(self._data[key])   
            QtWidgets.QApplication.processEvents()
    
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
            del self._data[key]
            del self._id_map[data.id]
            self.crud.emit()

    def removeId(self, id: str):
        if id in self._id_map:
            data = self._id_map[id]
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

    def from_xml(self, root):
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



class StateCategoryConfigDialog(gremlin.ui.ui_common.QRememberDialog):
    ''' dialog showing the category configuration options '''

    def __init__(self, parent = None):
        '''
        :param index - the input item index zero based
        :param identifier - the input item identifier 
        '''
        
        super().__init__(self.__class__.__name__,parent = parent)

        self._curent_category = None # contains the name of the new category

        
        main_layout = QtWidgets.QVBoxLayout(self)
        self.setWindowTitle("Category Editor")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._parent = parent # list view

        self._cm = StateCategories()
        self._list_view = QtWidgets.QListView()
        self._model = gremlin.ui.ui_common.QSimpleModel()
        self._list_view.setModel(self._model)
        
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
        self._edit_widget.textChanged.connect(self._new_category_changed_cb)

        widget, layout = gremlin.ui.ui_common.getHContainer([self._edit_widget, self._add_button, self._delete_button],"New Category:")
        main_layout.addWidget(widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget, layout = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True)
        
        main_layout.addWidget(widget)

        self._update()

    def _update(self):
        name = self._curent_category
        if name:
            name = name.casefold().strip()
        self._add_button.setEnabled(bool(name))

    @QtCore.Slot()
    def _delete_cb(self):
        """Callback executed when the delete button is pressed."""

        indices = self._list_view.selectedIndexes()
        if indices:

            # warn box 
            msgbox = gremlin.ui.ui_common.ConfirmBox(f"Delete selected entries?")
            result = msgbox.show()

            if result == QtWidgets.QMessageBox.StandardButton.Ok:
                rows = [idx.row() for idx in indices]
                keep = []
                for index, item in enumerate(self._model.items()):
                    if index in rows:
                        continue
                    keep.append(item)
                
                self._model.clear()
                for item in keep:
                    self._model.addItem(item.name, item)

                # select the first item kept
                if keep:
                    self.list_view.setCurrentIndex(self.model.index(0,0))
    @QtCore.Slot()
    def _new_category_changed_cb(self):
        self._curent_category = self._edit_widget.text()
        self._update()

    @QtCore.Slot()
    def _edit_category_cb(self):
        pass



    @QtCore.Slot()
    def _add_input_cb(self):
        name = self._curent_category
        if name:
            name = name.casefold().strip()
        if name:
            if self._cm.findByName(name):
                gremlin.ui.ui_common.MessageBox(title = "Category Error", prompt = f"Category [{name}] already exists.")
            else:
                category = StateCategory(name)
                self._model.addItem(name, category)
                



     
    def _ok_button_cb(self):
        ''' ok button pressed '''
        self.accept()   

    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()        
                
    def getCategories(self) -> list:
        ''' gets a list of edited categories '''
        return self._model.items()

        



    def populate_ui(self):
        self._list_view.items().clear()
        for category in self._cm.getCategories():
            item = QtWidgets.QListWidgetItem()
            item.setText(category.name)
            item.setData(category)
            self._list_view.addItem(item)

        


class StateInputConfigDialog(gremlin.ui.ui_common.QRememberDialog):
    ''' dialog showing the state input configuration options '''

    def __init__(self, data : StateInputItem, parent):
        '''
        :param index - the input item index zero based
        :param identifier - the input item identifier 
        '''
        
        super().__init__(self.__class__.__name__,parent = parent)

        gremlin.shared_state.push_suspend_highlighting() # prevent device highlight changes while editing a state 

        # self._sequence = InputKeyboardModel(sequence=sequence)
        main_layout = QtWidgets.QVBoxLayout()
        self.setWindowTitle("State Editor")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._parent = parent # list view
        

        main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(main_layout)

        self._config_widget, self._config_layout = gremlin.ui.ui_common.getGridContainer()
        self.data = data

        self._name_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._name_widget.setText(data.key)
        self._name_widget.textChanged.connect(self._name_changed)


        self._is_expression_widget = QtWidgets.QCheckBox("This state is an expression")
        self._is_expression_widget.setToolTip("If enabled, the state uses an expression to derive its value.  If not set, a default value on start can be set.")
        self._is_expression_widget.setChecked(self.data.isExpression)
        self._is_expression_widget.clicked.connect(self._is_expression_changed)

        self._expression_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._expression_widget.setText(data.expression)
        self._expression_widget.textChanged.connect(self._expression_changed)

        self._test_widget = QtWidgets.QPushButton("Test")
        self._test_widget.setToolTip("Tests the state expression")
        self._test_widget.clicked.connect(self._test_expression)
        self._test_widget.setEnabled(bool(data.expression))


        self._description_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._description_widget.setText(data._description)
        self._description_widget.textChanged.connect(self._description_changed)

        self._cm = StateCategories()


        self._category_selector_widget = self._cm.getSelector(self._category_changed_cb)
        if self.data.category:
            index = self._category_selector_widget.findData(self.data.category)
            if index != -1:
                with QtCore.QSignalBlocker(self._category_selector_widget):
                    self._category_selector_widget.setCurrentIndex(index)
        self._category_config_widget = QtWidgets.QPushButton()
        self._category_config_widget.setIcon(gremlin.ui.ui_common.Icons.gearIcon())
        self._category_config_widget.setMaximumWidth(24)
        self._category_config_widget.clicked.connect(self._category_config_cb)

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
        
        self._default_on_widget = gremlin.ui.ui_common.QDataRadioButton("On", True)
        self._default_off_widget = gremlin.ui.ui_common.QDataRadioButton("Off", False)
        if data.default_value:
            self._default_on_widget.setChecked(True)
        else:
            self._default_off_widget.setChecked(True)
        self._default_off_widget.clicked.connect(self._default_changed)    
        self._default_on_widget.clicked.connect(self._default_changed)

        self._default_container_widget, _ = gremlin.ui.ui_common.getHContainer([self._default_on_widget, self._default_off_widget],"Default State:")
        self._config_layout.addWidget(self._default_container_widget, row, col, 1, -1)

        main_layout.addWidget(self._config_widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget, layout = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True)
        
        main_layout.addWidget(widget)
        self._update_ui()

    def _category_changed_cb(self, index):
        ''' called when selected command changes '''
        category = self._category_selector_widget.currentData()
        self.data.setCategory(category)
        index = self._category_selector_widget.findData(category)
        if index == -1:
            self._cm.updateSelector(self._category_selector_widget)
            index = self._category_selector_widget.findData(category)
        if index != -1:
            self._category_selector_widget.setCurrentIndex(index)
        
        

    def _category_config_cb(self):
        self._category_dialog = StateCategoryConfigDialog()
        self._category_dialog.accepted.connect(self._category_updated)
        self._category_dialog.show()

    def _category_updated(self):
        categories = self._category_dialog.getCategories()
        if categories:
            self._cm.setCategories(categories)
            self._cm.updateSelector(self._category_selector_widget)

    def _validate(self):
        sd = StateData()
        enabled = bool(self.data.key)
        if enabled:
            item = sd.getState(self.data.key)
            if item:
                enabled = item.id == self.data.id

        self.ok_widget.setEnabled(enabled)


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
        if key:
            key_low = self.data.key.casefold().strip()
            if key_low:
                id = self.data.id
                sc = StateData()
                data = sc.getStates()
                if not is_expression:
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


class  StateFilterWidget(QtWidgets.QWidget):
    ''' displays a filter widget that can be enabled, and a state category selected '''
    changed = Signal(StateCategory)  # fires when the category is changed
        
    def __init__(self, parent = None):
        super().__init__(parent)

        self._config = gremlin.config.Configuration()

         # filter widget
        cm = StateCategories()
        category_id = self._config.state_category_filter
        category = cm.findById(category_id)
        self._category_filter = category

        self.filter_enabled_widget = QtWidgets.QCheckBox("Enable Filtering")
        self.filter_enabled_widget.setToolTip("Enables filtering on the state list by category")
        is_filter = self._config.state_filter_enabled
        self.filter_enabled_widget.setChecked(is_filter)
        self.filter_enabled_widget.clicked.connect(self._filter_enabled_changed)

        self.filter_widget = cm.getSelector(self._category_filter_changed, category)
        self.filter_widget.setEnabled(is_filter)
        self.filter_widget.setEditable(False) # don't allow editing of categories for the main filter
        widget, layout = gremlin.ui.ui_common.getHContainer([self.filter_enabled_widget, QtWidgets.QLabel(" Filter:"), self.filter_widget])
        self.setLayout(layout)

    @QtCore.Slot(bool)
    def _filter_enabled_changed(self, is_filter):
        self._config.state_filter_enabled = is_filter
        self.filter_widget.setEnabled(is_filter) 
        has_categories = self.filter_widget.count()
        category = self.filter_widget.currentData() if is_filter and has_categories else None
        self.changed.emit(category)

    @QtCore.Slot()
    def _category_filter_changed(self):
        ''' called when the state category filter is changed '''
        category = self.filter_widget.currentData()
        self._category_filter = category
        gremlin.config.Configuration().state_category_filter = category.id if category else ""
        self.changed.emit(category)

    @property
    def category(self) -> StateCategory:
        ''' current category'''
        return self._category_filter
        
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
        

        self.filter_widget = StateFilterWidget()
        self.filter_widget.changed.connect(self._category_filter_changed)
        self._category_filter = self.filter_widget.category # current category

        config = gremlin.config.Configuration()
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
        
        self.addLeftPanelWidget(self.filter_widget)


        # data model
        self.input_item_list_model = input_item.InputItemListModel(
            device_profile,
            current_mode,
            [InputType.State], # only allow Mode inputs for this widget,
            custom_update_handler= self._update_handler,
            custom_remove_handler = self._remove_handler,
            custom_clear_handler = self._clear_handler
        )        

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
        find_button = QtWidgets.QPushButton()
        icon = gremlin.ui.ui_common.Icons.findIcon()
        find_button.setIcon(icon)
        find_button.setToolTip("Find State")
        find_button.clicked.connect(self._find_input_cb)
        button_container_layout.addWidget(find_button)

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

        

        # el = gremlin.event_handler.EventListener()
        # el.mode_name_changed.connect(self._mode_name_changed)
        # el.edit_mode_changed.connect(self._edit_mode_changed_cb) # edit mode changed or mode added/removed
        

        # last index selected, -1 means none
        self._last_selected_index = -1 


        
        # Select default entry
        selected_index = self.input_item_list_view.current_index
        if selected_index is None:
            selected_index = -1
        self._select_item_cb(selected_index)


    def _show_clear_cb(self):
        return self.input_item_list_model.rows() > 0

    def _config_changed_cb(self):
        ''' called when configuraition has changed '''
        self.refresh()      

    @QtCore.Slot(bool)
    def _filter_enabled_changed(self, is_filter):
        config = gremlin.config.Configuration()
        config.state_filter_enabled = is_filter
        self.filter_widget.setEnabled(is_filter)
        self.refresh()

    @QtCore.Slot(StateCategory)
    def _category_filter_changed(self, category):
        ''' called when the state category filter is changed '''
        self._category_filter = category
        self.refresh()




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
        """Adds a new state to the inputs list  """
        input_id = StateInputItem()
        index = self.input_item_list_model.add(input_id)
        self._edit_dialog = StateInputConfigDialog(input_id, self)
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
        self._edit_dialog = StateInputConfigDialog(tmp_input_id, self)
        self._edit_dialog.accepted.connect(self._dialog_ok_edit_cb)
        gremlin.util.centerDialog(self._edit_dialog)
        self._edit_dialog.showNormal()
        self._edit_item = input_id
        self._edit_item_index = index
        self._is_edit = True
        self._index = index

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
        if not sd.exists(data.key):
            sd.add(data)
            self.input_item_list_model.refresh()
        else:
            syslog.warning(f"STATE: [{data.key}] already exists, ignoring edit")
            return 
        


        # index = sd.index(data)
        index = self._edit_item_index
        identifier = self.input_item_list_model.data(index)
        input_item : StateInputItem = identifier.input_id
        input_item.key = data.key
        input_item.setDescription(data.description)
        input_item.default_value = data.default_value
        self.refresh()
        self._select_item_cb(index)

        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_id)            

    def _dialog_ok_edit_cb(self):        
        ''' called when edit dialog closes with ok on an edited state '''
        data = self._edit_dialog.data
        sd = StateData()
        trigger = False
        if self._edit_item._key != data.key:
            sd.unregister(self._edit_item.key) # remove the old
            self._edit_item._key = data.key # change the key and don't fire the event
            sd.add(self._edit_item, False) # this fires the event
            trigger = True
        self._edit_item.description = data.description
        self._edit_item.setCategory(data.category)
        self._edit_item.expression = data.expression
        self.input_item_list_model.refresh()
        index = sd.index(self._edit_item)
        self.refresh()
        self._select_item_cb(index)
        if trigger:
            sd.crud.emit()

        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_id)


    def _clear_inputs_cb(self):
        ''' clears all input keys '''
        self.input_item_list_model.clear(input_types=[InputType.State])
        self.input_item_list_view.redraw()

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

        config = gremlin.config.Configuration()
        is_filter = config.state_filter_enabled


        cm = StateCategories()
        default_category = cm.default()
        category = None
        if is_filter:
            category = self._category_filter 
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
            index += 1
            
        
        if changed and emit_change:
            model.data_changed.emit()

    def _remove_handler(self, model, index, emit_change = True):
        ''' clears a single index '''
        if index in model._index_map:
            item = model._index_map[index]
            key = item.input_id.key
            sd = StateData()
            sd.remove(key)
            self._update_handler(model, emit_change)
            

    def _clear_handler(self, model, emit_change = True):
        ''' clears all state data '''
        model._index_map = {}
        model._item_map = {}
        model.data_changed.emit()
        sd = StateData()
        sd.clear()
        if emit_change:
            model.data_changed.emit()

    
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
    
     
    def getWidgetKey(self, input_id):
        ''' gets the content widget compound key for the item / input combination'''
        return (self.device_guid, input_id)



    def refresh(self, emit = True):
        """Refreshes the current selection, ensuring proper synchronization."""
        #self.set_mode(gremlin.shared_state.edit_mode) # force a model and reload
        self.input_item_list_view.redraw()
        self._select_item_cb(self.input_item_list_view.current_index, emit)

    def _select_item_cb(self, index, emit = True):
        """Handles the selection of an input item.

        :param index the index of the selected item
        """
        import gremlin.ui.input_item
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
        input_id = item_data.input_id
        key = self.getWidgetKey(input_id)
        widget = self.getRegisteredWidget(key)
        if not widget:
            widget = gremlin.ui.input_item.InputItemConfigurationWidget(item_data, object_name=f"STATE: {item_data.input_id.key}")
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

        widget = gremlin.ui.input_item.InputItemWidget(identifier = identifier, populate_ui_callback = self._populate_input_widget_ui, update_callback = self._update_input_widget, config_external=True, parent = parent)
        widget.data = data
        widget.create_action_icons(data)
        input_id : StateInputItem = data.input_id

        
        title = f"State: [{input_id.key}] [{input_id.id}]" if gremlin.config.Configuration().show_container_id else f"State: [{input_id.key}]"
        widget.setTitle(title)
        layout = widget.content_layout
        gremlin.util.clear_layout(layout)

        if input_id.description:
            layout.addWidget(QtWidgets.QLabel(f"{input_id.description}"))
        
        
        
        category_name =input_id.category_name
        if category_name:
            layout.addWidget(QtWidgets.QLabel(f"Category: [{category_name}]"))

        if input_id.expression:
            icon = gremlin.ui.ui_common.Icons.calculateIcon(gremlin.ui.ui_common.Color.expressionColor())
            layout.addWidget(gremlin.ui.ui_common.QIconLabel(icon, input_id.expression))
        else:
            layout.addWidget(QtWidgets.QLabel(f"Default: {input_id.display_value}"))
            
        # widget.disable_close()
        # widget.disable_edit()
        widget.setIcon("mdi.state-machine")



        # remember what widget is at what index
        widget.index = index
        return widget

   
    
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