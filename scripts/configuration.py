# configuration file for device IDs

import gremlin


'''
2019-03-16 13:48:37      DEBUG Added: name=T-Rudder windows_id=11 hardware_id=72332921
2019-03-16 13:48:37      DEBUG Added: name=vJoy Device windows_id=10 hardware_id=305446573
2019-03-16 13:48:37      DEBUG Added: name=vJoy Device windows_id=9 hardware_id=305446573
2019-03-16 13:48:37      DEBUG Added: name=vJoy Device windows_id=8 hardware_id=305446573
2019-03-16 13:48:37      DEBUG Added: name=DSD Flight Series Button Controller windows_id=7 hardware_id=81300029
2019-03-16 13:48:37      DEBUG Added: name=CH FLIGHT SIM YOKE USB  windows_id=6 hardware_id=109969663
2019-03-16 13:48:37      DEBUG Added: name=Throttle - HOTAS Warthog windows_id=5 hardware_id=72287236
2019-03-16 13:48:37      DEBUG Added: name=T.16000M windows_id=4 hardware_id=72331530
2019-03-16 13:48:37      DEBUG Added: name=Logitech G29 Driving Force Racing Wheel USB windows_id=3 hardware_id=74302031
2019-03-16 13:48:37      DEBUG Added: name=CH THROTTLE QUADRANT windows_id=2 hardware_id=109969658
2019-03-16 13:48:37      DEBUG Added: name=DSD Flight Series Button Controller windows_id=1 hardware_id=81300029
2019-03-16 13:48:37      DEBUG Added: name=Joystick - HOTAS Warthog windows_id=0 hardware_id=72287234


2019-07-07 14:37:32      DEBUG Added: name=T-Rudder guid={A5AA2B50-25E9-11E7-8001-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=Joystick - HOTAS Warthog guid={A60B8530-25E9-11E7-8004-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=CH THROTTLE QUADRANT guid={82B95310-3277-11E7-8001-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=Logitech G29 Driving Force Racing Wheel USB guid={DFEF1600-2876-11E8-8001-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=DSD Flight Series Button Controller guid={A4F58A50-2156-11E9-8001-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=T.16000M guid={A60B5E20-25E9-11E7-8002-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=CH FLIGHT SIM YOKE USB  guid={21C09900-4347-11E9-8001-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=Throttle - HOTAS Warthog guid={A60B8530-25E9-11E7-8003-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=DSD Flight Series Button Controller guid={0C2523B0-2158-11E9-8001-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=vJoy Device guid={2D3260A0-6FA6-11E7-8002-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=vJoy Device guid={705DC1A0-C170-11E7-8003-444553540000}
2019-07-07 14:37:32      DEBUG Added: name=vJoy Device guid={8245C100-2705-11E9-8002-444553540000}
'''

    

TM_STICK_ID = 1
TM_STICK_HWID = 72287234
TM_STICK_NAME = "Joystick - HOTAS Warthog"
TM_STICK_GUID = "{A60B8530-25E9-11E7-8004-444553540000}"

# panel with rotating knobs on side
P1_DSD_ID = 4
P1_DSD_HWID = 81300029
P1_DSD_NAME = "DSD FLight Series Button Controller"
P1_DSD_GUID = "{A4F58A50-2156-11E9-8001-444553540000}"

# panel with rotating knobs on top
P2_DSD_HWID = 81300029
P2_DSD_ID = 8
P2_DSD_NAME = "DSD FLight Series Button Controller"
P2_DSD_GUID = "{0C2523B0-2158-11E9-8001-444553540000}"

CH_QUADRANT_ID = 2
CH_QUADRANT_HWID = 109969658
CH_QUADRANT_NAME = "CH THROTTLE QUADRANT"
CH_QUADRANT_GUID = "{82B95310-3277-11E7-8001-444553540000}"

G29_ID = 3
G29_HWID = 74302031
G29_NAME = "Logitech G29 Driving Force Racing Wheel USB"
G29_GUID = "{DFEF1600-2876-11E8-8001-444553540000}"

T16K_ID = 5
T16K_HWID = 72331530
T16K_NAME = "T.16000M"
T16K_GUID = "{A60B5E20-25E9-11E7-8002-444553540000}"

TM_THROTTLE_ID = 7
TM_THROTTLE_HWID = 72287236
TM_THROTTLE_NAME = "Throttle - HOTAS Warthog"
TM_THROTTLE_GUID = "{A60B8530-25E9-11E7-8003-444553540000}"

CH_YOKE_ID = 6
CH_YOKE_HWID = 109969663
CH_YOKE_NAME = "CH FLIGHT SIM YOKE USB"
CH_YOKE_GUID = "{21C09900-4347-11E9-8001-444553540000}"


VPC_RIGHT_ID = 12
VPC_RIGHT_GUID = "{5CDF3590-F2A1-11EA-8002-444553540000}"
VPC_RIGHT_NAME = "RIGHT VPC Stick WarBRD"

VPC_LEFT_ID = 9
VPC_LEFT_GUID = "{15138A40-F2A1-11EA-8001-444553540000}"
VPC_LEFT_NAME = "LEFT VPC Stick WarBRD"

VJOY_INPUT_GUID = "{203C80E0-15C8-11EA-8002-444553540000}"
VJOY_INPUT_NAME = "vJoy Device"


# 9 vjoy
# 10 vjoy
# 11 vjoy

TM_RUDDER_ID = 0
TM_RUDDER_HWID = 72332921
TM_RUDDER_NAME = "T-Rudder"
TM_RUDDER_GUID = "{A5AA2B50-25E9-11E7-8001-444553540000}"

MFG_Crosswind_V2_3_NAME = "MFG Crosswind V2/3"
MFG_Crosswind_V2_3_GUID = "{9C5A2470-DA31-11EE-8002-444553540000}"

ALPHA_NAME = "Alpha Flight Controls"
ALPHA_GUID = "{B11A3E70-DDE1-11EC-8001-444553540000}"

BRAVO_NAME = "Bravo Throttle Quadrant"
BRAVO_GUID = "{0D258FE0-1A64-11EC-8001-444553540000}"

SIMTEK_NAME = "SIMVERTEX TH13"
SIMTEK_GUID = "{7F168740-6991-11EC-8001-444553540000}"


# pulse length in seconds

PULSE_LENGTH = 0.1

# delay in seconds to determine slow rotation vs fast rotation pulses for rotary knobs - this is time in seconds between rotation pulses
LONG_PULSE = 0.1

MODE_ALL = "Default"
MODE_DEFAULT = MODE_ALL

MODE_A = "A"

''' REFERENCE AXES '''

'''
_AxisNames_to_enum_lookup = {
   1 "X Axis": AxisNames.X,
   2 "Y Axis": AxisNames.Y,
   3 "Z Axis": AxisNames.Z,
   4 "X Rotation": AxisNames.RX,
   5 "Y Rotation": AxisNames.RY,
   6 "Z Rotation": AxisNames.RZ,
   7 "Slider": AxisNames.SLIDER,
   8 "Dial": AxisNames.DIAL
}
'''

AXIS_X = 1
AXIS_Y = 2
AXIS_Z = 3
AXIS_RX = 4
AXIS_RY = 5
AXIS_RZ = 6
AXIS_SLIDER = 7
AXIS_DIAL = 8

# GremlinEx plugin script device list


# device Alpha Flight Controls - axis count: 2  hat count: 1  button count: 35
Alpha_Flight_Controls_NAME = "Alpha Flight Controls"
Alpha_Flight_Controls_GUID = "{B11A3E70-DDE1-11EC-8001-444553540000}"

# device Bravo Throttle Quadrant - axis count: 6  hat count: 0  button count: 48
Bravo_Throttle_Quadrant_NAME = "Bravo Throttle Quadrant"
Bravo_Throttle_Quadrant_GUID = "{0D258FE0-1A64-11EC-8001-444553540000}"

# device LEFT VPC Stick WarBRD - axis count: 6  hat count: 0  button count: 31
LEFT_VPC_Stick_WarBRD_NAME = "LEFT VPC Stick WarBRD"
LEFT_VPC_Stick_WarBRD_GUID = "{15138A40-F2A1-11EA-8001-444553540000}"

# device RaspberryPi Pico - axis count: 8  hat count: 4  button count: 128
RaspberryPi_Pico_NAME = "RaspberryPi Pico"
RaspberryPi_Pico_GUID = "{83E65A90-1F06-11ED-8001-444553540000}"

# device Throttle - HOTAS Warthog - axis count: 5  hat count: 1  button count: 32
Throttle_HOTAS_Warthog_NAME = "Throttle - HOTAS Warthog"
Throttle_HOTAS_Warthog_GUID = "{A60B8530-25E9-11E7-8003-444553540000}"

# device RIGHT VPC Stick WarBRD - axis count: 6  hat count: 0  button count: 31
RIGHT_VPC_Stick_WarBRD_NAME = "RIGHT VPC Stick WarBRD"
RIGHT_VPC_Stick_WarBRD_GUID = "{5CDF3590-F2A1-11EA-8002-444553540000}"

# device T-Rudder - axis count: 3  hat count: 0  button count: 0
T_Rudder_NAME = "T-Rudder"
T_Rudder_GUID = "{A5AA2B50-25E9-11E7-8001-444553540000}"


X_Rudder_NAME = "MFG Crosswind V2/3"
X_Rudder_GUID = "{9C5A2470-DA31-11EE-8002-444553540000}"


# device DSD Flight Series Button Controller - axis count: 0  hat count: 0  button count: 32
DSD_Flight_Series_Button_Controller_NAME = "DSD Flight Series Button Controller"
DSD_Flight_Series_Button_Controller_GUID = "{A4F58A50-2156-11E9-8001-444553540000}"

# plugin decorator definitions

# decorators for mode A
LEFT_VPC_Stick_WarBRD_A = gremlin.input_devices.JoystickDecorator(LEFT_VPC_Stick_WarBRD_NAME, LEFT_VPC_Stick_WarBRD_GUID, "A")
T_Rudder_A = gremlin.input_devices.JoystickDecorator(T_Rudder_NAME, T_Rudder_GUID, "A")
RaspberryPi_Pico_A = gremlin.input_devices.JoystickDecorator(RaspberryPi_Pico_NAME, RaspberryPi_Pico_GUID, "A")
Alpha_Flight_Controls_A = gremlin.input_devices.JoystickDecorator(Alpha_Flight_Controls_NAME, Alpha_Flight_Controls_GUID, "A")
Bravo_Throttle_Quadrant_A = gremlin.input_devices.JoystickDecorator(Bravo_Throttle_Quadrant_NAME, Bravo_Throttle_Quadrant_GUID, "A")
RIGHT_VPC_Stick_WarBRD_A = gremlin.input_devices.JoystickDecorator(RIGHT_VPC_Stick_WarBRD_NAME, RIGHT_VPC_Stick_WarBRD_GUID, "A")
Throttle_HOTAS_Warthog_A = gremlin.input_devices.JoystickDecorator(Throttle_HOTAS_Warthog_NAME, Throttle_HOTAS_Warthog_GUID, "A")
DSD_Flight_Series_Button_Controller_A = gremlin.input_devices.JoystickDecorator(DSD_Flight_Series_Button_Controller_NAME, DSD_Flight_Series_Button_Controller_GUID, "A")

# decorators for mode Default
RaspberryPi_Pico_Default = gremlin.input_devices.JoystickDecorator(RaspberryPi_Pico_NAME, RaspberryPi_Pico_GUID, "Default")
LEFT_VPC_Stick_WarBRD_Default = gremlin.input_devices.JoystickDecorator(LEFT_VPC_Stick_WarBRD_NAME, LEFT_VPC_Stick_WarBRD_GUID, "Default")
T_Rudder_Default = gremlin.input_devices.JoystickDecorator(T_Rudder_NAME, T_Rudder_GUID, "Default")
DSD_Flight_Series_Button_Controller_Default = gremlin.input_devices.JoystickDecorator(DSD_Flight_Series_Button_Controller_NAME, DSD_Flight_Series_Button_Controller_GUID, "Default")
RIGHT_VPC_Stick_WarBRD_Default = gremlin.input_devices.JoystickDecorator(RIGHT_VPC_Stick_WarBRD_NAME, RIGHT_VPC_Stick_WarBRD_GUID, "Default")
Alpha_Flight_Controls_Default = gremlin.input_devices.JoystickDecorator(Alpha_Flight_Controls_NAME, Alpha_Flight_Controls_GUID, "Default")
Throttle_HOTAS_Warthog_Default = gremlin.input_devices.JoystickDecorator(Throttle_HOTAS_Warthog_NAME, Throttle_HOTAS_Warthog_GUID, "Default")
Bravo_Throttle_Quadrant_Default = gremlin.input_devices.JoystickDecorator(Bravo_Throttle_Quadrant_NAME, Bravo_Throttle_Quadrant_GUID, "Default")

# decorators for mode mining
T_Rudder_mining = gremlin.input_devices.JoystickDecorator(T_Rudder_NAME, T_Rudder_GUID, "mining")
RIGHT_VPC_Stick_WarBRD_mining = gremlin.input_devices.JoystickDecorator(RIGHT_VPC_Stick_WarBRD_NAME, RIGHT_VPC_Stick_WarBRD_GUID, "mining")
Alpha_Flight_Controls_mining = gremlin.input_devices.JoystickDecorator(Alpha_Flight_Controls_NAME, Alpha_Flight_Controls_GUID, "mining")
RaspberryPi_Pico_mining = gremlin.input_devices.JoystickDecorator(RaspberryPi_Pico_NAME, RaspberryPi_Pico_GUID, "mining")
Bravo_Throttle_Quadrant_mining = gremlin.input_devices.JoystickDecorator(Bravo_Throttle_Quadrant_NAME, Bravo_Throttle_Quadrant_GUID, "mining")
Throttle_HOTAS_Warthog_mining = gremlin.input_devices.JoystickDecorator(Throttle_HOTAS_Warthog_NAME, Throttle_HOTAS_Warthog_GUID, "mining")
LEFT_VPC_Stick_WarBRD_mining = gremlin.input_devices.JoystickDecorator(LEFT_VPC_Stick_WarBRD_NAME, LEFT_VPC_Stick_WarBRD_GUID, "mining")
DSD_Flight_Series_Button_Controller_mining = gremlin.input_devices.JoystickDecorator(DSD_Flight_Series_Button_Controller_NAME, DSD_Flight_Series_Button_Controller_GUID, "mining")

# decorators for mode missile
Alpha_Flight_Controls_missile = gremlin.input_devices.JoystickDecorator(Alpha_Flight_Controls_NAME, Alpha_Flight_Controls_GUID, "missile")
Throttle_HOTAS_Warthog_missile = gremlin.input_devices.JoystickDecorator(Throttle_HOTAS_Warthog_NAME, Throttle_HOTAS_Warthog_GUID, "missile")
RaspberryPi_Pico_missile = gremlin.input_devices.JoystickDecorator(RaspberryPi_Pico_NAME, RaspberryPi_Pico_GUID, "missile")
Bravo_Throttle_Quadrant_missile = gremlin.input_devices.JoystickDecorator(Bravo_Throttle_Quadrant_NAME, Bravo_Throttle_Quadrant_GUID, "missile")
RIGHT_VPC_Stick_WarBRD_missile = gremlin.input_devices.JoystickDecorator(RIGHT_VPC_Stick_WarBRD_NAME, RIGHT_VPC_Stick_WarBRD_GUID, "missile")
LEFT_VPC_Stick_WarBRD_missile = gremlin.input_devices.JoystickDecorator(LEFT_VPC_Stick_WarBRD_NAME, LEFT_VPC_Stick_WarBRD_GUID, "missile")
T_Rudder_missile = gremlin.input_devices.JoystickDecorator(T_Rudder_NAME, T_Rudder_GUID, "missile")
DSD_Flight_Series_Button_Controller_missile = gremlin.input_devices.JoystickDecorator(DSD_Flight_Series_Button_Controller_NAME, DSD_Flight_Series_Button_Controller_GUID, "missile")

# decorators for mode scan
RIGHT_VPC_Stick_WarBRD_scan = gremlin.input_devices.JoystickDecorator(RIGHT_VPC_Stick_WarBRD_NAME, RIGHT_VPC_Stick_WarBRD_GUID, "scan")
RaspberryPi_Pico_scan = gremlin.input_devices.JoystickDecorator(RaspberryPi_Pico_NAME, RaspberryPi_Pico_GUID, "scan")
T_Rudder_scan = gremlin.input_devices.JoystickDecorator(T_Rudder_NAME, T_Rudder_GUID, "scan")
Alpha_Flight_Controls_scan = gremlin.input_devices.JoystickDecorator(Alpha_Flight_Controls_NAME, Alpha_Flight_Controls_GUID, "scan")
Bravo_Throttle_Quadrant_scan = gremlin.input_devices.JoystickDecorator(Bravo_Throttle_Quadrant_NAME, Bravo_Throttle_Quadrant_GUID, "scan")
LEFT_VPC_Stick_WarBRD_scan = gremlin.input_devices.JoystickDecorator(LEFT_VPC_Stick_WarBRD_NAME, LEFT_VPC_Stick_WarBRD_GUID, "scan")
DSD_Flight_Series_Button_Controller_scan = gremlin.input_devices.JoystickDecorator(DSD_Flight_Series_Button_Controller_NAME, DSD_Flight_Series_Button_Controller_GUID, "scan")
Throttle_HOTAS_Warthog_scan = gremlin.input_devices.JoystickDecorator(Throttle_HOTAS_Warthog_NAME, Throttle_HOTAS_Warthog_GUID, "scan")

# decorators for mode view
LEFT_VPC_Stick_WarBRD_view = gremlin.input_devices.JoystickDecorator(LEFT_VPC_Stick_WarBRD_NAME, LEFT_VPC_Stick_WarBRD_GUID, "view")
DSD_Flight_Series_Button_Controller_view = gremlin.input_devices.JoystickDecorator(DSD_Flight_Series_Button_Controller_NAME, DSD_Flight_Series_Button_Controller_GUID, "view")
T_Rudder_view = gremlin.input_devices.JoystickDecorator(T_Rudder_NAME, T_Rudder_GUID, "view")
Throttle_HOTAS_Warthog_view = gremlin.input_devices.JoystickDecorator(Throttle_HOTAS_Warthog_NAME, Throttle_HOTAS_Warthog_GUID, "view")
RaspberryPi_Pico_view = gremlin.input_devices.JoystickDecorator(RaspberryPi_Pico_NAME, RaspberryPi_Pico_GUID, "view")
Bravo_Throttle_Quadrant_view = gremlin.input_devices.JoystickDecorator(Bravo_Throttle_Quadrant_NAME, Bravo_Throttle_Quadrant_GUID, "view")
RIGHT_VPC_Stick_WarBRD_view = gremlin.input_devices.JoystickDecorator(RIGHT_VPC_Stick_WarBRD_NAME, RIGHT_VPC_Stick_WarBRD_GUID, "view")
Alpha_Flight_Controls_view = gremlin.input_devices.JoystickDecorator(Alpha_Flight_Controls_NAME, Alpha_Flight_Controls_GUID, "view")
