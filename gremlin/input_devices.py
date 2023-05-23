# -*- coding: utf-8; -*-

# Copyright (C) 2015 - 2022 Lionel Ott
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


import collections
import functools
import heapq
import inspect
import logging
import time
import threading
from typing import Callable

from PySide6 import QtCore

import gremlin.common
import gremlin.keyboard
import gremlin.types
from dill import DILL, GUID, GUID_Invalid

from . import common, error, event_handler, joystick_handling, util
from gremlin.common import InputType


import socketserver, socket, msgpack


syslog = logging.getLogger("system")

class CallbackRegistry:

    """Registry of all callbacks known to the system."""

    def __init__(self):
        """Creates a new callback registry instance."""
        self._registry = {}
        self._current_id = 0

    def add(self, callback, event, mode, always_execute=False):
        """Adds a new callback to the registry.

        :param callback function to add as a callback
        :param event the event on which to trigger the callback
        :param mode the mode in which to trigger the callback
        :param always_execute if True the callback is run even if Gremlin
            is paused
        """
        self._current_id += 1
        function_name = "{}_{:d}".format(callback.__name__, self._current_id)

        if event.device_guid not in self._registry:
            self._registry[event.device_guid] = {}
        if mode not in self._registry[event.device_guid]:
            self._registry[event.device_guid][mode] = {}

        if event not in self._registry[event.device_guid][mode]:
            self._registry[event.device_guid][mode][event] = {}
        self._registry[event.device_guid][mode][event][function_name] = \
            (callback, always_execute)

    @property
    def registry(self):
        """Returns the registry dictionary.

        :return registry dictionary
        """
        return self._registry

    def clear(self):
        """Clears the registry entries."""
        self._registry = {}


class PeriodicRegistry:

    """Registry for periodically executed functions."""

    def __init__(self):
        """Creates a new instance."""
        self._registry = {}
        self._running = False
        self._thread = threading.Thread(target=self._thread_loop)
        self._queue = []
        self._plugins = []

    def start(self):
        """Starts the event loop."""
        # Only proceed if we have functions to call
        if len(self._registry) == 0:
            return

        # Only create a new thread and start it if the thread is not
        # currently running
        self._running = True
        if not self._thread.is_alive():
            self._thread = threading.Thread(target=self._thread_loop)
            self._thread.start()

    def stop(self):
        """Stops the event loop."""
        self._running = False
        if self._thread.is_alive():
            self._thread.join()

    def add(self, callback, interval):
        """Adds a function to execute periodically.

        :param callback the function to execute
        :param interval the time between executions
        """
        self._registry[callback] = (interval, callback)

    def clear(self):
        """Clears the registry."""
        self._registry = {}

    def _install_plugins(self, callback):
        """Installs the current plugins into the given callback.

        :param callback the callback function to install the plugins
            into
        :return new callback with plugins installed
        """
        signature = inspect.signature(callback).parameters
        partial_fn = functools.partial
        if "self" in signature:
            partial_fn = functools.partialmethod
        for plugin in self._plugins:
            if plugin.keyword in signature:
                callback = plugin.install(callback, partial_fn)
        return callback


    def _thread_loop(self):
        """Main execution loop run in a separate thread."""
        import uuid
        # Setup plugins to use
        self._plugins = [
            JoystickPlugin(),
            VJoyPlugin(),
            KeyboardPlugin()
        ]
        callback_map = {}
        period_map = {}
        # Populate the queue
        self._queue = []
        for item in self._registry.values():
            plugin_cb = self._install_plugins(item[1])
            node_id = str(uuid.uuid1())
            callback_map[node_id] = plugin_cb
            period_map[node_id] = item[0]
            value = time.time() + period_map[node_id]
            heapq.heappush(self._queue, (value, node_id))


        # Main thread loop
        while self._running:
            # Process all events that require running
            if self._queue:
                while self._queue[0][0] < time.time():
                    value, node_id = heapq.heappop(self._queue)
                    callback_map[node_id]()

                    heapq.heappush(
                        self._queue,
                        (time.time() + period_map[node_id], node_id)
                    )

            # Sleep until either the next function needs to be run or
            # our timeout expires
            time.sleep(min(self._queue[0][0] - time.time(), 1.0))

            

class SimpleRegistry:

    """Registry for functions executed  """

    def __init__(self):
        """Creates a new instance."""
        self._registry = {}
        self._running = False
        self._plugins = []

    def start(self):
        """Starts the event loop."""
        # Only proceed if we have functions to call
        if len(self._registry) == 0:
            return

        # Only create a new thread and start it if the thread is not
        # currently running
        self._running = True
        for item in self._registry.values():
            plugin_cb = self._install_plugins(item)
            plugin_cb()


    def stop(self):
        """Stops the event loop."""
        self._running = False


    def add(self, callback):
        """Adds a function to execute periodically.

        :param callback the function to execute
        :param interval the time between executions
        """
        self._registry[callback] = callback


    def clear(self):
        """Clears the registry."""
        self._registry = {}

    def _install_plugins(self, callback):
        """Installs the current plugins into the given callback.

        :param callback the callback function to install the plugins
            into
        :return new callback with plugins installed
        """
        signature = inspect.signature(callback).parameters
        partial_fn = functools.partial
        if "self" in signature:
            partial_fn = functools.partialmethod
        for plugin in self._plugins:
            if plugin.keyword in signature:
                callback = plugin.install(callback, partial_fn)
        return callback


class ModeChangeRegistry():
    """Registry for functions executed on mode change """
    def __init__(self):
        """Creates a new instance."""
        self._registry = {}
        self._running = False
        self._plugins = []

    def add(self, callback):
        """Adds a function to execute periodically.

        :param callback the function to execute
        :param interval the time between executions
        """
        self._registry[callback] = callback


    def clear(self):
        """Clears the registry."""
        self._registry = {}

    def _install_plugins(self, callback):
        """Installs the current plugins into the given callback.

        :param callback the callback function to install the plugins
            into
        :return new callback with plugins installed
        """
        signature = inspect.signature(callback).parameters
        print ("Signature:")
        for item in signature:
            print(item)
        print("End signature")
        partial_fn = functools.partial
        if "self" in signature:
            partial_fn = functools.partialmethod
        for plugin in self._plugins:
            if plugin.keyword in signature:
                callback = plugin.install(callback, partial_fn)
        return callback

    def mode_changed(self, mode_name):
            
        if len(self._registry) == 0:
            return
        for item in self._registry.values():
            plugin_cb = self._install_plugins(item)
            plugin_cb(mode_name)


class GremlinServer(socketserver.ThreadingMixIn,socketserver.UDPServer):
    pass

class GremlinSocketHandler(socketserver.BaseRequestHandler):
    ''' handles remote input from a gremlin client on the network '''
    def handle(self):
        
      
        # handles input data
        raw_data = self.request[0].strip()
        socket = self.request[1]
        
        current_thread = threading.currentThread()
        data = msgpack.unpackb(raw_data)
        syslog.debug(f"Gremlin received remote data: {data}")

        sender = data["sender"]

        if sender == remote_client.id:
            # ignore our own broadcasts
            return 
        
        action = data["action"]
        device = data["device"]
        target = data["target"]
        value = data["value"]
        proxy = joystick_handling.VJoyProxy()
        if device in proxy.vjoy_devices:
            # valid device
            vjoy = proxy[device]
            
            if action == "button":
                # emit button change
                if target > 0 and target < vjoy.button_count:
                    proxy[device].button(target).is_pressed = value
            elif action == "axis":
                if target > 0 and target <= vjoy.axis_count:
                    proxy[device].axis(target).value = value
            elif action == "hat":
                if target > 0 and target <= vjoy.hat_count:
                    proxy[device].hat(target).direction = value
       


class RPCGremlin():
    ''' remote UDP multicast listener '''

    MULTICAST_GROUP = '224.0.0.25' # non routable - clients must be on the same vlan
    # multicast time to live
    MULTICAST_TTL = 2

    def __init__(self):
        # self._address = "0.0.0.0"
        # self._server_address = "localhost"
        config = gremlin.config.Configuration()
        self._port = config.server_port
        self._server = None
        self._running = False
        self._thread = None
        self._server_thread = None
        self._keep_running = False

        

    def _run(self):
        import struct
        syslog.debug("Starting gremlin listener...")
        self._server = GremlinServer(('', self._port),GremlinSocketHandler)
        self._server_thread = threading.Thread(target=self._server.serve_forever)
        self._server_thread.daemon = True
        try:
            self._server_thread.start()
            # enable listen to multicast UDP
            group = socket.inet_aton(RPCGremlin.MULTICAST_GROUP)
            mreq = struct.pack('4sL', group, socket.INADDR_ANY)
            self._server.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            syslog.debug(f"Starting gremlin server listener:  multicast group {RPCGremlin.MULTICAST_GROUP} port {self._port} ...")
            self._keep_running = True
            self._running = True
            while self._keep_running:
                time.sleep(10)
        except Exception as ex:
            pass

        self._server.shutdown()
        self._server.server_close()
        self._running = False
        syslog.debug("Gremlin listener stopped.")
        
    @property
    def running(self):
        return self._running

    def start(self):
        ''' starts the listener '''

        config = gremlin.config.Configuration()
        if not config.enable_remote_control:
            syslog.debug("Remote control disabled - Gremlin listener not started")
            return
        if self._running:
            # already running
            return
        self._thread = threading.Thread(target=self._run)
        self._thread.start()

        

    def stop(self):
        ''' stops the loop'''
        if not self._running:
            return
        
        # stop the server loop
        self._keep_running = False
        self._thread.join()
        self._thread = None

        syslog.debug("Gremlin RPC server stopped...")



class RemoteServer(QtCore.QObject):
    """ Provides access to remote a remote Gremlin instance events """

    def __init__(self):
        """Initialises a new object."""
        QtCore.QObject.__init__(self)
        self._rpc = None


    def start(self):
        ''' start listening '''
        config = gremlin.config.Configuration()
        self._enabled = config.enable_remote_control
        if self._enabled:
            self._rpc = RPCGremlin()
            self._rpc.start()
            syslog.debug("Gremlin RPC server started...")
        

    def stop(self):
        ''' stop listening'''
        if self._rpc:
            self._rpc.stop()

    @property
    def running(self):
        ''' true if the server is running'''
        return self._rpc and self._rpc.running
    
    @property
    def enabled(self):
        ''' true if server is accepting input from clients '''
        return self._enabled
    
    @enabled.setter
    def enabled(self, value):
        self._enabled = value


class RemoteClient(QtCore.QObject):
    """ Provides access to remote a remote Gremlin instance events """

    def __init__(self):
        """Initialises a new object."""
        QtCore.QObject.__init__(self)
        self._host = "localhost"
        config = gremlin.config.Configuration()
        self._port = config.server_port
        self._enabled = config.enable_remote_broadcast
        self._address = (RPCGremlin.MULTICAST_GROUP, self._port)
        self._sock = None
        # unique ID of this client
        self._id = get_guid()
        

    def start(self):
        ''' creates a multicast client send socket'''
        import struct
        if not self._enabled:
            return
        
        if not self._sock:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            ttl = struct.pack('b', RPCGremlin.MULTICAST_TTL)
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
            syslog.debug("Gremlin RPC client started...")

    def stop(self):
        ''' closes the client socket'''
        if not self._enabled:
            return        
        if self._sock:
            self._sock.close()
            self._sock = None
            syslog.debug("Gremlin RPC client stopped.")

    def _send(self, data = None):
        ''' sends data to the socket'''
        if data:
            self._sock.sendto(data, self._address)

    def send_button(self, device_id, button_id, is_pressed):
        ''' handles a remote joystick event '''
        if self._enabled:
            data = {}
            data["sender"] = self._id
            data["action"] = "button"
            data["device"] = device_id
            data["target"] = button_id
            data["value"] = is_pressed
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            syslog.debug(f"remote gremlin event set button: {device_id} {button_id} {is_pressed}")

    def send_axis(self, device_id, axis_id, value):
        ''' handles a remote joystick event '''
        if self._enabled:
            data = {}
            data["sender"] = self._id
            data["action"] = "axis"
            data["device"] = device_id
            data["target"] = axis_id
            data["value"] = value
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            syslog.debug(f"remote gremlin event set axis: {device_id} {axis_id} {value}")

    def send_hat(self, device_id, hat_id, direction):
        ''' handles a remote joystick event '''
        if self._enabled:
            data = {}
            data["sender"] = self._id
            data["action"] = "hat"
            data["device"] = device_id
            data["target"] = hat_id
            data["value"] = direction
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            syslog.debug(f"remote gremlin event set hat: {device_id} {hat_id} {direction}")    

    @property
    def enabled(self):
        ''' enables or disabled sending remote events'''
        return self._enabled
    
    @enabled.setter
    def enabled(self, value):
        self._enabled = value

    @property
    def id(self):
        return self._id

            


def get_guid(strip=True):
    ''' generates a reasonably lowercase unique guid string '''
    import uuid
    guid = f"{uuid.uuid4()}"
    if strip:
        return guid.replace("-",'')
    return guid
    

# Global registry of all registered callbacks
callback_registry = CallbackRegistry()

# Global registry of all periodic callbacks
periodic_registry = PeriodicRegistry()

# Global registry of all start callbacks
start_registry = SimpleRegistry()

# Global registry of all stop callbacks
stop_registry = SimpleRegistry()

# Global remote server = listens to remote client events
remote_server = RemoteServer()

# Global remote client = sends events to server
remote_client = RemoteClient()






# Global registry of all mode change callbacks
mode_registry = ModeChangeRegistry()


def register_callback(callback, device, input_type, input_id):
    """Adds a callback to the registry.

    This function adds the provided callback to the global callback_registry
    for the specified event and mode combination.

    Parameters
    ==========
    callback : callable
        The callable object to execute when the event with the specified
        conditions occurs
    device : JoystickDecorator
        Joystick decorator specifying the device and mode in which to execute
        the callback
    input_type : gremlin.types.InputType
        Type of input on which to execute the callback
    input_id : int
        Index of the input on which to execute the callback
    """
    event = event_handler.Event(
        event_type=input_type,
        device_guid=device.device_guid,
        identifier=input_id
    )
    callback_registry.add(callback, event, device.mode, False)


class JoystickWrapper:

    """Wraps joysticks and presents an API similar to vjoy."""

    class Input:

        """Represents a joystick input."""

        def __init__(self, joystick_guid, index):
            """Creates a new instance.

            :param joystick_guid the GUID of the device instance
            :param index the index of the input
            """
            self._joystick_guid = joystick_guid
            self._index = index

    class Axis(Input):

        """Represents a single axis of a joystick."""

        def __init__(self, joystick_guid, index):
            super().__init__(joystick_guid, index)

        @property
        def value(self):
            # FIXME: This bypasses calibration and any other possible
            #        mappings we might do in the future
            return DILL.get_axis(self._joystick_guid, self._index) / float(32768)

    class Button(Input):

        """Represents a single button of a joystick."""

        def __init__(self, joystick_guid, index):
            super().__init__(joystick_guid, index)

        @property
        def is_pressed(self):
            return DILL.get_button(self._joystick_guid, self._index)

    class Hat(Input):

        """Represents a single hat of a joystick,"""

        def __init__(self, joystick_guid, index):
            super().__init__(joystick_guid, index)

        @property
        def direction(self):
            return util.dill_hat_lookup(DILL.get_hat(self._joystick_guid, self._index))

    def __init__(self, device_guid):
        """Creates a new wrapper object for the given object id.

        :param device_guid the GUID of the joystick instance to wrap
        """
        if DILL.device_exists(device_guid) is False:
            raise error.GremlinError(
                "No device with the provided GUID {} exist".format(device_guid)
            )
        self._device_guid = device_guid
        self._info = DILL.get_device_information_by_guid(self._device_guid)
        self._axis = self._init_axes()
        self._buttons = self._init_buttons()
        self._hats = self._init_hats()

    @property
    def device_guid(self):
        """Returns the GUID of the joystick.

        :return GUID for this joystick
        """
        return self._device_guid

    @property
    def name(self):
        """Returns the name of the joystick.

        :return name of the joystick
        """
        return self._info.name

    def is_axis_valid(self, axis_index):
        """Returns whether or not the specified axis exists for this device.

        :param axis_index the index of the axis in the AxisNames enum
        :return True the specified axis exists, False otherwise
        """
        for i in range(self._info.axis_count):
            if self._info.axis_map[i].axis_index == axis_index:
                return True
        return False

    def axis(self, index):
        """Returns the current value of the axis with the given index.

        The index is 1 based, i.e. the first axis starts with index 1.

        :param index the index of the axis to return to value of
        :return the current value of the axis
        """
        if index not in self._axis:
            raise error.GremlinError(
                "Invalid axis {} specified for device {}".format(
                    index,
                    self._device_guid
            ))
        return self._axis[index]

    def button(self, index):
        """Returns the current state of the button with the given index.

        The index is 1 based, i.e. the first button starts with index 1.

        :param index the index of the axis to return to value of
        :return the current state of the button
        """
        if not (0 < index < len(self._buttons)):
            raise error.GremlinError(
                "Invalid button {} specified for device {}".format(
                    index,
                    self._device_guid
                )
            )
        return self._buttons[index]

    def hat(self, index):
        """Returns the current state of the hat with the given index.

        The index is 1 based, i.e. the first hat starts with index 1.

        :param index the index of the hat to return to value of
        :return the current state of the hat
        """
        if not (0 < index < len(self._hats)):
            raise error.GremlinError(
                "Invalid hat {} specified for device {}".format(
                    index,
                    self._device_guid
                )
            )
        return self._hats[index]

    def axis_count(self) -> int:
        """Returns the number of axis of the joystick.

        Returns:
            Number of axes
        """
        return self._info.axis_count

    def button_count(self) -> int:
        """Returns the number of buttons on the joystick.

        Returns:
            Number of buttons
        """
        return self._info.button_count

    def hat_count(self) -> int:
        """Returns the number of hats on the joystick.

        Returns:
            Number of hats
        """
        return self._info.hat_count

    def _init_axes(self):
        """Initializes the axes of the joystick.

        :return list of JoystickWrapper.Axis objects
        """
        axes = {}
        for i in range(self._info.axis_count):
            aid = self._info.axis_map[i].axis_index
            axes[aid] = JoystickWrapper.Axis(self._device_guid, aid)
        return axes

    def _init_buttons(self):
        """Initializes the buttons of the joystick.

        :return list of JoystickWrapper.Button objects
        """
        buttons = [None,]
        for i in range(self._info.button_count):
            buttons.append(JoystickWrapper.Button(self._device_guid, i+1))
        return buttons

    def _init_hats(self):
        """Initializes the hats of the joystick.

        :return list of JoystickWrapper.Hat objects
        """
        hats = [None,]
        for i in range(self._info.hat_count):
            hats.append(JoystickWrapper.Hat(self._device_guid, i+1))
        return hats


class JoystickProxy:

    """Allows read access to joystick state information."""

    # Dictionary of initialized joystick devices
    joystick_devices = {}

    def __getitem__(self, device_guid):
        """Returns the requested joystick instance.

        If the joystick instance exists it is returned directly, otherwise
        it is first created and then returned.

        :param device_guid GUID of the joystick device
        :return the corresponding joystick device
        """
        if device_guid not in JoystickProxy.joystick_devices:
            # If the device exists add process it and add it, otherwise throw
            # an exception
            if DILL.device_exists(device_guid):
                joy = JoystickWrapper(device_guid)
                JoystickProxy.joystick_devices[device_guid] = joy
            else:
                raise error.GremlinError(
                    "No device with guid {} exists".format(device_guid)
                )

        return JoystickProxy.joystick_devices[device_guid]


class VJoyPlugin:

    """Plugin providing automatic access to the VJoyProxy object.

    For a function to use this plugin it requires one of its parameters
    to be named "vjoy".
    """

    vjoy = joystick_handling.VJoyProxy()

    def __init__(self):
        self.keyword = "vjoy"

    def install(self, callback, partial_fn):
        """Decorates the given callback function to provide access to
        the VJoyProxy object.

        Only if the signature contains the plugin's keyword is the
        decorator applied.

        :param callback the callback to decorate
        :param partial_fn function to create the partial function / method
        :return callback with the plugin parameter bound
        """
        return partial_fn(callback, vjoy=VJoyPlugin.vjoy)


class JoystickPlugin:

    """Plugin providing automatic access to the JoystickProxy object.

    For a function to use this plugin it requires one of its parameters
    to be named "joy".
    """

    joystick = JoystickProxy()

    def __init__(self):
        self.keyword = "joy"

    def install(self, callback, partial_fn):
        """Decorates the given callback function to provide access
        to the JoystickProxy object.

        Only if the signature contains the plugin's keyword is the
        decorator applied.

        :param callback the callback to decorate
        :param partial_fn function to create the partial function / method
        :return callback with the plugin parameter bound
        """
        return partial_fn(callback, joy=JoystickPlugin.joystick)


@common.SingletonDecorator
class Keyboard(QtCore.QObject):

    """Provides access to the keyboard state."""

    def __init__(self):
        """Initialises a new object."""
        QtCore.QObject.__init__(self)
        self._keyboard_state = {}

    @QtCore.Slot(event_handler.Event)
    def keyboard_event(self, event):
        """Handles keyboard events and updates state.

        :param event the keyboard event to use to update state
        """
        key = gremlin.keyboard.key_from_code(
            event.identifier[0],
            event.identifier[1]
        )
        self._keyboard_state[key] = event.is_pressed

    def is_pressed(self, key):
        """Returns whether or not the key is pressed.

        :param key the key to check
        :return True if the key is pressed, False otherwise
        """
        if isinstance(key, str):
            key = gremlin.keyboard.key_from_name(key)
        elif isinstance(key, gremlin.keyboard.Key):
            pass
        return self._keyboard_state.get(key, False)


class KeyboardPlugin:

    """Plugin providing automatic access to the Keyboard object.

    For a function to use this plugin it requires one of its parameters
    to be named "keyboard".
    """

    keyboard = Keyboard()

    def __init__(self):
        self.keyword = "keyboard"

    def install(self, callback, partial_fn):
        """Decorates the given callback function to provide access to
        the Keyboard object.

        :param callback the callback to decorate
        :param partial_fn function to create the partial function / method
        :return callback with the plugin parameter bound
        """
        return partial_fn(callback, keyboard=KeyboardPlugin.keyboard)


class JoystickDecorator:

    """Creates customized decorators for physical joystick devices."""

    def __init__(self, name, device_guid, mode):
        """Creates a new instance with customized decorators.

        :param name the name of the device
        :param device_guid the device id in the system
        :param mode the mode in which the decorated functions
            should be active
        """
        self.name = name
        self.mode = mode
        # Convert string based GUID to the actual GUID object
        try:
            self.device_guid = gremlin.profile.parse_guid(device_guid)
        except error.ProfileError:
            logging.getLogger("system").error(
                "Invalid guid value '' received".format(device_guid)
            )
            self.device_guid = GUID_Invalid

        self.axis = functools.partial(
            _axis, device_guid=self.device_guid, mode=mode
        )
        self.button = functools.partial(
            _button, device_guid=self.device_guid, mode=mode
        )
        self.hat = functools.partial(
            _hat, device_guid=self.device_guid, mode=mode
        )


ButtonReleaseEntry = collections.namedtuple(
    "Entry", ["callback", "event", "mode"]
)


@common.SingletonDecorator
class ButtonReleaseActions(QtCore.QObject):

    """Ensures a desired action is run when a button is released."""

    def __init__(self):
        """Initializes the instance."""
        QtCore.QObject.__init__(self)

        self._registry = {}
        el = event_handler.EventListener()
        el.joystick_event.connect(self._input_event_cb)
        el.keyboard_event.connect(self._input_event_cb)
        el.virtual_event.connect(self._input_event_cb)
        eh = event_handler.EventHandler()
        self._current_mode = eh.active_mode
        eh.mode_changed.connect(self._mode_changed_cb)

    def register_callback(
        self,
        callback: Callable[[], None],
        physical_event: event_handler.Event
    ) -> None:
        """Registers a callback with the system.

        Args:
            callback: the function to run when the corresponding button is
                released
            physical_event: the physical event of the button being pressed
        """
        release_evt = physical_event.clone()
        release_evt.is_pressed = False

        if release_evt not in self._registry:
            self._registry[release_evt] = []
        # Do not record the mode since we may want to run the release action
        # independent of a mode
        self._registry[release_evt].append(
            ButtonReleaseEntry(callback, release_evt, None)
        )

    def register_button_release(
        self,
        vjoy_input: int,
        physical_event: event_handler.Event,
        activate_on: bool = False
    ):
        """Registers a physical and vjoy button pair for tracking.

        This method ensures that a vjoy button is pressed/released when the
        specified physical event occurs next. This is useful for cases where
        an action was triggered in a different mode or using a different
        condition.

        Args:
            vjoy_input: the vjoy button to release, represented as
                (vjoy_device_id, vjoy_button_id)
            physical_event: the button event when release should
                trigger the release of the vjoy button
        """
        release_evt = physical_event.clone()
        release_evt.is_pressed = activate_on

        if release_evt not in self._registry:
            self._registry[release_evt] = []
        # Record current mode so we only release if we've changed mode
        self._registry[release_evt].append(ButtonReleaseEntry(
            lambda: self._release_callback_prototype(vjoy_input),
            release_evt,
            self._current_mode
        ))

    def _release_callback_prototype(self, vjoy_input: int) -> None:
        """Prototype of a button release callback, used with lambdas.

        Args:
            vjoy_input: the vjoy input data to use in the release
        """
        vjoy = joystick_handling.VJoyProxy()
        # Check if the button is valid otherwise we cause Gremlin to crash
        if vjoy[vjoy_input[0]].is_button_valid(vjoy_input[1]):
            vjoy[vjoy_input[0]].button(vjoy_input[1]).is_pressed = False
        else:
            logging.getLogger("system").warning(
                f"Attempted to use non existent button: " +
                f"vJoy {vjoy_input[0]:d} button {vjoy_input[1]:d}"
            )

    def _input_event_cb(self, event: event_handler.Event):
        """Runs callbacks associated with the given event.

        Args:
            event: the event to process
        """
        #if evt in [e for e in self._registry if e.is_pressed != evt.is_pressed]:
        if event in self._registry:
            new_list = []
            for entry in self._registry[event]:
                if entry.event.is_pressed == event.is_pressed:
                    entry.callback()
                else:
                    new_list.append(entry)
            self._registry[event] = new_list

    def _mode_changed_cb(self, mode):
        """Updates the current mode variable.

        :param mode the new mode
        """
        self._current_mode = mode


@common.SingletonDecorator
class JoystickInputSignificant:

    """Checks whether or not joystick inputs are significant."""

    def __init__(self):
        """Initializes the instance."""
        self.reset()

   
    def should_process(self, event: event_handler.Event, deviation = 0.1) -> bool:
        """Returns whether or not a particular event is significant enough to
        process.

        Args:
            event: the event to check for significance

        Returns:
            True if the event should be processed, False otherwise
        """
        self._mre_registry[event] = event

        if event.event_type == InputType.JoystickAxis:
            return self._process_axis(event, deviation)
        elif event.event_type == InputType.JoystickButton:
            return self._process_button(event)
        elif event.event_type == InputType.JoystickHat:
            return self._process_hat(event)
        else:
            logging.getLogger("system").warning(
                "Event with unknown type received"
            )
            return False

    def last_event(self, event: event_handler.Event) -> event_handler.Event:
        """Returns the most recent event of this type.

        Args:
            event: the type of event for which to return the most recent one

        Returns:
            Latest event instance corresponding to the specified event
        """
        return self._mre_registry[event]

    def reset(self) -> None:
        """Resets the detector to a clean state for subsequent uses."""
        self._event_registry = {}
        self._mre_registry = {}
        self._time_registry = {}
        

    def _process_axis(self, event: event_handler.Event, deviation = 0.1) -> bool:
        """Process an axis event.

        Args:
            event: the axis event to process

        Returns:
            True if it should be processed, False otherwise
        """

        if event in self._event_registry:
            # Reset everything if we have no recent data (10 seconds)
            if self._time_registry[event] + 10.0 < time.time():
                self._event_registry[event] = event
                self._time_registry[event] = time.time()
                return False
            # Update state
            else:
                self._time_registry[event] = time.time()
                
                if abs(self._event_registry[event].value - event.value) > deviation:
                    self._event_registry[event] = event
                    self._time_registry[event] = time.time()
                    # print (f"axis move: {abs(self._event_registry[event].value - event.value)} deviation: {deviation} TRUE")    
                    return True
                else:
                    #print (f"axis move: {abs(self._event_registry[event].value - event.value)} deviation: {deviation} FALSE")    
                    return False
        else:
            self._event_registry[event] = event
            self._time_registry[event] = time.time()
            return False

    def _process_button(self, event: event_handler.Event) -> bool:
        """Process a button event.

        Args:
            event: the button event to process

        Returns:
            True if it should be processed, False otherwise
        """
        return True

    def _process_hat(self, event: event_handler.Event) -> bool:
        """Process a hat event.

        Args:
            event: the hat event to process

        Returns:
            True if it should be processed, False otherwise
        """
        return event.value != (0, 0)


def _button(button_id, device_guid, mode, always_execute=False):
    """Decorator for button callbacks.

    :param button_id the id of the button on the physical joystick
    :param device_guid the GUID of input device
    :param mode the mode in which this callback is active
    :param always_execute if True the decorated function is executed
        even when the program is not listening to inputs
    """

    def wrap(callback):

        @functools.wraps(callback)
        def wrapper_fn(*args, **kwargs):
            callback(*args, **kwargs)

        event = event_handler.Event(
            event_type=gremlin.types.InputType.JoystickButton,
            device_guid=device_guid,
            identifier=button_id
        )
        callback_registry.add(wrapper_fn, event, mode, always_execute)

        return wrapper_fn

    return wrap


def _hat(hat_id, device_guid, mode, always_execute=False):
    """Decorator for hat callbacks.

    :param hat_id the id of the button on the physical joystick
    :param device_guid the GUID of input device
    :param mode the mode in which this callback is active
    :param always_execute if True the decorated function is executed
        even when the program is not listening to inputs
    """

    def wrap(callback):

        @functools.wraps(callback)
        def wrapper_fn(*args, **kwargs):
            callback(*args, **kwargs)

        event = event_handler.Event(
            event_type=gremlin.types.InputType.JoystickHat,
            device_guid=device_guid,
            identifier=hat_id
        )
        callback_registry.add(wrapper_fn, event, mode, always_execute)

        return wrapper_fn

    return wrap


def _axis(axis_id, device_guid, mode, always_execute=False):
    """Decorator for axis callbacks.

    :param axis_id the id of the axis on the physical joystick
    :param device_guid the GUID of input device
    :param mode the mode in which this callback is active
    :param always_execute if True the decorated function is executed
        even when the program is not listening to inputs
    """

    def wrap(callback):

        @functools.wraps(callback)
        def wrapper_fn(*args, **kwargs):
            callback(*args, **kwargs)

        event = event_handler.Event(
            event_type=gremlin.types.InputType.JoystickAxis,
            device_guid=device_guid,
            identifier=axis_id
        )
        callback_registry.add(wrapper_fn, event, mode, always_execute)

        return wrapper_fn

    return wrap


def keyboard(key_name, mode, always_execute=False):
    """Decorator for keyboard key callbacks.

    :param key_name name of the key of this callback
    :param mode the mode in which this callback is active
    :param always_execute if True the decorated function is executed
        even when the program is not listening to inputs
    """

    def wrap(callback):

        @functools.wraps(callback)
        def wrapper_fn(*args, **kwargs):
            callback(*args, **kwargs)

        key = gremlin.keyboard.key_from_name(key_name)
        event = event_handler.Event.from_key(key)
        callback_registry.add(wrapper_fn, event, mode, always_execute)

        return wrapper_fn

    return wrap






def periodic(interval):
    """Decorator for periodic function callbacks.

    :param interval the duration between executions of the function
    """

    def wrap(callback):

        @functools.wraps(callback)
        def wrapper_fn(*args, **kwargs):
            callback(*args, **kwargs)

        periodic_registry.add(wrapper_fn, interval)

        return wrapper_fn

    return wrap

def gremlin_start():
    ''' decorator when a profile is activated '''
    def wrap(callback):

        @functools.wraps(callback)
        def wrapper_fn(*args, **kwargs):
            callback(*args, **kwargs)

        start_registry.add(wrapper_fn)

        return wrapper_fn

    return wrap

def gremlin_stop():
    ''' decorator when a profile is de-activated '''
    def wrap(callback):

        @functools.wraps(callback)
        def wrapper_fn(*args, **kwargs):
            callback(*args, **kwargs)

        stop_registry.add(wrapper_fn)

        return wrapper_fn

    return wrap


def gremlin_mode():
    ''' decorator when gremlin changes profile modes - passes the new mode to the plugin '''
    def wrap(callback):
        @functools.wraps(callback)
        def wrapper_fn(*args, **kwargs):
            callback(*args, **kwargs)

        mode_registry.add(wrapper_fn)

        return wrapper_fn

    return wrap


def squash(value, func):
    """Returns the appropriate function value when the function is
    squashed to [-1, 1].

    :param value the function value to compute
    :param func the function to be squashed
    :return function value at value after squashing
    """
    return (2 * func(value)) / abs(func(-1) - func(1))


def deadzone(value, low, low_center, high_center, high):
    """Returns the mapped value taking the provided deadzone into
    account.

    The following relationship between the limits has to hold.
    -1 <= low < low_center <= 0 <= high_center < high <= 1

    :param value the raw input value
    :param low low deadzone limit
    :param low_center lower center deadzone limit
    :param high_center upper center deadzone limit
    :param high high deadzone limit
    :return corrected value
    """
    if value >= 0:
        return min(1, max(0, (value - high_center) / abs(high - high_center)))
    else:
        return max(-1, min(0, (value - low_center) / abs(low - low_center)))


def format_input(event: event_handler.Event) -> str:
    """Formats the input specified the the device and event into a string.

    Args:
        event: event to format

    Returns:
        Textual representation of the event
    """
    # Retrieve device instance belonging to this event
    device = None
    for dev in joystick_handling.joystick_devices():
        if dev.device_guid == event.device_guid:
            device = dev
            break

    # Retrieve device name
    label = ""
    if device is None:
        logging.warning(
            f"Unable to find a device with GUID {str(event.device_guid)}"
        )
        label = "Unknown"
    else:
        label = device.name

    # Retrive input name
    label += " - "
    label += gremlin.common.input_to_ui_string(
        event.event_type,
        event.identifier
    )

    return label