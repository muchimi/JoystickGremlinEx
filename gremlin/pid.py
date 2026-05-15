''' PID controllers = adapted from 
    https://github.com/m-lundberg/simple-pid/tree/master
    and
    https://github.com/ThunderTecke/PID_Py


'''
# from __future__ import annotations # deprecated with python 3.14+
import time
from enum import Flag, auto
from threading import Thread
import logging



def _clamp(value, limits):
    lower, upper = limits
    if value is None:
        return None
    elif (upper is not None) and (value > upper):
        return upper
    elif (lower is not None) and (value < lower):
        return lower
    return value


class SimplePID(object):
    """A simple PID controller."""

    def __init__(
        self,
        Kp=1.0,
        Ki=0.0,
        Kd=0.0,
        setpoint=0,
        sample_time=0.01,
        output_limits=(None, None),
        auto_mode=True,
        proportional_on_measurement=False,
        differential_on_measurement=True,
        error_map=None,
        time_fn=None,
        starting_output=0.0,
    ):
        """
        Initialize a new PID controller.

        :param Kp: The value for the proportional gain Kp
        :param Ki: The value for the integral gain Ki
        :param Kd: The value for the derivative gain Kd
        :param setpoint: The initial setpoint that the PID will try to achieve
        :param sample_time: The time in seconds which the controller should wait before generating
            a new output value. The PID works best when it is constantly called (eg. during a
            loop), but with a sample time set so that the time difference between each update is
            (close to) constant. If set to None, the PID will compute a new output value every time
            it is called.
        :param output_limits: The initial output limits to use, given as an iterable with 2
            elements, for example: (lower, upper). The output will never go below the lower limit
            or above the upper limit. Either of the limits can also be set to None to have no limit
            in that direction. Setting output limits also avoids integral windup, since the
            integral term will never be allowed to grow outside of the limits.
        :param auto_mode: Whether the controller should be enabled (auto mode) or not (manual mode)
        :param proportional_on_measurement: Whether the proportional term should be calculated on
            the input directly rather than on the error (which is the traditional way). Using
            proportional-on-measurement avoids overshoot for some types of systems.
        :param differential_on_measurement: Whether the differential term should be calculated on
            the input directly rather than on the error (which is the traditional way).
        :param error_map: Function to transform the error value in another constrained value.
        :param time_fn: The function to use for getting the current time, or None to use the
            default. This should be a function taking no arguments and returning a number
            representing the current time. The default is to use time.monotonic() if available,
            otherwise time.time().
        :param starting_output: The starting point for the PID's output. If you start controlling
            a system that is already at the setpoint, you can set this to your best guess at what
            output the PID should give when first calling it to avoid the PID outputting zero and
            moving the system away from the setpoint.
        """
        self.Kp, self.Ki, self.Kd = Kp, Ki, Kd
        self.setpoint = setpoint
        self.sample_time = sample_time

        self._min_output, self._max_output = None, None
        self._auto_mode = auto_mode
        self.proportional_on_measurement = proportional_on_measurement
        self.differential_on_measurement = differential_on_measurement
        self.error_map = error_map

        self._proportional = 0
        self._integral = 0
        self._derivative = 0

        self._last_time = None
        self._last_output = None
        self._last_error = None
        self._last_input = None

        if time_fn is not None:
            # Use the user supplied time function
            self.time_fn = time_fn
        else:
            import time

            try:
                # Get monotonic time to ensure that time deltas are always positive
                self.time_fn = time.monotonic
            except AttributeError:
                # time.monotonic() not available (using python < 3.3), fallback to time.time()
                self.time_fn = time.time

        self.output_limits = output_limits
        self.reset()

        # Set initial state of the controller
        self._integral = _clamp(starting_output, output_limits)

    def __call__(self, input_, dt=None):
        """
        Update the PID controller.

        Call the PID controller with *input_* and calculate and return a control output if
        sample_time seconds has passed since the last update. If no new output is calculated,
        return the previous output instead (or None if no value has been calculated yet).

        :param dt: If set, uses this value for timestep instead of real time. This can be used in
            simulations when simulation time is different from real time.
        """
        if not self.auto_mode:
            return self._last_output

        now = self.time_fn()
        if dt is None:
            dt = now - self._last_time if (now - self._last_time) else 1e-16
        elif dt <= 0:
            raise ValueError('dt has negative value {}, must be positive'.format(dt))

        if self.sample_time is not None and dt < self.sample_time and self._last_output is not None:
            # Only update every sample_time seconds
            return self._last_output

        # Compute error terms
        error = self.setpoint - input_
        d_input = input_ - (self._last_input if (self._last_input is not None) else input_)
        d_error = error - (self._last_error if (self._last_error is not None) else error)

        # Check if must map the error
        if self.error_map is not None:
            error = self.error_map(error)

        # Compute the proportional term
        if not self.proportional_on_measurement:
            # Regular proportional-on-error, simply set the proportional term
            self._proportional = self.Kp * error
        else:
            # Add the proportional error on measurement to error_sum
            self._proportional -= self.Kp * d_input

        # Compute integral and derivative terms
        self._integral += self.Ki * error * dt
        self._integral = _clamp(self._integral, self.output_limits)  # Avoid integral windup

        if self.differential_on_measurement:
            self._derivative = -self.Kd * d_input / dt
        else:
            self._derivative = self.Kd * d_error / dt

        # Compute final output
        output = self._proportional + self._integral + self._derivative
        output = _clamp(output, self.output_limits)

        # Keep track of state
        self._last_output = output
        self._last_input = input_
        self._last_error = error
        self._last_time = now

        return output

    def __repr__(self):
        return (
            '{self.__class__.__name__}('
            'Kp={self.Kp!r}, Ki={self.Ki!r}, Kd={self.Kd!r}, '
            'setpoint={self.setpoint!r}, sample_time={self.sample_time!r}, '
            'output_limits={self.output_limits!r}, auto_mode={self.auto_mode!r}, '
            'proportional_on_measurement={self.proportional_on_measurement!r}, '
            'differential_on_measurement={self.differential_on_measurement!r}, '
            'error_map={self.error_map!r}'
            ')'
        ).format(self=self)

    @property
    def components(self):
        """
        The P-, I- and D-terms from the last computation as separate components as a tuple. Useful
        for visualizing what the controller is doing or when tuning hard-to-tune systems.
        """
        return self._proportional, self._integral, self._derivative

    @property
    def tunings(self):
        """The tunings used by the controller as a tuple: (Kp, Ki, Kd)."""
        return self.Kp, self.Ki, self.Kd

    @tunings.setter
    def tunings(self, tunings):
        """Set the PID tunings."""
        self.Kp, self.Ki, self.Kd = tunings

    @property
    def auto_mode(self):
        """Whether the controller is currently enabled (in auto mode) or not."""
        return self._auto_mode

    @auto_mode.setter
    def auto_mode(self, enabled):
        """Enable or disable the PID controller."""
        self.set_auto_mode(enabled)

    def set_auto_mode(self, enabled, last_output=None):
        """
        Enable or disable the PID controller, optionally setting the last output value.

        This is useful if some system has been manually controlled and if the PID should take over.
        In that case, disable the PID by setting auto mode to False and later when the PID should
        be turned back on, pass the last output variable (the control variable) and it will be set
        as the starting I-term when the PID is set to auto mode.

        :param enabled: Whether auto mode should be enabled, True or False
        :param last_output: The last output, or the control variable, that the PID should start
            from when going from manual mode to auto mode. Has no effect if the PID is already in
            auto mode.
        """
        if enabled and not self._auto_mode:
            # Switching from manual mode to auto, reset
            self.reset()

            self._integral = last_output if (last_output is not None) else 0
            self._integral = _clamp(self._integral, self.output_limits)

        self._auto_mode = enabled

    @property
    def output_limits(self):
        """
        The current output limits as a 2-tuple: (lower, upper).

        See also the *output_limits* parameter in :meth:`PID.__init__`.
        """
        return self._min_output, self._max_output

    @output_limits.setter
    def output_limits(self, limits):
        """Set the output limits."""
        if limits is None:
            self._min_output, self._max_output = None, None
            return

        min_output, max_output = limits

        if (None not in limits) and (max_output < min_output):
            raise ValueError('lower limit must be less than upper limit')

        self._min_output = min_output
        self._max_output = max_output

        self._integral = _clamp(self._integral, self.output_limits)
        self._last_output = _clamp(self._last_output, self.output_limits)

    def reset(self):
        """
        Reset the PID controller internals.

        This sets each term to 0 as well as clearing the integral, the last output and the last
        input (derivative calculation).
        """
        self._proportional = 0
        self._integral = 0
        self._derivative = 0

        self._integral = _clamp(self._integral, self.output_limits)

        self._last_time = self.time_fn()
        self._last_output = None
        self._last_input = None
        self._last_error = None



class HistorianParams(Flag):
    """
    Enumeration to configure historian.
    Use with `or` (|) to sum parameters
        - (HistorianParams.P | HistorianParams.I | HistorianParams.D)
    """
    P = auto()
    I = auto()
    D = auto()
    OUTPUT = auto()
    SETPOINT = auto()
    PROCESS_VALUE = auto()
    ERROR = auto()

class PID:
    """
    PID controller base class.

    Parameters
    ----------
    kp: float
        Proportionnal gain
    
    ki: float
        Integral gain
    
    kd: float
        Derivative gain
    
    indirectAction: bool, default = False
        Invert PID action. Direct action (False) -> error = setpoint - processValue, Indirect action (True) -> error = processValue - setpoint.
        This option implies that when error is increasing the output is decreasing.
    
    proportionnalOnMeasurement: bool, default = False
        Activate proportionnal part calculation on processValue, instead of error.
        This avoid output bump when the setpoint change strongly, but increase stabilization time.
        False -> P = kp * error
        True  -> P = -kp * processValue

    integralLimit: float, default = None
        Limit the integral part. When this value is set to None, the integral part is not limited.
        The integral part is clamped between -`integralLimit` and +`integralLimit`.
    
    derivativeOnMeasurement: bool, default = False
        Activate derivative part calculation on processValue, instead of error.
        This avoid output bump when the setpoint change strongly, and there is no repercution on the PID behavior.
        If the processValue change strongly, the derivative part will slow down the processValue.s6
        False -> D = kd * ((error - lastError) / dt)
        True  -> D = -kd * ((processValue - lastProcessValue) / dt)
    
    setpointRamp: float, default = None
        Determine the maximum variation of the setpoint per second (unit/s).
        If None, no ramps are applied.

    setpointStableLimit: float, default = None
        Determine the maximum difference between the setpoint and the process value (the error) to be considered stable on the setpoint.
        If None, the PID will not be considered stabilized on the setpoint.

    setpointStableTime: float, default = 1.0
        Determine the amount of time (second) which the process value must be stabilized on the setpoint to activate `setpointReached` output.
    
    deadband: float, defaut = None
        Determine the interval ([-`deadband`, `deadband`]) on the error, where the integral part is no longer calculated.
        If None, the deadband is ignored.

    deadbandActivationTime: float, default = 1.0
        Determine the amount of time which the error is in the deadband interval to stop the integral calculation.

    processValueStableLimit: float, default = None
        Determine the maximum variation to be considered stabilized.
        If None, the process value will not be considered stabilized.
    
    processValueStableTime: float, default = 1.0
        Determine the amount of time (second) which the process value must be stabilized to activate `processValueStabilized` output.
    
    historianParams: HistorianParams, default = None
        Configure historian to record some value of the PID. When at least one value is recorded, time is recorded too.
        Possible value :
            - HistorianParams.P : Proportionnal part
            - HistorianParams.I : Integral part
            - HistorianParams.D : Derivative part
            - HistorianParams.ERROR : PID error
            - HistorianParams.SETPOINT : PID setpoint
            - HistorianParams.PROCESS_VALUE : PID process value
            - HistorianParams.OUTPUT : PID output
    
    historianLenght: int, default = 100000
        The maximum lenght of the historian. When the limit is reached, remove the oldest element.
    
    outputLimits: tuple[float, float], default = (None, None)
        Limit the output between a minimum and a maximum (min, max).
        If a limit is set to None, the limit is deactivated.
        If `outputLimit` is set to None, there is no limits.
    
    logger: logging.Logger or str, default = None
        Logging system. `logging.Logger` instance or logger name (str) can be passed.
        If it's anything else (None or other type), the PID will not send any log.
    
    simulation: Simulation, default = None
        Pass a simulation object to activate simulation.
    
    Attributes
    ----------
    kp: float
        Same as `kp` in parameters section
    
    ki: float
        Same as `ki` in parameters section
    
    kd: float
        Same as `kd` in parameters section
    
    indirectAction: float
        Same as `indirectAction` in parameters section
    
    proportionnalOnMeasurement: bool
        Same as `proportionnalOnMeasurement` in parameters section

    integralLimit: float
        Same as `integralLimit` in parameters section
    
    derivativeOnMeasurement: bool
        Same as `derivativeOnMeasurement` in parameters section
    
    setpointRamp: float
        Same as `setpointRamp` in parameters section

    setpointStableLimit: float
        Same as `setpointStableLimit` in parameters section

    setpointStableTime: float
        Same as `setpointStableTime` in parameters section

    processValueStableLimit: float
        Same as `processValueStableLimit` in parameters section
    
    processValueStableTime: float
        Same as `processValueStableTime` in parameters section

    outputLimits: float
        Same as `outputLimits` in parameters section

    integralFreezing: bool
        The integral part keep the same value until this option is activated.
        It can used when a disturbance is known in advance. For example in a oven, when it's temperature is stable and you open the door, the temperature drops quickly.
        But the door is closed again, then the temperature will rise to the previous temperature without heating more. So the integral part don't need to increase it's value to heating the oven.

    historianParams: HistorianParams
        Same as `historianParams` in parameters section
    
    historian: dict[str, list]
        PID value recorded
    
    historianLenght: int
        Same as `historianLenght` in parameters section.
    
    output: float
        PID output
    
    manualMode: bool
        Activate manual mode. In manual mode `output` is directly written by `manualValue` (limitations are always active).
        PID calculation is no longer executed in manual mode.
        Default value : False
    
    manualValue: float
        In manual mode `output` is directly written by `manualValue` (limitations are always active).
    
    bumplessSwitching: bool
        If `bumplessSwitching` is activate, in automatic mode `manualValue` is written by `output` to avoid bump when the manual mode is activated.
        When automatic mode is activated, the PID calculation restart and take setpoint.
        Bump can occur if the setpoint is too far from process value when automatic mode is reactivated.
        Default value : True
    
    logger: logging.Logger
        Contain the `logging.Logger` instance. If it's None or other type, the PID will not send any log.

    simulation: Simulation
        Same as `simulation` in parameters section.
    
    Methods
    -------
    compute(processValue, setpoint)
        Execution PID calculation. Return `output`.

    __call__(processValue, setpoint)
        call `compute`. Is a code simplification.
    """
    def __init__(self, kp: float, ki: float, kd: float, indirectAction: bool = False, proportionnalOnMeasurement: bool = False, integralLimit: float = None, derivativeOnMeasurement: bool = False, setpointRamp: float = None, setpointStableLimit: float = None, setpointStableTime: float = 1.0, deadband: float = None, deadbandActivationTime: float = 1.0, processValueStableLimit: float = None, processValueStableTime: float = 1.0, historianParams: HistorianParams = None, historianLenght: int = 100000, outputLimits: tuple[float, float] = (None, None), logger: logging.Logger = None, simulation: Simulation = None) -> None:
        # PID parameters
        self.kp = kp
        self.ki = ki
        self.kd = kd

        self.indirectAction = indirectAction

        self.proportionnalOnMeasurement = proportionnalOnMeasurement
        self.integralLimit = integralLimit
        self.derivativeOnMeasurement = derivativeOnMeasurement

        self.setpointRamp = setpointRamp

        self.setpointStableLimit = setpointStableLimit
        self.setpointStableTime = setpointStableTime

        self.deadband = deadband
        self.deadbandActivationTime = deadbandActivationTime

        self.processValueStableLimit = processValueStableLimit
        self.processValueStableTime = processValueStableTime

        self.outputLimits = outputLimits

        self.integralFreezing = False

        # Manual mode
        self.manualMode = False
        self.manualValue = 0.0
        self.bumplessSwitching = True

        # Historian setup
        self.historianParams = historianParams
        self.historian = {}

        if (historianLenght <= 0):
            raise ValueError("`historianLenght` can't be 0 or negative!")

        self.historianLenght = historianLenght
        
        if self.historianParams is not None:
            if HistorianParams.P in self.historianParams:
                self.historian["P"] = []
            
            if HistorianParams.I in self.historianParams:
                self.historian["I"] = []

            if HistorianParams.D in self.historianParams:
                self.historian["D"] = []
            
            if HistorianParams.OUTPUT in self.historianParams:
                self.historian["OUTPUT"] = []
            
            if HistorianParams.SETPOINT in self.historianParams:
                self.historian["SETPOINT"] = []
            
            if HistorianParams.PROCESS_VALUE in self.historianParams:
                self.historian["PROCESS_VALUE"] = []

            if HistorianParams.ERROR in self.historianParams:
                self.historian["ERROR"] = []

            if (HistorianParams.P in self.historianParams) or (HistorianParams.I in self.historianParams) or (HistorianParams.D in self.historianParams) or (HistorianParams.ERROR in self.historianParams) or (HistorianParams.OUTPUT in self.historianParams) or (HistorianParams.PROCESS_VALUE in self.historianParams) or (HistorianParams.SETPOINT in self.historianParams):
                self.historian["TIME"] = []
        else:
            self.historian = None
        
        # Internal attributes
        self._lastTime = None
        self._lastError = 0.0
        self._lastProcessValue = 0.0
        self._startTime = None

        self._processValueCurrStableTime = 0.0
        self._setpointValueCurrStableTime = 0.0
        self._deadbandTime = 0.0

        self._p = 0.0
        self._i = 0.0
        self._d = 0.0

        self._setpoint = 0.0

        self._setuptoolControl = False
        self._setuptoolSetpoint = 0.0

        # Outputs
        self.output = 0.0
        self.processValueStabilized = False
        self.setpointReached = False

        # Logger
        self.logger = None
        if (isinstance(logger, logging.Logger)):
            self.logger = logger
            self.logger.info("PID object created")
        elif (isinstance(logger, str)):
            self.logger = logging.getLogger(logger)
            self.logger.info("PID object created")

        self.memManualMode = False
        self.integralLimitReached = False
        self.memIntegralLimitReached = False
        self.outputLimitsReached = False
        self.memoutputLimitsReached = False

        # Simulation
        self.simulation = simulation

    def compute(self, setpoint: float, processValue: float = None, currentTime: float = None) -> float:
        """
        PID calculation execution

        Parameters
        ----------
        setpoint: float
            The target value for the PID

        processValue: float, default = None
            The actual system feedback
            Leave it to `None` when the simulation is used.

        currentTime: float, default = None
            The current time. For simulation purpose only.
            Leave it to `None` for a real application.
        
        Returns
        -------
        float
            Return the PID output (same as `self.output`)
        """
        # Process value
        if processValue is None:
            processValue = self.simulation.output
        
        # Logging mode switching
        if (self.manualMode and not self.memManualMode and isinstance(self.logger, logging.Logger)):
            self.logger.info("PID switched to manual mode")
        elif (not self.manualMode and self.memManualMode and isinstance(self.logger, logging.Logger)):
            self.logger.info("PID switched to automatic mode")
        
        self.memManualMode = self.manualMode
        
        if (currentTime is None):
            actualTime = time.time()
        else:
            actualTime = currentTime
        
        # PID calculation
        if self._startTime is not None and self._lastTime is not None:
            # ===== Delta time =====
            deltaTime = actualTime - self._lastTime

            # Process value stabilization
            if (self.processValueStableLimit is not None):
                if (abs((processValue - self._lastProcessValue) / deltaTime) < self.processValueStableLimit):
                    self._processValueCurrStableTime += deltaTime
                else:
                    self._processValueCurrStableTime = 0.0

                self.processValueStabilized = self._processValueCurrStableTime > self.processValueStableTime
            else:
                self.processValueStabilized = False
                self._processValueCurrStableTime = 0.0

            # ===== Setpoint ramp =====
            if not self._setuptoolControl:
                setpointDiff = setpoint - self._setpoint
                self._setuptoolSetpoint = setpoint
            else:
                setpointDiff = self._setuptoolSetpoint - self._setpoint

            if (self.setpointRamp is not None):
                if (self.setpointRamp > 0.0):
                    if (setpointDiff > self.setpointRamp * deltaTime):
                        setpointDiff = self.setpointRamp * deltaTime
                    elif (setpointDiff < -self.setpointRamp * deltaTime):
                        setpointDiff = -self.setpointRamp * deltaTime
                
            self._setpoint += setpointDiff

            # ===== Error calculation =====
            if self.indirectAction:
                error = processValue - self._setpoint
            else:
                error = self._setpoint - processValue

            # ===== Setpoint reached =====
            if (self.setpointStableLimit is not None):
                if abs(error) < self.setpointStableLimit:
                    self._setpointValueCurrStableTime += deltaTime
                else:
                    self._setpointValueCurrStableTime = 0.0
                
                self.setpointReached = self._setpointValueCurrStableTime > self.setpointStableTime
            else:
                self._setpointValueCurrStableTime = 0.0
                self.setpointReached = False
            
            # ===== Proportionnal part =====
            if (not self.proportionnalOnMeasurement):
                self._p = error * self.kp
            else:
                self._p = -processValue * self.kp

            # ===== Deadband =====
            if (self.deadband is not None):
                if (abs(error) < self.deadband):
                    self._deadbandTime += deltaTime
                else:
                    self._deadbandTime = 0.0
            else:
                self._deadbandTime = 0.0

            # ===== Integral part =====
            if (not self.manualMode and not self.integralFreezing and (self._deadbandTime < self.deadbandActivationTime)):
                self._i += ((error + self._lastError) / 2.0) * deltaTime * self.ki

            # Integral part limitation
            self.integralLimitReached = False

            if self.integralLimit is not None:
                if self._i > self.integralLimit:
                    self._i = self.integralLimit

                    self.integralLimitReached = True
                    
                elif self._i < -self.integralLimit:
                    self._i = -self.integralLimit

                    self.integralLimitReached = True
            
            # Integral limit reached warning message
            if (self.integralLimitReached and not self.memIntegralLimitReached and isinstance(self.logger, logging.Logger)):
                self.logger.warning("Integral part has reached the limit (%d, %d)", -self.integralLimit, self.integralLimit)
            
            self.memIntegralLimitReached = self.integralLimitReached
            
            # ===== Derivative part =====
            if (not self.derivativeOnMeasurement):
                self._d = ((error - self._lastError) / deltaTime) * self.kd
            else:
                self._d = -((processValue - self._lastProcessValue) / deltaTime) * self.kd
            
            # ===== Output =====
            if (not self.manualMode):
                _output = self._p + self._i + self._d

                # Bumpless manual value
                if (self.bumplessSwitching):
                    self.manualValue = _output
            else:
                _output = self.manualValue

            # Output limitation
            self.outputLimitsReached = False

            if self.outputLimits is not None:
                if self.outputLimits[0] is not None:
                    if _output < self.outputLimits[0]:
                        _output = self.outputLimits[0]

                        self.outputLimitsReached = True
                if self.outputLimits[1] is not None:
                    if _output > self.outputLimits[1]:
                        _output = self.outputLimits[1]
                        
                        self.outputLimitsReached = True
            
            # Output limit reached warning message
            if (self.outputLimitsReached and not self.memoutputLimitsReached and isinstance(self.logger, logging.Logger)):
                self.logger.warning("Output limits reached (%d, %d)", self.outputLimits[0], self.outputLimits[1])
            
            self.memoutputLimitsReached = self.outputLimitsReached

            # Interal part equal to output in manual mode
            if (self.manualMode):
                self._i = _output - self._p
            
            # ===== Output =====
            self.output = _output

            # ===== Historian =====
            if self.historian is not None:
                if HistorianParams.P in self.historianParams:
                    self.historian["P"].append(self._p)
                    
                    if len(self.historian["P"]) > self.historianLenght:
                        del self.historian["P"][0]
                
                if HistorianParams.I in self.historianParams:
                    self.historian["I"].append(self._i)
                    
                    if len(self.historian["I"]) > self.historianLenght:
                        del self.historian["I"][0]

                if HistorianParams.D in self.historianParams:
                    self.historian["D"].append(self._d)
                    
                    if len(self.historian["D"]) > self.historianLenght:
                        del self.historian["D"][0]
                
                if HistorianParams.OUTPUT in self.historianParams:
                    self.historian["OUTPUT"].append(self.output)
                    
                    if len(self.historian["OUTPUT"]) > self.historianLenght:
                        del self.historian["OUTPUT"][0]
                
                if HistorianParams.SETPOINT in self.historianParams:
                    self.historian["SETPOINT"].append(self._setpoint)
                    
                    if len(self.historian["SETPOINT"]) > self.historianLenght:
                        del self.historian["SETPOINT"][0]
                
                if HistorianParams.PROCESS_VALUE in self.historianParams:
                    self.historian["PROCESS_VALUE"].append(processValue)
                    
                    if len(self.historian["PROCESS_VALUE"]) > self.historianLenght:
                        del self.historian["PROCESS_VALUE"][0]

                if HistorianParams.ERROR in self.historianParams:
                    self.historian["ERROR"].append(error)
                    
                    if len(self.historian["ERROR"]) > self.historianLenght:
                        del self.historian["ERROR"][0]

                if (HistorianParams.P in self.historianParams) or (HistorianParams.I in self.historianParams) or (HistorianParams.D in self.historianParams) or (HistorianParams.ERROR in self.historianParams) or (HistorianParams.OUTPUT in self.historianParams) or (HistorianParams.PROCESS_VALUE in self.historianParams) or (HistorianParams.SETPOINT in self.historianParams):
                    self.historian["TIME"].append(actualTime - self._startTime)
                    
                    if len(self.historian["TIME"]) > self.historianLenght:
                        del self.historian["TIME"][0]
            
            # ===== Saving data for next execution =====
            self._lastError = error
            self._lastTime = actualTime
            self._lastProcessValue = processValue

            # ===== Simulation =====
            if self.simulation is not None:
                self.simulation(self.output, actualTime)

            return self.output
        else: # First execution
            self._startTime = actualTime
            self._lastTime = actualTime

            self.output = 0.0
            return 0.0

    def __call__(self, setpoint: float, processValue: float = None, currentTime: float = None) -> float:
        """
        call `compute`. Is a code simplification.
        
        Parameters
        ----------
        setpoint: float
            The target value for the PID

        processValue: float, default = None
            The actual system feedback
            Leave it to `None` when the simulation is used.

        currentTime: float, default = None
            The current time. For simulation purpose only.
            Leave it to `None` for a real application.
        
        Returns
        -------
        float
            Return the PID output (same as `self.output`)
        """
        return self.compute(setpoint, processValue, currentTime)

class ThreadedPID(PID, Thread):
    """
    PID controller in a thread. Inherit from `PID` and `threading.Thread`.
    For more information on `threading.Thread` follow this link https://docs.python.org/3/library/threading.html#thread-objects.

    Parameters
    ----------
    kp: float
        Proportionnal gain
    
    ki: float
        Integral gain
    
    kd: float
        Derivative gain
    
    indirectAction: bool, default = False
        Invert PID action. Direct action (False) -> error = setpoint - processValue, Indirect action (True) -> error = processValue - setpoint.
        This option implies that when error is increasing the output is decreasing.
    
    proportionnalOnMeasurement: bool
        Activate proportionnal part calculation on processValue, instead of error.
        This avoid output bump when the setpoint change strongly, but increase stabilization time.
        False -> P = kp * error
        True  -> P = -kp * processValue

    integralLimit: float, default = None
        Limit the integral part. When this value is set to None, the integral part is not limited.
        The integral part is clamped between -`integralLimit` and +`integralLimit`.
    
    derivativeOnMeasurement: bool
        Activate derivative part calculation on processValue, instead of error.
        This avoid output bump when the setpoint change strongly, and there is no repercution on the PID behavior.
        If the processValue change strongly, the derivative part will slow down the processValue.s6
        False -> D = kd * ((error - lastError) / dt)
        True  -> D = -kd * ((processValue - lastProcessValue) / dt)

    setpointRamp: float, default = None
        Determine the maximum variation of the setpoint per second (unit/s).
        If None, no ramps are applied.

    setpointStableLimit: float, default = None
        Determine the maximum difference between the setpoint and the process value (the error) to be considered stable on the setpoint.
        If None, the PID will not be considered stabilized on the setpoint.

    setpointStableTime: float, default = 1.0
        Determine the amount of time (second) which the process value must be stabilized on the setpoint to activate `setpointReached` output.
    
    deadband: float, defaut = None
        Determine the interval ([-`deadband`, `deadband`]) on the error, where the integral part is no longer calculated.
        If None, the deadband is ignored.

    deadbandActivationTime: float, default = 1.0
        Determine the amount of time which the error is in the deadband interval to stop the integral calculation.

    processValueStableLimit: float, default = None
        Determine the maximum variation to be considered stabilized.
        If None, the process value will not be considered stabilized.
    
    processValueStableTime: float, default = 1.0
        Determine the amount of time which the process value must be stabilized to activate `processValueStabilized` output.
    
    historianParams: HistorianParams, default = None
        Configure historian to record some value of the PID. When at least one value is recorded, time is recorded too.
        Possible value :
            - HistorianParams.P : Proportionnal part
            - HistorianParams.I : Integral part
            - HistorianParams.D : Derivative part
            - HistorianParams.ERROR : PID error
            - HistorianParams.SETPOINT : PID setpoint
            - HistorianParams.PROCESS_VALUE : PID process value
            - HistorianParams.OUTPUT : PID output
            
    historianLenght: int, default = 100000
        The maximum lenght of the historian. When the limit is reached, remove the oldest element.
    
    outputLimits: tuple[float, float], default = (None, None)
        Limit the output between a minimum and a maximum (min, max).
        If a limit is set to None, the limit is deactivated.
        If `outputLimit` is set to None, there is no limits.
    
    logger: logging.Logger or str, default = None
        Logging system. `logging.Logger` instance or logger name (str) can be passed.
        If it's anything else (None or other type), the PID will not send any log.

    simulation: Simulation, default = None
        Pass a simulation object to activate simulation.
    
    cycleTime: float, default = 0.0
        Define the minimum time between two PID calculations.
        If this time is lower than the real execution time, there is no pause between execution.
        If `cycleTime` is higher than the real execution time, a pause is made to wait `cycleTime` since the start of the previous execution.

    Attributes
    ----------
    setpoint: float
        The current target value used for the PID calculation.
    
    processValue: float
        The current system feedback used for the PID calculation. For a better PID, update it more faster than the PID execution.
    
    cycleTime: float
        Same as `cycleTime` in parameters section.
    
    quit: bool
        When the threaded PID is started, it can be stopped by setting `quit` to `True`. The PID finish the current execution and stop the thread.
    
    Methods
    -------
    start()
        Used to start the thread.
    """
    def __init__(self, kp: float, ki: float, kd: float, indirectAction: bool = False, proportionnalOnMeasurement: bool = False, integralLimit: float = None, derivativeOnMeasurment: bool = False, setpointRamp: float = None, setpointStableLimit: float = None, setpointStableTime: float = 1.0, deadband: float = None, deadbandActivationTime: float = 1.0, processValueStableLimit: float = None, processValueStableTime: float = 1.0, historianParams: HistorianParams = None, historianLenght: int = 100000, outputLimits: tuple[float, float] = (None, None), logger: logging.Logger = None, simulation: Simulation = None, cycleTime: float = 0.0) -> None:
        PID.__init__(self, kp, ki, kd, indirectAction, proportionnalOnMeasurement, integralLimit, derivativeOnMeasurment, setpointRamp, setpointStableLimit, setpointStableTime, deadband, deadbandActivationTime, processValueStableLimit, processValueStableTime, historianParams, historianLenght, outputLimits, logger, simulation)
        Thread.__init__(self)

        self.setpoint = 0.0
        self.processValue = 0.0
        self.cycleTime = cycleTime

        self.quit = False
    
    def start(self) -> None:
        """
        Used to start the threaded PID. Overrided from `threading.Thread`
        See `threading.Thread` documentation for more information.
        """
        # Call PID execution to initialize time memory
        self.compute(self.setpoint, self.processValue if self.simulation is None else None)
        self.quit = False
        return Thread.start(self)
    
    def run(self):
        """
        Thread execution. Overrided from `threading.Thread`
        See `threading.Thread` documentation for more information
        """
        while self.quit is False:
            while time.time() < (self._lastTime + self.cycleTime):
                time.sleep(self.cycleTime / 100.0)

            self.compute(self.setpoint, self.processValue if self.simulation is None else None)


class Simulation:
    def __init__(self, K: float, tau: float) -> None:
        # System simulation parameters
        self.K = K
        self.tau = tau

        # Internal attributes
        self._lastTime = None

        # Output
        self.output = 0.0
        
    def __call__(self, input: float, t: float = None) -> float:
        if (t is None):
            actualTime = time.time()
        else:
            actualTime = t

        if self._lastTime is not None:
            deltaTime = actualTime - self._lastTime
            self.output += (1.0/self.tau) * ((self.K * input) - self.output) * deltaTime
        
        self._lastTime = actualTime            