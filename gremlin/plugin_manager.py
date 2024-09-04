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


import importlib
import logging
import os
import copy

from . import common, error
from gremlin.util import *

from gremlin.singleton_decorator import SingletonDecorator


@SingletonDecorator
class ContainerPlugins:

    """Handles discovery and handling of container plugins."""

    def __init__(self):
        """Initializes the container plugin manager."""
        self._plugins = {}
        self._discover_plugins()

        self._tag_to_type_map = {}
        self._name_to_type_map = {}
        # tracks all functors
        self._functors = []

        self._create_maps()

        self._parent_widget_map = {} # map of item data to QT widget main UI container widget
        self._input_data_container_map = {} # map of item data to the actual containers created for it

        
    def reset_functors(self):
        ''' clears functor tracking '''
        self._functors = []

    def register_functor(self, functor):
        ''' registers a functor for latching purposes'''
        if not functor in self._functors:
            self._functors.append(functor)

    @property
    def functors(self):
        return self._functors

    @property
    def repository(self):
        """Returns the dictionary of all found plugins.

        :return dictionary containing all plugins found
        """
        return self._plugins
    
    def set_widget(self, item_data, widget):
        ''' sets the associated parent widget of a container for the specific input type'''
        self._parent_widget_map[item_data] = widget

    def get_widget(self, item_data):
        ''' gets the associated parent widget of a container for the specific input type '''
        if item_data in self._parent_widget_map.keys():
            return self._parent_widget_map[item_data]
        return None
    
    def set_container_data(self, item_data, container):
        if not item_data in self._input_data_container_map.keys():
            self._input_data_container_map[item_data] = []
        if not container in self._input_data_container_map[item_data]:
            self._input_data_container_map[item_data].append(container)

    def get_container(self, item_data):
        if not item_data in self._input_data_container_map.keys():
            return []
        return self._input_data_container_map[item_data]
    
    def get_parent_widget(self, container):
        ''' gets the parent widget of the given container '''
        for item_data, containers in self._input_data_container_map.items():
            for container_item in containers:
                if container == container_item:
                    return self.get_widget(item_data)
        # not found for this container
        return None


    @property
    def tag_map(self):
        """Returns the mapping from a container tag to the container plugin.

        :return mapping from container name to container plugin
        """
        return self._tag_to_type_map

    def get_class(self, name):
        """Returns the class object corresponding to the given name.

        :param name of the container class to return
        :return class object corresponding to the provided name
        """
        if name not in self._name_to_type_map:
            raise error.GremlinError(
                f"No container with name '{name}' exists"
            )
        return self._name_to_type_map[name]

    def _discover_plugins(self):
        """Processes known plugin folders for action plugins."""
        import gremlin.shared_state
        plugin_folder = "container_plugins"
        root_path = gremlin.shared_state.root_path
        walk_path = os.path.join(root_path, plugin_folder)
        log_sys(f"Using container plugin folder: {walk_path}")
        if not os.path.isdir(walk_path):
            raise error(f"Unable to find container plugins: {walk_path}")
        
        for root, dirs, files in os.walk(walk_path):
            for fname in [v for v in files if v == "__init__.py"]:
                try:
                    folder, module = os.path.split(root)

                    if not folder.lower().endswith(plugin_folder):
                        continue

                    # Attempt to load the file and if it looks like a proper
                    # action_plugins store it in the registry
                    plugin = importlib.import_module(
                        f"container_plugins.{module}"
                    )
                    if "version" in plugin.__dict__:
                        self._plugins[plugin.name] = plugin.create
                        log_sys(f"\tLoaded container plugin: {plugin.name}"
                        )
                    else:
                        del plugin
                except Exception as e:
                    # Log an error and ignore the action_plugins if
                    # anything is wrong with it
                    logging.getLogger("system").warning(
                        f"\tLoading container_plugins '{fname}' failed due to: {e}"
                    )

    def _create_maps(self):
        """Creates a lookup table from container tag to container object."""
        for entry in self._plugins.values():
            self._tag_to_type_map[entry.tag] = entry
            self._name_to_type_map[entry.name] = entry

    def duplicate(self, container):
        ''' duplicates a container '''
        # because containers can be quite complex - we'll just generate the xml and change IDs as needed and reload
        # into a new container of the same type
        from gremlin.base_profile import AbstractContainer
        from gremlin.util import get_guid
        assert isinstance(container, AbstractContainer),"Invalid container data for duplicate()"
        container_item = copy.deepcopy(container)

        for action_set in container_item.get_action_sets():
            for action in action_set:
                action.action_id = get_guid()
        
        return container_item




    

       


@SingletonDecorator
class ActionPlugins:

    """Handles discovery and handling of action plugins."""

    def __init__(self):
        """Initializes the action plugin manager."""
        self._plugins = {}
        self._type_to_action_map = {}
        self._type_to_name_map = {}
        self._name_to_type_map = {}
        self._tag_to_type_map = {}
        self._parameter_requirements = {}

        self._discover_plugins()

        self._create_type_action_map()
        self._create_action_name_map()

    @property
    def repository(self):
        """Returns the dictionary of all found plugins.

        :return dictionary containing all plugins found
        """
        return self._plugins

    @property
    def type_action_map(self):
        """Returns a mapping from input types to valid action plugins.

        :return mapping from input types to associated actions
        """
        return self._type_to_action_map

    @property
    def tag_map(self):
        """Returns the mapping from an action tag to the action plugin.

        :return mapping from action name to action plugin
        """
        return self._tag_to_type_map

    def get_class(self, name):
        """Returns the class object corresponding to the given name.

        :param name of the action class to return
        :return class object corresponding to the provided name
        """
        if name not in self._name_to_type_map:
            raise error.GremlinError(
                f"No action with name '{name}' exists"
            )
        return self._name_to_type_map[name]

    def plugins_requiring_parameter(self, param_name):
        """Returns the list of plugins requiring a certain parameter.

        :param param_name the parameter name required by the returned actions
        :return list of actions requiring a certain parameter in the callback
        """
        return self._parameter_requirements.get(param_name, [])

    def _create_type_action_map(self):
        """Creates a lookup table from input types to available actions."""
        self._type_to_action_map = {}
        for input_type in common.InputType.to_list():
            self._type_to_action_map[input_type] = []
        
        for entry in self._plugins.values():
            for input_type in entry.input_types:
                self._type_to_action_map[input_type].append(entry)

    def _create_action_name_map(self):
        """Creates a lookup table from action names to actions."""
        for entry in self._plugins.values():
            self._name_to_type_map[entry.name] = entry
            self._tag_to_type_map[entry.tag] = entry

    def _discover_plugins(self):
        """Processes known plugin folders for action plugins."""
        import gremlin.shared_state
        plugin_folder = "action_plugins"
        root_path = gremlin.shared_state.root_path
        walk_path = os.path.join(root_path, plugin_folder)
        log_sys(f"Using action plugin folder: {walk_path}")
        if not os.path.isdir(walk_path):
            raise error(f"Unable to find action_plugins: {walk_path}")
        
        for root, dirs, files in os.walk(walk_path):
            for _ in [v for v in files if v == "__init__.py"]:
                try:
                    folder, module = os.path.split(root)
                    if not folder.lower().endswith(plugin_folder):
                        continue

                    # Attempt to load the file and if it looks like a proper
                    # action_plugins store it in the registry
                    plugin = importlib.import_module(
                        f"action_plugins.{module}"
                    )
                    if "version" in plugin.__dict__:
                        self._plugins[plugin.name] = plugin.create
                        log_sys(f"\tLoaded action plugin: {plugin.name}")
                    else:
                        del plugin
                except Exception as e:
                    # Log an error and ignore the action_plugins if
                    # anything is wrong with it
                    log_sys_warn(f"\tLoading action_plugins '{root.split("\\")[-1]}' failed due to: {e}")


    def duplicate(self, action):
        ''' duplicates an action and gives it a unique ID '''
        from gremlin.util import get_guid
        dup = copy.deepcopy(action)
        dup.parent = action.parent
        dup.action_id = get_guid()
        return dup
    
