import gremlin
from gremlin.user_plugin import PhysicalInputVariable
import time
import uuid
import atexit
from gremlin.spline import CubicSpline
from gremlin.input_devices import Keyboard
from vjoy.vjoy import AxisName
from configuration import * # load constants defining the devices connected to this PC
from util import *
from hardware import *
from gremlin.macro import Macro, MacroManager


gremlin.util.log("Custom MSFS module enabled")

from util import register_handler, unregister_handler



MODE_CHART = "chart"

alpha = gremlin.input_devices.JoystickDecorator(ALPHA_NAME, ALPHA_GUID , MODE_ALL )
bravo = gremlin.input_devices.JoystickDecorator(BRAVO_NAME,BRAVO_GUID , MODE_ALL )
left_vpc = gremlin.input_devices.JoystickDecorator(VPC_LEFT_NAME, VPC_LEFT_GUID , MODE_DEFAULT )
left_vpc_chart = gremlin.input_devices.JoystickDecorator(VPC_LEFT_NAME, VPC_LEFT_GUID , MODE_CHART )
vjoy_input = gremlin.input_devices.JoystickDecorator(VJOY_INPUT_NAME, VJOY_INPUT_GUID , MODE_DEFAULT )
t_rudder = gremlin.input_devices.JoystickDecorator(MFG_Crosswind_V2_3_NAME, MFG_Crosswind_V2_3_GUID, MODE_DEFAULT )


# gremlin.util.log(f"Bravo type: {type(bravo)}")

PULSE_DURATION = 0.5

# class Rudder():
#     ''' implements a PID for rudder control '''




#     def __init__(self, setpoint, vjoy_id, vjoy_axis):
#         self._vjoy_id = vjoy_id
#         self._vjoy_axis = vjoy_axis
#         self._vjoy = GetVjoy()
#         self._value = 1
#         self._pid = PID(self.read, self.update, setpoint + 1,  1, 0.05, 0.25, True)
#         self._pid.output_limits = (0, 2.0)
#         self._pid.auto = True
        
        

#     def update(self, value):
#         ''' updates the output value '''
#         # gremlin.util.log(f"{value}")
#         v = self._value + value - 1
#         if v > 1:
#             v = 1
#         elif v  < -1:
#             v = -1
#         self._value = v
#         gremlin.util.log(f"{v}")
#         self._vjoy[self._vjoy_id].axis(self._vjoy_axis).value = v

#     def read(self):
#         ''' gets the current value '''
#         return self._value
    
#     def tick(self):
#         ''' updates the PID on the tick value'''
#         self._pid.compute()
        

#     @property
#     def setpoint(self):
#         return self._pid.setpoint 
    
#     @setpoint.setter
#     def setpoint(self, value):
#         ''' setpoint of the PID - input value is expected to be -1 to +1'''
#         self._pid.setpoint = value + 1

# _rudder_pid = Rudder(0, 1, 3)
# PERIODIC = 0.25
# @gremlin.input_devices.periodic(PERIODIC)
# def update_rudder():
#     global _rudder_pid
#     _rudder_pid.tick()


# @t_rudder.axis(3)
# def rudder(event, vjoy):
#     global _rudder_pid
#     _rudder_pid.setpoint = event.value
#     # vjoy[1].axis(3).value = event.value
#     #_rudder_pid.setpoint = event.value
        


f1_macro = Macro()
f1_macro.press('F1')
f1_macro.pause(0.5)
f1_macro.release('F1')

joy = gremlin.input_devices.JoystickProxy()

t_rudder_raw = joy[gremlin.profile.parse_guid(MFG_Crosswind_V2_3_GUID)]
vpc_left_raw = joy[gremlin.profile.parse_guid(VPC_LEFT_GUID)]





bravo_raw = joy[gremlin.profile.parse_guid(BRAVO_GUID)]

RUDDER_FACTOR = 0.75 # scale value when scaling the rudder
rudder_scaled = False # don't start with scaled rudder - left stick trigger toggles between the modes

default_curve = CubicSpline([
    (-1.00, -1.00),
    (-0.75, -0.50),
    (-0.25, -0.05),
    ( 0.00,  0.00),
    ( 0.25,  0.05),
    ( 0.75,  0.50),
    ( 1.00,  1.00),
])    

# airbus throttle gates
GATE_NONE = 0
GATE_REV = 1
GATE_IDLE = 2
GATE_CLIMB = 3
GATE_FLEX = 4
GATE_TOGA = 5

# axis range for each gate (approx)
REV_MIN = -1.0
REV_MAX = -0.91
IDLE_MIN = -1.0
IDLE_MAX = -0.8
CLB_MIN = 0.01
CLB_MAX = 0.15
FLEX_MIN = 0.40
FLEX_MAX = 0.6
TOGA_MIN = 0.9
TOGA_MAX = 1.0

AXIS_CLB = (CLB_MIN + CLB_MAX)/2
AXIS_FLEX = (FLEX_MIN + FLEX_MAX)/2
AXIS_TOGA = 1.0
AXIS_IDLE = -1
AXIS_REV = -1

MIX_LOW_MIN = -0.5
MIX_LOW_MAX = 0

MIX_HI_MIN = 0.5
MIX_HI_MAX = 1

MIX_NONE = -1
MIX_CUTOFF = 0
MIX_LOW = 1
MIX_HIGH = 2

AB_REV_1 = 50
AB_IDLE_1 = 51
AB_CLIMB_1 = 52
AB_FLEX_1 = 53
AB_TOGA_1 = 54

AB_REV_2 = 55
AB_IDLE_2 = 56
AB_CLIMB_2 = 57
AB_FLEX_2 = 58
AB_TOGA_2 = 59


active_curve = default_curve 
airbus_mode = False
airbus_gate = GATE_NONE
last_gate = GATE_NONE

mixture_gate = {}
mixture_gate[1] = MIX_NONE
mixture_gate[2] = MIX_NONE


@t_rudder.axis(3)
def rudder(event, vjoy):     
    ''' rudder axis = Z axis'''
    vjoy[1].axis(3).value = active_curve(event.value)

# throttle 1 min trigger
@bravo.button(25)
def axis_1_toggle(event, vjoy):
    fireButton(event, vjoy, 2, 16, 17, True, PULSE_DURATION)

# throttle 2 min trigger
@bravo.button(26)
def axis_2_toggle(event, vjoy):
    # fireButton(event, vjoy, 2, 18, 19, True, PULSE_DURATION)
    vjoy[1].button(17).is_pressed = event.is_pressed

# prop 1 min trigger
@bravo.button(27)
def axis_3_toggle(event, vjoy):
    #fireButton(event, vjoy, 2, 20, 21, True, PULSE_DURATION)
    vjoy[1].button(18).is_pressed = event.is_pressed

# prop 2 min trigger
@bravo.button(28)
def axis_4_toggle(event, vjoy):
    # fireButton(event, vjoy, 2, 22, 23, True, PULSE_DURATION)
    vjoy[1].button(19).is_pressed = event.is_pressed


@bravo.axis(2)
def spoiler_axis(event, vjoy):
    vjoy[2].button(1).is_pressed = event.value > 0.9
    vjoy[2].button(2).is_pressed = event.value < -0.9



def update_reversers(vjoy):
    global _rev_1_engaged, _rev_2_engaged
    if _rev_1_engaged:
        vjoy[1].button(98).is_pressed = True
        vjoy[1].button(99).is_pressed = False
        # say("reverser")
    else:
        vjoy[1].button(98).is_pressed = False
        vjoy[1].button(99).is_pressed = True
    if _rev_2_engaged:
        vjoy[1].button(96).is_pressed = True
        vjoy[1].button(97).is_pressed = False
    else:
        vjoy[1].button(96).is_pressed = False
        vjoy[1].button(97).is_pressed = True



     


last_x_value = 0
last_y_value = 0
AXIS_THRESHOLD = 0.5
HAT_INDEX_ONE = 1
HAT_INDEX_THUMB = 2

VJOY_INDEX = 2
HAT_BUTTON = 5
hat_state = {}
'''
Gremlin hat directions: 

    (x, y):  for x and y 

    0 = center
    +1 = up (right)
    -1 = down (left)

    examples:

    (0, 0): "Center",
    (0, 1): "North",
    (1, 1): "North East",
    (1, 0): "East",
    (1, -1): "South East",
    (0, -1): "South",
    (-1, -1): "South West",
    (-1, 0): "West",
    (-1, 1): "North West",
'''

def ensure_hat():
    ''' builds the dictionary of hats indexed by the hat index '''
    global hat_state
    if len(hat_state.keys()) == 0:
        for index in range(4):
            hat_state[index] = [0,0]

def update_state(vjoy, vjoy_index, hat_index, state):
    ''' sets the hat state on a specific vjoy device and hat index '''
    device = vjoy[vjoy_index]
    device.hat(hat_index).direction  = tuple(state[hat_index])

    # device.button(HAT_BUTTON).is_pressed = state[0] == 1
    # device.button(HAT_BUTTON+1).is_pressed = state[0] == -1
    # device.button(HAT_BUTTON+2).is_pressed = state[1] == 1
    # device.button(HAT_BUTTON+3).is_pressed = state[1] == -1

# x rotation
@left_vpc_chart.axis(4)
def x_axis(event, vjoy):
    global last_x_value, hat_state
    value = event.value
    if last_x_value != value:
        last_x_value = value
        #gremlin.util.log(f"y value: {value}")
        if value < -AXIS_THRESHOLD:
            hat_state[HAT_INDEX_THUMB][0] = -1
            #gremlin.util.log(f"left")    
        elif value > AXIS_THRESHOLD:
            hat_state[HAT_INDEX_THUMB][0] = 1
            #gremlin.util.log(f"right")    
        else:
            hat_state[HAT_INDEX_THUMB][0] = 0
            #gremlin.util.log(f"center")
        update_state(vjoy,VJOY_INDEX,HAT_INDEX_THUMB,hat_state)

# y rotation
@left_vpc_chart.axis(5)
def y_axis(event, vjoy):
    global last_y_value, hat_state
    value = event.value
    if last_y_value != value:
        last_y_value = value
        #gremlin.util.log(f"y value: {value}")    
        if value < -AXIS_THRESHOLD:
            #gremlin.util.log(f"up")
            hat_state[HAT_INDEX_THUMB][1] = 1
        elif value > AXIS_THRESHOLD:
            hat_state[HAT_INDEX_THUMB][1] = -1
            #gremlin.util.log(f"down")
        else:
            hat_state[HAT_INDEX_THUMB][1] = 0
            #gremlin.util.log(f"middle")
        update_state(vjoy,VJOY_INDEX,HAT_INDEX_THUMB,hat_state)

# hat 1 up
@left_vpc.button(14)
def hat_1_up(event, vjoy):
    global hat_state
    value = 1 if event.is_pressed else 0
    hat_state[HAT_INDEX_ONE][1] = value
    update_state(vjoy,VJOY_INDEX,HAT_INDEX_ONE,hat_state)

# hat 1 right
@left_vpc.button(15)
def hat_1_up(event, vjoy):
    global hat_state
    value = 1 if event.is_pressed else 0
    hat_state[HAT_INDEX_ONE][0] = value
    update_state(vjoy,VJOY_INDEX,HAT_INDEX_ONE,hat_state)

# hat 1 down
@left_vpc.button(16)
def hat_1_up(event, vjoy):
    global hat_state
    value = -1 if event.is_pressed else 0
    hat_state[HAT_INDEX_ONE][1] = value
    update_state(vjoy,VJOY_INDEX,HAT_INDEX_ONE,hat_state)    

# hat 1 left
@left_vpc.button(17)
def hat_1_up(event, vjoy):
    global hat_state
    value = -1 if event.is_pressed else 0
    hat_state[HAT_INDEX_ONE][0] = value
    update_state(vjoy,VJOY_INDEX,HAT_INDEX_ONE,hat_state)    


# make sure hats are setup
ensure_hat()

_rev_1_engaged = False
_rev_2_engaged = False
_rev_1_bottom = False
_rev_2_bottom = False



    
# BRAVO AXIS from left to right
# 1 spoiler - bravo axis 2
# 2 throttle 1 - bravo axis 1
# 3 throttle 2 - bravo axis 6
# 4 prop - bravo axis 5
# 5 mixture / condition - bravo axis 4
# 6 flaps - bravo axis 3



def get_gate_value(value):
    ''' returns the axis value based on airbus gates '''
    
    gate = GATE_NONE
    if value >= CLB_MIN and value <= CLB_MAX:
        value = AXIS_CLB
        gate = GATE_CLIMB
    elif value >= FLEX_MIN and value <= FLEX_MAX:
        value = AXIS_FLEX
        gate = GATE_FLEX
    elif value >= TOGA_MIN:
        value = AXIS_TOGA
        gate = GATE_TOGA
    elif value >= IDLE_MIN and value <= IDLE_MAX:
        value = AXIS_IDLE
        gate = GATE_IDLE
    elif value < IDLE_MIN:
        value = AXIS_REV
        gate = GATE_REV

    else:
        gate = GATE_NONE

    return value, gate


@bravo.button(35)
def set_airbus_mode(event):
    ''' left rocker button above throttles on bravo '''
    global airbus_mode
    airbus_mode = event.is_pressed
    if airbus_mode:
        say("airbus mode enabled")
    else:
        say("airbus mode disabled")

def osc_callback(cmd, value):
    ''' OSC message handler '''
    if cmd == "cmd":
        vjoy = gremlin.joystick_handling.VJoyProxy()
        if value == "toggle_rev_1":
            _rev_1_engaged = not _rev_1_engaged
        elif value == "toggle_rev_2":
            _rev_2_engaged = not _rev_2_engaged
        elif value == "set_rev_1":
            _rev_1_engaged = True
        elif value == "set_rev_2":
            _rev_2_engaged = True
        elif value == "clear_rev_1":
            _rev_1_engaged = False
        elif value == "clear_rev_2":
            _rev_2_engaged = False
        elif value == "set_toga":
            vjoy[2].axis(2).value = AXIS_TOGA
            vjoy[2].axis(3).value = AXIS_TOGA
        elif value == "set_flex":
            vjoy[2].axis(2).value = AXIS_FLEX
            vjoy[2].axis(3).value = AXIS_FLEX
        elif value == "set_climb":
            vjoy[2].axis(2).value = AXIS_CLB
            vjoy[2].axis(3).value = AXIS_CLB
        elif value == "set_idle":
            vjoy[2].axis(2).value = AXIS_IDLE
            vjoy[2].axis(3).value = AXIS_IDLE
        elif value == "set_rev":
            _rev_1_engaged = True
            _rev_2_engaged = True
            vjoy[2].axis(2).value = AXIS_REV
            vjoy[2].axis(3).value = AXIS_REV
        elif value == "set_toga_1":
            vjoy[2].axis(2).value = AXIS_TOGA
        elif value == "set_flex_1":
            vjoy[2].axis(2).value = AXIS_FLEX
        elif value == "set_climb_1":
            vjoy[2].axis(2).value = AXIS_CLB
        elif value == "set_idle_1":
            vjoy[2].axis(2).value = AXIS_IDLE
        elif value == "set_rev_1":
            _rev_1_engaged = True
            vjoy[2].axis(2).value = AXIS_REV
        elif value == "set_toga_2":
            vjoy[2].axis(3).value = AXIS_TOGA
        elif value == "set_flex_2":
            vjoy[2].axis(3).value = AXIS_FLEX
        elif value == "set_climb_2":
            vjoy[2].axis(3).value = AXIS_CLB
        elif value == "set_idle_2":
            vjoy[2].axis(3).value = AXIS_IDLE
        elif value == "set_rev_2":
            _rev_2_engaged = True
            vjoy[2].axis(3).value = AXIS_REV                        
            



def update_airbus_gate(vjoy, index, gate):
    ''' sets joystick buttons based on gate ranges for either throttle 1 or 2 '''
    gates = [AB_IDLE_1, AB_IDLE_2, AB_CLIMB_1, AB_CLIMB_2, AB_FLEX_1, AB_FLEX_2, AB_REV_1, AB_REV_2, AB_TOGA_1, AB_TOGA_2 ]
    global airbus_gate
    if airbus_gate != gate:
        airbus_gate = gate
        # if gate == GATE_IDLE:
        #     say("idle mode")
        # elif gate == GATE_CLIMB:
        #     say("climb mode")
        # elif gate == GATE_FLEX:
        #     say("flex mode")
        # elif gate == GATE_TOGA:
        #     say("toga mode")
        # elif gate == GATE_REV:
        #     say("reverse mode")
        

        if gate == GATE_IDLE:
            if index == 1 or index == 0:
                vjoy[2].button(AB_IDLE_1).is_pressed = True
            if index == 2 or index == 0:
                vjoy[2].button(AB_IDLE_2).is_pressed = True
            gates.remove(AB_IDLE_1)
            gates.remove(AB_IDLE_2)
                
        elif gate == GATE_CLIMB:
            if index == 1  or index == 0:
                vjoy[2].button(AB_CLIMB_1).is_pressed = True
            if index == 2 or index == 0:
                vjoy[2].button(AB_CLIMB_2).is_pressed = True
            gates.remove(AB_CLIMB_1)
            gates.remove(AB_CLIMB_2)
        elif gate == GATE_FLEX:
            if index == 1 or index == 0:
                vjoy[2].button(AB_FLEX_1).is_pressed = True
            if index == 2 or index == 0:
                vjoy[2].button(AB_FLEX_2).is_pressed = True
            gates.remove(AB_FLEX_1)
            gates.remove(AB_FLEX_2)
        elif gate == GATE_TOGA:
            if index == 1 or index == 0:
                vjoy[2].button(AB_TOGA_1).is_pressed = True
            if index == 2 or index == 0:
                vjoy[2].button(AB_TOGA_2).is_pressed = True
            gates.remove(AB_TOGA_1)
            gates.remove(AB_TOGA_2)

        # clear other gate buttons
        for gate in gates:
            vjoy[2].button(gate).is_pressed = False



def update_mixture_gate(vjoy, index):
    ''' updates mixture gate value cutoff/low/high '''
    global mixture_gate
    gate = mixture_gate[index]
    base = 60
    vjoy[2].button(base).is_pressed = gate == MIX_CUTOFF
    vjoy[2].button(base+1).is_pressed = gate == MIX_LOW
    vjoy[2].button(base+2).is_pressed = gate == MIX_HIGH
    

def clear_gates(vjoy, index = 0):
    ''' clears the airbus gate buttons '''
    rlow = None
    if index == 0:
        rlow = 50
        rhigh = 59
    elif index == 1:
        rlow = 50
        rhigh = 54
    elif index == 2:
        rlow = 55
        rhigh = 59
    if rlow:
        for b in range(rlow,rhigh+1):
            vjoy[2].button(b).is_pressed = False

def gate_name(gate):
    
    if gate == GATE_IDLE:
        return "Idle"
    elif gate == GATE_CLIMB:
        return "CLB"
    elif gate == GATE_FLEX:
        return "FLX"
    elif gate == GATE_TOGA:
        return "TGA"
    return "None"
    

@bravo.axis(1)
def read_throttle_1(event, vjoy):
    ''' LEFT THROTTLE (ENGINE 1)'''
    global airbus_mode, _rev_1_engaged, airbus_gate
    # throttle 1 idle
    value = event.value
    vjoy[1].button(105).is_pressed = value == -1
    
    if airbus_mode:
        if _rev_1_engaged:
            value = AXIS_REV
            gate = GATE_REV
        else:
            # gate the throttle for three positions (CLB, FLT and TOGA)
            value, gate = get_gate_value(value)
        # gremlin.util.log(f"left {gate_name(gate)} {value} raw: {event.value}")
    vjoy[2].axis(2).value = value

@bravo.axis(6)
def read_throttle_2(event, vjoy):
    ''' RIGHT THROTTLE (ENGINE 2)'''
    global airbus_mode, _rev_2_engaged
    # throttle 2 idle
    
    value = event.value
    vjoy[1].button(106).is_pressed = value == -1
    
    if airbus_mode:
        if _rev_2_engaged:
            value = AXIS_REV
            gate = GATE_REV
        else:
            # gate the throttle for three positions (CLB, FLT and TOGA)
            value, gate = get_gate_value(value)
        # gremlin.util.log(f"right {gate_name(gate)} output: {value} raw: {event.value}")
        

    vjoy[2].axis(3).value = value



@bravo.axis(4)
def read_mixture(event, vjoy):
    ''' reads the mixture axis '''
    global mixture_gate
    value = event.value
    #gremlin.util.log(f"mixture {value}")
    if value >= MIX_LOW_MIN and value <= MIX_LOW_MAX:
        mixture_gate[1] = MIX_LOW
        #gremlin.util.log(f"mixture low")
    elif value >= MIX_HI_MIN and value <= MIX_HI_MAX:
        mixture_gate[1] = MIX_HIGH
        #gremlin.util.log(f"mixture high")
    update_mixture_gate(vjoy, 1)


    


# # thrust lever
@bravo.button(30)
def toggle_rev_1(event, vjoy, joy):
    global _rev_1_engaged
    _rev_1_engaged = event.is_pressed
    update_reversers(vjoy)
    
# thrust lever
@bravo.button(29)
def toggle_rev_2(event, vjoy, joy):
    global _rev_2_engaged
    _rev_2_engaged = event.is_pressed
    update_reversers(vjoy)
    
# mixture cutoff
@bravo.button(28)
def mixture_cutoff(event, vjoy):
    global mixture_gate
    #gremlin.util.log(f"mixture cutoff event")
    mixture_gate[1] = MIX_CUTOFF if event.is_pressed else MIX_NONE
    update_mixture_gate(vjoy, 1)


@bravo.axis(2)
def read_speed_brake(event, vjoy):
    value = event.value
    vjoy[1].button(107).is_pressed = value == 1
    vjoy[1].button(108).is_pressed = value == value > -0.1 and value < 0.1
    vjoy[1].button(109).is_pressed = value == -1


@bravo.axis(4)
def condition_lever(event, vjoy):
    value = event.value
    vjoy[1].button(85).is_pressed = value == 1
    vjoy[1].button(86).is_pressed = value == -1


# def unscale_rudder(event, vjoy):
#     global rudder_scaled
#     rudder_factor = RUDDER_FACTOR if rudder_scaled else 1.0

#     # update the rudder
#     value = t_rudder_raw.axis(3).value
#     vjoy[1].axis(3).value = active_curve(value * rudder_factor)



@left_vpc.button(1)
# button - left yoke rear
def alpha_rudder(event):
    # top guard = reversers
    RunMacro(f1_macro)
    #unscale_rudder(event)

# @bravo.button(30)
# def vpc_rudder_b30(event,vjoy):
#     # thrust reverser engine 1
#     RunMacro(f1_macro)

# @bravo.button(48)
# def vpc_rudder_b48(event,vjoy):
#     # thrust reverser engine 2
#     RunMacro(f1_macro)

# @left_vpc.button(3)
# # trigger button - left stick
# def vpc_rudder(event,vjoy):
#     if event.is_pressed:
#         global rudder_scaled
#         rudder_scaled = not rudder_scaled
#         if rudder_scaled:
#             say("Rudder scale on")
#         else:
#             say("rudder scale off")
#         unscale_rudder(event, vjoy)



@bravo.button(31)
def gear_up(event, vjoy):
    if event.is_pressed:
        fireButton(event, vjoy, 1, 31, None, True, PULSE_DURATION)

@bravo.button(32)
def gear_down(event, vjoy):
    if event.is_pressed:
        fireButton(event, vjoy, 1, 32, None, True, PULSE_DURATION)


PERIODIC = 0.25
@gremlin.input_devices.periodic(PERIODIC)
def update():

    # update trim axis based on the current position of the axis
    global vpc_left_raw
    stick_value = vpc_left_raw.axis(5).value
    small_offset = 0.025
    medium_offset = 0.05
    large_offset = 0.1
    if stick_value == 0:
        return
    if stick_value > 0.1:
        offset = small_offset
    elif stick_value > 0.5:
        offset = medium_offset
    elif stick_value > 0.9:
        offset = large_offset
    elif stick_value < -0.1:
        offset = -small_offset
    elif stick_value < -0.5:
        offset = -medium_offset
    elif stick_value < -0.9:
        offset = -large_offset
    else:
        return
    
    vjoy = gremlin.joystick_handling.VJoyProxy()
    value = vjoy[2].axis(4).value
    # reverse
    value -= offset
    if value > 1:
        value = 1
    elif value < -1:
        value = -1
    #gremlin.util.log(f"{offset} {value}")
    vjoy[2].axis(4).value = value


  
@gremlin.input_devices.gremlin_start()
def on_start():
    global _rev_1_engaged, _rev_2_engaged
    _rev_1_engaged = bravo_raw.button(30).is_pressed
    _rev_2_engaged = bravo_raw.button(48).is_pressed

    # zero the throttles
    osc_callback("cmd","set_idle")
    # flaps UP
    vjoy = gremlin.joystick_handling.VJoyProxy()
    vjoy[2].axis(6).value = 1

    register_handler(osc_callback)  
    

@gremlin.input_devices.gremlin_stop()
def on_stop():
    unregister_handler(osc_callback)