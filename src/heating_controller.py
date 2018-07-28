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
from __future__ import unicode_literals

import logging
import pigpio
from utils import BaseRaspiHomeDevice

logging.basicConfig(format='[%(asctime)s RASPITHERM] %(message)s', datefmt='%H:%M:%S',level=logging.INFO)


class HeatingController(BaseRaspiHomeDevice):
    """
    Represents a heating programmer
    """
    # Runtime vars
    hw = 0  # Current status of hot water
    ch = 0  # Current status of central heating
    iface = None  #Pigpio interface
    # Pins
    _HW_TOGGLE_PIN = 5 
    _CH_TOGGLE_PIN = 26
    _HW_STATUS_PIN = 22
    _CH_STATUS_PIN = 27
    
    def __init__(self, config, interface=None):
        """
        Sets this up
        """
        self.iface = self.get_or_build_interface(config=config, interface=interface)
        
        # Outputs
        self._HW_TOGGLE_PIN = config.get("hw_toggle_pin", self._HW_TOGGLE_PIN)
        self._CH_TOGGLE_PIN = config.get("ch_toggle_pin", self._CH_TOGGLE_PIN)
        
        # Inputs
        self._HW_STATUS_PIN = config.get("hw_status_pin", self._HW_STATUS_PIN)
        self._CH_STATUS_PIN = config.get("ch_status_pin", self._CH_STATUS_PIN)
        
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
            except (AttributeError, IOError, pigpio.error) as e:
                print("ERROR: Cannot configure pins hw={},{} ch={},{}: {}".format(self._HW_TOGGLE_PIN, self._HW_STATUS_PIN, self._CH_TOGGLE_PIN, self._CH_STATUS_PIN, e))
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
        return {
            "hw": self.hw,
            "ch": self.ch
        }
    
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
        self.pulse_if_different(current=current_value, intended=intended_value, output_pin=self._HW_TOGGLE_PIN)
        return self.check_status()  # Actually measure the result!

    def set_ch(self, value):
        """
        Turns the hot water to the value of mode
        """
        current_value = self.check_ch()
        intended_value = self.human_bool(value)
        self.pulse_if_different(current=current_value, intended=intended_value, output_pin=self._CH_TOGGLE_PIN)
        return self.check_status()  # Actually measure the result!

    def teardown(self):
        """
        Called when exiting the listener. Tear down any async threads here
        """
        logging.info("\tHeatingController {}: exiting...".format(self.__class__.__name__))
    
