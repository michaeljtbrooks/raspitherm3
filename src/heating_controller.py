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

import datetime
import logging
from decimal import Decimal, InvalidOperation

import pigpio
from time import sleep

from config import DEBUG
from utils import BaseRaspiHomeDevice, TemperatureHumiditySensor, WaterTemperatureSensor

logging.basicConfig(format='[%(asctime)s RASPITHERM] %(message)s', datefmt='%H:%M:%S',level=logging.INFO)


class HeatingController(BaseRaspiHomeDevice):
    """
    Represents a heating programmer
    """
    # Runtime vars
    hw = 0  # Current status of hot water
    ch = 0  # Current status of central heating
    th = None  # Current temp and humidity
    hw_temp = None  # Current hot water temperature
    iface = None  # General Pigpio interface
    iface_temp_humid = None  # Humidity temperature sensor interface  (could expand this into multiples in future)
    iface_hw_temp = None  # Hot water temperature sensor interface (DS18B20)

    # Pins
    _HW_TOGGLE_PIN = 5 
    _CH_TOGGLE_PIN = 26
    _HW_STATUS_PIN = 22
    _CH_STATUS_PIN = 27
    _TH_SENSOR_PIN = None  # Temperature humidity sensor pin
    _TH_SENSOR_POWER_PIN = None  # Temperature humidity sensor power pin (to help reset a crashed sensor)
    _TH_SENSOR_TYPE = "DHT11"  # Temperature humidity sensor type (DHT11 or DHT22)
    _HW_TEMP_SENSOR_PIN = 0  # Hot water temperature sensor pin (DS18B20 - w1)
    _PULSE_DURATION_MS = 200  # How long a toggle pulse should be (milliseconds)
    _RELAY_DELAY_MS = 200  # How long to wait before rechecking the status after a toggle (enough time for relay to switch) 

    # Freeze protection: an intrinsic failsafe in case Home Assistant falls over
    _FREEZE_PROTECTION_TEMP_C = Decimal("7")  # Room temperature floor. None = disabled
    FREEZE_PROTECTION_HYSTERESIS_C = Decimal("3")  # Heat until floor + this (i.e. 10 degrees C)
    FREEZE_PROTECTION_TRIGGER_DURATION = datetime.timedelta(minutes=5)  # Must be below the floor for this long...
    FREEZE_PROTECTION_TRIGGER_MIN_READS = 5  # ...and for this many consecutive reads, so it's not just a noisy sensor
    FREEZE_PROTECTION_MAX_RUN_TIME = datetime.timedelta(hours=1)
    FREEZE_PROTECTION_MIN_SENSOR_MAX_AGE = datetime.timedelta(minutes=5)  # Readings older than this mean sensor isn't responding
    freeze_protection_active_since = None  # Datetime when freeze protection turned the heating on
    _freeze_cold_since = None  # Timestamp of first read in the current run of reads below the floor
    _n_freeze_cold_reads = 0  # Number of consecutive reads below the floor
    _freeze_last_read_timestamp = None  # So we only count each sensor read once
    
    def __init__(self, config, interface=None, emulated_readable_pins=None, registry=None):
        """
        Sets this up
        """
        super(HeatingController, self).__init__(registry=registry, emulated_readable_pins=emulated_readable_pins)

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
        self._TH_SENSOR_POWER_PIN = config.get("th_sensor_power_pin", self._TH_SENSOR_POWER_PIN)
        self._HW_TEMP_SENSOR_PIN = config.get("hw_temp_sensor_pin", self._HW_TEMP_SENSOR_PIN)

        # Freeze protection
        self._FREEZE_PROTECTION_TEMP_C = self.parse_freeze_protection_temp_c(config.get("freeze_protection_temp_c", self._FREEZE_PROTECTION_TEMP_C))
        polling_period = datetime.timedelta(seconds=config.get("sensor_polling_period_seconds", 60))
        self._freeze_protection_sensor_max_age = max(self.FREEZE_PROTECTION_MIN_SENSOR_MAX_AGE, polling_period * 3)
        
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
                if (self._TH_SENSOR_PIN or DEBUG) and self._TH_SENSOR_TYPE:  # The sensor will emulate in development mode
                    self.iface.set_mode(self._TH_SENSOR_PIN, pigpio.INPUT)
                    self.add_temp_humidity_interface(pin_id=self._TH_SENSOR_PIN, sensor_type=self._TH_SENSOR_TYPE, sensor_power_pin=self._TH_SENSOR_POWER_PIN)
                    if self._TH_SENSOR_POWER_PIN:
                        self.iface.set_mode(self._TH_SENSOR_POWER_PIN, pigpio.OUTPUT)
                        self.iface.set_pull_up_down(self._TH_SENSOR_POWER_PIN, pigpio.PUD_OFF)  # We use a hardware pull-up
                        self.iface.write(self._TH_SENSOR_POWER_PIN, pigpio.ON)  # Power up that sensor!!

            except (AttributeError, IOError, pigpio.error) as e:
                print(
                    (
                        "ERROR: Cannot configure pins hw={},{} ch={},{} th={} hw_pwr={}: {}".format(
                            self._HW_TOGGLE_PIN, self._HW_STATUS_PIN,
                            self._CH_TOGGLE_PIN, self._CH_STATUS_PIN,
                            self._TH_SENSOR_PIN, self._TH_SENSOR_POWER_PIN,
                            e
                        )
                    )
                )
        else:
            print("ERROR: Interface not connected. Cannot configure pins.")
            if DEBUG:  # We will still emulate the temperature sensor
                self.add_temp_humidity_interface(pin_id=self._TH_SENSOR_PIN, sensor_type=self._TH_SENSOR_TYPE)

        # Configure the DS18B20 interface if requested
        if self._HW_TEMP_SENSOR_PIN:
            self.add_hw_temp_interface(pin_id=self._HW_TEMP_SENSOR_PIN)
            
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

    @classmethod
    def parse_freeze_protection_temp_c(cls, value):
        """
        Returns the freeze protection floor as a Decimal, or None if freeze protection is disabled
        """
        try:
            return Decimal(str(value).strip())
        except (ValueError, TypeError, InvalidOperation):
            logging.warning("Freeze protection is DISABLED (freeze_protection_temp_c = '{}')".format(value))
            return None

    @property
    def freeze_protection_target_temp_c(self):
        if self._FREEZE_PROTECTION_TEMP_C is None:
            return None
        return self._FREEZE_PROTECTION_TEMP_C + self.FREEZE_PROTECTION_HYSTERESIS_C
    
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
            out["th_available"] = 1
        else:
            out["th_available"] = 0
        if self.get_has_hw_temp_sensor() and self.hw_temp:
            out["hw_temp"] = self.hw_temp
            out["hw_temp_c"] = self.hw_temp.get("temp_c")
            out["hw_temp_f"] = self.hw_temp.get("temp_f")
            out["hw_temp_available"] = 1
        else:
            out["hw_temp_available"] = 0
        out["freeze_protection_active"] = int(bool(self.freeze_protection_active_since))
        out["freeze_protection_since"] = self.freeze_protection_active_since
        return out

    def add_temp_humidity_interface(self, pin_id=None, sensor_type=None, sensor_power_pin=None):
        """
        Add in the pigpio_dht powered interface
        """
        if pin_id is None:
            print("Error: Cannot add a temperature/humidity sensor, no pin number supplied.")
        self.iface_temp_humid = TemperatureHumiditySensor(gpio=pin_id, mode=sensor_type, pigpio_interface=self.iface, sensor_power_pin=sensor_power_pin)
        self.iface_temp_humid.read_non_blocking(delay=5.0)  # Perform first read after enough time has passed for sensor to initialise
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
            if not self.th:  # Force a delay for our first ever read
                delay = 5.0
            else:
                delay = 0.0
            self.iface_temp_humid.read_non_blocking(delay=delay)  # Now update the cache
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

    def add_hw_temp_interface(self, pin_id=None):
        """
        Add in the DS18B20-powered interface (via the kernel w1 interface).
        """
        if pin_id is None:
            logging.warning("Cannot add a hot water temperature sensor; no pin number supplied.")
            return None
        self.iface_hw_temp = WaterTemperatureSensor(gpio_pin=pin_id)
        return self.iface_hw_temp

    def get_has_hw_temp_sensor(self):
        """
        Return True if a water temperature sensor exists or is configured.
        """
        return bool(self.iface_hw_temp)

    def read_hw_temp(self):
        """
        Read the hot water temperature sensor.
        """
        if not self.iface_hw_temp:
            return {}
        return self.iface_hw_temp.read()

    def check_hw_temp(self):
        """
        Reads water temperature with caching of last known good value.
        """
        if self.iface_hw_temp:
            self.hw_temp = self.read_hw_temp() or self.hw_temp
            return self.hw_temp or {}
        return {}
    
    def check_status(self):
        """
        Interrogates both CH and HW pins, returning the statuses of the pins and 
        setting the internal pointers to those values
        """
        self.check_ch()
        self.check_hw()
        self.check_th()
        self.check_hw_temp()
        return self.status    
    
    def set_hw(self, value):
        """
        Turns the hot water to the value of mode. This involves a transient 75ms pulse to the 
        toggle pin.
        """
        current_value = self.check_hw()
        intended_value = self.human_bool(value)
        self.pulse_if_different(current=current_value, intended=intended_value, output_pin=self._HW_TOGGLE_PIN, duration_ms=self._PULSE_DURATION_MS)
        if DEBUG:
            self.emulated_readable_pins[self._HW_STATUS_PIN] = intended_value
        sleep(self._RELAY_DELAY_MS/1000.0)
        return self.check_status()  # Actually measure the result!

    def set_ch(self, value):
        """
        Turns the central heating to the value of mode, as commanded externally (web UI / Home Assistant).
        External commands always take control back from freeze protection.
        """
        if self.freeze_protection_active_since:
            self.stop_freeze_protection(
                reason="external command to turn central heating {}".format(value),
                switch_ch_off=False  # The command itself decides
            )
        self._reset_freeze_cold_streak()
        return self._switch_ch(value)

    def _switch_ch(self, value):
        """
        Turns the central heating to the value of mode
        """
        current_value = self.check_ch()
        intended_value = self.human_bool(value)
        self.pulse_if_different(current=current_value, intended=intended_value, output_pin=self._CH_TOGGLE_PIN, duration_ms=self._PULSE_DURATION_MS)
        if DEBUG:
            self.emulated_readable_pins[self._CH_STATUS_PIN] = intended_value
        sleep(self._RELAY_DELAY_MS/1000.0)
        return self.check_status()  # Actually measure the result!

    def _reset_freeze_cold_streak(self):
        self._freeze_cold_since = None
        self._n_freeze_cold_reads = 0

    def _get_new_room_temperature(self, now):
        """
        Returns the room temperature as a Decimal if there has been a fresh sensor read since we last looked, else None
        """
        th = self.iface_temp_humid.read_last_result()
        read_timestamp = th.get("query_timestamp")
        if not read_timestamp or read_timestamp == self._freeze_last_read_timestamp:
            return None
        self._freeze_last_read_timestamp = read_timestamp
        if now - read_timestamp > self._freeze_protection_sensor_max_age:
            return None
        try:
            return Decimal(str(th["temp_c"]))
        except (KeyError, ValueError, TypeError, InvalidOperation):
            return None

    def update_freeze_protection(self):
        """
        Failsafe in case Home Assistant falls over. If the room sensor is responding and has been below the floor
        for long enough (and enough reads) to be believable, turn the central heating on until the room reaches
        floor + hysteresis, or it has run for FREEZE_PROTECTION_MAX_RUN_TIME. Any external command takes control back.

        Call this periodically (on each sensor poll). NOT from check_status() as it can switch the heating.
        """
        if self._FREEZE_PROTECTION_TEMP_C is None or not self.get_has_temp_humidity_sensor():
            return False
        now = datetime.datetime.now()
        temp_c = self._get_new_room_temperature(now)

        if self.freeze_protection_active_since:
            if not self.check_ch():
                # Something else switched it off (e.g. the programmer's own schedule or buttons). Don't fight it.
                self.stop_freeze_protection(reason="central heating was switched off by something else", switch_ch_off=False)
            elif temp_c is not None and temp_c >= self.freeze_protection_target_temp_c:
                self.stop_freeze_protection(reason="room has reached {}°C".format(temp_c))
            elif now - self.freeze_protection_active_since >= self.FREEZE_PROTECTION_MAX_RUN_TIME:
                self.stop_freeze_protection(reason="maximum run time reached")
            return True

        # Not active: track how long the room has been below the floor
        if temp_c is None:
            last_read_timestamp = self._freeze_last_read_timestamp
            if not last_read_timestamp or now - last_read_timestamp > self._freeze_protection_sensor_max_age:
                self._reset_freeze_cold_streak()  # Sensor isn't responding. Don't trust the streak.
            return False
        if temp_c >= self._FREEZE_PROTECTION_TEMP_C:
            self._reset_freeze_cold_streak()
            return False
        if self._freeze_cold_since is None:
            self._freeze_cold_since = self._freeze_last_read_timestamp
        self._n_freeze_cold_reads += 1
        cold_for = self._freeze_last_read_timestamp - self._freeze_cold_since
        if cold_for < self.FREEZE_PROTECTION_TRIGGER_DURATION or self._n_freeze_cold_reads < self.FREEZE_PROTECTION_TRIGGER_MIN_READS:
            return False
        if self.check_ch():  # Already heating, so nothing for us to do
            return False
        logging.warning(
            "FREEZE PROTECTION ON: room below {}°C for {} ({} reads, now {}°C). Central heating on until {}°C, for at most {}.".format(
                self._FREEZE_PROTECTION_TEMP_C, str(cold_for).split(".")[0], self._n_freeze_cold_reads, temp_c,
                self.freeze_protection_target_temp_c, self.FREEZE_PROTECTION_MAX_RUN_TIME
            )
        )
        status = self._switch_ch(1)
        if not status.get("ch"):
            logging.error("FREEZE PROTECTION: failed to turn central heating on! Will retry at next poll.")
            return False
        self.freeze_protection_active_since = now
        self._reset_freeze_cold_streak()
        return True

    def stop_freeze_protection(self, reason="", switch_ch_off=True):
        """
        Ends freeze protection, optionally turning the central heating back off
        """
        ran_for = datetime.datetime.now() - self.freeze_protection_active_since
        logging.warning("FREEZE PROTECTION OFF after {}: {}.".format(str(ran_for).split(".")[0], reason))
        self.freeze_protection_active_since = None
        self._reset_freeze_cold_streak()
        if switch_ch_off:
            self._switch_ch(0)

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
