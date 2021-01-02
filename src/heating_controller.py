#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
    Raspitherm - Controller
    
    GPIO 22    Input    Detect hot water state
    GPIO 27    Input    Detect central heating state
    GPIO 5     Output   Toggle hot water
    GPIO 26    Output   Toggle central heating

    The actual Raspberry Pi controller class wrapper
"""

import logging
import pigpio
from time import sleep

from pigpio_dht import DHT11, DHT22

from utils import BaseRaspiHomeDevice, TemperatureHumiditySensor

logging.basicConfig(format='[%(asctime)s RASPITHERM] %(message)s', datefmt='%H:%M:%S',level=logging.INFO)


class HeatingController(BaseRaspiHomeDevice):
    """
    Represents a heating programmer
    """
    # Runtime vars
    hw = 0  # Current status of hot water
    ch = 0  # Current status of central heating
    th = None  # Current temp and humidity
    iface = None  # General Pigpio interface
    iface_temp_humid = None  # Humidity temperature sensor interface  (could expand this into multiples in future)

    # Pins
    _HW_TOGGLE_PIN = 5 
    _CH_TOGGLE_PIN = 26
    _HW_STATUS_PIN = 22
    _CH_STATUS_PIN = 27
    _TH_SENSOR_PIN = None  # Temperature humidity sensor pin
    _TH_SENSOR_TYPE = "DHT11"  # Temperature humidity sensor type (DHT11 or DHT22)
    _PULSE_DURATION_MS = 200  # How long a toggle pulse should be (milliseconds)
    _RELAY_DELAY_MS = 200  # How long to wait before rechecking the status after a toggle (enough time for relay to switch) 
    
    def __init__(self, config, interface=None):
        """
        Sets this up
        """
        self.iface = self.get_or_build_interface(config=config, interface=interface)
        
        # Outputs
        self._HW_TOGGLE_PIN = config.get("hw_toggle_pin", self._HW_TOGGLE_PIN)
        self._CH_TOGGLE_PIN = config.get("ch_toggle_pin", self._CH_TOGGLE_PIN)
        self._PULSE_DURATION_MS = config.get("pulse_duration_ms", self._PULSE_DURATION_MS)
        
        # Inputs
        self._HW_STATUS_PIN = config.get("hw_status_pin", self._HW_STATUS_PIN)
        self._CH_STATUS_PIN = config.get("ch_status_pin", self._CH_STATUS_PIN)
        self._TH_SENSOR_PIN = config.get("th_sensor_pin", self._TH_SENSOR_PIN)
        self._TH_SENSOR_TYPE = config.get("th_sensor_type", self._TH_SENSOR_TYPE)
        
        # Configure pins (we are using hardware pull-down resistors, so turn the internals off):
        if self.iface.connected:
            try:
                self.iface.set_mode(self._HW_TOGGLE_PIN, pigpio.OUTPUT)
                self.iface.set_mode(self._CH_TOGGLE_PIN, pigpio.OUTPUT)
                self.iface.set_mode(self._HW_STATUS_PIN, pigpio.INPUT)
                self.iface.set_mode(self._CH_STATUS_PIN, pigpio.INPUT)
                self.iface.set_pull_up_down(self._HW_TOGGLE_PIN, pigpio.PUD_OFF)
                self.iface.set_pull_up_down(self._CH_TOGGLE_PIN, pigpio.PUD_OFF)
                self.iface.set_pull_up_down(self._HW_STATUS_PIN, pigpio.PUD_OFF)
                self.iface.set_pull_up_down(self._CH_STATUS_PIN, pigpio.PUD_OFF)
                if self._TH_SENSOR_PIN and self._TH_SENSOR_TYPE:
                    self.add_temp_humidity_interface(pin_id=self._TH_SENSOR_PIN, sensor_type=self._TH_SENSOR_TYPE)
            except (AttributeError, IOError, pigpio.error) as e:
                print(("ERROR: Cannot configure pins hw={},{} ch={},{}: {}".format(self._HW_TOGGLE_PIN, self._HW_STATUS_PIN, self._CH_TOGGLE_PIN, self._CH_STATUS_PIN, e)))
        else:
            print("ERROR: Interface not connected. Cannot configure pins.")
            
        # Now set internal vars to initial state:
        self.check_status()
    
    @classmethod
    def human_bool(cls, value):
        """
        Returns the boolean equivalent of the given value
        """
        if value in ("off", "OFF", "-", "low", "0", "LOW", "L", "False", "false", "None", "null",
                     b"off", b"OFF", b"-", b"low", b"0", b"LOW", b"L", b"False", b"false", b"None", b"null"):
            return 0
        return bool(value)
    
    @property
    def status(self):
        """
        Returns the current runtime vars (which should represent the pin values)
        """
        out = {
            "hw": self.hw,
            "ch": self.ch
        }
        if self.get_has_temp_humidity_sensor() and self.th:
            out["th"] = self.th
        return out

    def add_temp_humidity_interface(self, pin_id=None, sensor_type=None):
        """
        Add in the pigpio_dht powered interface
        """
        if pin_id is None:
            print("Error: Cannot add a temperature/humidity sensor, no pin number supplied.")
        self.iface_temp_humid = TemperatureHumiditySensor(gpio=pin_id, mode=sensor_type, pigpio_interface=self.iface)
        self.iface_temp_humid.read()  # Perform first read.
        return self.iface_temp_humid

    def get_has_temp_humidity_sensor(self):
        """
        Return True if sensor exists
        """
        return bool(self.iface_temp_humid)

    def read_temp_humidity(self, use_cache=True):
        """
        Read the relevant interface:

        :param use_cache: <bool> If True, don't perform a blocking read. Read the cached data then do an async refetch.
        """
        if not self.iface_temp_humid:
            logging.warning("{}.read_temp_humidity(): No sensor interface.".format(self.__class__.__name__))
            return {}
        # We always read the last data item unless told to otherwise:
        if use_cache:
            latest_temp_humidity = self.iface_temp_humid.read_last_result()
            self.iface_temp_humid.read_non_blocking()  # Now update the cache
        else:
            latest_temp_humidity = self.iface_temp_humid.read()
        self.th = latest_temp_humidity
        return latest_temp_humidity
    
    def check_hw(self):
        """
        Interrogates the HW pin. Returns the current status of the Hot Water
        """
        self.hw = self.read(self._HW_STATUS_PIN)
        return self.hw
    
    def check_ch(self):
        """
        Interrogates the CH pin. Returns the current status of the Central Heating
        """
        self.ch = self.read(self._CH_STATUS_PIN)
        return self.ch

    def check_th(self):
        """
        Reads temp and humidity with caching
        :return: {
            'temp_c': 22,
            'temp_f': 71.6,
            'humidity': 41,
            'valid': True,
            'query_timestamp': datetime.datetime(2021, 1, 2, 13, 27, 31, 644130)
        }

        """
        if self.iface_temp_humid:
            return self.read_temp_humidity(use_cache=True) or {}
        return {}
    
    def check_status(self):
        """
        Interrogates both CH and HW pins, returning the statuses of the pins and 
        setting the internal pointers to those values
        """
        self.check_ch()
        self.check_hw()
        self.check_th()
        return self.status    
    
    def set_hw(self, value):
        """
        Turns the hot water to the value of mode. This involves a transient 75ms pulse to the 
        toggle pin.
        """
        current_value = self.check_hw()
        intended_value = self.human_bool(value)
        self.pulse_if_different(current=current_value, intended=intended_value, output_pin=self._HW_TOGGLE_PIN, duration_ms=self._PULSE_DURATION_MS)
        sleep(self._RELAY_DELAY_MS/1000.0)
        return self.check_status()  # Actually measure the result!

    def set_ch(self, value):
        """
        Turns the hot water to the value of mode
        """
        current_value = self.check_ch()
        intended_value = self.human_bool(value)
        self.pulse_if_different(current=current_value, intended=intended_value, output_pin=self._CH_TOGGLE_PIN, duration_ms=self._PULSE_DURATION_MS)
        sleep(self._RELAY_DELAY_MS/1000.0)
        return self.check_status()  # Actually measure the result!

    def teardown(self):
        """
        Called when exiting the listener. Tear down any async threads here
        """
        logging.info("\tHeatingController {}: exiting...".format(self.__class__.__name__))
        if self.iface_temp_humid:
            try:
                self.iface_temp_humid.teardown()
            except TimeoutError:
                pass
