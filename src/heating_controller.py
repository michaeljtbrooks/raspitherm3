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

from utils import BaseRaspiHomeDevice

logging.basicConfig(format='[%(asctime)s RASPITHERM] %(message)s', datefmt='%H:%M:%S',level=logging.INFO)


class HeatingController(BaseRaspiHomeDevice):
    """
    Represents a heating programmer
    """
    # Runtime vars
    hw = 0  # Current status of hot water
    ch = 0  # Current status of central heating
    th = None  # Current temp and humidity
    iface = None  #Pigpio interface
    # Pins
    _HW_TOGGLE_PIN = 5 
    _CH_TOGGLE_PIN = 26
    _HW_STATUS_PIN = 22
    _CH_STATUS_PIN = 27
    _DH11_SENSOR_PIN = None
    _DH22_SENSOR_PIN = None
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
        self._DH11_SENSOR_PIN = config.get("DH11_sensor_pin", self._DH11_SENSOR_PIN)
        self._DH22_SENSOR_PIN = config.get("DH22_sensor_pin", self._DH22_SENSOR_PIN)
        self._RELAY_DELAY_MS = config.get("relay_delay_ms", self._RELAY_DELAY_MS)
        
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
                if self._DH22_SENSOR_PIN:
                    self.iface.set_mode(self._DH22_SENSOR_PIN, pigpio.INPUT)
                    self.iface.set_pull_up_down(self._DH22_SENSOR_PIN, pigpio.PUD_OFF)
                    self.add_temp_humidity_dht22_interface(pin_id=self._DH22_SENSOR_PIN)
                elif self._DH11_SENSOR_PIN:
                    self.iface.set_mode(self._DH11_SENSOR_PIN, pigpio.INPUT)
                    self.iface.set_pull_up_down(self._DH11_SENSOR_PIN, pigpio.PUD_OFF)
                    self.add_temp_humidity_dht11_interface(pin_id=self._DH11_SENSOR_PIN)
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
        if value in ("off", "OFF", "-", "low", "0", "LOW", "L", "False", "false", "None", "null"):
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
        if self.get_has_temp_humidity_sensor():
            out["th"] = self.th
        return out

    def add_temp_humidity_dht11_interface(self, pin_id=None, name="temp_humidity"):
        """
        Add in the pigpio_dht powered interface
        """
        return self.iface.add_supplementary_pin_interface(pin_id=pin_id, name=name, interface_class=DHT11)

    def add_temp_humidity_dht22_interface(self, pin_id=None, name="temp_humidity"):
        """
        Add in the pigpio_dht powered interface
        """
        return self.iface.add_supplementary_pin_interface(pin_id=pin_id, name=name, interface_class=DHT22)

    def get_has_temp_humidity_sensor(self, name="temp_humidity"):
        """
        Return True if sensor exists
        """
        return bool(getattr(self.iface, name, False))

    def read_temp_humidity(self, name="temp_humidity"):
        """
        Read the relevant interface:
        """
        try:
            temp_humidity_subinterface = getattr(self.iface, name)
        except AttributeError:
            logging.warning("{}.read_temp_humidity(): No sensor interface by name {}.".format(self.__class__.__name__, name))
            return {}
        if temp_humidity_subinterface:  # No sensor added
            return {}
        try:
            latest_temp_humidity = temp_humidity_subinterface.read()
        except TimeoutError:
            logging.warning("{}.read_temp_humidity(): Sensor timeout! {}".format(self.__class__.__name__, name))
            return {}
        if latest_temp_humidity.get("valid"):  # Only return a value if it is valid!
            self.th = latest_temp_humidity
            return latest_temp_humidity
        return self.th
    
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
    
    def check_status(self):
        """
        Interrogates both CH and HW pins, returning the statuses of the pins and 
        setting the internal pointers to those values
        """
        self.check_ch()
        self.check_hw()
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
    
