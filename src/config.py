"""
Raspitherm - Config

Parses config file and fetches config data
"""
import logging

import configparser
import os

import pytz


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


logging.basicConfig(format='[%(asctime)s RASPITHERM] %(message)s', datefmt='%H:%M:%S', level=logging.INFO)

RASPILED_DIR = os.path.dirname(os.path.realpath(__file__)) #The directory we're running in

DEFAULTS = {
        'config_path' : RASPILED_DIR,
        'timezone': "Europe/London",
        'pi_host'     : 'localhost',
        'pi_port'     : 9090,
        'pig_port'    : 8888,
        'hw_toggle_pin': 5,
        'cw_toggle_pin': 26,
        'hw_status_pin': 22,
        'cw_status_pin': 27,
        'pulse_duration_ms': 200,  # Duration of pulse
        'relay_delay_ms': 200,  # How long it takes for the relays to be thrown
        'sensor_polling_period_seconds': 60,
        'th_sensor_pin': 0,
        'th_sensor_type': "DHT11",
        'debug': 0  # Must be lower case!
}

# Generate or read a config file.
config_path = os.path.expanduser(RASPILED_DIR+'/raspitherm.conf')
parser = configparser.ConfigParser(defaults=DEFAULTS)

if os.path.exists(config_path):
    logging.info('Using config file: {}'.format(config_path))
    parser.read(config_path)
    # print(parser.defaults())
else:
    logging.warning('No config file found. Creating default {} file.'.format(config_path))
    logging.warning('*** Please edit this file as needed. ***')
    parser = configparser.ConfigParser(defaults=DEFAULTS)
    with open(config_path, 'w') as f:
        parser.write(f)


CONFIG_SETTINGS = odict2int(parser.defaults()) #Turn the Config file into settings


class NotSet(object):
    """
    Null class
    """

    @classmethod
    def __bool__(cls):
        return False

    @classmethod
    def __nonzero__(cls):
        return False


NOT_SET = NotSet()


def get_setting(name, default=NOT_SET):
    """
    Gets a setting
    """
    return CONFIG_SETTINGS.get(name, default)


def get_current_timezone():
    """
    Gets a full PyTZ timezone from the config file expression
    """
    tz_expression = get_setting("timezone", default="Europe/London")
    return pytz.timezone(tz_expression)


get_config = get_setting


DEBUG = bool(get_setting("debug", default=False))
