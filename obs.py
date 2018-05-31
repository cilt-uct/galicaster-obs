import os
import time
import json
import math
import threading
import tempfile
import serial.tools.list_ports
from bottle import route, run, response, abort, request, install
from gi.repository import GObject, Gdk, GLib

from galicaster.core import context
from galicaster.mediapackage.serializer import set_manifest
from galicaster.utils import readable
from galicaster.utils import ical
from galicaster.utils.miscellaneous import get_screenshot_as_pixbuffer

from evdev import InputDevice, ecodes, list_devices
import logging
import errno

import requests
from collections import namedtuple
from datetime import timedelta, datetime, tzinfo
from dateutil.parser import parse
from tzlocal import get_localzone

conf = context.get_conf()
dispatcher = context.get_dispatcher()
logger = context.get_logger()
repo = context.get_repository()
recorder = context.get_recorder()
my_lights = []
url = "http://camonitor.uct.ac.za/obs-api/event/"

# Simple function to print a message on each event
def print_message(message):
    def dumb_echo(*args):
        logger.info(message)
    return dumb_echo

def start_recording():
    def process():
        logger.info("Trying to start recording")
        if recorder.is_recording():
            Gdk.threads_add_idle(GLib.PRIORITY_HIGH, recorder.stop)
            logger.info("Couldn't start capture")            
        else:
            recorder.record(None)
            logger.info("Signal to start recording sent")
    return process

def check_recordings():
    my_response = requests.get(url)

    if (my_response.ok):
        logger.info("getting calendar events ...")
        x = json.loads(my_response.content, object_hook=lambda d: namedtuple('X', d.keys())(*d.values()))
        now = datetime.now(GMT2())
        logger.info("Now: "+ str(now.astimezone(get_localzone())))

        for line in x:
            #if line.ocSeries is not None:
                start = parse(line.start.dateTime + 'Z')
                end = parse(line.start.dateTime + 'Z')
                if start < now < end:
                    logger.info("scheduled event")
                else:
                    logger.info("no event")

def init():
    try:
        # Attempt to find a powermate wheel
        try:
            device = find_wheels()
        except DeviceNotFound:
            logger.error('Device not found')

        # Use the first one, as this is just for testing purposes
        my_wheel = PowerMateWheel(device[0])
        my_wheel.set_logger(logger) 

        # Add event handlers
        my_wheel.on('press', print_message('Down'))
        #my_wheel.on('depress', print_message('Up'))
        my_wheel.on('depress', start_recording()) #print_message('Up'))

        logger.info('PowerMate Running...')

        # Start listening
        p_thread = threading.Thread(target=my_wheel.listen)
        p_thread.setDaemon(True)
        p_thread.start()

        # set up the lights
        arduino_ports = [
            p.device
            for p in serial.tools.list_ports.comports()
            if ('Serial' in p.description) or ('Arduino' in p.description) or (p.device.startswith('/dev/ttyACM'))
        ]

        for p in arduino_ports:
            my_lights.append( serial.Serial(p, 115200))
        
        dispatcher.connect("timer-long", check_recordings)

    except ValueError:
        pass

class PowerMateWheel():
    def __init__(self, device=None):
        self.__logger = logging.getLogger('lib-powermate')

        if device != None:
            self.set_device(device)

        self.__wheel_pressed = False
        self.__ignore_multiple_twists = False
        self.__has_twisted = False
        self.__ignore_all_events = False

        # Functions to be called
        self._press = self.__dummy_call
        self._depress = self.__dummy_call
        self._turn_left = self.__dummy_call
        self._turn_right = self.__dummy_call
        self._twist_left = self.__dummy_call
        self._twist_right = self.__dummy_call

    @staticmethod
    def __dummy_call(*args):
        pass

    def ignore_all_events(self, value=True):
        self.__ignore_all_events = value

    def ignore_multiple_twists(self, value=True):
        self.__ignore_multiple_twists = value

    def set_device(self, device):
        self.__device = InputDevice(device)

    def get_device(self):
        return self.__device

    def is_pressed(self):
        return self.__wheel_pressed

    def has_twisted(self):
        return self.__has_twisted

    def set_logger(self, new_logger):
        self.__logger = new_logger

    def brightness(self, level):
        self.__device.write(ecodes.EV_MSC, ecodes.MSC_PULSELED, level % 256)

    def led_on(self):
        self.brightness(255)

    def led_off(self):
        self.brightness(0)

    def on(self, event_name, your_function):
        if not callable(your_function):
            raise TypeError('Expected a callable')

        if event_name == 'press':
            self._press = your_function
        elif event_name == 'depress' or event_name == 'release':
            self._depress = your_function
        elif event_name == 'turn_left':
            self._turn_left = your_function
        elif event_name == 'turn_right':
            self._turn_right = your_function
        elif event_name == 'twist_left':
            self._twist_left = your_function
        elif event_name == 'twist_right':
            self._twist_right = your_function
        else:
            raise NameError('Event %s not implemented' % event_name)

    def listen(self):
        self.__logger.info('Listening on device %s' % self.__device.fn)
        try:
            for event in self.__device.read_loop():
                # ignore synchronization events
                if self.__ignore_all_events or event.type == ecodes.EV_SYN:
                    continue

                self.__logger.debug('Processing event: ' + str(event))

                # button event
                if event.type == ecodes.EV_KEY:
                    if event.value == 0:
                        self.__wheel_pressed = False
                        self._depress()
                        self.__has_twisted = False
                    else:
                        self.__wheel_pressed = True
                        self._press()

                # turn/twist event
                elif event.type == ecodes.EV_REL:
                    if event.value > 0:
                        if self.is_pressed():
                            if not self.__has_twisted:
                                self._twist_right(abs(event.value))
                                if self.__ignore_multiple_twists:
                                    self.__has_twisted = True
                        else:
                            self._turn_right(abs(event.value))
                    else:
                        if self.is_pressed():
                            if not self.__has_twisted:
                                self._twist_left(abs(event.value))
                                if self.__ignore_multiple_twists:
                                    self.__has_twisted = True
                        else:
                            self._turn_left(abs(event.value))

        except IOError as e:
            if e.errno == errno.ENODEV:
                self.__logger.error('Device unplugged')
                raise IOError('Device not found')
            else:
                self.__logger.error(e.message)
                raise e

        except (KeyboardInterrupt, SystemExit):
            self.__logger.info('Listen aborted on device %s' % self.__device)

        except Exception as e:
            self.__logger.debug('Error: %s' % e)
            raise e


class DeviceNotFound(Exception):
    pass


def find_wheels():
    devices = [InputDevice(fn) for fn in list_devices()]
    wheels = []

    for device in devices:
        if device.name.find('PowerMate') != -1:
            # print ('Device found: ' + device.name + ' (' + device.phys + ')')
            wheels.append(device.fn)

    if len(wheels) == 0:
        raise DeviceNotFound

    return wheels

class GMT2(tzinfo):
    def utcoffset(self, dt):
        return timedelta(hours=2) + self.dst(dt)
    def dst(self, dt):
        d = datetime(dt.year, 4, 1)
        self.dston = d - timedelta(days=d.weekday() + 1)
        d = datetime(dt.year, 11, 1)
        self.dstoff = d - timedelta(days=d.weekday() + 1)
        if self.dston <=  dt.replace(tzinfo=None) < self.dstoff:
            return timedelta(hours=1)
        else:
            return timedelta(0)
    def tzname(self,dt):
        return "GMT +2"