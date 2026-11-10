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


def clone_xml_for_paste(source):
    """Copy XML and replace owned IDs before readers register the pasted data."""
    from lxml import etree
    import copy

    if isinstance(source, str | bytes):
        node = etree.fromstring(source, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    elif isinstance(source, etree._Element):
        node = copy.deepcopy(source)
    else:
        raise ValueError("Clipboard data does not contain XML")
    ids = {}
    for child in node.iter():
        attributes = ["action_id", "container_id", "condition_id"]
        if child.tag == "action-set":
            attributes += ["guid", "set-guid"]
        elif child.tag in ("gate", "range"):
            attributes += ["id"]
        for attribute in attributes:
            old_id = child.get(attribute)
            if old_id:
                if old_id not in ids:
                    ids[old_id] = get_guid()
    # Resolve references after collecting every definition, including forward
    # references and range endpoints in a gated-axis mapping.
    references = {"action-id", "container-id", "condition-id", "action-ref", "container-ref", "condition-ref",
                  "action_ref", "container_ref", "condition_ref", "min_id", "max_id"}
    for child in node.iter():
        owned = {"action_id", "container_id", "condition_id"}
        if child.tag == "action-set":
            owned.update(("guid", "set-guid"))
        elif child.tag in ("gate", "range"):
            owned.add("id")
        for attribute, value in list(child.attrib.items()):
            if attribute in owned | references and value in ids:
                child.set(attribute, ids[value])
    return node


def discard_pasted_conditions(node):
    """Roll back tracker entries belonging to newly cloned XML."""
    from gremlin.input_item import ConditionTracker

    ConditionTracker().discardConditionIds(
        child.get("condition_id") for child in node.iter() if child.get("condition_id")
    )


@SingletonDecorator
class ContainerPlugins:
    """Handles discovery and handling of container plugins."""

    def __init__(self):
        """Initializes the container plugin manager."""
        self.reset()

    def reset(self):
        """resets the plugins"""
        self._plugins = {}
        self._plugins_folder_map = {} # map of plugin names to the folder
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

    def _validate_plugin(self, plugin):
        """Validates a plugin based on the current configuration."""
        import gremlin.config
        if "version" not in plugin.__dict__:
            # not one of our plugins
            return False
        return True


    def _discover_plugins(self):
        """Processes known plugin folders for action plugins."""
        import gremlin.shared_state

        plugin_folder = "container_plugins"
        root_path = gremlin.shared_state.root_path
        walk_path = os.path.join(root_path, plugin_folder)
        syslog.info(f"Containers: Using container plugin folder: {toUrl(walk_path)}")
        if not os.path.isdir(walk_path):
            raise error.GremlinError(f"Unable to find container plugins: {walk_path}")

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
                    if self._validate_plugin(plugin):
                        self._plugins[plugin.name] = plugin.create
                        self._plugins_folder_map[plugin.name] = root
                        syslog.info(f"\tFound: {plugin.name}")
                        loaded_count += 1
                    else:
                        del plugin
                except Exception as e:
                    # Log an error and ignore the action_plugins if
                    # anything is wrong with it
                    syslog.warning(f"\tLoading container_plugins '{fname}' failed due to: {e}")

        syslog.info(f"\tLoaded {loaded_count} container plugins")

    def getPluginFolderMap(self):
        """Returns a mapping from plugin names to their folder paths."""
        return self._plugins_folder_map

    def _create_maps(self):
        """Creates a lookup table from container tag to container object."""
        for entry in self._plugins.values():
            self._tag_to_type_map[entry.tag] = entry
            self._name_to_type_map[entry.name] = entry

    def save_template(self, fname, containers):
        """Save a template atomically, preserving the previous file on failure."""
        from lxml import etree
        import tempfile

        root = etree.Element("container_template")
        for container in containers:
            node = container.to_xml()
            if node is None or node.tag != "container":
                raise ValueError("A mapping could not be serialized as a container")
            root.append(node)
        tree = etree.ElementTree(root)
        target = os.path.abspath(os.fspath(fname))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=os.path.dirname(target), prefix=".gex-template-", suffix=".tmp", delete=False) as stream:
                temporary = stream.name
                tree.write(stream, pretty_print=True, xml_declaration=True, encoding="utf-8")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)
        return True

    def load_template(self, fname, input_item, extra_data=None):
        """Read new mappings with consistent IDs; attach only after validation."""
        from lxml import etree
        import gremlin.shared_state

        parser = etree.XMLParser(remove_comments=True, remove_blank_text=True, resolve_entities=False, no_network=True)
        root = etree.parse(fname, parser=parser).getroot()
        if root.tag != "container_template":
            raise ValueError("The file is not a mapping template (expected container_template)")
        root = clone_xml_for_paste(root)
        nodes = list(root)
        valid_names = input_item.get_valid_container_list()
        factories = []
        for node in nodes:
            factory = self.tag_map.get(node.get("type"))
            if node.tag != "container" or factory is None or factory.name not in valid_names:
                raise ValueError(f"Container {node.get('type', node.tag)!r} is not available for the destination input")
            factories.append(factory)
        context = dict(extra_data or {})
        context.update(input_item.toExtraData())
        context.update(paste=True, ids_regenerated=True, input_item=input_item)
        profile = gremlin.shared_state.current_profile
        if profile is not None:
            context["mode_object"] = profile.get_mode_object(input_item.profile_mode)
        containers = []
        try:
            for node, factory in zip(nodes, factories):
                container = factory(input_item)
                container.from_xml(node, input_item, dict(context))
                containers.append(container)
        except Exception:
            for node in nodes:
                discard_pasted_conditions(node)
            raise
        return containers

    def duplicate(self, container, input_item=None):
        """duplicates a container"""
        # because containers can be quite complex - we'll just generate the xml and change IDs as needed and reload
        # into a new container of the same type
        from gremlin.input_item import AbstractContainer, InputItem

        if input_item is None:
            input_item = getattr(container, "input_item", None)
        if not isinstance(container, AbstractContainer) or not isinstance(input_item, InputItem):
            raise ValueError("Invalid container or destination input for duplicate()")

        node = clone_xml_for_paste(container.to_xml())
        container_type = node.attrib["type"]
        container_tag_map = self.tag_map

        new_container = container_tag_map[container_type](input_item)
        try:
            new_container.from_xml(node, input_item, {"paste": True, "ids_regenerated": True})
        except Exception:
            discard_pasted_conditions(node)
            raise

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
        self._plugins_folder_map = {} # map of plugin names to the folder
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
            if hasattr(entry, "aliases"):
                for alias in entry.aliases:
                    self._name_to_type_map[alias] = entry
            self._name_to_type_map[entry.name] = entry
            self._name_to_type_map[entry.name] = entry
            self._tag_to_type_map[entry.tag] = entry

    def getPluginFolderMap(self):
        """Returns a mapping from plugin names to their folder paths."""
        return self._plugins_folder_map

    def _validate_plugin(self, plugin):
        """Validates that a module is a JG Ex action plugin.

        Optional features (Stream Deck / OSC / SimConnect / AFCS) must NOT gate
        discovery here. Skipping those plugins made profile load treat their XML
        tags as unknown and drop the actions; a later save then blanked mappings.
        Gate the Add Action UI via :meth:`is_action_available` instead.
        """
        if "version" not in plugin.__dict__:
            # not one of our plugins
            return False
        return True

    @staticmethod
    def is_action_available(entry) -> bool:
        """True if *entry* may be offered in the Add Action list.

        Always keep the plugin loaded for profile load/save; only hide it from
        the picker when the related Options module toggle is off.
        """
        import gremlin.config

        config = gremlin.config.Configuration()
        tag = str(getattr(entry, "tag", "") or "").casefold()
        name = str(getattr(entry, "name", "") or "").casefold()
        key = f"{tag} {name}"
        if "streamdeck" in key and not config.startup_streamdeck_enabled:
            return False
        if ("map-to-osc" in key or "map_to_osc" in key) and not config.startup_osc_enabled:
            return False
        if "simconnect" in key and not config.simconnect_enabled:
            return False
        if "afcs" in key and not config.afcs_enabled:
            return False
        return True

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

                    if self._validate_plugin(plugin):
                        self._plugins[plugin.name] = plugin.create
                        self._plugins_folder_map[plugin.name] = root
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
        from gremlin.clipboard import ObjectEncoder, EncoderType
        from gremlin.input_item import AbstractAction

        if input_item is None:
            input_item = getattr(container, "input_item", None)
        if container is None or input_item is None:
            raise ValueError("An action paste requires a destination container and input")
        if isinstance(action, ObjectEncoder):
            if action.encoder_type != EncoderType.Action:
                raise ValueError("Clipboard data is not an action")
            node = clone_xml_for_paste(action.data)
        elif isinstance(action, AbstractAction):
            node = clone_xml_for_paste(action.to_xml())
        else:
            raise ValueError("Unsupported action clipboard data")
        action_tag = node.tag
        action_tag_map = self.tag_map
        if action_tag not in action_tag_map:
            raise ValueError(f"Unknown action plugin: {action_tag}")
        new_action = action_tag_map[action_tag](container)
        extra_data = dict(extra_data or {})
        if "mode_object" not in extra_data and gremlin.shared_state.current_profile is not None:
            mode_object = gremlin.shared_state.current_profile.get_mode_object(gremlin.shared_state.edit_mode)
            extra_data["mode_object"] = mode_object
        extra_data.update(paste=True, ids_regenerated=True, input_item=input_item, container=container)
        try:
            new_action.from_xml(node, (input_item, container), extra_data)
            new_action.update_inputs(input_item)
        except Exception:
            discard_pasted_conditions(node)
            raise

        return new_action

    def duplicate_for_paste(self, action, container, input_item=None, extra_data=None):
        """Decode clipboard actions for UI handlers without propagating bad data."""
        try:
            return self.duplicate(action, container, input_item, extra_data)
        except Exception:
            syslog.exception("Unable to paste an action from the clipboard")
            return None

    def fromClipboard(self, container, input_item, decode=True) -> list:
        """grabs an action from the clipboard"""
        from lxml import etree
        from gremlin.clipboard import Clipboard, ObjectEncoder, EncoderType

        if container is None or input_item is None:
            syslog.warning("FromClipboard: invalid container and input data")
            return []
        item = Clipboard().data

        def read_action(encoded):
            node = clone_xml_for_paste(encoded.data)
            factory = self.tag_map.get(node.tag)
            if factory is None:
                raise ValueError(f"Unknown action plugin: {node.tag}")
            return ObjectEncoder(encoded, etree.tostring(node), factory.name, EncoderType.Action)

        try:
            actions = []
            if isinstance(item, ObjectEncoder):
                if item.encoder_type == EncoderType.Action:
                    actions = [read_action(item)]
                elif item.encoder_type in (EncoderType.Container, EncoderType.MultiContainer):
                    root = clone_xml_for_paste(item.data)
                    if root.tag == "multi_containers":
                        nodes = list(root)
                    elif root.tag == "container":
                        nodes = [root]
                    else:
                        raise ValueError(f"Invalid container clipboard root: {root.tag}")
                    for node in nodes:
                        if node.tag != "container":
                            raise ValueError(f"Invalid container clipboard node: {node.tag}")
                        for action_node in node.findall("./action-set/*"):
                            encoded = ObjectEncoder(item, etree.tostring(action_node), action_node.tag, EncoderType.Action)
                            actions.append(read_action(encoded))
            else:
                from gremlin.input_item import AbstractAction
                if isinstance(item, AbstractAction):
                    actions = [read_action(ObjectEncoder(item, etree.tostring(item.to_xml()), item.name, EncoderType.Action))]
            if decode:
                decoded = [self.duplicate_for_paste(action, container, input_item) for action in actions]
                return [action for action in decoded if action is not None]
            return actions
        except Exception:
            syslog.exception("Unable to paste actions from the clipboard")
        return []
