import requests
from collections import namedtuple
from datetime import timedelta, datetime, tzinfo
from dateutil.parser import parse
from tzlocal import get_localzone
from time import sleep
import json

import threading
from gi.repository import GObject, Gdk, GLib

import serial.tools.list_ports
from galicaster.core import context
from evdev import InputDevice, ecodes, list_devices

import logging
import errno

conf = context.get_conf()
dispatcher = context.get_dispatcher()
logger = context.get_logger()
repo = context.get_repository()
recorder = context.get_recorder()

url = "http://camonitor.uct.ac.za/obs-api/event/"

# Simple function to print a message on each event
def print_message(message):
    def dumb_echo(*args):
        logger.info(message)
    return dumb_echo

def start_recording(obs):
    def process():
        logger.info("Button Pressed: ")
        if recorder.is_recording():
            obs.set_recording(False)
            Gdk.threads_add_idle(GLib.PRIORITY_HIGH, recorder.stop)
            logger.info("# Stopping Recording")
        else:
            obs.set_recording(True)
            recorder.record(None)
            logger.info("# Start Recording")
    return process

def init():
    obs = OBSPlugin(logger, url)
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
        my_wheel.on('depress', start_recording(obs)) #print_message('Up'))

        logger.info('PowerMate Running...')

        # Start listening
        p_thread = threading.Thread(target=my_wheel.listen)
        p_thread.setDaemon(True)
        p_thread.start()

    except ValueError:
        pass

class OBSPlugin():
    def __init__(self, _logger, _url):
        self.__logger = _logger
        self.url = _url

        self.__logger.info("obs initializing...")
        arduino_ports = [
            p.device
            for p in serial.tools.list_ports.comports()
            if ('Serial' in p.description) or ('Arduino' in p.description) or (p.device.startswith('/dev/ttyACM'))
        ]

        self.lights = []
        for p in arduino_ports:
            self.lights.append(serial.Serial(p, 115200))

        self.upcoming_time = 1000
        self.error = False
        self.end_time = None
        self.is_recording = False
        self.state = 0

        dispatcher.connect('timer-short', self._handle_timer)

        # make sure led is off when plugin starts
        sleep(2) # arduino initialize timer
        self.set_status(0)
        self.__logger.info("obs initializing...Done")

    def _handle_timer(self, sender):

        my_response = requests.get(url)

        if (my_response.ok):
            x = json.loads(my_response.content, object_hook=lambda d: namedtuple('X', d.keys())(*d.values()))
            now = datetime.now(GMT2())
            self.__logger.info("getting calendar events : " + str(now.astimezone(get_localzone())) +" ["+ str(self.is_recording) +"]")

            for line in x:
                #if line.ocSeries is not None:
                start = parse(line.start.dateTime + 'Z')
                end = parse(line.end.dateTime + 'Z')
                if start < now < end:
                    self.__logger.info("scheduled event: " + str(start.astimezone(get_localzone())))
                    self.state = 1
                    self.end_time = end
                else:
                    self.__logger.info("no event: " + str(start.astimezone(get_localzone())))
                    self.state = 0
                    self.end_time = None

        # if we are not recording then play with the lights - otherwise NO
        if not self.is_recording:
            self.set_status(self.state)

    def set_recording(self, is_recording):
        now = datetime.now(GMT2())

        if is_recording:
            self.state = 2
            self.is_recording = is_recording
        else:    
            if self.end_time is not None:
                if now < self.end_time:
                    self.__logger.info("@ Still shceduled time")
                    self.state = 1
                else:
                    self.__logger.info("@ Past Time")
                    self.state = 0
            else:
                self.__logger.info("@ No Time")
                self.state = 0
        
        self.set_status(self.state)

    def set_status(self, status):
        self.__logger.info('switching to ' + str(status))
        if status == 0:
            for p in self.lights:
                p.write('SetLed,0,0,0;')
        elif status == 2: # RECORDING_STATUS:
            for p in self.lights:
                p.write('SetLed,1,0,0;')
        elif status == 1:
            for p in self.lights:
                p.write('SetLed,0,1,0;')

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
