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

from __future__ import annotations  # deprecated with python 3.14+
import importlib
import logging
import os

from . import common, error
from gremlin.util import get_guid, toUrl

from gremlin.singleton_decorator import SingletonDecorator

syslog = logging.getLogger("system")


@SingletonDecorator
class ContainerPlugins:
    """Handles discovery and handling of container plugins."""

    def __init__(self):
        """Initializes the container plugin manager."""
        self.reset()

    def reset(self):
        """resets the plugins"""
        self._plugins = {}
        self._discover_plugins()

        self._tag_to_type_map = {}
        self._name_to_type_map = {}
        # tracks all functors

        self._functors = []

        self._create_maps()

        self._parent_widget_map = {}  # map of item data to QT widget main UI container widget
        self._input_data_container_map = {}  # map of item data to the actual containers created for it

    def reset_functors(self):
        """clears functor tracking"""
        self._functors = []

    def register_functor(self, functor):
        """registers a functor for latching purposes"""
        if functor not in self._functors:
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
        """sets the associated parent widget of a container for the specific input type"""
        self._parent_widget_map[item_data] = widget

    def get_widget(self, item_data):
        """gets the associated parent widget of a container for the specific input type"""
        if item_data in self._parent_widget_map.keys():
            return self._parent_widget_map[item_data]
        return None

    def set_container_data(self, item_data, container):
        if item_data not in self._input_data_container_map.keys():
            self._input_data_container_map[item_data] = []
        if container not in self._input_data_container_map[item_data]:
            self._input_data_container_map[item_data].append(container)

    def get_container(self, item_data):
        if item_data not in self._input_data_container_map.keys():
            return []
        return self._input_data_container_map[item_data]

    def get_parent_widget(self, container):
        """gets the parent widget of the given container"""
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
            raise error.GremlinError(f"No container with name '{name}' exists")
        return self._name_to_type_map[name]

    def _discover_plugins(self):
        """Processes known plugin folders for action plugins."""
        import gremlin.shared_state

        plugin_folder = "container_plugins"
        root_path = gremlin.shared_state.root_path
        walk_path = os.path.join(root_path, plugin_folder)
        syslog.info(f"Containers: Using container plugin folder: {toUrl(walk_path)}")
        if not os.path.isdir(walk_path):
            raise error(f"Unable to find container plugins: {walk_path}")

        loaded_count = 0
        for root, dirs, files in os.walk(walk_path):
            for fname in [v for v in files if v == "__init__.py"]:
                try:
                    folder, module = os.path.split(root)

                    if not folder.lower().endswith(plugin_folder):
                        continue

                    # Attempt to load the file and if it looks like a proper
                    # action_plugins store it in the registry
                    plugin = importlib.import_module(f"container_plugins.{module}")
                    if "version" in plugin.__dict__:
                        self._plugins[plugin.name] = plugin.create
                        syslog.info(f"\tFound: {plugin.name}")
                        loaded_count += 1
                    else:
                        del plugin
                except Exception as e:
                    # Log an error and ignore the action_plugins if
                    # anything is wrong with it
                    syslog.warning(f"\tLoading container_plugins '{fname}' failed due to: {e}")

        syslog.info(f"\tLoaded {loaded_count} container plugins")

    def _create_maps(self):
        """Creates a lookup table from container tag to container object."""
        for entry in self._plugins.values():
            self._tag_to_type_map[entry.tag] = entry
            self._name_to_type_map[entry.name] = entry

    def duplicate(self, container, input_item=None):
        """duplicates a container"""
        # because containers can be quite complex - we'll just generate the xml and change IDs as needed and reload
        # into a new container of the same type
        from gremlin.input_item import AbstractContainer, InputItem

        assert isinstance(container, AbstractContainer), "Invalid container data for duplicate()"
        assert isinstance(input_item, InputItem), "Invalid input item tyhpe for duplicate()"

        if input_item is None:
            input_item = container.parent

        node = container.to_xml()
        container_type = node.attrib["type"]
        container_tag_map = self.tag_map

        new_container = container_tag_map[container_type](input_item)
        new_container.from_xml(node, input_item)

        # new_container = copy.deepcopy(container)

        for action_set in new_container.get_action_sets():
            for action in action_set:
                action.setId(get_guid())

        return new_container


@SingletonDecorator
class ActionPlugins:
    """Handles discovery and handling of action plugins."""

    def __init__(self):
        """Initializes the action plugin manager."""
        self.reset()

    def reset(self):
        """resets the plugins"""
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
            raise error.GremlinError(f"No action with name '{name}' exists")
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
            input_types = entry.input_types
            for input_type in input_types:
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
        if not os.path.isdir(walk_path):
            raise error(f"Unable to find action_plugins: {walk_path}")

        syslog.info(f"Action plugins: {toUrl(walk_path)}")
        plugin_count = 0
        error_count = 0
        for root, dirs, files in os.walk(walk_path):
            for _ in [v for v in files if v == "__init__.py"]:
                try:
                    folder, module = os.path.split(root)
                    if not folder.lower().endswith(plugin_folder):
                        continue

                    # Attempt to load the file and if it looks like a proper
                    # action_plugins store it in the registry
                    plugin = importlib.import_module(f"action_plugins.{module}")
                    if "version" in plugin.__dict__:
                        self._plugins[plugin.name] = plugin.create
                        syslog.info(f"\tFound: {plugin.name}")
                        plugin_count += 1

                    else:
                        del plugin
                except Exception as e:
                    # Log an error and ignore the action_plugins if
                    # anything is wrong with it
                    syslog.error(f"\tLoading action_plugins '{root.split('\\')[-1]}'")
                    syslog.error(e)
                    error_count += 1

        syslog.info(f"\tLoaded {plugin_count} action plugins")
        if error_count > 0:
            syslog.error(f"{error_count} plugin(s) failed to load")

    def duplicate(self, action, container, input_item=None, extra_data: dict = None):
        """duplicates an action and gives it a unique ID"""
        import gremlin.shared_state

        if input_item is None:
            input_item = container.parent
        node = action.to_xml()
        action_tag = node.tag
        action_tag_map = self.tag_map
        new_action = action_tag_map[action_tag](container)
        if not extra_data:
            mode_object = gremlin.shared_state.current_profile.get_mode_object(gremlin.shared_state.edit_mode)
            extra_data = {"mode_object": mode_object}
        new_action.from_xml(node, input_item, extra_data)
        new_action.setId(get_guid())

        return new_action

    def fromClipboard(self, container, input_item) -> list:
        """grabs an action from the clipboard"""
        from lxml import etree
        from gremlin.clipboard import Clipboard, ObjectEncoder, EncoderType
        import gremlin.plugin_manager
        import gremlin.shared_state

        clipboard = Clipboard()
        action_list = []
        if container is None and input_item is None or input_item.parent is None:
            syslog.warning("FromClipboard: invalid container and input data")
            return None
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        if isinstance(clipboard.data, ObjectEncoder):
            item = clipboard.data
            if item.encoder_type == EncoderType.Action:
                xml = item.data
                if container is None:
                    # no container provided for the parent - can't duplicate
                    syslog.error("FromClipboard: unable to instantiate action because no container is provided")
                    return None
                if container is not None:
                    node = etree.fromstring(xml)
                    action = self.get_class(item.name)(container)
                    mode_object = gremlin.shared_state.current_profile.get_mode_object(gremlin.shared_state.edit_mode)
                    extra_data = {"mode_object": mode_object}
                    action._parse_xml(node, extra_data=extra_data)
                action_list.append(action)
            elif item.encoder_type in (EncoderType.Container, EncoderType.MultiContainer):
                # extract actions from the data
                xml = item.data
                container_nodes = []
                root = etree.fromstring(xml)
                if root.tag == "multi_containers":
                    # encoded as a multi container
                    container_nodes = root.xpath("//container[not(ancestor::container)]")
                elif root.tag == "container":
                    # encoded as a single container
                    container_nodes = [root]
                else:
                    syslog.warning(f"FromClipboard: invalid data node: {node.tag} found")
                    return None

                for node in container_nodes:
                    container_type = node.get("type")
                    # verify the container is valid for the input
                    container_tag_map = plugin_manager.tag_map
                    if container_type in container_tag_map:
                        new_container = container_tag_map[container_type](input_item)
                        new_container.from_xml(node, input_item)
                        for action_set in new_container.action_sets:
                            for action in action_set:
                                action_list.append(action)

        return action_list
