import gremlin
import time
import uuid
import atexit
from gremlin.spline import CubicSpline
from gremlin.input_devices import keyboard
from gremlin.macro import Macro, MacroManager
from vjoy.vjoy import AxisName
from configuration import * # load constants defining the devices connected to this PC
from util import *
from hardware import *
import time
import random
import threading

import gremlin.input_devices


# class RemoteState():
#     is_remote = False
#     is_local = True
#     is_broadcast = False


class ProfileState():
    ''' holds state information for the profile '''
    is_running = False 


import logging

syslog = logging.getLogger("system")


# this must match the mode defined in the main profile - case sensitive
MODE_MINING = "mining"
MODE_SCAN = "scan"
MODE_MOUSE = "mouse"

MOUSE_MOVE_DELTA_MAX = 10
MOUSE_MOVE_DELTA_MIN = 1
MOUSE_MOVE_DELTA_SPAN = MOUSE_MOVE_DELTA_MAX - MOUSE_MOVE_DELTA_MIN

''' axis names to ID 

    X   # 1
    Y   # 2
    Z   # 3
    RX  # 4
    RY  # 5
    RZ  # 6
    SL0 # 7
    SL1 # 8

'''

# joystick button for scan mode functions
SCAN_JOY = 1
SCAN_UP = 41
SCAN_DN = 42

right_vpc_mining = RIGHT_VPC_Stick_WarBRD_mining
left_vpc_mining = LEFT_VPC_Stick_WarBRD_mining


right_vpc_scan = RIGHT_VPC_Stick_WarBRD_scan
left_vpc_scan = LEFT_VPC_Stick_WarBRD_scan

right_vpc = RIGHT_VPC_Stick_WarBRD_Default
left_vpc = LEFT_VPC_Stick_WarBRD_Default

bravo = Bravo_Throttle_Quadrant_Default

throttle = Throttle_HOTAS_Warthog_Default

bump_a_index = 4 # should match the initial value on the axis
#  index         0    1     2      3     4    5    6      7     8     9    10   11   12   13   14
bump_a_table = [-1,-0.98,-0.96, -0.94, -0.9,-0.8,-0.75, -0.7, -0.6, -0.5, -0.3, 0.0, 0.5, 0.75,1.0]
bump_a_max = len(bump_a_table)

gremlin.util.log("Custom SC module enabled")

brake_threshold = 0.95 # value of deviation (+ or -) to reach to trigger brake action on twist


''' MACRO DEFINITIONS '''
# macro functions are: press(key), release(key), tap(key), pause(seconds)

brake_on_macro = Macro()
brake_off_macro = Macro()
brake_on_macro.press("Z")
brake_off_macro.release("Z")


gear_toggle_macro = Macro()
gear_toggle_macro.tap('N')

mining_mode_toggle_macro = Macro()
mining_mode_toggle_macro.tap('M')

scanning_mode_toggle_macro = Macro()
scanning_mode_toggle_macro.tap('S')

cruise_toggle_macro = Macro()
cruise_toggle_macro.tap("C")





flip_trigger = False
repeat_trigger_a = False
repeat_trigger_b = False
trigger_a_pressed = False
trigger_b_pressed = False

def exit_handler():
    gremlin.util.log("sc exit!")
    repeat_fire_cancel_all()

atexit.register(exit_handler)


# gets a bracket value for a given joystick value - will be the low or high bracket depending on direction
def get_value(direction, current):
    old_value = bump_a_table[1] # smallest value possible
    gremlin.util.log(f"current joystick value: {current}")
    for value in bump_a_table:
        gremlin.util.log(f"current bracket: [{old_value}, {value}]")
        if current >= old_value and ((direction > 0 and current < value) or (direction < 0 and current <= value)):
            if direction > 0:
                gremlin.util.log(f"return value: {value}")  
                return value
            else:
                gremlin.util.log(f"return value: {old_value}")
                return old_value
        old_value = value
    gremlin.util.log(f"no bracket found: return value: {value}")    
    return value
    
    
# cruise control


last_gear_status = False

def toggle_cruise():
    ''' toggles the cruise mode'''
    MacroManager().queue_macro(cruise_toggle_macro) 

def toggle_gear():
    global last_gear_status
    MacroManager().queue_macro(gear_toggle_macro) 
    if last_gear_status == -1 or last_gear_status == 0:
        last_gear_status = 1
    else:
        last_gear_status = -1




@left_vpc.button(1)
def cruise_toggle(event, vjoy):
    MacroManager().queue_macro(cruise_toggle_macro) 
    

        
# handle acceleration presets       
def speed_limit_increase(event, vjoy):
	
    if event.is_pressed:
        (is_local, is_remote) = gremlin.input_devices.remote_state.state
        global bump_a_table, bump_a_index
        current = vjoy[1].axis(6).value
        new_value = get_value(+1, current)
        #gremlin.util.log(f"increase speed: Current: {current} New {new_value}")
        vjoy[1].axis(6).value = new_value
        if is_remote:
            gremlin.input_devices.remote_client.send_axis(1, 6, new_value)
    

def speed_limit_decrease(event, vjoy):
    if event.is_pressed:
        (is_local, is_remote) = gremlin.input_devices.remote_state.state
        global bump_a_table, bump_a_index
        current = vjoy[1].axis(6).value
        new_value = get_value(-1, current)
        #gremlin.util.log(f"descrease speed: Current: {current} New {new_value}")

        vjoy[1].axis(6).value = new_value
        if is_remote:
            gremlin.input_devices.remote_client.send_axis(1, 6, new_value)

def init_speed_limiter(vjoy):
    (is_local, is_remote) = gremlin.input_devices.remote_state.state
    global bump_a_table, bump_a_index
    current = bump_a_table[bump_a_index]
    vjoy[1].axis(6).value = current
    gremlin.input_devices.remote_client.send_axis(1, 6, current)

@left_vpc.button(24)
def speed_inc_a(event, vjoy):
    speed_limit_increase(event, vjoy)
    
# @left_vpc.button(26)
# def speed_inc_b(event, vjoy):
    # speed_limit_increase(event, vjoy)

@left_vpc.button(23)
def speed_dec_a(event, vjoy):
    speed_limit_decrease(event, vjoy)

# @left_vpc.button(28)
# def speed_dec_b(event, vjoy):
    # speed_limit_decrease(event, vjoy)

# acceleration presets  


def acc_limit_increase(event, vjoy):
    if event.is_pressed:
        (is_local, is_remote) = gremlin.input_devices.remote_state.state
        global bump_a_table, bump_a_index
        current = vjoy[1].axis(7).value
        new_value = get_value(+1, current)
        #gremlin.util.log(f"increase acc: Current: {current} New {new_value}")

        vjoy[1].axis(7).value = new_value
        if is_remote:
            gremlin.input_devices.remote_client.send_axis(1, 7, new_value)
        
        
    

def acc_limit_decrease(event, vjoy):
    if event.is_pressed:
        (is_local, is_remote) = gremlin.input_devices.remote_state.state
        global bump_a_table, bump_a_index
        current = vjoy[1].axis(7).value
        new_value = get_value(-1, current)
        #gremlin.util.log(f"decrease acc: Current: {current} New {new_value}")

        vjoy[1].axis(7).value = new_value
        if is_remote:
            gremlin.input_devices.remote_client.send_axis(1, 7, new_value)




# @right_vpc.button(24)
# def acc_inc_a(event, vjoy):
    # acc_limit_increase(event, vjoy)

@left_vpc.button(27)
def acc_inc_b(event, vjoy):
    acc_limit_increase(event, vjoy) 

# @right_vpc.button(23)
# def acc_dec_a(event, vjoy):
    # acc_limit_decrease(event, vjoy)

@left_vpc.button(29)
def acc_dec_b(event, vjoy):
    acc_limit_decrease(event, vjoy)     


@left_vpc_scan.button(27)
def acc_inc_b1(event, vjoy):
    acc_limit_increase(event, vjoy) 

# @right_vpc.button(23)
# def acc_dec_a(event, vjoy):
    # acc_limit_decrease(event, vjoy)

@left_vpc_scan.button(29)
def acc_dec_b1(event, vjoy):
    acc_limit_decrease(event, vjoy)     

last_rot_value = -2 # invalid value


brake_on = False # not braking by default

@left_vpc.axis(3)
def space_brake(event, vjoy):
    global brake_on
    brake_threshold = 0.8
    value = abs(event.value) 
    if not brake_on and value >= brake_threshold: 
        brake_on = True
        MacroManager().queue_macro(brake_on_macro) 
            
    elif brake_on and value < brake_threshold:
        MacroManager().queue_macro(brake_off_macro)
            
        brake_on = False


# stick z rotation (#6 is the rudder for some reason) = brake
#@t16k.axis(6)
def speed_brake(event, vjoy):
    global last_rot_value, brake_on, brake_threshold
    if event.value != last_rot_value:
        last_rot_value = event.value
        value = abs(event.value) 
        if not brake_on and value >= brake_threshold: 
            brake_on = True
            MacroManager().queue_macro(brake_on_macro) 
            
        elif brake_on and value < brake_threshold:
            MacroManager().queue_macro(brake_off_macro) 
            brake_on = False


def update_mouse(vjoy):
    global mouse_dx, mouse_dy, is_mouse_mode
    if is_mouse_mode: # and (mouse_dx != 0 or mouse_dy != 0):
        gremlin.sendinput.mouse_relative_motion(mouse_dx,mouse_dy)

@gremlin.input_devices.periodic(0.05)
def periodic_function(vjoy):
    update_laser(vjoy)
    return




''' scan mode axis options for mouse thumb '''
KEY_SCAN_DECREASE = ','
KEY_SCAN_INCREASE = '.'

scan_increase_macro = Macro()
scan_increase_macro.press(KEY_SCAN_INCREASE)


scan_increase_macro.release(KEY_SCAN_INCREASE)

scan_decrease_macro = Macro()
scan_decrease_macro.press(KEY_SCAN_DECREASE)
scan_decrease_macro.release(KEY_SCAN_DECREASE)
last_scan_value = 0
last_mining_value = 0


is_mouse_mode = False
last_thumb_x = 0
last_thumb_y = 0

# current mouse delta to send
mouse_dx = 0 
mouse_dy = 0

# initial mouse setup
def sync_initial_state():
    # get a reference to vjoy devices
    vjoy = gremlin.joystick_handling.VJoyProxy()
    # get a reference to actual raw hardware devices
    joy = gremlin.input_devices.JoystickProxy()

    try:

        r_vpc = joy[gremlin.profile.parse_guid(VPC_RIGHT_GUID)]
        global is_mouse_mode
        is_mouse_mode = r_vpc.button(1).is_pressed

    except:
        pass


# mouse modes
@right_vpc.button(1)
def mouse_mode(event, vjoy):
    global is_mouse_mode
    is_mouse_mode = event.is_pressed
    if is_mouse_mode:
        say("mouse mode on")
    else:
        say("mouse mode off")




STICK_THRESHOLD = 0.1
STICK_THRESHOLD_SPAN = 1 - STICK_THRESHOLD

@right_vpc.axis(4) # x axis thumb
def thumb_x(event, vjoy):
    global is_mouse_mode, last_thumb_x, mouse_dx, mouse_dy
    if is_mouse_mode:
        value = event.value
    else:
        value = 0   
    vjoy[3].axis(1).value = value
    
@right_vpc.axis(5) # y axis thumb
def thumb_y(event, vjoy):
    global is_mouse_mode, last_thumb_x, mouse_dx, mouse_dy
    if is_mouse_mode:
        value = event.value
    else:
        value = 0

    vjoy[3].axis(2).value = value


''' MODE CHANGES '''

MODE_CHANGE_DELAY_SECONDS = 0.5
mining_mode_timer = None
scan_mode_timer = None
default_mode_timer = None
last_mode = MODE_DEFAULT


def set_mining_mode(quiet = False):
    ''' enter mining mode '''
    global mining_throttle_value, last_mode
    mode = ActiveMode()
    
    if mode == MODE_MINING:
        if not quiet: say ("mining mode off")
        SetMode(MODE_DEFAULT)
        last_mode = MODE_DEFAULT
    else:
        if not quiet: say("mining mode")
        SetMode(MODE_MINING)
        last_mode = MODE_MINING

    RunMacro(mining_mode_toggle_macro)
    mining_throttle_value = -1.0

def set_scan_mode(quiet = False):
    ''' enter scanning mode '''
    global last_mode
    mode = ActiveMode()
    if mode == MODE_SCAN:
        if not quiet: say ("scan mode off")
        SetMode(MODE_DEFAULT)
        last_mode = MODE_DEFAULT
    else:
        if not quiet: say("scan mode")
        SetMode(MODE_SCAN)
        last_mode = MODE_SCAN

    RunMacro(scanning_mode_toggle_macro)
    

def set_default_mode(quiet=False):
    ''' enter default mode '''
    global last_mode
    SetMode(MODE_DEFAULT)
    if not quiet: say("default mode")
    last_mode = MODE_DEFAULT


def set_mode(mode):
    ''' general set mode '''
    global last_mode
    active_mode = ActiveMode()
    # if mode == active_mode or mode == last_mode:
    #     # nothing to do
    #     if active_mode == MODE_SCAN:
    #         say("already in scanning mode")
    #     elif active_mode == MODE_MINING:
    #         say("already in mining mode")
    #     elif active_mode == MODE_DEFAULT:
    #         say("already in default mode")
    #     return

    # deactivate old mode by calling it again
    if active_mode == MODE_MINING:
        set_mining_mode()
    elif active_mode == MODE_SCAN:
        set_scan_mode()

    # set the new mode
    if mode == MODE_DEFAULT:
        set_default_mode()
    elif mode == MODE_MINING:
        set_mining_mode()
    elif mode == MODE_SCAN:
        set_scan_mode()

    

        

# left stick, right hat down = toggle mining mode
@left_vpc.button(16)
def mining_mode(event, vjoy):
    global mining_mode_timer
    if mining_mode_timer:
        mining_mode_timer.cancel()
        mining_mode_timer = None
    if event.is_pressed:
        # button down, kickoff delay timer 
        mining_mode_timer = threading.Timer(MODE_CHANGE_DELAY_SECONDS, set_mode, [MODE_MINING])
        mining_mode_timer.start()

# left stick, right hat up = toggle scanning mode
@left_vpc.button(14)
def scanning_mode(event, vjoy):
    global scan_mode_timer
    if scan_mode_timer:
        scan_mode_timer.cancel()
        scan_mode_timer = None
    if event.is_pressed:
        # button down, kickoff delay timer 
        scan_mode_timer = threading.Timer(MODE_CHANGE_DELAY_SECONDS, set_mode, [MODE_SCAN])
        scan_mode_timer.start()


# left stick, right hat push - set default mode
@left_vpc.button(13)
def default_mode(event, vjoy):
    global default_mode_timer
    if default_mode_timer:
        default_mode_timer.cancel()
        default_mode_timer = None
    if event.is_pressed:
        # button down, kickoff delay timer 
        default_mode_timer = threading.Timer(MODE_CHANGE_DELAY_SECONDS, set_mode, [MODE_DEFAULT])
        default_mode_timer.start()



LASER_BUMP_SLOW = 0.008
LASER_BUMP_FAST = 0.02
LASER_BUMP_THUMB_THRESHOLD = 0.1  # trigger
LASER_BUMP_THUMB_TURBO = 0.6 # fast mode

laser_bump = 0.01
last_thumstick_position = 0
class laser_data():
    go_up = False
    go_down = False
    
def update_laser(vjoy):
    if laser_data.go_up or laser_data.go_down:
        global laser_bump
        current = vjoy[2].axis(7).value
        if laser_data.go_up:
            current += laser_bump
            gremlin.sendinput.mouse_wheel(-1)
        elif laser_data.go_down:
            current -= laser_bump
            gremlin.sendinput.mouse_wheel(1)

        if current > 1:
            current = 1
        elif current < -1:
            current = -1
        vjoy[2].axis(7).value = current
            
    
@left_vpc.button(26)    
def scc_laser_increase(event, vjoy):
    ''' button to decrease laser '''
    mode = ActiveMode()
    if mode != MODE_MINING:
        laser_data.go_up = False
        laser_data.go_down = False
        return  
    laser_data.go_up = event.is_pressed
    laser_data.go_down = False
    global laser_bump
    laser_bump = LASER_BUMP_SLOW
    
        
@left_vpc.button(28)    
def scc_laser_decrease(event, vjoy):
    ''' button in increase laser'''
    mode = ActiveMode()
    if mode != MODE_MINING:
        laser_data.go_down = False
        laser_data.go_up = False
        return

    laser_data.go_down = event.is_pressed
    laser_data.go_up = False
    global laser_bump
    laser_bump = LASER_BUMP_SLOW    
    



@left_vpc.axis(5)
def mining_throttle(event, vjoy):
    ''' sets up a mining throttle on the left thumbstick up/down '''
    mode = ActiveMode()
    if mode == MODE_MINING: 
        global last_thumstick_position
        value = event.value
        # if value == last_thumstick_position:
        # 	return
        last_thumstick_position = value
        if value >= LASER_BUMP_THUMB_THRESHOLD:
            laser_data.go_down = True
            laser_data.go_up = False
        elif value <= -LASER_BUMP_THUMB_THRESHOLD:
            laser_data.go_down = False
            laser_data.go_up = True
        else: 
            laser_data.go_down = False
            laser_data.go_up = False

        global laser_bump

        # speed up or down based on thumb position
        if value == 1:
            # instant OFF
            laser_bump = 1
        else:
            if value < 0:
                value = -value
            laser_bump = LASER_BUMP_SLOW if value < LASER_BUMP_THUMB_TURBO else LASER_BUMP_FAST

		


''' custom wiggle modes for SC '''

class Wiggle():

    """Implements more advanced wiggle functionality using macro functionality """

    
    def __init__(self):
        # setup wiggle steps
        Wiggle._mouse_controller = gremlin.sendinput.MouseController()


        self._wiggle_local_thread = None
        self._wiggle_remote_thread = None
        self._wiggle_local_stop_requested = None
        self._wiggle_remote_stop_requested = None
        self._mouse_controller = None
        self._steps = []
        self._current_local_step = 0
        self._current_remote_step = 0


        # define the wiggle macro for Star Citizen

        # wiggle the mouse
        self._steps.append(self.get_mouse_move_macro(100,0))
        self._steps.append(self.get_mouse_move_macro(-100,0))
        self._steps.append(self.get_mouse_move_macro(0,0))
        # send the D key - press between 1 to 3 seconds 
        self._steps.append(self.get_key_macro("d"))
        # pause between 2 and 10 seconds 
        self._steps.append(self.get_pause_macro(2, 10))
        # send the A key 
        self._steps.append(self.get_key_macro("a"))
        # pause between 2 and 10 seconds
        self._steps.append(self.get_pause_macro(2, 10))
        # press F1
        self._steps.append(self.get_key_macro("f1",0.5))
        # pause between 2 and 10 seconds
        self._steps.append(self.get_pause_macro(2, 10))
        # press F1 again
        self._steps.append(self.get_key_macro("f1", 0.5))
        # pause between 2 and 10 seconds
        self._steps.append(self.get_key_macro("w"))
        # pause between 2 and 10 seconds
        self._steps.append(self.get_pause_macro(2, 10))
        # send the S key - hold or 1 second
        self._steps.append(self.get_key_macro("s"))
        # pause between 2 and 10 seconds
        self._steps.append(self.get_pause_macro(2, 10))

        self._step_count = len(self._steps)

        self._force_remote = False

        self._lock = threading.Lock()

    def __del__(self):
        # stop anything running
        self.stop_local()
        self.stop_remote()


    @property
    def force_remote(self):
        ''' flag that forces remote mode on even if mode is local '''
        return self._force_remote
    
    @force_remote.setter
    def force_remote(self, value):
        self._force_remote = value



    def get_key_macro(self, name, duration_min = 0.3, duration_max = 0):
        ''' gets a keyboard macro '''
        m = Macro()
        k = gremlin.macro.Key.from_key(gremlin.keyboard.key_from_name(name))
        if k:
            a = gremlin.macro.KeyAction(k,True)
            m.add_action(a)
            a = gremlin.macro.PauseAction(duration=duration_min, duration_max = duration_max)
            m.add_action(a)
            a = gremlin.macro.KeyAction(k,False)
            m.add_action(a)
        return m
    
    def get_pause_macro(self, duration_min = 2, duration_max = 0):
        m = Macro()
        a = gremlin.macro.PauseAction(duration=duration_min, duration_max = duration_max)
        m.add_action(a)
        return m 

    def get_mouse_move_macro(self, x = 0, y = 0):
        ''' returns a mouse move macro '''
        m = Macro()
        a = gremlin.macro.MouseMotionAction(x, y)
        m.add_action(a)
        a = gremlin.macro.MouseMotionAction(-x, -y)
        m.add_action(a)
        return m


    def start_local(self):
        # starts local wiggle 
        self._wiggle_start(is_local=True)

    def start_remote(self):
        # starts remote wiggle
        self._wiggle_start(is_remote=True)

    def stop_local(self):
        # stops remote wiggle
        self._wiggle_stop(is_local=True)
    
    def stop_remote(self):
        # stops remote wiggle
        self._wiggle_stop(is_remote=True)

    @property
    def local_running(self):
        ''' true if the local thread is running '''
        return self._wiggle_local_stop_requested is not None
    

    @property
    def remote_running(self):
        ''' true if the remote thread is running '''
        return self._wiggle_remote_stop_requested is not None

    def _wiggle_start(self, is_local = False, is_remote = False):
        ''' starts the wiggle thread, local or remote '''
        if is_local and not self.local_running:
            syslog.debug("Wiggle start local requested...")
            self._current_local_step = 0
            with self._lock:
                self._wiggle_local_stop_requested = threading.Event()
            self._wiggle_local_thread = threading.Thread(target=self._wiggle_local)
            self._wiggle_local_thread.start()

        if is_remote and not self.remote_running:
            syslog.debug("Wiggle start remote requested...")
            self._current_remote_step = 0
            with self._lock:
                self._wiggle_remote_stop_requested = threading.Event()
            self._wiggle_remote_thread = threading.Thread(target=self._wiggle_remote)
            self._wiggle_remote_thread.start()

    def _wiggle_stop(self, is_local = False, is_remote = False):
        ''' stops the wiggle thread, local or remote '''
        if is_local and self.local_running:
            syslog.debug("Wiggle stop local requested...")
            with self._lock:
                self._wiggle_local_stop_requested.set()
                if self._wiggle_local_thread.is_alive():
                    self._wiggle_local_thread.join()
                syslog.debug("Wiggle thread local exited...")
                self._wiggle_local_thread = None
                self._wiggle_local_stop_requested = None

        if is_remote and self.remote_running:
            syslog.debug("Wiggle stop local requested...")
            with self._lock:
                self._wiggle_remote_stop_requested.set()
                if self._wiggle_remote_thread.is_alive():
                    self._wiggle_remote_thread.join()
                syslog.debug("Wiggle thread remote exited...")
                self._wiggle_remote_thread = None            
                self._wiggle_remote_stop_requested = None

    def _wiggle_local(self):
        ''' wiggles the mouse '''

        syslog.debug("Wiggle local start...")


        msg = "local wiggle mode on"
        gremlin.input_devices.remote_state.say(msg)

        if self._step_count > 0:
            while not self._wiggle_local_stop_requested.is_set():
                macro = self._steps[self._current_local_step]
                self._current_local_step += 1
                if self._current_local_step == self._step_count:
                    self._current_local_step = 0

                # execute the macro synchronously
                for action in macro.sequence:
                    if not self._wiggle_local_stop_requested.is_set():
                        action(True, False, self.force_remote)
                        time.sleep(0.1)
                time.sleep(0.1)
            
        syslog.debug("Wiggle local stop...")
        gremlin.input_devices.remote_state.say("local wiggle mode off")


    def _wiggle_remote(self):
        ''' wiggles the mouse - remote clients'''
        syslog.debug("Wiggle remote start...")

        msg = "remote wiggle mode on"
        gremlin.input_devices.remote_state.say(msg)

        if self._step_count > 0:
            while not self._wiggle_remote_stop_requested.is_set():
                macro = self._steps[self._current_remote_step]
                self._current_remote_step += 1
                if self._current_remote_step == self._step_count:
                    self._current_remote_step = 0

                # execute the macro synchronously
                for action in macro.sequence:
                    if not self._wiggle_remote_stop_requested.is_set():
                        action(False, True, self.force_remote)
                        time.sleep(0.1)
            time.sleep(0.1)
            
        syslog.debug("Wiggle remote stop...")
        gremlin.input_devices.remote_state.say("remote wiggle mode off")


wiggle = Wiggle()
wiggle.force_remote = True  # force remote mode wiggle 

# external wiggle
@throttle.button(24)
def ext_wiggle(event):
    if event.is_pressed:
        wiggle.start_remote()
    else:
        wiggle.stop_remote()

# external wiggle
@throttle.button(25)
def local_wiggle(event):
    if event.is_pressed:
        wiggle.start_local()
    else:
        wiggle.stop_local()


@gremlin.input_devices.gremlin_state()
def state_changed(event):
    ''' called when Gremlin's state changes '''
    # remote_state.is_remote = event.is_remote
    # remote_state.is_local = event.is_local
    # remote_state.is_broadcast = event.is_broadcast_enabled

# init function when profile is starting
@gremlin.input_devices.gremlin_start()
def profile_start():
    sync_initial_state()
    vjoy = gremlin.joystick_handling.VJoyProxy()
    init_speed_limiter(vjoy)


@gremlin.input_devices.gremlin_stop()
def profile_stop():
    # stops all threads
    ProfileState.is_running = False
    wiggle.stop_remote()
    wiggle.stop_local()
