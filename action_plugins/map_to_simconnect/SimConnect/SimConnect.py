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

# Adapted from: https://github.com/odwdinc/Python-SimConnect  Credit for original code goes to the authors of the Python-SimConnect project

import ctypes
from ctypes import *
from ctypes.wintypes import *
import logging
import time
from .Enum import *
from .Constants import *
from .Attributes import *
import os
import threading
from PySide6 import QtCore
import gremlin.event_handler
import gremlin.singleton_decorator



_library_path = os.path.splitext(os.path.abspath(__file__))[0] + '.dll'



def millis():
	return int(round(time.time() * 1000))


class SimConnect():
	''' MSFS simconnect interface '''


	def __init__(self, handler, auto_connect=True, library_path=_library_path, verbose = False, 
			  	sim_paused_callback = None,
				sim_running_callback = None,
				aircraft_loaded_callback = None):
		
		#from action_plugins.map_to_simconnect.SimConnectData import SimConnectEventHandler
		
		self.Requests = {}
		self.Facilities = []

		self.verbose = True # verbose
		self.verbose_details = False
		self._library_path = library_path
		self._hSimConnect = HANDLE()
		self._quit = 0
		self.ok = False
		self.running = False
		self._is_loop_running = False  # true if the DLL event listen loop is running
		self._is_connected = False # true if the DLL is hooked
		self._request_busy = False
		self.paused = False
		self.DEFINITION_POS = None
		self.DEFINITION_WAYPOINT = None
		self._my_dispatch_proc_rd = None
		
		self._sim_paused_callback = sim_paused_callback
		self._sim_running_callback = sim_running_callback
		self._sim_start_callback = None
		self._sim_stop_callback = None
		self._aircraft_loaded_callback = aircraft_loaded_callback


		self.handler = handler
		
		# hook connect
		handler.simconnect_connected.connect(self._connected)

		# hook disconnect
		handler.simconnect_disconnected.connect(self._disconnected)

		# hook disconnect request
		handler.request_disconnect.connect(self._disconnect_request)

		# hook connect request
		handler.request_connect.connect(self._connect_request)
	
		if auto_connect:
			self.connect()

					

		
				
	@QtCore.Slot()
	def _connected(self):
		# marke completed
		self._request_busy = False
		syslog = logging.getLogger("system")
		syslog.info(f"Simconnect: connect request completed")

	@QtCore.Slot()
	def _disconnected(self):
		# marke completed
		self._request_busy = False
		syslog = logging.getLogger("system")
		syslog.info(f"Simconnect: disconnect request completed")
		

	@QtCore.Slot()
	def _connect_request(self):
		''' connection request received '''
		if not self._request_busy:
			self._request_busy = True
			if not self._is_connected:
				self.connect()

				while not self._is_loop_running:
					time.sleep(0.1)
			else:
				# already running
				self._request_busy = False 

			


	@QtCore.Slot()
	def _disconnect_request(self):
		''' connection disconnect received '''
		if not self._request_busy:
			self._request_busy = True
			if self._is_loop_running:
				self.exit()
			else:
				# not running
				self._request_busy = False
		

	# events fired by SimConnect

	def IsHR(self, hr, value):
		_hr = ctypes.HRESULT(hr)
		return ctypes.c_ulong(_hr.value).value == value

	def handle_id_event(self, event):
		syslog = logging.getLogger("system")
		uEventID = event.uEventID
		if uEventID == self._dll.EventID.EVENT_SIM_START:
			self.handler.simconnect_sim_start.emit()
			syslog.info("SimConnect: event: SIM START")
			self.running = True
			if self._sim_running_callback:
				self._sim_running_callback(True)
		elif uEventID == self._dll.EventID.EVENT_SIM_STOP:
			self.handler.simconnect_sim_stop.emit()
			if self.verbose:
				syslog.info("SimConnect: event: SIM Stop")
			self.running = False
			if self._sim_running_callback:
				self._sim_running_callback(False)
		# Unknow whay not reciving
		elif uEventID == self._dll.EventID.EVENT_SIM_PAUSED:
			self.handler.simconnect_sim_paused.emit()
			if self.verbose:
				syslog.info("SimConnect: event: SIM Paused")
			self.paused = True
			if self._sim_paused_callback:
				self._sim_paused_callback(True)
		elif uEventID == self._dll.EventID.EVENT_SIM_UNPAUSED:
			self.handler.simconnect_sim_unpaused.emit()
			if self.verbose:
				syslog.info("SimConnect: event: SIM Unpaused")
			self.paused = False
			if self._sim_paused_callback:
				self._sim_paused_callback(False)
		elif uEventID == self._dll.EventID.EVENT_SIM_RUNNING:
			self.handler.simconnect_sim_running.emit()
			if self.verbose:
				syslog.info("SimConnect: event: SIM Running")
			state = event.dwData != 0
			self.running = state
			if self._sim_running_callback:
				self._sim_running_callback(state)
		elif uEventID == self._dll.EventID.EVENT_SIM_AIRCRAFT_LOADED:
			
			aircraft_air = event.dwData
			if self.verbose:
				syslog.info(f"SimConnect: event: AIRCRAFT LOADED: {aircraft_air}")
			folder = os.path.dirname(aircraft_air)
			if self._aircraft_loaded_callback:
				self._aircraft_loaded_callback(folder)
			self.handler.simconnect_aircraft_loaded.emit(folder)

	def handle_simobject_event(self, ObjData):
		
		dwRequestID = ObjData.dwRequestID
		if dwRequestID in self.Requests:
			_request = self.Requests[dwRequestID]
			rtype = _request.definitions[0][1].decode()
			if 'string' in rtype.lower():
				pS = cast(ObjData.dwData, c_char_p)
				_request.outData = pS.value
			else:
				_request.outData = cast(
					ObjData.dwData, POINTER(c_double * len(_request.definitions))
				).contents[0]
		else:
			syslog = logging.getLogger("system")
			syslog.warning(f"SimConnect: Event ID: {dwRequestID} is not handled")

	def handle_exception_event(self, exc):
		_exception = SIMCONNECT_EXCEPTION(exc.dwException).name
		_unsendid = exc.UNKNOWN_SENDID
		# _sendid = exc.dwSendID
		# _unindex = exc.UNKNOWN_INDEX
		# _index = exc.dwIndex

		# request exceptions
		syslog = logging.getLogger("system")
		for _reqin in self.Requests:
			_request = self.Requests[_reqin]
			if _request.LastID == _unsendid:
				
				syslog.warning(f"SimConnect: error: {_exception} {_request.definitions[0]}")
				return

		syslog.warning(_exception)

	def handle_state_event(self, pData : SIMCONNECT_RECV_SYSTEM_STATE):
		if self.verbose:
			syslog = logging.getLogger("system")
			syslog.info(f"SimConnect: state event: int: {pData.dwInteger} float: {pData.fFloat} str: {pData.szString}")
		

	# TODO: update callbackfunction to expand functions.
	def my_dispatch_proc(self, pData, cbData, pContext):
		# print("my_dispatch_proc")
		syslog = logging.getLogger("system")
		dwID = pData.contents.dwID
		if dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_EVENT:
			evt = cast(pData, POINTER(SIMCONNECT_RECV_EVENT)).contents
			self.handle_id_event(evt)

		elif dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_SYSTEM_STATE:
			state = cast(pData, POINTER(SIMCONNECT_RECV_SYSTEM_STATE)).contents
			self.handle_state_event(state)

		elif dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_SIMOBJECT_DATA_BYTYPE:
			pObjData = cast(
				pData, POINTER(SIMCONNECT_RECV_SIMOBJECT_DATA_BYTYPE)
			).contents
			self.handle_simobject_event(pObjData)

		elif dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_OPEN:

			syslog.info("Simconnect: SIM OPEN")
			self.ok = True

		elif dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_EXCEPTION:
			exc = cast(pData, POINTER(SIMCONNECT_RECV_EXCEPTION)).contents
			self.handle_exception_event(exc)
		
		elif dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_ASSIGNED_OBJECT_ID:
			pObjData = cast(
				pData, POINTER(SIMCONNECT_RECV_ASSIGNED_OBJECT_ID)
			).contents
			objectId = pObjData.dwObjectID
			os.environ["SIMCONNECT_OBJECT_ID"] = str(objectId)

		elif (dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_AIRPORT_LIST) or (
			dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_WAYPOINT_LIST) or (
			dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_NDB_LIST) or (
			dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_VOR_LIST):
			pObjData = cast(
				pData, POINTER(SIMCONNECT_RECV_FACILITIES_LIST)
			).contents
			dwRequestID = pObjData.dwRequestID
			for _facility in self.Facilities:
				if dwRequestID == _facility.REQUEST_ID.value:
					_facility.parent.dump(pData)
					_facility.dump(pData)

		elif dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_QUIT:
			self._quit = 1
		elif dwID == SIMCONNECT_RECV_ID.SIMCONNECT_RECV_ID_EVENT_FILENAME:
			# file name
			pObjData = cast(pData, POINTER(SIMCONNECT_RECV_EVENT_FILENAME)).contents
			file = pObjData.zFileName.decode()
			folder = os.path.dirname(file)
			if self._aircraft_loaded_callback:
				self._aircraft_loaded_callback(folder)

		else:
			if self.verbose:
				syslog = logging.getLogger("system")
				syslog.debug(f"Simconnect: Received: {SIMCONNECT_RECV_ID(dwID)}")
		return


	def connect(self):
		if self._is_connected:
			# already connected
			return 
		syslog = logging.getLogger("system")
		try:
			self._is_loop_running = False
			self._quit = 0
			self._dll = SimConnectDll(self._library_path)
			self._my_dispatch_proc_rd = self._dll.DispatchProc(self.my_dispatch_proc)
			err = self._dll.Open(
				byref(self._hSimConnect), LPCSTR(b"Request Data"), None, 0, 0, 0
			)
			if self.IsHR(err, 0):
				syslog.info("Simconnect: Connected to Flight Simulator!")
				# Request an event when the simulation starts

				# The user is in control of the aircraft
				self._dll.SubscribeToSystemEvent(
					self._hSimConnect, self._dll.EventID.EVENT_SIM_START, b"SimStart"
				)
				# The user is navigating the UI.
				self._dll.SubscribeToSystemEvent(
					self._hSimConnect, self._dll.EventID.EVENT_SIM_STOP, b"SimStop"
				)
				# Request a notification when the flight is paused
				self._dll.SubscribeToSystemEvent(
					self._hSimConnect, self._dll.EventID.EVENT_SIM_PAUSED, b"Paused"
				)
				# Request a notification when the flight is un-paused.
				self._dll.SubscribeToSystemEvent(
					self._hSimConnect, self._dll.EventID.EVENT_SIM_UNPAUSED, b"Unpaused"
				)
				# Request a notification when the flight is un-paused.
				self._dll.SubscribeToSystemEvent(
					self._hSimConnect, self._dll.EventID.EVENT_SIM_RUNNING, b"Sim"
				)
				self._dll.SubscribeToSystemEvent(
					self._hSimConnect, self._dll.EventID.EVENT_SIM_AIRCRAFT_LOADED, b"AircraftLoaded"
				)

			syslog = logging.getLogger("system")
			syslog.info(f"Simconnect: interface connected")
			self._is_connected = True

			self.run()

				
		except OSError:
			syslog.info("Simconnect: Did not find Flight Simulator running.")
			raise ConnectionError("Did not find Flight Simulator running.")
		
	def run(self):
		if not self._is_loop_running:
			self.timerThread = threading.Thread(target=self._run)
			self.timerThread.daemon = True
			self.timerThread.start()
			while self.ok is False:
				pass


	def _run(self):
		self.handler.simconnect_connected.emit()
		self._is_loop_running = True
		syslog = logging.getLogger("system")
		syslog.info("Simconnect: Open connection")
		while self._quit == 0:
			try:
				self._dll.CallDispatch(self._hSimConnect, self._my_dispatch_proc_rd, None)
				time.sleep(.002)
			except:
				pass
		# close the connection
		try:
			self._dll.Close(self._hSimConnect)
			self._dll = None
			self._is_connected = False	
			
			self.handler.simconnect_disconnected.emit()
			syslog.info("Simconnect: Close connection")
		except:
			pass

		
		self._is_loop_running = False

	def exit(self):
		if self._is_loop_running:
			self._quit = 1
			self.timerThread.join()

	def is_connected(self, auto_connect = True):
		''' determines if connected and optionally starts the connection '''
		if self.ok:
			return True
		# attempt to connect
		if auto_connect:
			self.connect()
		return self.ok
	
	def is_running(self, auto_connect = True):
		''' determines if the event loop is running or not '''
		if not self._is_loop_running and auto_connect:
			self.connect()

		return self._is_loop_running


	def map_to_sim_event(self, name):
		if self._dll is not None:
			for m in self._dll.EventID:
				if name.decode() == m.name:
					if self.verbose_details:
						syslog = logging.getLogger("system")
						syslog.debug(f"Simconnect: Already have event: {name} {m}")
					return m

			names = [m.name for m in self._dll.EventID] + [name.decode()]
			self._dll.EventID = Enum(self._dll.EventID.__name__, names)
			evnt = list(self._dll.EventID)[-1]
			try:
				err = self._dll.MapClientEventToSimEvent(self._hSimConnect, evnt.value, name)
				if self.IsHR(err, 0):
					return evnt
			except:
				pass			
		
		syslog.error(f"Simconnect: Error: MapToSimEvent: event: {name}")
		return None

	def add_to_notification_group(self, group, evnt, bMaskable=False):
		if self._dll is not None:
			self._dll.AddClientEventToNotificationGroup(
				self._hSimConnect, group, evnt, bMaskable
			)

	def request_data(self, _Request):
		if self._dll is not None:
			_Request.outData = None
			self._dll.RequestDataOnSimObjectType(
				self._hSimConnect,
				_Request.DATA_REQUEST_ID.value,
				_Request.DATA_DEFINITION_ID.value,
				0,
				SIMCONNECT_SIMOBJECT_TYPE.SIMCONNECT_SIMOBJECT_TYPE_USER,
			)
			temp = DWORD(0)
			self._dll.GetLastSentPacketID(self._hSimConnect, temp)
			_Request.LastID = temp.value

	def set_data(self, _Request):
		if self._dll is None:
			return False
		
		rtype = _Request.definitions[0][1].decode()
		if 'string' in rtype.lower():
			pyarr = bytearray(_Request.outData)
			dataarray = (ctypes.c_char * len(pyarr))(*pyarr)
		else:
			pyarr = list([_Request.outData])
			dataarray = (ctypes.c_double * len(pyarr))(*pyarr)

		pObjData = cast(
			dataarray, c_void_p
		)
		err = self._dll.SetDataOnSimObject(
			self._hSimConnect,
			_Request.DATA_DEFINITION_ID.value,
			SIMCONNECT_SIMOBJECT_TYPE.SIMCONNECT_SIMOBJECT_TYPE_USER,
			0,
			0,
			sizeof(ctypes.c_double) * len(pyarr),
			pObjData
		)
		if self.IsHR(err, 0):
			# LOGGER.debug("Request Sent")
			return True
		else:
			return False

	def get_data(self, _Request):
		self.request_data(_Request)
		retries = 0
		while _Request.outData is None and retries < _Request.attemps:
			time.sleep(.01)
			retries += 1
		if _Request.outData is None:
			if self.verbose:
				syslog.warning(f"Simconnect: warning: timeout in request {_Request}")
			return False

		return True

	def send_event(self, evnt, data=DWORD(0)):
		if self._dll is None:
			return False

		err = self._dll.TransmitClientEvent(
			self._hSimConnect,
			SIMCONNECT_OBJECT_ID_USER,
			evnt.value,
			data,
			SIMCONNECT_GROUP_PRIORITY_HIGHEST,
			DWORD(16),
		)

		if self.IsHR(err, 0):
			# LOGGER.debug("Event Sent")
			return True
		else:
			return False

	def new_def_id(self):
		if self._dll is None:
			return None
		
		_name = "Definition" + str(len(list(self._dll.DATA_DEFINITION_ID)))
		names = [m.name for m in self._dll.DATA_DEFINITION_ID] + [_name]

		self._dll.DATA_DEFINITION_ID = Enum(self._dll.DATA_DEFINITION_ID.__name__, names)
		DEFINITION_ID = list(self._dll.DATA_DEFINITION_ID)[-1]
		return DEFINITION_ID

	def new_request_id(self):
		if self._dll is None:
			return None
		
		name = "Request" + str(len(self._dll.DATA_REQUEST_ID))
		names = [m.name for m in self._dll.DATA_REQUEST_ID] + [name]
		self._dll.DATA_REQUEST_ID = Enum(self._dll.DATA_REQUEST_ID.__name__, names)
		REQUEST_ID = list(self._dll.DATA_REQUEST_ID)[-1]

		return REQUEST_ID

	def add_waypoints(self, _waypointlist):
		if self._dll is None:
			return
		if self.DEFINITION_WAYPOINT is None:
			self.DEFINITION_WAYPOINT = self.new_def_id()
			err = self._dll.AddToDataDefinition(
				self._hSimConnect,
				self.DEFINITION_WAYPOINT.value,
				b'AI WAYPOINT LIST',
				b'number',
				SIMCONNECT_DATATYPE.SIMCONNECT_DATATYPE_WAYPOINT,
				0,
				SIMCONNECT_UNUSED,
			)
		pyarr = []
		for waypt in _waypointlist:
			for e in waypt._fields_:
				pyarr.append(getattr(waypt, e[0]))
		dataarray = (ctypes.c_double * len(pyarr))(*pyarr)
		pObjData = cast(
			dataarray, c_void_p
		)
		sx = int(sizeof(ctypes.c_double) * (len(pyarr) / len(_waypointlist)))
		return


	def set_pos(
		self,
		_Altitude,
		_Latitude,
		_Longitude,
		_Airspeed,
		_Pitch=0.0,
		_Bank=0.0,
		_Heading=0,
		_OnGround=0,
	):
		
		if self._dll is None:
			return False

		Init = SIMCONNECT_DATA_INITPOSITION()
		Init.Altitude = _Altitude
		Init.Latitude = _Latitude
		Init.Longitude = _Longitude
		Init.Pitch = _Pitch
		Init.Bank = _Bank
		Init.Heading = _Heading
		Init.OnGround = _OnGround
		Init.Airspeed = _Airspeed

		if self.DEFINITION_POS is None:
			self.DEFINITION_POS = self.new_def_id()
			err = self._dll.AddToDataDefinition(
				self._hSimConnect,
				self.DEFINITION_POS.value,
				b'Initial Position',
				b'',
				SIMCONNECT_DATATYPE.SIMCONNECT_DATATYPE_INITPOSITION,
				0,
				SIMCONNECT_UNUSED,
			)

		hr = self._dll.SetDataOnSimObject(
			self._hSimConnect,
			self.DEFINITION_POS.value,
			SIMCONNECT_OBJECT_ID_USER,
			0,
			0,
			sizeof(Init),
			pointer(Init)
		)
		if self.IsHR(hr, 0):
			return True
		else:
			return False

	def load_flight(self, flt_path):
		if self._dll is None:
			return False
		hr = self._dll.FlightLoad(self._hSimConnect, flt_path.encode())
		if self.IsHR(hr, 0):
			return True
		else:
			return False

	def load_flight_plan(self, pln_path):
		if self._dll is None:
			return False
		hr = self._dll.FlightPlanLoad(self._hSimConnect, pln_path.encode())
		if self.IsHR(hr, 0):
			return True
		else:
			return False

	def save_flight(
		self,
		flt_path,
		flt_title,
		flt_description,
		flt_mission_type='FreeFlight',
		flt_mission_location='Custom departure',
		flt_original_flight='',
		flt_flight_type='NORMAL'):

		if self._dll is None:
			return False
		hr = self._dll.FlightSave(self._hSimConnect, flt_path.encode(), flt_title.encode(), flt_description.encode(), 0)
		if not self.IsHR(hr, 0):
			return False

		dicp = self.flight_to_dic(flt_path)
		if 'MissionType' not in dicp['Main']:
			dicp['Main']['MissionType'] = flt_mission_type

		if 'MissionLocation' not in dicp['Main']:
			dicp['Main']['MissionLocation'] = flt_mission_location

		if 'FlightType' not in dicp['Main']:
			dicp['Main']['FlightType'] = flt_flight_type

		if 'OriginalFlight' not in dicp['Main']:
			dicp['Main']['OriginalFlight'] = flt_original_flight
		self.dic_to_flight(dicp, flt_path)

		return False

	def get_paused(self):
		if self._dll is None:
			return False
		hr = self._dll.RequestSystemState(
			self._hSimConnect,
			self._dll.EventID.EVENT_SIM_PAUSED,
			b"Sim"
		)


	def get_aircraft_loaded(self):
		''' returns the path to the loaded active aircraft '''
		if self._dll is None:
			return False
		hr = self._dll.RequestSystemState(
			self._hSimConnect,
			self._dll.EventID.EVENT_SIM_AIRCRAFT_LOADED,
			b"AircraftLoaded"
		)


	def dic_to_flight(self, dic, fpath):
		with open(fpath, "w") as tempfile:
			for root in dic:
				tempfile.write(f"\n[{root}]\n")
				for member in dic[root]:
					tempfile.write(f"{member}={dic[root][member]}\n")

	def flight_to_dic(self, fpath):
		while not os.path.isfile(fpath):
			pass
		time.sleep(0.5)
		dic = {}
		index = ""
		with open(fpath, "r") as tempfile:
			for line in tempfile.readlines():
				if line[0] == '[':
					index = line[1:-2]
					dic[index] = {}
				else:
					if index != "" and line != '\n':
						temp = line.split("=")
						dic[index][temp[0]] = temp[1].strip()
		return dic

	def sendText(self, text, timeSeconds=5, TEXT_TYPE=SIMCONNECT_TEXT_TYPE.SIMCONNECT_TEXT_TYPE_PRINT_WHITE):
		if self._dll is None:
			return False
		pyarr = bytearray(text.encode())
		dataarray = (ctypes.c_char * len(pyarr))(*pyarr)
		pObjData = cast(dataarray, c_void_p)
		self._dll.Text(
			self._hSimConnect,
			TEXT_TYPE,
			timeSeconds,
			0,
			sizeof(ctypes.c_double) * len(pyarr),
			pObjData
		)
	
	def createSimulatedObject(self, name, lat, lon, rqst, hdg=0, gnd=1, alt=0, pitch=0, bank=0, speed=0):
		if self._dll is None:
			return False
		simInitPos = SIMCONNECT_DATA_INITPOSITION()
		simInitPos.Altitude = alt
		simInitPos.Latitude = lat
		simInitPos.Longitude = lon
		simInitPos.Pitch = pitch
		simInitPos.Bank = bank
		simInitPos.Heading = hdg
		simInitPos.OnGround = gnd
		simInitPos.Airspeed = speed
		self._dll.AICreateSimulatedObject(
			self._hSimConnect,
			name.encode(),
			simInitPos,
			rqst.value
		)
