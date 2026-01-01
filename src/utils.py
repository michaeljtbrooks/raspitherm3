#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    Raspihome - Utils
    
    Useful functions
"""
import copy
import datetime
import random
from decimal import Decimal, InvalidOperation

import six
from dateutil.relativedelta import relativedelta
import threading
import pigpio
import os
import logging
import subprocess
from time import sleep

import pytz as pytz
from pigpio_dht import DHT11, DHT22
from twisted.web.server import Request

from src.config import NOT_SET, get_current_timezone, DEBUG


logging.basicConfig(format='[%(asctime)s RASPIhome] %(message)s', datefmt='%H:%M:%S', level=logging.INFO)


def D(item="", *args, **kwargs):
    if DEBUG:
        if args or kwargs:
            try:
                item = item.format(*args, **kwargs)
                print(item)
            except IndexError:
                item = "{} {} {}".format(item, args, kwargs)
                print("D_FORMAT_ERROR: {}".format(item))
        logging.debug(item)


def pigpiod_process():
    """
    Checks if the Pigpiod daemon is already running, if not, runs it!!
    """
    cmd='pgrep pigpiod'

    process = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE)
    output, _error = process.communicate()

    if output == '':
        logging.warning('*** [STARTING PIGPIOD] i.e. "sudo pigpiod" ***')
        cmd = 'sudo pigpiod'
        process = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE)
        output, _error = process.communicate()
    else:
        logging.info('PIGPIOD is running! PID: %s' % output.split('\n')[0]) 
    return process


class SmartRequest(Request, object):
    """
    The class for request objects returned by our web server.
        This child version has methods for easily grabbing params safely.
    
        Usage:
            #If you just want the first value
            sunset = request["sunset"]
            sunset = request.get_param("sunset")
            
            #You can even test the water with multiple values, it will stop at the first valid one
            sunset = request.get_param(["sunset","ss","twilight"])
            
            #If you want a whole list of values
            jump = request.get_list("jump")
            
    """
    def get_param_values(self, name, default=None):
        """
        Failsafe way of getting querystring get and post params from the Request object
        If not provided, will return default
        
        @return: ["val1","val2"] LIST of arguments, or the default
        """
        print(self.args)
        try:
            return self.args[name]
        except KeyError:
            name_as_bytestring = bytes(name, encoding="utf-8", errors="ignore")
            try:
                return self.args[name_as_bytestring]
            except KeyError:
                pass
        return default
    get_params = get_param_values #Alias
    get_list = get_param_values #Alias
    get_params_list = get_param_values #Alias
    
    def get_param(self, names, default=None, force=None):
        """
        Failsafe way of getting a single querystring value. Will only return one (the first) value if found
        
        @param names: <str> The name of the param to fetch, or a list of candidate names to try
        @keyword default: The default value to return if we cannot get a valid value
        @keyword force: <type> A class / type to force the output into. Default is returned if we cannot force the value into this type 
        """
        val = NOT_SET
        if isinstance(names, (str, bytes)):
            names = [names]
        for name in names:
            val = self.get_param_values(name=name, default=NOT_SET)
            if val is not NOT_SET:  # Once we find a valid value, continue
                break
        # If we have no valid value, then bail
        if val is NOT_SET:
            return default
        try:
            if len(val) == 1:
                single_val = val[0]
                if force is not None:
                    if force == str:
                        try:
                            return single_val.decode(encoding="utf-8", errors="unicode_escape")
                        except (UnicodeError, AttributeError):
                            return str(single_val)
                    return force(single_val)
                return single_val
            else:
                mult_val = val
                if force is not None:
                    mult_val = [force(ii) for ii in val]
                return mult_val
        except (IndexError, ValueError, TypeError):
            pass
        return default
    get_value = get_param
    param = get_param
    
    def has_params(self, *param_names):
        """
        Returns True or the value if any of the param names given by args exist
        """
        for param_name in param_names:
            try:
                return self.args[param_name] or True
            except KeyError:
                try:
                    return self.args[bytes(param_name, encoding="utf-8", errors="ignore")] or True
                except KeyError:
                    pass
        return False

    def has_param(self, param_name):
        """
        Returns True or the value if the param exists
        """
        return self.has_params(param_name)
    has_key = has_param
    
    def __getitem__(self, name):
        """
        Lazy way of getting a param list, with the fallback default being None 
        """
        return self.get_param(name)


class PiPinInterface(pigpio.pi, object):
    """
    Represents an interface to the pins on ONE Raspberry Pi. This is a lightweight python wrapper around
    pigpio.pi.
    
    Create a new instance for every Raspberry Pi you wish to connect to. Normally we'll stick with one (localhost)
    """
    
    def __init__(self, params):
        super(PiPinInterface, self).__init__(params['pi_host'], params['pig_port'])
    
    def __unicode__(self):
        """
        Says who I am!
        """
        status = "DISCONNECTED"
        if self.connected:
            status = "CONNECTED!"
        return "RaspberryPi Pins @ {ipv4}:{port}... {status}".format(ipv4=self._host, port=self._port, status=status)
    
    def __repr__(self):
        return str(self.__unicode__())

    def get_port(self):
        """
        :return: port number
        """
        return self._port

    def add_supplementary_pin_interface(self, pin_id=None, name=None, interface_class=None, *args, **kwargs):
        """
        Adds the supplementary interface to this instance object. Useful for when using other libraries to add
        stuff in
        """
        if interface_class is None:
            logging.warning('PiPinInterface.add_supplementary_pin_interface(): No pin_id provided. Interface ignored.')
            return None
        if name is None:
            name = str(interface_class.__name__).lower()
        supplementary_interface = interface_class(pin_id, *args, **kwargs)
        setattr(self, name, supplementary_interface)
        return supplementary_interface


class TemperatureHumiditySensor(object):
    """
    Binds a temperature/humidity sensor
    Uses DHTXX class, which is an interface to pigpio.pi(). pigpio_interface keyword allows us to reuse objects.
    """
    iface_class = DHT11
    iface = None
    pigpio_interface = None
    gpio_pin = 20
    sensor_power_pin = None
    mode = 11
    lockout_secs = 10
    async_read_thread = None
    async_reset_thread = None
    last_data = None
    last_query_time = None
    n_timeouts_since_last_successful_read = 0
    MAX_BELIEVABLE_CHANGE_IN_TEMPERATURE_PER_MINUTE = Decimal("6.5")  # Absolute change. i.e. +/-6.5 degrees per minute either way will count.

    def __init__(self, gpio=gpio_pin, mode=mode, pigpio_interface=None, sensor_power_pin=None, *args, **kwargs):
        """
        Bind the correct interface
        :param gpio: The pin this sensor is available on
        :param mode: The mode we're in (either DHT11 or DHT22)
        :param pigpio_interface: <Pigpio> Reuse this Pigpio interface if desired
        :param sensor_power_pin: <int> If set, is the pin which turns on and off the DHT sensor's power
                                 used to reset the thing if it misbehaves
        """
        self.mode = mode
        if mode in (1, 11, "1", "11", "DHT11"):
            self.iface_class = DHT11
            self.lockout_secs = 10
        else:
            self.iface_class = DHT22
            self.lockout_secs = 5
        self.gpio_pin = gpio
        self.sensor_power_pin = sensor_power_pin or self.sensor_power_pin
        self.pigpio_interface = pigpio_interface

    def get_mode_str(self):
        """
        States what sensor we're using
        """
        return self.iface_class.__name__

    def __repr__(self):
        """
        Say what this is
        """
        return "{} @ pin #{}".format(self.get_mode_str(), self.gpio_pin)

    def get_interface(self):
        """
        Gets the active interface or sets a new one
        """
        if self.iface is None:
            self.iface = self.generate_interface(gpio=self.gpio_pin)
        return self.iface

    def generate_interface(self, gpio=None, pigpio_interface=None):
        """
        Generates a new interface based upon the iface class
        """
        if gpio is None:
            gpio = self.gpio_pin
        print("get_interface: gpio_pin=%s" % self.gpio_pin)
        if not self.gpio_pin and DEBUG:  # We can emulate this in DEBUG mode now
            self.iface = "EMULATED"
            return self.iface
        if pigpio_interface is None:
            pigpio_interface = self.pigpio_interface
        self.iface = self.iface_class(gpio=gpio, pi=pigpio_interface)
        print("\tTemperature/Humidity {} sensor added on pin {}.".format(self.iface_class.__name__, gpio))
        return self.iface

    def check_data_just_read_is_realistic(self, data_just_read, read_datetime):
        """
        Calculate the delta-T and if it's clearly bonkers, suppress the read.
        """
        read_datetime = read_datetime or datetime.datetime.now()
        try:
            latest_temperature = Decimal(data_just_read.get("temp_c"))
        except (AttributeError, KeyError, ValueError, TypeError):
            # If there is no latest data, then it ain't real.
            return False
        try:
            previous_temperature = Decimal(self.last_data["temp_c"])
            previous_query_timestamp = self.last_data["query_timestamp"]
        except (AttributeError, KeyError, ValueError, TypeError):
            # If there is no prior data, but there is current data, then believe it
            return True
        # Calculate delta:
        try:
            time_interval_timedelta = read_datetime - previous_query_timestamp
            time_interval_seconds = Decimal(time_interval_timedelta.total_seconds() or 1)
            delta_t = latest_temperature - previous_temperature
            delta_t_per_minute = Decimal(delta_t) / (time_interval_seconds / Decimal("60"))
            # Only believe temperature swings of less than +/-6.5 degrees C per minute.
            if abs(delta_t_per_minute) > abs(Decimal(self.MAX_BELIEVABLE_CHANGE_IN_TEMPERATURE_PER_MINUTE)):
                return False
        except (ValueError, TypeError, AttributeError, InvalidOperation) as e:
            logging.exception("Unable to calculate the delta-t: %s", e)
        return True  # Assume all good

    def read(self, iface=None, delay=0.0):
        """
        Attempts to get the temperature

        BLOCKING

        :param iface: The interface class instance. Required when calling read() in threads. Otherwise fetches from self.
        :param delay: <float> how many seconds to pause before actually trying to read the sensor
        """
        now = datetime.datetime.now()
        query_again = True
        if self.last_query_time:
            queried_ago_td = now - self.last_query_time
            if queried_ago_td.seconds < self.lockout_secs:
                query_again = False
        if iface is None:  # Necessary workaround to stop threads from spinning up another interface
            iface = self.get_interface()
        if query_again:
            if delay:
                sleep(delay)

            # In development mode, if no pin set, then return a randomly walking humidity / temperature
            if not self.gpio_pin and DEBUG:
                print("DEBUG mode, and no pin set, emulating read...")
                latest_temp_humidity = self._development_emulate_sensor_read()
            else:
                # Otherwise actually attempt to read the sensor
                try:
                    latest_temp_humidity = iface.read(retries=3)  # Blocking!!
                except TimeoutError:
                    logging.warning("{}.read(): Sensor timeout, pin {}! Reset power pin {}".format(self.__class__.__name__, self.gpio_pin, self.sensor_power_pin))
                    self.n_timeouts_since_last_successful_read += 1
                    if self.n_timeouts_since_last_successful_read >= 16:
                        logging.warning("Too many sensor timeouts. I give up!")
                        self.last_data = {}
                        return self.last_data
                    elif self.n_timeouts_since_last_successful_read >= 2 and self.sensor_power_pin:
                        logging.info("Temperature sensor has crashed... Resetting via pin %s!" % self.sensor_power_pin)
                        self.reset_sensor(iface=iface)  # Blocking
                        # After a reset, let's try to read it again...
                        try:
                            latest_temp_humidity = iface.read(retries=2)  # Blocking!!
                        except TimeoutError:
                            logging.warning("Last reset attempt appeared to be unsuccessful.")
                            return self.last_data or {}
                    else:
                        return self.last_data or {}
            if latest_temp_humidity.get("valid"):  # Only return a value if it is valid!
                self.last_query_time = now  # We have successfully polled it here. We don't want to hammer the sensor, even if it spat out bollocks.
                # Bail if it's clearly not a sensible temperature.
                if not self.check_data_just_read_is_realistic(data_just_read=latest_temp_humidity, read_datetime=now):
                    logging.warning("Latest temperature (%s) is likely to be nonsense. Ignoring it.", latest_temp_humidity.get("temp_c", "?"))
                    self.n_timeouts_since_last_successful_read += 1  # Treat as a failing sensor.
                    return self.last_data or {}
                self.n_timeouts_since_last_successful_read = 0
                self.last_data = latest_temp_humidity or {}
                self.last_data["query_timestamp"] = now
                print(latest_temp_humidity)
                return self.last_data
        return self.last_data

    def reset_sensor(self, iface=None):
        """
        Kills power to the sensor, reinstates power, thus resetting it.

        BLOCKING

        :param iface: The interface class instance. Required when calling read() in threads. Otherwise fetches from self.
        """
        # Only perform a reset if there is a sensor power pin
        if not self.sensor_power_pin:
            print("\treset_sensor(): There is no reset pin configured. Ignoring reset request.")
            return None

        print("\tPowering sensor off for 20 seconds...")
        self.pigpio_interface.write(self.sensor_power_pin, pigpio.OFF)  # Off you go, twat.
        sleep(20)  # Enough time to let capacitors discharge
        print("\tPowering sensor back on...")
        self.pigpio_interface.write(self.sensor_power_pin, pigpio.ON)  # Back on
        print("\tPause for 5 seconds to let it initialise...")
        sleep(5)  # Enough time to let the temperature sensor initialise
        return True

    def _development_emulate_sensor_read(self):
        """
        Emulates reading the sensor for the purposes of development
        """
        last_data = self.read_last_result()
        try:
            last_temp = Decimal(last_data.get("temp_c", 20.0))
            new_temp = last_temp + Decimal(random.randint(-20, 20)) / Decimal("10.0")  # Walk it a little bit
        except (TypeError, ValueError):
            new_temp = Decimal("20.0")
        try:
            last_humidity = Decimal(last_data.get("humidity", 50.0))
            new_humidity = last_humidity + Decimal(random.randint(-50, 50)) / Decimal("10.0") # Walk it a little bit
        except (TypeError, ValueError):
            new_humidity = Decimal("50.0")
        return {
            "temp_c": six.u("{}".format(new_temp)),
            "humidity": six.u("{}".format(new_humidity)),
            "valid": 1  # Pretend this is real
        }

    def read_last_result(self):
        """
        Read the last result without re-querying the sensor ever
        """
        return self.last_data or {}

    def read_non_blocking(self, delay=0.0):
        """
        Attempts to read the sensor, updates self.last_data without blocking.
        :param delay: <float> how many seconds to pause before actually trying to read the sensor
        """
        async_thread_is_running = False
        if self.async_read_thread and self.async_read_thread.is_alive():
            async_thread_is_running = True
        if not async_thread_is_running:
            self.async_read_thread = threading.Thread(target=self.read, kwargs={"iface": self.iface, "delay": delay})
            self.async_read_thread.start()
            return True
        else:
            print("\tread_non_blocking(): A read is already taking place. Ignoring duplicate call.")
            return None

    read_async = read_non_blocking  # alias

    def get_temp_c(self):
        data = self.read()
        return data.get("temp_c", None)

    @property
    def temp_c(self):
        return self.get_temp_c()

    @property
    def temperature(self):
        return self.get_temp_c()

    @property
    def temp(self):
        return self.get_temp_c()

    def get_humidity(self):
        data = self.read()
        return data.get("humidity", None)

    @property
    def humidity(self):
        return self.get_humidity()

    def __bool__(self):
        return bool(self.iface)

    def teardown(self):
        """
        Tear down any async threads here.
        """
        if self.async_read_thread:
            self.async_read_thread.join(timeout=3.0)
        if self.async_reset_thread:
            self.async_reset_thread.join(timeout=2.0)


class WaterTemperatureSensor(object):
    """
    Represents a single-wire water temperature sensor (e.g. DS18B20).
    Uses the kernel w1 device interface, and holds on to the last believable value.
    """
    base_dir = "/sys/bus/w1/devices"
    device_prefix = "28-"
    MAX_BELIEVABLE_CHANGE_IN_TEMPERATURE_PER_MINUTE = Decimal("13.0")  # Very rapid changes get ignored. This sensor is much less noisy compared to DHT11 so we can be less restrictive.

    def __init__(self, gpio_pin=0):
        self.gpio_pin = gpio_pin
        self.device_path = None
        self.last_data = {}
        self.last_query_time = None
        self.detect_sensor()

    def detect_sensor(self):
        """
        Locates a DS18B20-compatible device exposed via the w1 kernel interface.
        """
        if not os.path.isdir(self.base_dir):
            logging.debug("WaterTemperatureSensor.detect_sensor(): no w1 devices directory %s", self.base_dir)
            return None
        try:
            device_dirs = [d for d in os.listdir(self.base_dir) if d.startswith(self.device_prefix)]
        except OSError as e:
            logging.warning("WaterTemperatureSensor.detect_sensor(): unable to list w1 devices: %s", e)
            return None
        for device_dir in device_dirs:
            candidate_path = os.path.join(self.base_dir, device_dir)
            temperature_file = os.path.join(candidate_path, "temperature")
            legacy_file = os.path.join(candidate_path, "w1_slave")
            if os.path.exists(temperature_file) or os.path.exists(legacy_file):
                self.device_path = candidate_path
                return self.device_path
        return None

    def _read_raw_temperature(self):
        """
        Reads the raw temperature in degrees Celsius from the w1 device files.
        """
        if not self.device_path:
            self.detect_sensor()
        if not self.device_path:
            return None
        temperature_file = os.path.join(self.device_path, "temperature")
        legacy_file = os.path.join(self.device_path, "w1_slave")
        try:
            if os.path.exists(temperature_file):
                with open(temperature_file, "r") as fh:
                    raw_str = fh.read().strip()
                temp_c = Decimal(raw_str) / Decimal("1000")
            else:
                with open(legacy_file, "r") as fh:
                    lines = fh.readlines()
                if len(lines) < 2 or "YES" not in lines[0]:
                    return None
                parts = lines[1].strip().split("t=")
                if len(parts) < 2:
                    return None
                temp_c = Decimal(parts[1]) / Decimal("1000")
        except (OSError, ValueError, InvalidOperation) as e:
            logging.warning("WaterTemperatureSensor._read_raw_temperature(): unable to read: %s", e)
            return None
        return temp_c

    def check_data_just_read_is_realistic(self, data_just_read, read_datetime):
        """
        Suppresses implausible readings (huge swings in very short time).
        """
        read_datetime = read_datetime or datetime.datetime.now()
        try:
            latest_temperature = Decimal(data_just_read.get("temp_c"))
        except (AttributeError, KeyError, ValueError, TypeError):
            return False
        try:
            previous_temperature = Decimal(self.last_data["temp_c"])
            previous_query_timestamp = self.last_data["query_timestamp"]
        except (AttributeError, KeyError, ValueError, TypeError):
            return True
        try:
            time_interval_timedelta = read_datetime - previous_query_timestamp
            time_interval_seconds = Decimal(time_interval_timedelta.total_seconds() or 1)
            delta_t = latest_temperature - previous_temperature
            delta_t_per_minute = Decimal(delta_t) / (time_interval_seconds / Decimal("60"))
            if abs(delta_t_per_minute) > abs(Decimal(self.MAX_BELIEVABLE_CHANGE_IN_TEMPERATURE_PER_MINUTE)):
                return False
        except (ValueError, TypeError, AttributeError, InvalidOperation) as e:
            logging.exception("WaterTemperatureSensor unable to calculate delta-t: %s", e)
        return True

    def read(self):
        """
        Reads the current water temperature, returning the latest believable value.
        """
        now = datetime.datetime.now()
        temp_c = self._read_raw_temperature()
        if temp_c is None:
            return self.last_data or {}
        latest_data = {
            "temp_c": temp_c,
            "temp_f": (temp_c * Decimal("9") / Decimal("5")) + Decimal("32"),
            "valid": True,
            "query_timestamp": now,
            "source_pin": self.gpio_pin
        }
        if not self.check_data_just_read_is_realistic(latest_data, read_datetime=now):
            logging.warning("Latest water temperature (%s) is likely to be nonsense. Ignoring it.", latest_data.get("temp_c", "?"))
            return self.last_data or {}
        self.last_data = latest_data
        self.last_query_time = now
        return self.last_data

    def read_last_result(self):
        """
        Returns the last known result without polling the sensor.
        """
        return self.last_data or {}

    def __bool__(self):
        return bool(self.device_path or self.gpio_pin)

    def teardown(self):
        # Nothing to tear down for w1 sensors, but kept for parity.
        return True


class BaseRaspiHomeDevice(object):
    """
    A base class for building subclasses to control devices from a Raspberry pi
    """
    iface = None
    emulated_readable_pins = None
    
    def __init__(self, registry=None, emulated_readable_pins=None, *args, **kwargs):
        """
        Ensure we have a registry to store data
        """
        super(BaseRaspiHomeDevice, self).__init__(*args, **kwargs)
        if registry is None:
            self.__class__.registry = {}
            registry = self.__class__.registry
        self.registry = registry
        if DEBUG and emulated_readable_pins is None:
            emulated_readable_pins = {}
        self.emulated_readable_pins = emulated_readable_pins
    
    def write(self, pin, value=0):
        """
        Sets the pin to the specified value. Fails safely.
        
        @param pin: <int> The pin to change
        @param value: <int> The value to set it to
        """
        if self.iface.connected:
            try:
                self.iface.write(pin, value)
            except (AttributeError, IOError):
                logging.error("ERROR: Cannot output to pins. Value of pin #%s would be %s" % (pin,value))
        else:
            logging.error("ERROR: Interface not connected. Cannot output to pins. Value of pin #%s would be %s" % (pin, value))
            if DEBUG:  # Emulate for debug
                self.emulated_readable_pins[pin] = value
        return value
    
    def read(self, pin):
        """
        Reads a current pin value
        
        @param pin: <int> The pin to read 
        """
        value = 0 #Default to nowt
        if self.iface.connected:
            try:
                value = self.iface.read(pin)
            except (AttributeError, IOError, pigpio.error):
                logging.error("ERROR: Cannot read value of pin #%s" % (pin,))
            else:
                if DEBUG:  # If we have had a successful read, update the emulated data too
                    self.emulated_readable_pins[pin] = value
        else:
            logging.error("ERROR: Interface not connected. Cannot read value of pin #%s." % (pin,))
            if DEBUG:  # Simulate the correct value if reading pin has failed.
                try:
                    return self.emulated_readable_pins[pin]
                except KeyError:  # TypeErrors occur when the emulated dict isn't passed in
                    pass
        return value
    
    def pulse_on(self, pin, duration_ms=100):
        """
        Pulses the given pin on for a short period.
        NB: This is BLOCKING for the duration. Run in a thread if the duration is long.
        
        @param pin: <int> The pin to change
        @param duration_ms: <int> How long the pulse should be in ms
        """
        self.write(pin, 1)
        sleep(duration_ms/1000.0)
        self.write(pin, 0)
        return duration_ms
    
    def pulse_if_different(self, current=None, intended=None, output_pin=None, duration_ms=100):
        """
        Pulses the given pin only if the current and intended values are different in the boolean sense
        i.e. if current XOR intended, send pulse
        """
        if current is None or intended is None or output_pin is None:
            logging.error("ERROR - pulse_if_different(): All parameters must be provided and not None. current={} intended={} output_pin={}".format(current, intended, output_pin))
        if bool(current) ^ bool(intended):
            self.pulse_on(output_pin, duration_ms)
    
    def get_or_build_interface(self, config=None, interface=None, *args, **kwargs):
        """
        Resolves the Pigpio interface or builds one if not already existing
        
        @keyword config: dict of configuration settings, e.g.
            {
                'pi_host'     : 'localhost', #The web server host we're talking to
                'pig_port'    : 8888,    #The Pigpio port
            }
        """
        #Resolve interface - create if not provided!
        need_to_generate_new_interface = False #Flag to see what we're doing
        
        pi_host = config.get("pi_host", kwargs.get("pi_host", "localhost"))
        pig_port = config.get("pig_port", kwargs.get("pig_port", 8888))
        
        if interface is None: 
            need_to_generate_new_interface = True
        else: #Check the interface is connected!
            try:
                iface_host = interface._host
            except AttributeError:
                iface_host = None
            if iface_host is None:
                need_to_generate_new_interface = True
                logging.info("No existing iface host")
            elif pi_host and str(pi_host) != str(iface_host):
                need_to_generate_new_interface = True
                logging.info("iface host different to intended: iface=%s vs pi=%s" % (iface_host, pi_host))
            try:
                iface_port = interface.get_port()
            except AttributeError:
                iface_port = None
            if iface_port is None:
                need_to_generate_new_interface = True
            elif pig_port and str(pig_port) != str(iface_port):
                need_to_generate_new_interface = True
                logging.info("iface port different to intended: iface=%s vs pi=%s" % (iface_port, pig_port))
            try:
                iface_connected = interface.connected
            except AttributeError:
                iface_connected = False
            if not iface_connected:
                logging.info("iface not connected!")
                need_to_generate_new_interface = True
        if need_to_generate_new_interface:
            iface_params = copy.copy(config)
            iface_params["pi_host"] = pi_host
            iface_params["pig_port"] = pig_port
            self.iface = self.generate_new_interface(iface_params)
        else:
            self.iface = interface
        return self.iface
    
    def generate_new_interface(self, params):
        """
        Builds a new interface, stores it in self.iface
        """
        #Kill existing iface
        try:
            self.iface.stop()
        except (AttributeError, IOError):
            pass
        self.iface = PiPinInterface(params)
        return self.iface

    def get_data(self, key, default=NOT_SET):
        """
        Pulls a certain piece of data from the registry, uses copy() to prevent changing data if pulling mutable types.
        """
        try:
            item = self.registry[key]
        except KeyError:
            return copy.copy(default)
        return copy.copy(item)

    def __getitem__(self, key):
        item = self.get_data(key)
        if item is NOT_SET:
            raise KeyError("{} not found in data registry.".format(key))
        return item

    def set_data(self, key, value):
        """
        Sets an item in the registry. Will be frozen in time thanks to copy()
        """
        self.registry[key] = copy.copy(value)

    def __setitem__(self, key, value):
        self.set_data(key, value)


class ProgrammeScheduleEvent(object):
    """
    One particular scheduled event
    """
    when_weekday = None  # Int
    when_time_start = None  # Time
    when_time_end = None  # Time
    when_timezone = get_current_timezone()  # Tzinfo
    what_action = None  # str
    what_action_status = None  # dict of data
    _day_names = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')

    def __init__(self, day=None, start=None, end=None, timezone=None, action=None, action_status=None, **kwargs):
        if day is None:  # Day might be int 0
            day = kwargs.get("weekday", None)
        self.when_weekday = self.parse_day(day)  # Handles strings and ints
        self.when_time_start = self.parse_time(start or kwargs.get("time_start", None))
        self.when_time_end = self.parse_time(end or kwargs.get("time_end", None))
        self.when_timezone = self.get_timezone_from_expression(timezone or kwargs.get("tz", "local"))
        self.what_action = action
        self.what_action_status = copy.copy(action_status)  # The data you'll send it

    def __str__(self):
        day_part = self._day_names[self.when_weekday]
        try:
            start_part = self.when_time_start.strftime("%H:%M")
        except (AttributeError, TypeError, ValueError):MAX_BELIEVABLE_CHANGE_IN_TEMPERATURE_PER_MINUTE
            start_part = ""
        try:
            end_part = self.when_time_end.strftime("%H:%M")
        except (AttributeError, TypeError, ValueError):
            end_part = ""
        return "{} {}-{}: {}={}".format(day_part, start_part, end_part, self.what_action, self.what_action_status)

    def __repr__(self):
        return self.__str__()

    def is_scheduled_for_now(self):
        """
        Determine if this rule should be active.
        """
        now = self.local_now()

        # If we're on a different day of the week, then
        if self.when_weekday is not None:
            D("when={} now={}", self.when_weekday, now.weekday())
            if now.weekday() != self.when_weekday:
                return False

        start_time_applied_to_today, end_time_applied_to_today = self.get_start_and_end_times_applied_to_today(now)

        if now < start_time_applied_to_today:
            return False
        if now > end_time_applied_to_today:
            return False
        return True

    def get_start_time_applied_to_today(self, now=None):
        """
        Get the start timestamp as though it were today
        """
        if now is None:
            now = self.local_now()
        if self.when_time_start:
            start_time_applied_to_today = datetime.datetime.combine(now.date(), self.when_time_start, tzinfo=self.when_timezone)
        else:
            start_time_applied_to_today = datetime.datetime.combine(now.date(), datetime.time(0, 0, 0), tzinfo=self.when_timezone)
        return start_time_applied_to_today

    def get_end_time_applied_to_today(self, now=None):
        """
        Get the end timestamp as though it were today
        """
        if now is None:
            now = self.local_now()
        if self.when_time_end:
            end_time_applied_to_today = datetime.datetime.combine(now.date(), self.when_time_end, tzinfo=self.when_timezone)
        else:
            end_time_applied_to_today = datetime.datetime.combine(now.date(), datetime.time(23, 59, 59, 999999), tzinfo=self.when_timezone)
        return end_time_applied_to_today

    def get_start_and_end_times_applied_to_today(self, now=None):
        """
        Gets the start and end times as though they were applied to now. Corrects for
        end times spanning midnight.
        """
        if now is None:
            now = self.local_now()
        start_time_applied_to_today = self.get_start_time_applied_to_today(now)
        end_time_applied_to_today = self.get_end_time_applied_to_today(now)
        if end_time_applied_to_today < start_time_applied_to_today:
            end_time_applied_to_today = end_time_applied_to_today + relativedelta(days=1)
        return start_time_applied_to_today, end_time_applied_to_today

    def next_start_and_end(self):
        """
        Determines if you are currently within the rule or not
        """
        now = self.local_now()
        start_time_applied_to_today, end_time_applied_to_today = self.get_start_and_end_times_applied_to_today(now)
        if self.is_scheduled_for_now():
            return start_time_applied_to_today, end_time_applied_to_today

        # Otherwise, assume now is the next day upon when the designated day of the week falls
        if self.when_weekday:
            next_start = start_time_applied_to_today + relativedelta(weekday=self.when_weekday)
            next_start, next_end = self.get_start_and_end_times_applied_to_today(next_start)
            return next_start, next_end

        # We shouldn't reach here
        return start_time_applied_to_today, end_time_applied_to_today

    @classmethod
    def utc_now(cls):
        return datetime.datetime.now(tz=pytz.utc)

    @classmethod
    def local_now(cls):
        local_timezone = get_current_timezone()
        return datetime.datetime.now(tz=local_timezone)

    @classmethod
    def convert_to_timezone(cls, dt=None, tz="local"):
        """
        Cast the datetime into localtime
        """
        target_timezone = cls.get_timezone_from_expression(tz)
        if dt is None:
            dt = datetime.datetime.now(tz=pytz.utc)
        try:
            try:
                return target_timezone.localize(dt)
            except ValueError:  # Occurs when the dt already has a tz set
                return target_timezone.normalize(dt)
        except AttributeError:
            return dt.astimezone(target_timezone)

    @classmethod
    def localtime(cls, dt=None):
        return cls.convert_to_timezone(dt=dt, tz="local")

    @classmethod
    def utctime(cls, dt=None):
        return cls.convert_to_timezone(dt=dt, tz="utc")

    @classmethod
    def strptime_formats(cls, dt_expression=None, *args, **kwargs):
        """
        Try to turn a string into dt using a variety of formats before bailing out

        :param dt_expression: <str> The expression
        :param args: Formats to try
        """
        if dt_expression is None:
            return None
        for format_to_try in args:
            try:
                return datetime.datetime.strptime(dt_expression, format_to_try)  # Mon, Tue etc
            except (TypeError, ValueError):
                pass
        return None

    @classmethod
    def parse_day(cls, day):
        """
        Convert a day expression into a python day
        """
        if day is None:
            return None
        # Assume an int
        try:
            day = int(day) % 7
            return day
        except (TypeError, ValueError):
            pass
        # Try a short day:
        try:
            return datetime.datetime.strptime(day, "%a").day  # Mon, Tue etc
        except (TypeError, ValueError):
            pass
        # Try a long day:
        try:
            return datetime.datetime.strptime(day, "%A").day  # Monday, Tuesday etc
        except (TypeError, ValueError):
            pass
        return None

    @classmethod
    def parse_time(cls, time_expression):
        """
        Convert time expression into hour + minutes as time object
        """
        return cls.strptime_formats(time_expression, "%H:%M", "%H%M", "%I:%M%p", "%I%M%p", "%I%p", "%H").time()

    @classmethod
    def get_timezone_from_expression(cls, tz_expression):
        """
        Returns a timezone object based upon the thing you ask for
        :param tz_expression: <str> or timezone
        :return:
        """
        if isinstance(tz_expression, (pytz.tzinfo.tzinfo,)):
            return tz_expression
        if str(tz_expression).lower() == u"local" or tz_expression in (True, 1, "true", "True", u"true", u"True"):  # Means they want the local timezone
            target_tz = get_current_timezone()  # Local according to config settings
        elif str(tz_expression).lower() == u"utc":  # UTC!
            target_tz = pytz.utc
        else:  # Ask pytz what timezone it things it is
            target_tz = pytz.timezone(tz_expression)
        return target_tz


class ProgrammeScheduleMode(object):
    """
    Mode which allows you to specify when heating should be on and hot water should be on etc.
    """
    name = None
    events = None


def get_matching_pids(name, exclude_self=True):
    """
    Checks the process ID of the specified processes matching name, having excluded itself
    
        check_output(["pidof", str]) will return a space delimited list of all process ids
        
    @param name: <str> The process name to search for
    @keyword exclude_self: <Bool> Whether to remove own ID from returned list (e.g. if searching for a python script!) 
    
    @return: <list [<str>,]> List of PIDs 
    """
    # Get all matching PIDs
    try:
        pids_str = subprocess.check_output(["pidof", name])
    except subprocess.CalledProcessError:  # No matches
        pids_str = ""
    # Process string-list into python list
    pids = pids_str.strip().split(" ")
    # Remove self if required:
    if exclude_self:
        my_pid = str(os.getpid())  # Own PID - getpid() returns integer
        try:
            pids.remove(my_pid)  # Remove my PID string:
        except ValueError:
            pass
    return pids
