#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    Raspihome - Utils
    
    Useful functions
"""
import datetime

import pigpio
import os
import logging
import subprocess
from time import sleep

from pigpio_dht import DHT11, DHT22
from twisted.web.server import Request


logging.basicConfig(format='[%(asctime)s RASPIhome] %(message)s', datefmt='%H:%M:%S',level=logging.INFO)


def odict2int(ordered_dict):
    """
    Converts an OrderedDict with unicode values to integers (port and pins).
    @param ordered_dict: <OrderedDict> containg RASPILED configuration.

    @returns: <OrderedDict> with integers instead of unicode values.
    """
    for key, value in list(ordered_dict.items()):
        try:
            ordered_dict[key] = int(value)
        except ValueError:
            ordered_dict[key] = value
    return ordered_dict


def pigpiod_process():
    """
    Checks if the Pigpiod daemon is already running, if not, runs it!!
    """
    cmd='pgrep pigpiod'

    process = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE)
    output, _error = process.communicate()

    if output=='':
        logging.warning('*** [STARTING PIGPIOD] i.e. "sudo pigpiod" ***')
        cmd='sudo pigpiod'
        process = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE)
        output, _error = process.communicate()
    else:
        logging.info('PIGPIOD is running! PID: %s' % output.split('\n')[0]) 
    return process


class NotSet():
    pass
NOT_SET = NotSet()


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
    mode = 11
    lockout_secs = 10
    last_data = None
    last_query_time = None

    def __init__(self, gpio=gpio_pin, mode=mode, pigpio_interface=None, *args, **kwargs):
        """
        Bind the correct interface
        :param gpio: The pin this sensor is available on
        :param mode: The mode we're in (either DHT11 or DHT22)
        :param pigpio_interface: <Pigpio> Reuse this Pigpio interface if desired
        """
        self.mode = mode
        if mode in (1, 11, "1", "11", "DHT11"):
            self.iface_class = DHT11
            self.lockout_secs = 10
        else:
            self.iface_class = DHT22
            self.lockout_secs = 5
        self.gpio_pin = gpio
        self.pigpio_interface = pigpio_interface

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
        if pigpio_interface is None:
            pigpio_interface = self.pigpio_interface
        self.iface = self.iface_class(gpio=gpio, pi=pigpio_interface)
        print("\tTemperature/Humidity {} sensor added on pin {}.".format(self.iface_class.__name__, gpio))
        return self.iface

    def read(self):
        """
        Attempts to get the temperature
        """
        now = datetime.datetime.now()
        query_again = True
        if self.last_query_time:
            queried_ago_td = now - self.last_query_time
            if queried_ago_td.seconds < self.lockout_secs:
                query_again = False
        iface = self.get_interface()
        if query_again:
            try:
                latest_temp_humidity = iface.read()  # Blocking!!
            except TimeoutError:
                logging.warning("{}.read(): Sensor timeout, pin {}!".format(self.__class__.__name__, self.gpio_pin))
                return self.last_data or {}
            if latest_temp_humidity.get("valid"):  # Only return a value if it is valid!
                self.last_data = latest_temp_humidity or {}
                self.last_data["query_timestamp"] = now
                self.last_query_time = now
                return self.last_data
        return self.last_data

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


class BaseRaspiHomeDevice(object):
    """
    A base class for building subclasses to control devices from a Raspberry pi
    """
    iface = None
    
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
            logging.error("ERROR: Interface not connected. Cannot output to pins. Value of pin #%s would be %s" % (pin,value))
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
            logging.error("ERROR: Interface not connected. Cannot read value of pin #%s." % (pin,))
        return value
    
    def pulse_on(self, pin, duration_ms=100):
        """
        Pulses the given pin on for a short period.
        NB: This is BLOCKING for the duration. Run in a thread if the duration is long.
        
        @param pin: <int> The pin to change
        @keyword duration: <int> How long the pulse should be in ms
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
            self.iface = self.generate_new_interface(config)
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
        pids_str = subprocess.check_output(["pidof",name])
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
