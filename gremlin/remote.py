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
import collections
import functools
import heapq
import inspect
import logging
import time
import threading
from typing import Callable

from PySide6 import QtCore


import gremlin.base_classes
import gremlin.config
import gremlin.event_handler
import gremlin.gamepad_handling
import gremlin.joystick_handling
import gremlin.shared_state
from gremlin.types import GamePadOutput

import gremlin.keyboard
import gremlin.shared_state
import gremlin.types
from dinput import DILL, GUID, GUID_Invalid
import gremlin.util
from gremlin.util import get_guid
import gremlin.input_types
import vjoy.vjoy


from . import error

import win32api
import gremlin.sendinput, gremlin.tts

import socketserver, socket, msgpack
import enum

import gremlin.singleton_decorator
from gremlin.types import VjoyAction



syslog = logging.getLogger("system")






class GremlinServer(socketserver.ThreadingMixIn,socketserver.UDPServer):
    pass

class GremlinSocketHandler(socketserver.BaseRequestHandler):
    ''' handles remote input from a gremlin client on the network
    
        received network events are processed here
    
    '''


    def handle(self):
        
        verbose = gremlin.config.Configuration().verbose_mode_remote
        # handles input data
        raw_data = self.request[0].strip()
        # socket = self.request[1]
        
        data = msgpack.unpackb(raw_data)
        if verbose: syslog.info(f"REMOTE: received remote data: {data}")

        sender = data["sender"]
        if sender == remote_client.id:
            # ignore our own broadcasts
            return
        
        action = data["action"]
        if action == "hb":
            # heart beat
            return
        
        if action == "key":
            # keyboard output
            virtual_code = data["vc"]
            scan_code = data["sc"]
            flags = data["flags"]
            if verbose: syslog.info(f"REMOTE: key 0x{scan_code:X}")
            win32api.keybd_event(virtual_code, scan_code, flags, 0)
        elif action == "mouse":
            
            subtype = data["subtype"]
            if subtype == "wheel":
                direction = data["direction"]
                if verbose: syslog.info(f"REMOTE: wheel {direction}")
                gremlin.sendinput.mouse_wheel(direction)
            elif subtype == "hwheel":
                direction = data["direction"]
                if verbose: syslog.info(f"REMOTE: wheel {direction}")
                gremlin.sendinput.mouse_h_wheel(direction)
            elif subtype == "button":
                button_id = data["button"]
                button = gremlin.types.MouseButton.to_enum(button_id)
                
                is_pressed = data["value"]
                if is_pressed:
                    if verbose: syslog.info(f"REMOTE: mouse button down {button.name}")    
                    gremlin.sendinput.mouse_press(button)
                else:
                    if verbose: syslog.info(f"REMOTE: mouse button up {button.name}")    
                    gremlin.sendinput.mouse_release(button)
            elif subtype == "button_double":
                button_id = data["button"]
                button = gremlin.types.MouseButton.to_enum(button_id)
                is_pressed = data["value"]
                if is_pressed:
                    if verbose: syslog.info(f"REMOTE: double click {button.name}")    
                    gremlin.sendinput.mouse_press_double_click(button)
            elif subtype == "axis":
                dx = data["dx"]
                dy = data["dy"]
                mouse_controller = gremlin.sendinput.MouseController()
                if verbose: syslog.info(f"REMOTE: mouse axis [{dx},{dy}]")    
                mouse_controller.set_absolute_motion(dx, dy)

            elif subtype == "amotion":
                # accelerated motion
                a = data["acc"]
                min_speed = data["min_speed"]
                max_speed = data["max_speed"]
                time_to_max_speed = data["time_to_speed"]
                mouse_controller = gremlin.sendinput.MouseController()
                if verbose: syslog.info(f"REMOTE: mouse accelerated motion")    
                mouse_controller.set_accelerated_motion(a,min_speed,max_speed,time_to_max_speed)
        elif action == "gamepad":
            # gamepad handling
            index = data["index"] # id of the gamepad to send the data to
            subtype = data["subtype"] # axis or button
            output_mode = data["mode"] # either a gamepadoutput or the translated button code
            vigem = gremlin.gamepad_handling.getGamepad(index)
            if vigem is not None:
                if subtype == "axis":
                    value = data["value"]
                    
                    if vigem:
                        if output_mode == GamePadOutput.LeftStickX:
                            if verbose: syslog.info(f"REMOTE: pad left x {value:0.3f}")
                            vigem.left_joystick_float_x(value)
                        elif output_mode == GamePadOutput.LeftStickY:
                            if verbose: syslog.info(f"REMOTE: pad left y {value:0.3f}")
                            vigem.left_joystick_float_y(value)
                        if output_mode == GamePadOutput.RightStickX:
                            if verbose: syslog.info(f"REMOTE: pad right x {value:0.3f}")
                            vigem.right_joystick_float_x(value)
                        elif output_mode == GamePadOutput.RightStickY:
                            if verbose: syslog.info(f"REMOTE: pad right y {value:0.3f}")
                            vigem.right_joystick_float_y(value)
                        if output_mode == GamePadOutput.LeftTrigger:
                            #vscaled = gremlin.util.scale_to_range(value.current,target_min=0.0, target_max=1.0)
                            if verbose: syslog.info(f"REMOTE: pad left trigger {value:0.3f}")
                            vigem.left_trigger_float(value)
                        if output_mode == GamePadOutput.RightTrigger:
                            #vscaled = gremlin.util.scale_to_range(value.current,target_min=0.0, target_max=1.0)
                            if verbose: syslog.info(f"REMOTE: pad right trigger {value:0.3f}")
                            vigem.right_trigger_float(value)

                elif subtype == "button":
                    is_pressed = data["is_pressed"]
                    if is_pressed:
                        if verbose: syslog.info(f"REMOTE: pad button press {button}")
                        vigem.press_button(button)
                    else:
                        if verbose: syslog.info(f"REMOTE: pad button release {button}")
                        vigem.release_button(button)
                vigem.update()
            





        elif action in ("button","axis","hat","relative_axis","toggle"):
            # joystick button
            
            device = data["device"]
            target = data["target"]
            value = data["value"]
            if "relative_value" in data:
                relative_value = data["relative_value"]
            else:
                relative_value = 0.0
            proxy = gremlin.joystick_handling.VJoyProxy()
            if device in proxy.vjoy_devices:
                # valid device
                vjoy = proxy[device]
                
                match action:
                    case "button":
                        # emit button change

                        if verbose: syslog.info(f"REMOTE: button vjoy {device} input id: {target} pressed: {value}")
                        if target > 0 and target < vjoy.button_count:
                            proxy[device].button(target).is_pressed = value
                    case "toggle":
                        # emit toggle
                        if verbose: syslog.info(f"REMOTE: button toggle vjoy {device} input id: {target}")
                        if target > 0 and target < vjoy.button_count:
                            proxy[device].button(target).is_pressed = not proxy[device].button(target).is_pressed
                    case "axis":
                        if value is None:
                            # relative mode = get the current value
                            value = proxy[device].axis(target).value    
                        if relative_value:
                            # apply the relative value
                            value = gremlin.util.clamp(value + relative_value)
                            if verbose: syslog.info(f"REMOTE: relative axis vjoy {device} input id: {target} relative value: {relative_value:0.3f}")
                        if target > 0 and target <= vjoy.axis_count:
                            if verbose: syslog.info(f"REMOTE: axis vjoy {device} input id: {target} {value:0.3f}")
                            proxy[device].axis(target).value = value
                    case "hat":
                        if target > 0 and target <= vjoy.hat_count:
                            if verbose: syslog.info(f"REMOTE: hat vjoy {device} input id: {target} direction: {value}")
                            proxy[device].hat(target).direction = value
                    case "relative_axis":
                        if target > 0 and target <= vjoy.axis_count:
                            new_value = gremlin.util.clamp(proxy[device].axis(target).value + value)
                            if verbose: syslog.info(f"REMOTE: relative axis vjoy {device} input id: {target} relative value: {value:0.3f} new value: {new_value:0.3f}")
                            proxy[device].axis(target).value = new_value
                    case _:
                        syslog.error(f"REMOTE: unknown action code received [{action}]")

class RPCGremlin():
    ''' remote UDP multicast listener '''

    MULTICAST_GROUP = '224.3.29.72' # multicast group
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

        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self.stop)

        

    def _run(self):
        import struct
        syslog.info("Starting gremlin listener...")
        self._server = GremlinServer(('', self._port),GremlinSocketHandler)
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=False)
        self._server_thread.daemon = True
        try:
            self._server_thread.start()
            # enable listen to multicast UDP
            group = socket.inet_aton(RPCGremlin.MULTICAST_GROUP)
            mreq = struct.pack('4sL', group, socket.INADDR_ANY)
            self._server.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            syslog.info(f"Starting gremlin server listener:  multicast group {RPCGremlin.MULTICAST_GROUP} port {self._port} ...")
            self._keep_running = True
            self._running = True
            while self._keep_running:
                time.sleep(1)
        except Exception as ex:
            pass

        self._server.shutdown()
        self._server.server_close()
        self._running = False
        syslog.info("Gremlin listener stopped.")
        proxy = gremlin.joystick_handling.VJoyProxy()
        # release any locks on devices
        proxy.reset()

        
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
        
        # register the devices we will need
        vjoyid_list = [dev.vjoy_id for dev in gremlin.joystick_handling.joystick_devices() if dev.is_virtual]
        for key in vjoyid_list:
            try:
                device = gremlin.joystick_handling.VJoyProxy()[key]
                syslog.info(f"Remote proxy VJOY [{key}] ok")
            except:
                pass
        self._thread = threading.Thread(target=self._run, daemon=False)
        self._thread.start()

        

    def stop(self):
        ''' stops the loop'''
        if not self._running:
            return
        
        # stop the server loop
        self._keep_running = False
        if self._thread.is_alive():
            self._thread.join()
        self._thread = None

        syslog.info("Gremlin RPC server stopped...")



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
        return remote_state.is_remote
        
    
    @enabled.setter
    def enabled(self, value):
        self._enabled = value



@gremlin.singleton_decorator.SingletonDecorator
class RemoteClient():
    """ Provides access to a remote Gremlin instance """

    class ClientMode(enum.Enum):
        Local = 1
        Remote = 2
        LocalAndRemote = 3

        

    def __init__(self):
        """Initialises a new object."""

        self._sock = None
        # unique ID of this client
        self._id = get_guid()
        self._alive_thread = None
        self._alive_thread_stop_requested = False
        self._started = False

        el = gremlin.event_handler.EventListener()
        # el.profile_stop.connect(self.stop) # hook stop event
        el.shutdown.connect(self.stop) # hook stop event
        el.remote_control_enable.connect(self._enable_control)
        el.remote_control_disable.connect(self.stop)

    def _enable_control(self):
        ''' called when request to enable remote control has been made '''
        self.start()
        remote_control = RemoteControl()
        remote_control.setRemote(True) # enable remote control

    def start(self):
        ''' creates a multicast client send socket on profile start '''
        if not self._started:
            if  self.ensure_socket():
                el = gremlin.event_handler.EventListener()
                el.heartbeat.connect(self._alive_ticker)
                self._started = True
            


    def ensure_socket(self):
        # makes sure the socket exists
        import struct
        try:
            if not self._sock:
                config = gremlin.config.Configuration()
                broadcast_host = config.broadcast_host_ip
                if broadcast_host == "127.0.0.1":
                     if broadcast_host == '127.0.0.1':
                        broadcast_host = gremlin.util.getHostIp()[0]
                        syslog.warning(f'RPC: broadcast host is not configured (using localhost). Using [{broadcast_host}].  This may not be correct if you have multiple IP addresses.')
                    
                bind_all = config.broadcast_bind_all_ips
                port = config.broadcast_port
                self._address = (RPCGremlin.MULTICAST_GROUP, port)
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                ttl = struct.pack('b', RPCGremlin.MULTICAST_TTL)
                #self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, socket.inet_aton(broadcast_host), ttl)
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
                if bind_all and broadcast_host:
                    self._sock.bind((broadcast_host, port))
                    syslog.debug(f"Gremlin RPC client started... IP: {broadcast_host} port: {port}")
                else:
                    syslog.debug(f"Gremlin RPC client started... ALL IP - port: {port}")
            return self._sock is not None
        except Exception as e:
            syslog.error("SOCKET: unable to open remote control socket. Feature will be disabled.")
            self._sock = None
            return False


    def stop(self):
        ''' closes the client socket'''
        if self._started:
            el = gremlin.event_handler.EventListener()
            el.heartbeat.disconnect(self._alive_ticker)

            if self._alive_thread:
                syslog.debug("Alive stop requested...")

    
                self._alive_thread_stop_requested = True
                if self._alive_thread.is_alive():
                    self._alive_thread.join()
                syslog.debug("Alive thread stopped")
                self._alive_thread = None
            
            if self._sock:
                self._sock.close()
                self._sock = None
                syslog.debug("Gremlin RPC client stopped.")

            self._started = False

    def _alive_ticker(self):
        ''' sends an alive packet to keep the ports alive '''
        enabled = gremlin.config.Configuration().enable_remote_broadcast
        if enabled:
                data = {}
                data["sender"] = self._id
                data["action"] = "hb"
                raw_data = msgpack.packb(data)
                self._send(raw_data)
                verbose = gremlin.config.Configuration().verbose
                if verbose: syslog.info("Alive heartbeat")
        

    def _send(self, data = None):
        ''' sends data to the socket'''
        if data:
            if self._sock:
                self._sock.sendto(data, self._address)
            else:
                # retry connection
                self.ensure_socket()
                if self._sock:
                    self._sock.sendto(data, self._address)


    def send_button(self, device_id, button_id, is_pressed, force_remote = False):
        ''' handles a remote joystick event '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: send button: VJoyId: {device_id} button {button_id} pressed: {is_pressed}")               
            data = {}
            data["sender"] = self._id
            data["action"] = "button"
            data["device"] = device_id
            data["target"] = button_id
            data["value"] = is_pressed
            raw_data = msgpack.packb(data)
            self._send(raw_data)

            #syslog.debug(f"remote gremlin event set button: {device_id} {button_id} {is_pressed}")

    def toggle_button(self, device_id, button_id, force_remote = False):
        ''' toggles a button '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: toggle button: VJoyId: {device_id} button {button_id}")            
            data = {}
            data["sender"] = self._id
            data["action"] = "toggle"
            data["device"] = device_id
            data["target"] = button_id
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            #syslog.debug(f"remote gremlin event toggle button: {device_id} {button_id}")

    def send_axis(self, device_id, axis_id, value, force_remote = False):
        ''' handles a remote joystick event '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                stub = f"{value:0.3f}" if value is not None else 'None'
                syslog.info(f"REMOTE OUTPUT: send axis: VJoyId: [{device_id}] axis: [{axis_id}] value: [{stub}]")
            data = {}
            data["sender"] = self._id
            data["action"] = "axis"
            data["device"] = device_id
            data["target"] = axis_id
            data["value"] = value
            data["relative_value"] = None
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            #syslog.debug(f"remote gremlin event set axis: {device_id} {axis_id} {value}")

    def send_relative_axis(self, device_id, axis_id, value, force_remote = False):
        ''' handles a remote relative axis joystick event '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_outputs
            if verbose:
                stub = f"{value:0.3f}" if value is not None else 'None'
                syslog.info(f"REMOTE OUTPUT: send relative axis: VJoyId: [{device_id}] axis: [{axis_id}] value: [{stub}]")
            data = {}
            data["sender"] = self._id
            data["action"] = "relative_axis"
            data["device"] = device_id
            data["target"] = axis_id
            data["value"] = value
            raw_data = msgpack.packb(data)
            self._send(raw_data)

    def send_hat(self, device_id, hat_id, direction, force_remote = False):
        ''' handles a remote joystick event '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: VJoyId: {device_id} hat: {hat_id} direction: {direction}")
        
            data = {}
            data["sender"] = self._id
            data["action"] = "hat"
            data["device"] = device_id
            data["target"] = hat_id
            data["value"] = direction
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            #syslog.debug(f"remote gremlin event set hat: {device_id} {hat_id} {direction}")

    def send_key(self, virtual_code, scan_code, flags, force_remote = False):
        ''' handles a key event '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                code = int(scan_code)
                syslog.info(f"REMOTE OUTPUT: key: 0x{code:02x} flags: 0x{flags:02x}")
        
            data = {}
            data["sender"] = self._id
            data["action"] = "key"
            data["vc"] = virtual_code
            data["sc"] = scan_code
            data["flags"] = flags
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            #syslog.debug(f"remote gremlin event set key: virtual code: {virtual_code} scan code: {scan_code} flags: {flags}")

    def send_mouse_button(self, button_id, is_pressed, force_remote = False):
        ''' sends a mouse button press or release '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse button: {button_id} pressed: {is_pressed}")
            data = {}
            data["sender"] = self._id
            data["action"] = "mouse"
            data["subtype"] = "button"
            data["button"] = button_id
            data["value"] = is_pressed
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            #syslog.debug(f"remote gremlin event set mouse: button: {button_id} pressed: {is_pressed}")


    def send_mouse_button_double_click(self, button_id, is_pressed, force_remote = False):
        ''' sends a mouse button press or release '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse dblclick {button_id} pressed: {is_pressed}")
        
            data = {}
            data["sender"] = self._id
            data["action"] = "mouse"
            data["subtype"] = "button_double"
            data["button"] = button_id
            data["value"] = is_pressed
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            #syslog.debug(f"remote gremlin event set mouse: button: {button_id} pressed: {is_pressed}")            

    def send_mouse_wheel(self, direction, force_remote = False):
        ''' sends mousewheel data  '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse wheel: {direction}")
        
            data = {}
            data["sender"] = self._id
            data["action"] = "mouse"
            data["subtype"] = "wheel"
            data["direction"] = direction
            
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            #syslog.debug(f"remote gremlin event set mouse: wheel {direction}")

    def send_mouse_h_wheel(self, direction, force_remote = False):
        ''' sends horizontal mousewheel data  '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_outputs
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse H wheel: {direction}")
        
            data = {}
            data["sender"] = self._id
            data["action"] = "mouse"
            data["subtype"] = "hwheel"
            data["direction"] = direction
            
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            #syslog.debug(f"remote gremlin event set mouse: wheel {direction}")

    def send_mouse_motion(self, dx, dy, force_remote = False):
        ''' sends mouse motion data '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse motion: {dx}, {dy}")
        
            data = {}
            data["sender"] = self._id
            data["action"] = "mouse"
            data["subtype"] = "axis"
            data["dx"] = dx
            data["dy"] = dy
            
            raw_data = msgpack.packb(data)
            self._send(raw_data)
            #syslog.debug(f"remote gremlin event set mouse: axis {dx} {dy}")

    def send_mouse_motion_acceleration(self, a, min_speed, max_speed, time_to_max_speed, force_remote = False):
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse motion acceleration")
        
            data = {}
            data["sender"] = self._id
            data["action"] = "mouse"
            data["subtype"] = "amotion"
            data["acc"] = a
            data["min_speed"] = min_speed
            data["max_speed"] = max_speed
            data["time_to_speed"] = time_to_max_speed
            raw_data = msgpack.packb(data)
            self._send(raw_data)

    def send_gamepad_axis(self, index, mode, value, force_remote = False):
        ''' sends a gamepad axis to the remote client '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: gamepad axis: index: {index} mode: {mode} value: {value:0.3f}")
        
            data = {}
            data["sender"] = self._id
            data["action"] = "gamepad"
            data["subtype"] = "axis"
            data["index"] = index # which device to send to
            data["mode"] = mode
            data["value"] = value
            raw_data = msgpack.packb(data)
            self._send(raw_data)
    
    def send_gamepad_button(self, index, mode, is_pressed, force_remote = False):
        ''' sends a gamepad button to the remote client '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: gamepad: index: {index} mode: {mode} pressed: {is_pressed}")
            
            data = {}
            data["sender"] = self._id
            data["action"] = "gamepad"
            data["index"] = index  # which device to send to
            data["subtype"] = "button"
            data["mode"] = mode
            data["is_pressed"] = is_pressed
            raw_data = msgpack.packb(data)
            self._send(raw_data)


    @property
    def enabled(self):
        ''' enables or disabled sending remote events'''
        return remote_state.is_remote
    

    @property
    def id(self):
        return self._id


class InternalSpeech():
	''' tts interface '''
	def __init__(self):
		import win32com.client
		self.speaker = win32com.client.Dispatch("SAPI.SpVoice")

	def speak(self, text):
		try:
			self.speaker.speak(text)
		except:
			pass


@gremlin.singleton_decorator.SingletonDecorator
class RemoteControl():
    ''' holds remote control status information'''

    def __init__(self):
        
        self._is_remote = False
        self._is_local = False
        self._is_paired = False
        self._mode = VjoyAction.VJoyEnableLocalOnly
        config = gremlin.config.Configuration()
        self._is_broadcast = config.enable_remote_broadcast
        self._update(self._mode)
        el = gremlin.event_handler.EventListener()
        el.config_changed.connect(self._config_changed)
        el.broadcast_changed.connect(self._broadcast_changed)
        
    def _update(self, value):
        import gremlin.event_handler
        is_local = self._is_local
        is_remote = self._is_remote
        is_paired = self._is_paired
        if value == VjoyAction.VJoyDisableLocal:
            is_local = False
        elif value == VjoyAction.VJoyDisableRemote:
            is_remote = False
        elif value == VjoyAction.VJoyEnableLocalOnly:
            is_local = True
            is_remote = False
        elif value == VjoyAction.VJoyEnableRemoteOnly:
            is_local = False
            is_remote = True
        elif value == VjoyAction.VJoyEnableLocalAndRemote:
            is_local = True
            is_remote = True
        elif value == VjoyAction.VJoyEnableLocal:
            is_local = True
        elif value == VjoyAction.VJoyEnableRemote:
            is_remote = True
        elif value == VjoyAction.VJoyToggleRemote:
            is_local = not self._is_local
            is_remote = not self._is_remote
        elif value == VjoyAction.VJoyEnablePairedRemote:
            is_paired = True
        elif value == VjoyAction.VJoyDisablePairedRemote:
            is_paired = False
        else:
            # not sure what this was
            return
        
        self._mode = value

        if self._is_local != is_local or self._is_remote != is_remote:
            # status changed
            self._is_local = is_local
            self._is_remote = is_remote

            syslog.info(f"REMOTE CONTROL: local [{'ENABLED' if self._is_local else 'DISABLED'}] remote [{'ENABLED' if self._is_remote and self._is_broadcast else 'DISABLED (broadcast mode off)' if self._is_remote else 'DISABLED'}]")            

            
            el = gremlin.event_handler.EventListener()
            el.broadcast_changed.emit(gremlin.event_handler.StateChangeEvent(self._is_local, self._is_remote, self._is_broadcast))
            el.remote_control_changed.emit(is_remote)

        if self._is_paired != is_paired:
            # pairing mode changed
            self._is_paired = is_paired
            if is_paired:
                msg = "Paired mode enabled"
            else:
                msg = "Paired mode disabled"
            syslog.debug(f"REMOTE CONTROL: Paired mode changed: {msg}")
            thread = threading.Thread(target = self.say, args=(msg,), daemon=False)
            thread.name = "REMOTE CONTROL remote control paired update"
            thread.start()


    def _config_changed(self):
        ''' called when broadcast config item changes '''
        
        config = gremlin.config.Configuration()
        if self._is_broadcast != config.enable_remote_broadcast:
            self._is_broadcast = config.enable_remote_broadcast
            el = gremlin.event_handler.EventListener()
            el.broadcast_changed.emit(gremlin.event_handler.StateChangeEvent(self._is_local, self._is_remote, self._is_broadcast))

    def say(self, msg):
        speech = InternalSpeech()
        speech.speak(msg)

    def setLocal(self, value : bool):
        ''' enable/disable local '''
        if value:
            self._update(VjoyAction.VJoyEnableLocal)
        else:
            self._update(VjoyAction.VJoyDisableLocal)

    def setRemote(self, value : bool):
        ''' enable/disable local '''
        if value:
            self._update(VjoyAction.VJoyEnableRemote)
        else:
            self._update(VjoyAction.VJoyDisableRemote)

    def toggleRemote(self):
        self._update(VjoyAction.VJoyToggleRemote)

    def _broadcast_changed(self, event):
        config = gremlin.config.Configuration()
        if config.enable_broadcast_speech:
            msg = None
            if event.is_local and event.is_remote:
                msg = "Concurrent control mode enabled"
            elif event.is_local:
                msg = "Local control is enabled"
            elif event.is_remote:
                msg = "Remote control is enabled"
            if msg:
                thread = threading.Thread(target = self.say, args=(msg,), daemon=False)
                thread.name = "remove control broadcast"
                thread.start()
        
    @property
    def mode(self):
        ''' gets the current mode '''
        return self._mode
    
    @mode.setter
    def mode(self, value):
        self._update(value)

    @property
    def is_local(self):
        ''' status of local control '''
        return self._is_local
    @property
    def is_remote(self):
        ''' status of remote control - requires both remote and broadcast to be enabled '''
        return self._is_remote and self._is_broadcast
    
    @property
    def state(self):
        ''' returns status as a pair of flags, local, remote'''
        return (self.is_local, self.is_remote)
    
    @property
    def paired(self):
        ''' paired status '''
        return self._is_paired

    
    def to_state_event(self):
        ''' returns event data for the current state '''
        from gremlin.event_handler import StateChangeEvent
        event = StateChangeEvent(self.is_local, self.is_remote, self._is_broadcast)
        return event
  


# remote state
remote_state = RemoteControl()

# Global remote server = listens to remote client events
remote_server = RemoteServer()

# Global remote client = sends events to server
remote_client = RemoteClient()

