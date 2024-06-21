
''' MUCHIMI'S Joystick Gremlin Python utilitites '''

import gremlin



import time
import threading
from threading import Timer

from gremlin.spline import CubicSpline
from vjoy.vjoy import AxisName
from configuration import * # load constants from the configuration.py file
import gremlin.input_devices

''' event handlers '''
custom_handlers = []

def register_handler(callback):
	if not callback in custom_handlers:
		custom_handlers.append(callback)

def unregister_handler(callback):
	if callback in custom_handlers:
		custom_handlers.remove(callback)

def fire_event(cmd, value):
	''' calls the registered handlers '''
	for callback in custom_handlers:
		callback(cmd, value)

timer_threads = {}

class Speech():
	''' tts interface '''
	def __init__(self):
		import win32com.client
		self.speaker = win32com.client.Dispatch("SAPI.SpVoice")

	def speak(self, text):
		try:
			self.speaker.speak(text)
		except:
			pass

def say(message):
	''' say something using text to speech'''
	speech = Speech()
	speech.speak(message)


class RepeatedTimer(object):
	def __init__(self, interval, function, *args, **kwargs):
		self._timer     = None
		self.interval   = interval
		self.function   = function
		self.args       = args
		self.kwargs     = kwargs
		self.is_running = False

		self.start()

	def _run(self):
		self.is_running = False
		#gremlin.util.log("run 1")
		self.function(*self.args, **self.kwargs)
		#gremlin.util.log("run 2")
		self.start()


	def start(self):
		if not self.is_running:
			self._timer = Timer(self.interval, self._run)
			self._timer.start()
			self.is_running = True

	def stop(self):
		self._timer.cancel()
		self._timer.join()
		self.is_running = False
		gremlin.util.log("stop")

	
		
# async routine to pulse a button
def _fire_pulse(vjoy, unit, button, repeat = 1, duration = 0.2):
	if repeat < 0:
		repeat = -repeat
		for i in range(repeat):
			# gremlin.util.log("Pulsing vjoy %s button %s on" % (unit, button) )    
			vjoy[unit].button(button).is_pressed = True
			time.sleep(duration)
			vjoy[unit].button(button).is_pressed = False
			time.sleep(duration)
	else:
		if repeat <= 1: 
			gremlin.util.log(f"Pulsing vjoy {unit} button {button} on" )  
			vjoy[unit].button(button).is_pressed = True
			time.sleep(duration)
			vjoy[unit].button(button).is_pressed = False
		else:
			vjoy[unit].button(button).is_pressed = True
			time.sleep(duration*repeat)
			vjoy[unit].button(button).is_pressed = False        
		
	# gremlin.util.log("Pulsing vjoy %s button %s off" % (unit, button) )

# pulses a button - unit is the vjoy output device number, button is the number of the button on the device to pulse
def pulse(vjoy, unit, button, duration = 0.2, repeat = 1):
	gremlin.util.log(f"pulsing: unit {unit} button {button}")
	threading.Timer(0.01, _fire_pulse, [vjoy, unit, button, repeat, duration]).start()

	
# gets the last timer tick for a unit/button - creates entries if needed
last_click = {}
def get_tick(unit,button):
	global last_click
	if not unit in last_click.keys():
		last_click[unit] = {}
		
	if not button in last_click[unit]:
		last_click[unit][button] = 0
	
	return last_click[unit][button]
	
		
		
	
# performs a slow or fast click depending on the last time the button fired 
# ref_unit = source unit clicked
# ref_button = source button on unit
# unit = vjoy device to pulse
# slow_button = vjoy button to pulse for slow rotation
# fast_button = vjoy button to pulse for fast rotation
def speed_click(vjoy, ref_unit, ref_button, unit, slow_button, fast_button, use_fast, duration = 0.1, repeat = 1):
	if use_fast:
		t1 = time.clock()
		t0 = get_tick(ref_unit,ref_button)
		gremlin.util.log("delta %s repeat %s " % (t1-t0, repeat) )
		last_click[ref_unit][ref_button] = t1
		if t1 - t0 < LONG_PULSE:
			pulse(vjoy, unit, fast_button, duration, repeat)
			gremlin.util.log("fast")
		else:
			pulse(vjoy, unit, slow_button, duration, repeat)
			gremlin.util.log("slow")
	else:
		pulse(vjoy, unit, slow_button, duration, repeat)
		gremlin.util.log("use slow button")

# fires specified button - either stead or pulse
# event = gremlin event
# vjoy = gremlin vjoy devices
# unit = vjoy device number to output
# on_button = button to fire when button is in the ON position (steady or pulse)
# off_button = button to fire when button is in the OFF position (steady or pulse)
# pulse = flag, when true, pulses, when false, steady output
def fireButton(event, vjoy, unit, on_button, off_button = None, momentary = False, pulse_duration  = 0.2):
	if not on_button:
		return

	if momentary:
		if event.is_pressed:
			pulse(vjoy, unit, on_button, pulse_duration)
			if off_button:
				vjoy[unit].button(off_button).is_pressed = False
			#gremlin.util.log("device %s button %s pulse" % (unit, on_button))
		elif off_button:
			pulse(vjoy, unit, off_button, pulse_duration)
			vjoy[unit].button(on_button).is_pressed = False
			#gremlin.util.log("device %s button %s pulse" % (unit, off_button))
	else:
		if event.is_pressed:
			vjoy[unit].button(on_button).is_pressed = True
			if off_button:
				vjoy[unit].button(off_button).is_pressed = False
		else:
			vjoy[unit].button(on_button).is_pressed = False
			if off_button:
				vjoy[unit].button(off_button).is_pressed = True


def pulseButton(event, vjoy, unit, on_button, off_button = None, pulse_duration  = 0.2):
	fireButton(event, vjoy, unit, on_button, off_button, True, pulse_duration)


def repeat_pulse(vjoy, unit, button, repeat, duration):
	gremlin.util.log(f"pulsing: unit {unit} button {button}")
	
	#threading.Timer(0.01, fire_pulse, [vjoy, unit, button, repeat, duration]).start()
	
def repeat_fire(name, vjoy, unit, button, repeat=1, interval = 0.5, duration = 0.2):
	global timer_threads
	repeat_fire_cancel(name)
	gremlin.util.log(f"repeat {name} unit {unit} button {button} repeat {repeat} interval {interval} duration {duration}")
	#args = (vjoy, unit, button, repeat, duration)
	rt = RepeatedTimer(interval, pulse, vjoy, unit, button, repeat, duration )
	timer_threads[name] = rt
	
def repeat_fire_cancel(name):
	global timer_threads
	gremlin.util.log(f"cancel {name}")	
	if name in timer_threads:
		rt = timer_threads[name]
		rt.stop()
		del timer_threads[name]
		
def repeat_fire_cancel_all():
	global timer_threads
	for name in timer_threads:
		rt = timer_threads[name]
		rt.stop()


# gets the current Gremlin active mode (will be a text value)
def ActiveMode() -> str:
	''' gets the current active mode'''
	eh = gremlin.event_handler.EventHandler()
	return eh.active_mode

def SetMode(mode_name: str):
	''' sets the active mode '''
	eh = gremlin.event_handler.EventHandler()
	eh.change_mode(mode_name)

def SetLastMode():
	''' returns to the last mode '''
	eh = gremlin.event_handler.EventHandler()
	eh.change_mode(eh.previous_mode)

def RunMacro(macro):
	''' runs a macro'''
	gremlin.macro.MacroManager().queue_macro(macro) 


def GetTimeMs(future = 0) -> int:
	''' returns the current time in milliseconds '''
	return int(time.time() * 1000) + future

def SendMouseWheel(direction):
	''' sends a mouse wheel output  direction is 1 or -1'''
	if direction in (1, -1):
		gremlin.sendinput.mouse_wheel(direction)

def GetVjoy():
	''' get the vjoy device (virtual hardware input)'''
	return gremlin.joystick_handling.VJoyProxy()

def GetJoy():
    ''' gets the joy device (raw hardware input)'''
    return gremlin.input_devices.JoystickProxy()


cubic_control_points = [(-1.0, -1.0), (1.0, 1.0)]

def cubic_curve(value):
	''' curves the data using a simple cubic curve '''
	points = cubic_control_points
	for cp in sorted(points, key=lambda e: e.center.x):
		points.append((cp.center.x, cp.center.y))
	if len(points) < 2:
		return None
	else:
		return gremlin.spline.CubicSpline(points)
