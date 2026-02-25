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
import uuid
import socket
from lxml import etree as ElementTree
from gremlin.util import safe_read, safe_format

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
from gremlin.types import MouseButton
from dinput import DILL, GUID, GUID_Invalid
import gremlin.util
from gremlin.util import get_guid
import gremlin.input_types
import vjoy.vjoy
from psygnal import Signal


from . import error

import win32api, win32con
import gremlin.sendinput, gremlin.tts

import socketserver, socket, msgpack
import enum

import gremlin.singleton_decorator
from gremlin.types import VjoyAction



syslog = logging.getLogger("system")






class GremlinServer(socketserver.ThreadingMixIn,socketserver.UDPServer):
    def handle_timeout(self):
        import gremlin.event_handler
        el = gremlin.event_handler.EventListener()
        el.remote_control_socket_timeout.emit() # fire the event to indicate we had a timeout
        return super().handle_timeout()
    
    def handle_error(self, request, client_address):
        el = gremlin.event_handler.EventListener()
        el.remote_control_socket_error.emit() # fire the event to indicate we had a timeout
        # return super().handle_error(request, client_address)

class GremlinSocketHandler(socketserver.BaseRequestHandler):
    ''' handles remote input from a gremlin client on the network
    
        received network events are processed here
    
    '''

   

    def handle(self):
        # config =  gremlin.config.Configuration()
        raw_data = self.request[0].strip()
        try:
            data = msgpack.unpackb(raw_data)

        except ValueError:
            # unpack error
            return
        
        remote_client.handle(data)

    
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

        if self._running:
            # already running
            return
        
        config = gremlin.config.Configuration()
        if not config.enable_remote_control:
            syslog.debug("Remote control disabled - Gremlin listener not started")
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

        self._running = True

        

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


@gremlin.singleton_decorator.SingletonDecorator
class RemoteServer(QtCore.QObject):
    """ Provides access to remote a remote Gremlin instance events """

    def __init__(self):
        """Initialises a new object."""

        QtCore.QObject.__init__(self)
        self._rpc = None
        self._started = False

        el = gremlin.event_handler.EventListener()
        el.remote_control_socket_timeout.connect(self._handle_socket_timeout)
        el.remote_control_socket_error.connect(self._handle_socket_error)




    def start(self):
        ''' start listening '''
        if self._started:
            return
        config = gremlin.config.Configuration()
        self._enabled = config.enable_remote_control
        if self._enabled:
            self._rpc = RPCGremlin()
            self._rpc.start()
            syslog.debug("Gremlin RPC server started...")
            self._started = True
        

    def stop(self):
        ''' stop listening'''
        if self._rpc:
            self._rpc.stop()
            self._started = False

    @property
    def running(self):
        ''' true if the server is running'''
        return self._rpc and self._rpc.running
    
    @property
    def enabled(self):
        ''' true if server is accepting input from clients '''
        return remote_control.is_remote
        
    
    @enabled.setter
    def enabled(self, value):
        self._enabled = value


    def _handle_socket_timeout(self):
        syslog.info("RPC: socket timeout")
        pass

    def _handle_socket_error(self):
        syslog.info("RPC: socket error")
        pass

@gremlin.singleton_decorator.SingletonDecorator
class RemoteClient():
    """ Provides access to a remote Gremlin instance and handles sending/receiving information between all clients on the network """

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

        self._callbacks = {} # map of callbacks by client ID

        self.remote_control = RemoteControl()

        el = gremlin.event_handler.EventListener()
        # el.profile_stop.connect(self.stop) # hook stop event
        el.shutdown.connect(self.stop) # hook stop event
        el.config_option_changed.connect(self._handle_config_options_changed)
        el.remote_control_enable.connect(self._handle_enable_control_request)
        el.remote_control_identify.connect(self.requestIdentify) # request network clients to identify
        el.profile_stop.connect(self._handle_profile_stop)

        # enable control if enabled
        if self.remote_control.remoteEnabled():
            self._handle_enable_control_request()

    @property
    def clientName(self) -> str:
        return self.remote_control.clientName
    
    @property
    def customName(self) -> str:
        ''' custom client name, if any '''
        return self.remote_control.customName
        
    def getClientName(self) -> str:
        ''' gets the custom or host name '''
        return self.remote_control.clientName


    def _handle_profile_stop(self):
        self.remote_control.is_remote = False # turn off profile remote mode on profile stop
    
    @property
    def clientId(self) -> int:
        ''' unique client ID'''
        return self.remote_control.clientId
    

    def _handle_config_options_changed(self):
        ''' called when configuration options are changed '''

        # get remote control options and start/stop as needed
        enabled = self.remote_control.remoteEnabled()
        if self._started and not enabled:
            self.stop() # terminate connection if remote control is no longer enabled and it was previously on
        elif not self._started and enabled:
            self._handle_enable_control_request() # enable remote control if it was previously off and now enabled

    def _handle_enable_control_request(self):
        ''' called when request to enable remote control has been made '''
        self.start()


    def getDatablock(self, action : str = None, data = None) -> dict:
        ''' gets a dict with the sender info '''
        block = {}
        if action:
            block["action"] = action
        if data:
            block['data'] = data

        return block


    def start(self):
        ''' creates a multicast client send socket on profile start '''
        if not self._started:
            if self.remote_control.remoteEnabled:
                if self.ensure_socket():
                    el = gremlin.event_handler.EventListener()
                    el.heartbeat.connect(self._alive_ticker)
                    self._started = True

                    # send ID request when starting to update clients
                    self.requestIdentify()

            
    def stop(self):
        ''' closes the client socket'''
        if self._started:

            # notify this client is disconnecting
            self.requestDisconnect()

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
                port = config.server_port
                self._address = (RPCGremlin.MULTICAST_GROUP, port)
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                ttl = struct.pack('b', RPCGremlin.MULTICAST_TTL)
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
                if bind_all and broadcast_host:
                    self._sock.bind((broadcast_host, port))
                    syslog.info(f"Gremlin RPC client started... IP: {broadcast_host} port: {port}")
                else:
                    syslog.info(f"Gremlin RPC client started... ALL IP - port: {port}")
            return self._sock is not None
        except Exception as e:
            syslog.error("SOCKET: unable to open remote control socket. Feature will be disabled.")
            self._sock = None
            return False
        
        
    def registerClient(self):
        ''' sends network our client data - this is called on network start'''
        enabled = gremlin.config.Configuration().remoteEnabled()
        if enabled:
            client = ClientData()
            data = self.getDatablock("register_client", client.toPayload())
            self.send(data) # send to all
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose: syslog.info(f"Register client [{client.client_name}]/[{client.client_id}]")

    def unregisterClient(self):
        enabled = gremlin.config.Configuration().remoteEnabled()
        if enabled:
            client = ClientData()
            data = self.getDatablock("unregister_client", client.toPayload())
            self.send(data) # send to all
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose: syslog.info(f"Unregister client [{client.client_name}]/[{client.client_id}]")

    def requestIdentify(self):
        ''' sends a network identify request which prompts each running client to send their information '''
        enabled = gremlin.config.Configuration().remoteEnabled()
        if enabled:
            data = self.getDatablock("identify")
            self.send(data)

    def requestDisconnect(self):
        ''' sends a network notice the current client is disconnecting '''
        self.unregisterClient()

    def _dispatch(self, data, client_list : list | tuple | int):
        if client_list is None:
            client_list = [0]
        elif not hasattr(client_list, "__iter__"):
            client_list = [client_list]
        for client_id in client_list:
            self.send(data, client_id)

  

    def _alive_ticker(self):
        ''' sends an alive packet to keep the socket alive '''
        enabled = gremlin.config.Configuration().enable_remote_broadcast
        if enabled:
                data = self.getDatablock("hb")
                self.send(data) # send to all
                verbose = gremlin.config.Configuration().verbose
                if verbose: syslog.info("Alive heartbeat")

    def send_pause(self, duration, client_list = None):
        if self.enabled:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: send pause: {duration}")   
            data = self.getDatablock("pause")               
            data['value'] = duration
            self._dispatch(data, client_list)
        
        

    def send_button(self, device_id, button_id, is_pressed, client_list = None, force_remote = False):
        ''' sends joystick buttons to clients '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: send button: VJoyId: {device_id} button {button_id} pressed: {is_pressed}")               
            bd = ButtonData.create(device_id, button_id, is_pressed, action = 'button')
            data = self.getDatablock("button", bd.toPayload())
            self._dispatch(data, client_list)
       
            

    def toggle_button(self, device_id, button_id, client_list = None, force_remote = False):
        ''' sends toggle button to clients '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: toggle button: VJoyId: {device_id} button {button_id}")            
            bd = ButtonData.create(device_id, button_id, action = 'toggle')
            data = self.getDatablock("toggle", bd.toPayload())
            self._dispatch(data, client_list)

    def send_axis(self, device_id, axis_id, value, client_list = None, force_remote = False):
        ''' sends axis data to clients '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                stub = f"{value:0.3f}" if value is not None else 'None'
                syslog.info(f"REMOTE OUTPUT: send axis: VJoyId: [{device_id}] axis: [{axis_id}] value: [{stub}]")
            payload = AxisData.create(device_id, axis_id, value, action = 'value').toPayload()
            data = self.getDatablock("axis", payload)
            self._dispatch(data, client_list)

    def send_relative_axis(self, device_id, axis_id, value, client_list = None, force_remote = False):
        ''' sends relative axis data to clients '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_outputs
            if verbose:
                stub = f"{value:0.3f}" if value is not None else 'None'
                syslog.info(f"REMOTE OUTPUT: send relative axis: VJoyId: [{device_id}] axis: [{axis_id}] value: [{stub}]")
            payload = AxisData.create(device_id, axis_id, relative_value = value, action = 'relative').toPayload()                
            data = self.getDatablock("axis", payload)
            self._dispatch(data, client_list)

    def send_hat(self, device_id, hat_id, direction, client_list = None, force_remote = False):
        ''' sends joystick hats to clients  '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: VJoyId: {device_id} hat: {hat_id} direction: {direction}")
            payload = AxisData.create(device_id, hat_id, direction, action = 'value').toPayload()
            data = self.getDatablock("hat", payload)
            self._dispatch(data, client_list)

    def send_key(self, virtual_code, scan_code, flags, client_list = None, force_remote = False, extra_data = None):
        ''' sends keyboard events to clients '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                code = int(scan_code)
                syslog.info(f"REMOTE OUTPUT: key: 0x{code:02x} flags: 0x{flags:02x}")
            payload = KeyData.create(virtual_code, scan_code, flags, action = 'value', extra_data = extra_data).toPayload()
            
            data = self.getDatablock("key", payload)
            self._dispatch(data, client_list)

    def send_mouse_button(self, button_id, is_pressed, client_list = None, force_remote = False, extra_data : dict = None):
        ''' sends a mouse button press or release to clients '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse button: {button_id} pressed: {is_pressed}")

            payload = MouseData().create(button_id, is_pressed, "button", extra_data).toPayload()
            data = self.getDatablock("mouse", payload)
            self._dispatch(data, client_list)


    def send_mouse_button_double_click(self, button_id, is_pressed, client_list = None, force_remote = False, extra_data : dict = None):
        ''' sends a mouse button press or release to clients  '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse dblclick {button_id} pressed: {is_pressed}")
            payload = MouseData().create(button_id, is_pressed, "button_double", extra_data).toPayload()
            data = self.getDatablock("mouse", payload)
            self._dispatch(data, client_list)        

    def send_mouse_wheel(self, direction, client_list = None, force_remote = False, extra_data : dict = None):
        ''' sends vertical mousewheel data  to clients '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse wheel: {direction}")
            payload = MouseData().create(MouseButton.Wheel, direction, "wheel", extra_data).toPayload()
            data = self.getDatablock("mouse", payload)
            self._dispatch(data, client_list)      

    def send_mouse_h_wheel(self, direction, client_list = None,  force_remote = False, extra_data : dict = None):
        ''' sends horizontal mousewheel data to clients '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_outputs
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse H wheel: {direction}")
        
            payload = MouseData().create(MouseButton.HWheel, direction, "hwheel", extra_data).toPayload()
            data = self.getDatablock("mouse", payload)
            self._dispatch(data, client_list) 

    def send_mouse_motion(self, dx, dy, client_list = None, force_remote = False, extra_data : dict = None):
        ''' sends mouse motion data to clients '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse motion: {dx}, {dy}")
            
            payload = MouseData().create(MouseButton.NotSet, (dx,dy), "axis", extra_data).toPayload()
            data = self.getDatablock("mouse", payload)
            self._dispatch(data, client_list)

    def send_mouse_motion_acceleration(self, a, min_speed, max_speed, time_to_max_speed, client_list = None, force_remote = False, extra_data : dict = None):
        ''' sends mouse acceleration data to clients '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: mouse motion acceleration")
            payload = MouseData().create(MouseButton.NotSet, (a, min_speed, max_speed, time_to_max_speed), "amotion", extra_data).toPayload()
            data = self.getDatablock("mouse", payload)
            self._dispatch(data, client_list)

    def send_gamepad_axis(self, index, mode, value, client_list = None, force_remote = False):
        ''' sends a gamepad axis to the remote client '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: gamepad axis: index: {index} mode: {mode} value: {value:0.3f}")
        
            data = self.getDatablock("gamepad")
            data["subtype"] = "axis"
            data["index"] = index # which device to send to
            data["mode"] = mode
            data["value"] = value
            self._dispatch(data, client_list)
    
    def send_gamepad_button(self, index, mode, is_pressed, client_list = None, force_remote = False):
        ''' sends a gamepad button to the remote client '''
        if self.enabled or force_remote:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"REMOTE OUTPUT: gamepad: index: {index} mode: {mode} pressed: {is_pressed}")
            
            data = self.getDatablock("gamepad")
            data["index"] = index  # which device to send to
            data["subtype"] = "button"
            data["mode"] = mode
            data["is_pressed"] = is_pressed
            self._dispatch(data, client_list)

    def send_kvm_mouse_motion_start(self, client_list = None):
        ''' sends kvm init '''
        data = self.getDatablock("kvm")
        data["subtype"] = "start"
        self._dispatch(data, client_list)

    def send_kvm_mouse_motion_stop(self, client_list = None):
        ''' sends kvm terminate '''
        data = self.getDatablock("kvm")
        data["subtype"] = "stop"
        self._dispatch(data, client_list)

    def send_kvm_mouse_motion(self, x : int, y: int, dx : int, dy : int, client_list = None):
        ''' sends mouse position '''
        if self.enabled:
            data = self.getDatablock("kvm")
            data["subtype"] = "motion"
            data["x"] = x
            data["y"] = y
            data["dx"] = dx
            data["dy"] = dy
            self._dispatch(data, client_list)

    def send_kvm_mouse_button(self, button_id : int, is_pressed: bool, client_list = None):
        ''' sends mouse button '''
        if self.enabled:
            data = self.getDatablock("kvm")
            data["subtype"] = "button"
            data["button"] = button_id
            data["is_pressed"] = is_pressed
            self._dispatch(data, client_list)

    def send_kvm_mouse_wheel(self, delta : int, leftright : bool, client_list = None):
        ''' sends mouse wheel '''
        if self.enabled:
            data = self.getDatablock("kvm")
            data["subtype"] = "hwheel" if leftright else "wheel"
            data["delta"] = 1 if delta > 0 else -1  # 120 for up, 65416 for down
            self._dispatch(data, client_list)
    
    def send_kvm_keyboard(self, virtual_code, scan_code, flags, client_list = None):
        ''' handles a kvm key event '''
        if self.enabled:
            data = self.getDatablock("kvm")
            data["subtype"] = "key"
            data["vc"] = virtual_code
            data["sc"] = scan_code
            data["flags"] = flags
            self._dispatch(data, client_list)




    @property
    def enabled(self):
        ''' enables or disabled sending remote events'''
        return True # as of T176 always enable due to the overrides
        # return remote_state.is_remote
    

    @property
    def id(self):
        return self._id
    

    def send(self, data = None, client_id : int = 0):
        ''' sends data to the socket'''
        if data:
            data["sender_id"] = self.clientId
            data["sender_name"] = self.clientName
            data["to"] = client_id if client_id is not None else 0

            # ensure started
            remote_server.start()

            verbose = gremlin.config.Configuration().verbose_mode_remote_extra
            if verbose: syslog.info(f"RPC:  send data {data}")
         
            # encode the data
            raw_data = msgpack.packb(data)    
            if self._sock:
                self._sock.sendto(raw_data, self._address)
            else:
                # retry connection
                self.ensure_socket()
                if self._sock:
                    self._sock.sendto(raw_data, self._address)     

    def sendRequest(self, callback, payload : dict = None, client_id : str = None):
        ''' sends a packet request to clients expecting a response
         
        :param callback: callback to call when the data is received, sends the packet block
        :param data: the data (dict) if any to send to the network - request dependent
        :param client_id: the id of the specific client to send the data to, None means broadcast to all

        if a packet is sent to multiple clients, the callback will be called multiple times, once for each responding client

        '''
        if client_id is None:
            # send to all clients
            client_id = 0
           
        id = gremlin.util.get_guid()
        data = self.getDatablock("request")
        data['request_id'] = id
        data['target'] = client_id
        data['reply_id'] = self.id # send response to self
        data['data'] = payload

        pd = PacketData(callback = callback, client_id = client_id, server_id = self.id, data = data)
        self._callbacks[id] = pd
        self.send(data)
        pd.start()

    def handleResponse(self, request_id, data : dict):
        ''' process a response from a client from sendRequest() '''
        if request_id in self._callbacks:
            pd : PacketData = self._callbacks[request_id]
            del self._callbacks[request_id] # remove the request
            pd.stop() # mark the request received
            pd.trigger(data) # trigger the callback


    def requestAlive(self, callback):
        ''' sends an alive request to a client or all clients '''
        payload = {'action': 'alive', 'response' : None}
        self.sendRequest(callback = callback, payload = payload)

    def requestClients(self, callback):
        ''' sends a client request to identify '''
        payload = {'action': 'identify', 'response' : None}
        syslog.info("RPC: send identify request")
        self.sendRequest(callback = callback, payload = payload)


    def handle(self, data : dict):
        ''' handles received data '''


        sender = data["sender_id"]
        action = data["action"]
        target = data["to"]

        client_id = self.clientId
        if not action in ('identify','identify_client', 'unregister_client', 'register_client'):
            # non global commands
            if sender == client_id:
                # ignore our own broadcasts
                    return
            if target and target != client_id:
                # ignore target if not the current client unless sending to all clients (target == 0)
                return
           
            if not gremlin.shared_state.is_running:
                # profile must be running
                return
        

        verbose = gremlin.config.Configuration().verbose_mode_remote_extra
        if verbose: syslog.info(f"REMOTE: received remote data: {data}")
        


        match action:
            case "hb":
                # heartbeat
                return
            
            case "key":
                # keyboard output
                import win32gui, win32con
                key_data = KeyData().fromPayload(data['data'])
                virtual_code = key_data.virtual_code
                scan_code = key_data.scan_code
                flags = key_data.flags
                if verbose: syslog.info(f"REMOTE: key 0x{scan_code:X}")
                extra_data = key_data.extra_data
                process_name = extra_data['process_name'] if extra_data and 'process_name' in extra_data else None
   
                hwnd = 0
                if process_name:
                    partial_match = extra_data['partial_match'] if extra_data and 'partial_match' in extra_data else False
                    
                    
                    ph = gremlin.process.ProcessHelper()
                    hwnd = ph.findProcessHwnd(process_name, partial_match)
                    if hwnd:
                        # Keyup Bits: (Transition=0, Previous=0, Extended=0, Scancode=0x1E, Repeat=1)
                        lparam = 0x00000001 | scan_code << 16 # Scan code, repeat=1
                        is_extended = flags & win32con.KEYEVENTF_EXTENDEDKEY 
                        msg = win32con.WM_KEYUP if flags & win32con.KEYEVENTF_KEYUP else win32con.WM_KEYDOWN
                        if is_extended:
                            lparam |= 0x01000000; # Extended code if required
                        hwnd_list = gremlin.keyboard.getInnerWindows(hwnd)
                        if msg == win32con.WM_KEYUP:
                            lparam |= 0xC0000000 # key up
                        for sub_hwnd in hwnd_list:  # must send to specific process subhandles for POST method
                            win32gui.PostMessage(sub_hwnd, msg, virtual_code, lparam)
                    else:
                        # send to window with focus
                        gremlin.sendinput.send_key(virtual_code, scan_code, flags)
                
                
                # win32api.keybd_event(virtual_code, scan_code, flags, 0) # deprecated
        
            case "mouse":
                # mouse output
                payload = data['data']
                mouse_data = MouseData().fromPayload(payload)
                subtype = mouse_data.action
                match subtype:
                    case"wheel":
                        direction = mouse_data.value
                        if verbose: syslog.info(f"REMOTE: wheel {direction}")
                        gremlin.sendinput.mouse_wheel(direction)
                    case "hwheel":
                        direction = mouse_data.value
                        if verbose: syslog.info(f"REMOTE: wheel {direction}")
                        gremlin.sendinput.mouse_h_wheel(direction)
                    case "button":
                        button_id = mouse_data.button_id
                        button = gremlin.types.MouseButton.to_enum(button_id)
                        is_pressed = mouse_data.value
                        if is_pressed:
                            if verbose: syslog.info(f"REMOTE: mouse button down {button.name}")    
                            gremlin.sendinput.mouse_press(button)
                        else:
                            if verbose: syslog.info(f"REMOTE: mouse button up {button.name}")    
                            gremlin.sendinput.mouse_release(button)
                    case "button_double":
                        button_id = mouse_data.button_id
                        button = gremlin.types.MouseButton.to_enum(button_id)
                        is_pressed = mouse_data.value
                        if is_pressed:
                            if verbose: syslog.info(f"REMOTE: double click {button.name}")    
                            gremlin.sendinput.mouse_press_double_click(button)
                    case "axis":
                        dx,dy = mouse_data.value
                        mouse_controller = gremlin.sendinput.MouseController()
                        if verbose: syslog.info(f"REMOTE: mouse axis [{dx},{dy}]")    
                        mouse_controller.set_absolute_motion(dx, dy)

                    case "amotion":
                        # accelerated motion
                        a, min_speed, max_speed, time_to_max_speed = mouse_data.value
                        mouse_controller = gremlin.sendinput.MouseController()
                        if verbose: syslog.info(f"REMOTE: mouse accelerated motion")    
                        mouse_controller.set_accelerated_motion(a,min_speed,max_speed,time_to_max_speed)

            case "kvm":
                # kvm mode
                
                subtype = data["subtype"]
                match subtype:
                    case "start" | "stop":
                        # set/reset
                        pass
                    case "motion":
                        # mouse movement (via deltas)
                        dx = data["dx"]
                        dy = data["dy"]

                        if verbose: syslog.info(f"KVM (client): received motion delta {dx} {dy}")
                        gremlin.sendinput.send_mouse_motion(dx, dy)
                        
                    case "button":
                        # mouse button 1 to 5 for normal buttons, > 5 for wheel codes
                        button_id = data["button"]
                        if button_id > 5:
                            # wheel
                            button = MouseButton(button_id)
                            if verbose: syslog.info(f"KVM (client): received mouse wheel: {button.name}")
                            match button:
                                case MouseButton.WheelUp:
                                    gremlin.sendinput.mouse_wheel(1)
                                case MouseButton.WheelDown:
                                    gremlin.sendinput.mouse_wheel(-1)
                                case MouseButton.WheelLeft:
                                    gremlin.sendinput.mouse_h_wheel(-1)
                                case MouseButton.WheelRight:
                                    gremlin.sendinput.mouse_h_wheel(1)
                        else:
                            # mouse button 1 to 5
                            is_pressed = data["is_pressed"]
                            if verbose: syslog.info(f"KVM (client): received mouse button: {button_id} pressed: {is_pressed}")
                            if is_pressed:
                                gremlin.sendinput.mouse_press(button_id)
                            else:
                                gremlin.sendinput.mouse_release(button_id)
                    case "wheel":
                        delta = data["delta"]
                        gremlin.sendinput.mouse_wheel(delta)
                    case "hwheel":
                        delta = data["delta"]
                        gremlin.sendinput.mouse_h_wheel(delta)
                    case "key":
                        virtual_code = data["vc"]
                        scan_code = data["sc"]
                        flags = data["flags"]
                        gremlin.sendinput.send_key(virtual_code, scan_code, flags)
                        

            case "request":
                # received a requet for information from a specific client - this is recevied by clients that need to reply
                request_data = data['data']
                match request_data['action']:
                    case "identify":
                        # identify client
                        data['action'] = "reply"
                        request_data['response'] = ClientData().toPayload()
                        self.send(data, client_id = data['reply_id'])

            case "reply":
                # received a reply packet from a prior request - this is received by the requesting client
                request_id = data['request_id']
                if request_id in self._callbacks:
                    # grab the specific request, ignore if not ours
                    payload : PacketData = self._callbacks[request_id]
                    request_data = data['data']
                    response = request_data['response']
                    payload.response = response
                    payload.callback(payload)

            case "identify":
                # received a request to self identify to the network
                data = self.getDatablock("identify_client", ClientData().toPayload())
                self.send(data) # send to all

            case "identify_client":
                # request to register the specified client as a result of a prior "identify" request
                payload = data['data']
                cd = ClientData.fromPayload(payload)
                if verbose:
                    syslog.info(f"RPC: identity received: {str(cd)}")

                self.remote_control.registerClient(cd)

            

            case "unregister_client":
                # request to unregister the specified client
                payload = data['data']
                cd = ClientData.fromPayload(payload)
                if verbose:
                    syslog.info(f"RPC: disconnect received: {str(cd)}")

                self.remote_control.unregisterClient(cd.client_id)
        
            case "gamepad":
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
            





            case "button" | "axis" | "hat" | "relative_axis" | "toggle":
                # joystick button
                
                relative_value = 0.0
                payload = data['data']
                match action:
                    case 'button' | 'toggle':
                        packet = ButtonData().fromPayload(payload)
                        device = packet.device_id
                        target = packet.button_id
                        value = packet.is_pressed
                    case 'axis' | 'relative_Axis':
                        packet = AxisData().fromPayload(payload)
                        device = packet.device_id
                        target = packet.axis_id
                        value = packet.value
                        relative_value = packet.relative_value
                    case 'hat':
                        packet = HatData().fromPayload(payload)
                        device = packet.device_id
                        target = packet.hat_id
                        value = packet.direction


                # device = data["device"]
                # target = data["target"]
                # value = data["value"]
                # if "relative_value" in data:
                #     relative_value = data["relative_value"]
                # else:
                #     relative_value = 0.0

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

            case "pause":
                # pause client 
                duration = data['value']
                time.sleep(duration)


            case _:
                syslog.error(f"REMOTE: don't know how to handle action [{action}]")



   
 


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

class ButtonData():
    ''' holds button data '''

    def __init__(self):
        self.device_id = None
        self.button_id = None
        self.is_pressed = None
        self.action = None

    @staticmethod
    def create(device_id : str, button_id : int, is_pressed : bool = None, action : str = None):
        self = ButtonData()
        self.device_id = device_id
        self.button_id = button_id
        self.is_pressed = is_pressed
        self.action = action
        return self
    
    def toPayload(self) -> dict:
        ''' creates a payload from the data '''
        return {
            'device' : self.device_id,
            'target' : self.button_id,
            'value' : self.is_pressed,
            'action' : self.action
        }
     
    @staticmethod
    def fromPayload(data : dict) -> ButtonData:
        ''' loads from payload '''
        self = ButtonData()
        self.device_id = data['device']
        self.button_id = data['target']
        self.is_pressed = data['value']
        self.action = data['action']
        return self

class AxisData():
    ''' holds axis data '''

    def __init__(self):
        self.device_id : str = None
        self.axis_id : int = None
        self.value = None
        self.relative_value = None
        self.action = None

    @staticmethod
    def create(device_id : str, axis_id : int, value : float = None, relative_value : float = None, action : str = None):
        self = AxisData()
        self.device_id = device_id
        self.axis_id = axis_id
        self.value = value
        self.relative_value = relative_value
        self.action = action

        return self
    
    def toPayload(self) -> dict:
        ''' creates a payload from the data '''
        return {
            'device' : self.device_id,
            'target' : self.axis_id,
            'value' : self.value,
            'rvalue' : self.relative_value,
            'action' : self.action
        }
     
    @staticmethod
    def fromPayload(data : dict) -> AxisData:
        ''' loads from payload '''
        self = AxisData()
        self.device_id = data['device']
        self.axis_id = data['target']
        self.value = data['value']
        self.relative_value = data['rvalue']
        self.action = data['action']
        
        return self
    
class HatData():
    ''' holds hat data '''
    def __init__(self):
        self.device_id : str = None
        self.hat_id : int = None
        self.direction : tuple = None # tuple
        self.action : str = None

        
    @staticmethod
    def create(device_id : str, hat_id : int, direction : tuple, action : str = None) -> HatData:
        self = HatData()
        self.device_id = device_id
        self.hat_id = hat_id
        self.direction = direction
        self.action = action
        return self
    
    def toPayload(self) -> dict:
        return {
            'device' : self.device_id,
            'target' : self.hat_id,
            'value' : self.direction,
            'action' : self.action
        }

    @staticmethod
    def fromPayload(data : dict) -> HatData:
        self = HatData()
        self.device_id = data['device']
        self.hat_id = data['target']
        self.direction = data['value']
        self.action = data['action']

class KeyData():
    ''' holds key data '''
    def __init__(self):
        self.virtual_code : int = None
        self.scan_code : int = None
        self.flags : int = None
        self.action : str = None
        self.extra_data : dict = None

    @staticmethod
    def create(virtual_code : int, scan_code : int, flags : int, action : str = None, extra_data : dict = None) -> KeyData:
        self = KeyData()
        self.virtual_code = virtual_code
        self.scan_code = scan_code
        self.flags = flags
        self.action = action
        self.extra_data = extra_data
        return self
    
    def toPayload(self) -> dict:
        return {
            'vc' : self.virtual_code,
            'sc' : self.scan_code,
            'flags' : self.flags,
            'action' : self.action,
            'extra' : self.extra_data
        }
    
    @staticmethod
    def fromPayload(data : dict) -> KeyData:
        self = KeyData()
        self.virtual_code = data['vc']
        self.scan_code = data['sc']
        self.flags = data['flags']
        self.action = data['action']
        self.extra_data = data['extra']
        return self

class MouseData():
    ''' holds mouse data '''
    def __init__(self):
        self.button_id : int = None
        self.value = None
        self.action : str = None
        self.extra_data : dict = None
        

    @staticmethod
    def create(button_id: int, value, action : str = None, extra_data : dict = None) -> MouseData:
        self = MouseData()
        self.button_id = button_id
        self.value = value
        self.action = action
        self.extra_data = extra_data
        return self

    def toPayload(self) -> dict:
        return {
            'button' : self.button_id,
            'value' : self.value,
            'action' : self.action,
            'extra' : self.extra_data
        }
    
    @staticmethod
    def fromPayload(data : dict) -> MouseData:
        self = MouseData()
        self.button_id = data['button']
        self.value = data['value']
        self.action = data['action']
        self.extra_data = data['extra']
        return self
    

class ClientData():
    ''' holds network client data '''
    def __init__(self, auto : bool = True):
        self.client_id = remote_client.clientId if auto else None # id is a unique id corresponding to the host 
        self.client_name = remote_client.clientName if auto else None # name of the client (optional)
        self.custom_name = remote_client.customName if auto else None # custom name of the client (optional)
        self.client_version = gremlin.shared_state.application_version if auto else None # version of the client (optional)
        self.client_timestamp = gremlin.shared_state.application_start_time if auto else None # start time of the client (optional)

    def getClientName(self):
        ''' gets the client name custom or system'''
        return self.custom_name if self.custom_name else self.client_name

    @staticmethod
    def fromData(
                 client_id : int,
                 client_name : str,
                 custom_name : str,
                 client_version : str = None,
                 client_timestamp : int = None):
        self = ClientData(False)
        self.client_name = client_name
        self.custom_name = custom_name
        self.client_id = client_id
        self.client_version = client_version
        self.client_timestamp = client_timestamp

        return self

    def toPayload(self) -> dict:
        ''' creates a payload from the data '''
        return {
            'client_id' : self.client_id,
            'client_name' : self.client_name,
            'client_custom' : self.custom_name,
            'client_version' : self.client_version,
            'client_timestamp' : self.client_timestamp
        }
    
    @staticmethod
    def fromPayload(data : dict) -> ClientData:
        ''' loads from payload '''
        cd = ClientData(auto = False)
        cd.client_id = data['client_id']
        cd.client_name = data['client_name']
        cd.custom_name = data['client_custom']
        cd.client_version = data['client_version']
        cd.client_timestamp =  data['client_timestamp']
        return cd
    
    @property
    def uptime(self):
        ''' client up time '''
        if self.client_timestamp:
            return time.time() - self.client_timestamp
        return None

    def __hash__(self):
        return hash((self.client_id, self.client_name, self.custom_name, self.client_version))

    def __str__(self):
        stub = f"({self.custom_name})" if self.custom_name else ''
        return f"client: {stub}[{self.client_name}]/[{self.client_id}]"

@gremlin.singleton_decorator.SingletonDecorator
class RemoteControl():
    ''' holds remote control status information and known network client tracker '''

    def __init__(self):
        
        self._is_remote = False
        self._is_local = False
        self._is_paired = False
        self._global_remote_enabled = gremlin.config.Configuration().remoteEnabled() # initial state of global options
        self._clients = {}
        
        self._mode = VjoyAction.VJoyEnableLocalOnly
        self._update(self._mode)
        el = gremlin.event_handler.EventListener()
        el.config_changed.connect(self._handle_options_changed)
        el.remote_control_enable.connect(self._handle_remote_control_enable)
        el.remote_control_disable.connect(self._handle_remote_control_disable)
        

        # map of clients

        self.registerSelf()
        
        
    def registerSelf(self):
        ''' registers the current client '''
        
        self.registerClient(
            ClientData.fromData(
                self.clientId,
                self.hostName,
                self.customName,
                gremlin.shared_state.application_version,
                gremlin.shared_state.application_start_time
            )
        )

    def _handle_remote_control_enable(self):
        ''' called when remote control should be enabled '''
        gremlin.config.Configuration().enable_remote_broadcast = True

    def _handle_remote_control_disable(self):
        ''' called when remote control should be enabled '''
        gremlin.config.Configuration().enable_remote_broadcast = False


    @property
    def customName(self) -> str:
        config = gremlin.config.Configuration()
        return config.custom_host_name
    
    @property
    def hostName(self) -> str:
        ''' host name of the current instance '''
        return socket.gethostname()
    
    @property
    def clientId(self) -> int:
        ''' unique instance id for this instance '''
        return uuid.getnode()
    
    @property
    def clientName(self) -> str:
        custom_name = self.customName
        return custom_name if custom_name else self.hostName

    

    @property
    def clientEnabled(self) -> bool:
        ''' true if remote control by another client is enabled'''
        config = gremlin.config.Configuration()
        return config.enable_remote_control
    
    @property 
    def serverEnabled(self) -> bool:
        ''' true if remote control enabled for broadcast/server '''
        config = gremlin.config.Configuration()
        return config.enable_remote_broadcast
    
    def remoteEnabled(self) -> bool:
        ''' true if remote control is enabled - client or server - this checks the global options '''
        config = gremlin.config.Configuration()
        return config.remoteEnabled()
    
    def getLocalClientId(self):
        ''' gets the local client ID (this machine)'''
        return self.clientId
    
    def getClients(self) -> dict:
        ''' gets all clients '''
        return self._clients
    
    def getClient(self, client_id: str):
        ''' gets a registered client '''
        if client_id in self._clients:
            return self._clients[client_id]
        return None
   
    

    def registerClient(self, data : ClientData):
        ''' registers a client '''
        client_id = data.client_id
        changed = False
        if client_id in self._clients:
            # client already exists, detect changes
            client = self._clients[client_id]
            if client != data:
                # at least one param changed
                self._clients[client_id] = data
                changed = True
        else:                
            changed = True
            self._clients[client_id] = data
            # fire an update event

        if changed:
            el = gremlin.event_handler.EventListener()
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose: syslog.info(f"RPC: new/updated client registered: {data}")
            
            el.remote_control_client_change.emit()

    def unregisterClient(self, client_id : str):
        ''' unregisters a client '''
        if client_id in self._clients:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                data = self._clients[client_id]
                syslog.info(f"RPC: new client unregistered: {data}")
            del self._clients[client_id]
            
        el = gremlin.event_handler.EventListener()
        el.remote_control_client_change.emit()


        
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
            self.is_local = is_local
            self.is_remote = is_remote

            syslog.info(f"REMOTE CONTROL: local [{'ENABLED' if self._is_local else 'DISABLED'}] remote [{'ENABLED' if self._is_remote and self.remoteEnabled() else 'DISABLED' if self._is_remote else 'DISABLED'}]")            

            self._handle_options_changed()

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


    def _handle_options_changed(self):
        ''' called when broadcast config item changes '''
        
        config = gremlin.config.Configuration()
        if self._global_remote_enabled != config.enable_remote_broadcast:
            self._global_remote_enabled = config.enable_remote_broadcast

            el = gremlin.event_handler.EventListener()
            el.broadcast_changed.emit(gremlin.event_handler.StateChangeEvent(self._is_local, self._is_remote, self._global_remote_enabled))
            el.remote_control_state_change.emit()

            self.registerSelf() # update

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

    def isKeyboardSupressed(self) -> bool:
        ''' gets the current suspended state '''
        import gremlin.windows_event_hook
        return gremlin.windows_event_hook.KeyboardHook().isSupressed()
    
    def isMouseSupressed(self) -> bool:
        ''' gets the current suspended state '''
        import gremlin.windows_event_hook
        return gremlin.windows_event_hook.MouseHook().isSupressed()
    
    

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
    @is_local.setter
    def is_local(self, value : bool):
        self._is_local = value
    
    @property
    def is_remote(self):
        ''' status of remote control - requires both remote and broadcast to be enabled '''
        config = gremlin.config.Configuration()
        return self._is_remote and config.remoteEnabled()
    
    @is_remote.setter
    def is_remote(self, value : bool):
        if self._is_remote != value:
            self._is_remote = value
            el = gremlin.event_handler.EventListener()
            el.remote_control_state_change.emit() # indicate remote control changed
    
    @property
    def state(self):
        ''' returns status as a pair of flags, local, remote'''
        kvm_mode = self.isKeyboardSupressed() or self.isMouseSupressed()
        return (self.is_local and not kvm_mode, self.is_remote or kvm_mode)
    
    @property
    def paired(self):
        ''' paired status '''
        return self._is_paired

    
    def to_state_event(self):
        ''' returns event data for the current state '''
        from gremlin.event_handler import StateChangeEvent
        config = gremlin.config.Configuration()
        event = StateChangeEvent(self.is_local, self.is_remote, config.enable_remote_broadcast)
        return event
  






class PacketState(enum.Enum):
    New = 0
    Sent = 1
    Received = 2
    TimedOut = 3


class PacketData:
    ''' holds callback data info to track sent requests to other GEX clients '''
    def __init__(self, id : str = None,
                 client_id : str = None,
                 server_id : str = None,
                 callback = None, data = None):
        self.id = id if id else gremlin.util.get_guid()
        self.callback = callback
        self.data = data
        self.response = None
        self.sent = time.time()
        self.received = None1
        self.client_id = client_id # who to send the request to
        self.server_id = server_id # who to send the request response to
        self.client_name = None # optional name
        self.timer = None
        self.status = PacketState.New
        self.response = None # receive data

    def start(self):
        self.timer = threading.Timer(4, self._handle_timeout)
        self.timer.start()

    def stop(self):
        ''' stops the timeout timer when a response is received '''
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def trigger(self, data : dict = None):
        ''' trigger the callback'''
        self.response = data
        self.callback(self)
   
    def _handle_timeout(self):
        ''' called when request times out before getting a response '''
        if not self.received:
            self.state = PacketState.TimedOut
            self.trigger()




class RemoteClientData():
    def __init__(self, client_name : str = None, custom_client_name : str = None, client_id : int = 0, client_version : str = None, selected : bool = False):
        self.client_name = client_name # client to send the data to (we store the name) - None = ANY
        self.custom_name = custom_client_name
        self._client_id = 0
        self.client_id = client_id # client MAC address (the client ID may change session to session) - None = ANY
        self.client_version = client_version
        self.selected = selected
        self.discovered = False # true if discovered on the network
    
     
    def getClientName(self) -> str:
        ''' gets the custom or host name '''
        return self.custom_name if self.custom_name else self.client_name

    @staticmethod
    def fromClientData(client : ClientData):
        self = RemoteClientData()
        self.client_name = client.client_name
        self.client_id = client.client_id
        self.client_version = client.client_version
        self.custom_name = client.custom_name
        return self
    
    @property
    def client_id(self) -> str:
        return self._client_id
    @client_id.setter
    def client_id(self, value : str):
        assert isinstance(value, int)
        self._client_id = value
 
    def to_xml(self):# -> Any:
        ''' creates a node from the data block and returns it '''
        node = ElementTree.Element('client')
        
        # only save selected clients
        if self.client_name:
            node.set("client-name", self.client_name)
        if self.custom_name:
            node.set("custom-name", self.custom_name)
        if self.client_id:
            node.set("client-id", safe_format(self.client_id, int))
        node.set("selected", safe_format(self.selected, bool))
        return node
        

    def from_xml(self, node):
        ''' reads from the xml node - the node should be the parent node '''
        if "client-name" in node.attrib:
            self.client_name = node.get("client-name")
        if "custom-name" in node.attrib:
            self.custom_name = node.get("custom-name")
        if "client-id" in node.attrib:
            client_id = node.get("client-id")
            if client_id == "any":
                client_id = 0
            else:
                client_id = safe_read(node, "client-id", int, 0)
            if client_id == "any": client_id = 0 # legacy change
            self.client_id = client_id
        self.selected = safe_read(node,"selected", bool, False)

    @property
    def connected(self) -> bool:
        ''' true if the client is currently known to GremlinEx '''
        remote_control = RemoteControl()
        return remote_control.getClient(self.client_id) is not None
    
    @property
    def isLocalClient(self) -> bool:
        ''' true if the data is for our own client '''
        remote_control = RemoteControl()
        return self._client_id == remote_control.getLocalClientId()


    @staticmethod
    def any() -> RemoteClientData:
        return RemoteClientData("Any", 0)
    
    def __str__(self):
        version_stub = f"/[{self.client_version}]" if self.client_version else ''
        return f"[{self.client_name}]/[{self.client_id}]{version_stub}"
   



class RemoteConfig():
    ''' holds configuration data for a remote client broadcast - this is persisted to the profile per action if needed '''
    client_changed = Signal() # fires when clients are added or removed
    def __init__(self,
                 local : bool = True,
                 remote : bool = False,
                 local_enabled : bool = True,
                 remote_enabled : bool = True,
                 remote_profile_enabled : bool = True,
                 singleton : bool = False,
                 client_change_callback = None):
        
        self._local : bool = local # send to local client
        self._local_enabled : bool = local_enabled # true if the action can send to the local client

        self._clients = {} # map of client [client_id] -> RemoteClientData 

        self._remote : bool = remote # send to remote client
        self._remote_enabled : bool = remote_enabled # true if remote is enabled

        self._remote_profile: bool = True # true if the action is sending local when profile is not in remote mode, and remote when profile is in remote mode
        self._remote_profile_enabled : bool = remote_profile_enabled # true when remote profile is enabled for this configuration (this is set by actions that don't allow this mode)

        self._is_custom : bool = False # true if the configuration is custom set
        
        self._profile_remote_mode_enabled : bool = remote_enabled # true if the action can send to a remote client
        self._process_name : str = None # target process name (None if target is the window with focus)
        self._is_target_process : bool = False # true if a target process is defined
        self._is_partial_match : bool = True # true if we are matching partial titles when looking for a target process by title

        self._client_changed_callbacks = []
        if client_change_callback:
            self._client_change_callbacks.append(client_change_callback)
        self.ensureAnyClient() # ensure the ANY client is in the list
        self.singleton : bool = singleton # true if the remote control can only send to a single client
        el = gremlin.event_handler.EventListener()
        el.remote_control_client_change.connect(self._clients_changed)

        self._sync_clients() # populate existing clients


    def registerClientChangeCallback(self, callback):
        ''' add a callback on client changes '''
        if callback and not callback in self._client_changed_callbacks:
            self._client_changed_callbacks.append(callback)

    def unregisterClientChangeCallback(self, callback):
        ''' removes a callback from this config object'''
        if callback and callback in self._client_changed_callbacks:
            self._client_changed_callbacks.remove(callback)

    def _clients_changed(self):
        ''' known client list chagned - synchronize with current list '''

        verbose = gremlin.config.Configuration().verbose_mode_remote_extra
        if verbose: syslog.info(f"RPC: remote config: received client change event")

        changed = self._sync_clients()


        # notify clients changed
        if changed:
            if self._client_changed_callbacks:
                for callback in self._client_changed_callbacks:
                    callback()

            self.client_changed.emit()

    def _sync_clients(self) -> bool:
        ''' synchronizes clients list with received network data '''
        verbose = gremlin.config.Configuration().verbose_mode_remote
        clients = remote_control.getClients()
        changed = len(self._clients) != (len(clients) if clients else 0)
        
        if clients:
            # update clients
            for client_id in clients:
                client : ClientData = clients[client_id]
                if not client_id in self._clients:
                    # if verbose: syslog.info(f"RPC: config: register new client [{client.client_name}]")
                    self.addClient(client.client_name, client.client_id, client.client_version, client.custom_name)
                    client.discovered = True
                    changed = True
                else:
                    c1 : RemoteClientData = self._clients[client_id]
                    # record changes
                    if c1.custom_name != client.custom_name:
                        c1.custom_name = client.custom_name
                        changed = True


            client : RemoteClientData
            for client in self._clients.values():
                connected = client.connected
                if client.discovered != connected:
                    client.discovered = connected
                    changed = True

        return changed
    
    def getClientList(self) -> list:
        ''' gets the list of active output clients '''
        if self.anySelected():
            return [0] # any
        return [client.client_id for client in self._clients.values() if client.selected and client.client_id != 0]
        


    @property
    def isCustom(self) -> bool:
        ''' true if using custom routing '''
        return self._is_custom
    @isCustom.setter
    def isCustom(self, value : bool):
        self._is_custom = value

    @property
    def isProcess(self) -> bool:
        ''' true if a custom target process is used '''
        return self._is_target_process
    @isProcess.setter
    def isProcess(self, value : bool):
        self._is_target_process = value        

    @property
    def partialMatch(self) -> bool:
        return self._is_partial_match
    @partialMatch.setter
    def partialMatch(self, value : bool):
        self._is_partial_match = value

    @property
    def localEnabled(self) -> bool:
        ''' true if local mode is enabled for active output '''
        if self._remote_profile:
            # exclusive mode
            rc = RemoteControl()
            return self._local_enabled and rc.is_local
        return self._local_enabled
    
    @localEnabled.setter
    def localEnabled(self, value : bool):
        self._local_enabled = value

    @property
    def remoteEnabled(self) -> bool:
        ''' true if profile remote mode is enabled for active output '''
        rc = RemoteControl()
        if self._remote_profile:
            # exclusive mode 
            return rc.is_remote and rc.remoteEnabled
        return rc.remoteEnabled
    
   
    
    @property
    def remote(self) -> bool:
        ''' true if remote control is enabled '''
        return self._remote
   
    @remote.setter
    def remote(self, value : bool):
        self._remote = value

    @property
    def remoteEnabled(self) -> bool:
        return self._remote_enabled
    
    @remoteEnabled.setter
    def remoteEnabled(self, value : bool):
        self._remote_enabled = value

    @property
    def activeRemote(self) -> bool:
        ''' true if remote control is actively enabled for this action (runtime) '''
        if gremlin.shared_state.is_running:
            # profile must be running
            rc = RemoteControl()
            if self._remote_profile:
                return self.remoteProfileEnabled and rc.is_remote
            if self._remote:
                return self.remoteEnabled and rc.remoteEnabled
        return False
    
    @property
    def activeLocal(self) -> bool:
        ''' true if local mode is enabled (runtime)'''
        return gremlin.shared_state.is_running and self._local and self.localEnabled
        

    @property
    def remoteProfile(self) -> bool:
        return self._remote_profile
    @remoteProfile.setter
    def remoteProfile(self, value : bool):
        self._remote_profile = value

    @property
    def remoteProfileEnabled(self) -> bool:
        return self._remote_profile_enabled 
    @remoteProfileEnabled.setter
    def remoteProfileEnabled(self, value : bool):
        self._remote_profile_enabled = value      

    @property
    def local(self) -> bool:
        ''' true if local is enabled '''
        return self._local_enabled and self._local
    @local.setter
    def local(self, value : bool):
        self._local= value

    


    @property
    def process(self) -> str:
        return self._process_name
    @process.setter
    def process(self, value : str):
        self._process_name = value

    def selectAll(self):
        ''' selects all clients '''
        for client in self._clients.values():
            client.selected = True
    def selectNone(self):
        ''' selects no clients '''
        for client in self._clients.values():
            client.selected = False

    @property
    def state(self) -> tuple:
        ''' gets the active local, remote state '''
        return (self.activeLocal, self.activeRemote)


    def _handle_request_client_response(self, packet: PacketData ):
        ''' called as clients respond to the request'''
        response = packet.response
        if response:
            client = ClientData(False).fromPayload(response)
            syslog.info(f"REMOTE: received client response:")
            syslog.info(f"client [{client.client_name}][{client.client_id}] version: [{client.client_version}]")
            remote_control.registerClient(client)

        syslog.info(f"Status: [{packet.status.name}]")

    def getState(self) -> tuple:
        ''' gets the connection state '''
        return (self.activeLocal, self.activeRemote)
   
    def getClient(self, client_id : int) -> RemoteClientData:
        ''' gets a client by ID '''
        if client_id in self._clients:
            return self._clients[client_id]
        return None
    
    def getLocalClientId(self):
        return remote_control.getLocalClientId()
   
    def addClient(self, client_name : str,  client_id : str, client_version : str = None, custom_name : str = None) -> RemoteClientData:
        ''' adds a new client to the config if it doesn't exist, can also update the name  '''
        if client_id in self._clients:
            client = self._clients[client_id]
            if client.client_name != client_name:
                client.client_name = client_name
        else:
            client = RemoteClientData(client_name, custom_name, client_id, client_version)
            self._clients[client_id] = client

        return client
   
    def ensureAnyClient(self):
        ''' makes sure the ANY client is in the client list '''
        if not 0 in self._clients:
            self.addClient("Any", 0)

   
    def removeClient(self, client_id : str):
        ''' removes a client from the client list '''
        if client_id in self._clients:
            del self._clients[client_id]

    def anySelected(self) -> bool:
        ''' true if the any client is selected '''
        self.ensureAnyClient()
        return self._clients[0].selected


    def getClients(self) -> list[RemoteClientData]:
        ''' gets a list of all clients for this configuration  '''
        self.ensureAnyClient()
        client_list = [client for client in self._clients.values()]
        if client_list:
            client_list.sort(key = lambda x: x.getClientName().casefold() if x.getClientName() else '')
        return client_list
   
    def getClientCount(self) -> int:
        ''' gets the number of clients '''
        return len(self._clients)

    def getSelectedCount(self) -> int:
        ''' returns the number of selected clients '''
        return sum((1 if client.selected else 0 for client in self._clients.values()))
   
    @property
    def enabled(self) -> bool:
        ''' true if remote control is enabled in GremlinEx '''
        return remote_client.enabled

    def setSelected(self, client_id : str, selected : bool):
        ''' selects or unselects a client '''

   
    def to_xml(self):# -> Any:
        ''' creates a node from the data block and returns it '''
        node = ElementTree.Element('remote-config')
        node.set("custom",safe_format(self._is_custom, bool) )
        node.set("local", safe_format(self._local, bool))
        node.set("remote", safe_format(self._remote, bool))
        node.set("remote-profile", safe_format(self._remote_profile, bool))
        node.set("singleton", safe_format(self.singleton, bool))
        if self.process:
            node.set("process", safe_format(self.process, str, escape = True))
        node.set("target-process", safe_format(self.isProcess, bool))
        node.set("partial-title", safe_format(self.partialMatch, bool))

        client : RemoteClientData
        for client in self._clients.values():
            if client.selected:
                client_node = client.to_xml()
                node.append(client_node)
       
        return node

    def from_xml(self, node):
        ''' reads from the xml node - the node should be the parent node '''
        self._is_custom  = safe_read(node,"custom", bool, False)
        self._local = safe_read(node, "local", bool, True)
        self._remote = safe_read(node, "remote", bool, True)
        self._remote_profile = safe_read(node, "remote-profile", bool, True)
        self.singleton = safe_read(node, "singleton", bool, False)
        if "process" in node.attrib:
            self.process = safe_read(node,"process", str, None, unescape=True)
        self.isProcess = safe_read(node,"target-process", bool, False)
        self.partialMatch = safe_read(node,"partial-title", bool, True)

        # list of clients
        client_nodes = node.xpath(".//client")
        for client_node in client_nodes:
            client = RemoteClientData()
            client.from_xml(client_node)
            self._clients[client.client_id] = client
           
        # ensure at least one client is selected
        count = self.getSelectedCount()
        if not count:
            client = self.getClient(0)
            client.selected = True


       




# remote state
remote_control = RemoteControl()

# Global remote server = listens to remote client events
remote_server = RemoteServer()

# Global remote client = sends events to server
remote_client = RemoteClient()