import requests
from collections import namedtuple
from datetime import timedelta, datetime, tzinfo
from dateutil.parser import parse
from tzlocal import get_localzone
from time import sleep
import json

from gi.repository import GLib

import serial.tools.list_ports
from galicaster.core import context

import logging
import errno

conf = context.get_conf()
dispatcher = context.get_dispatcher()
logger = context.get_logger()
repo = context.get_repository()
recorder = context.get_recorder()

obs = None
url = "http://camonitor.uct.ac.za/obs-api/event/"

def init():
    obs = OBSPlugin(logger, url)

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
            self.lights.append( serial.Serial(p, 115200) )

        self.upcoming_time = 1000
        self.error = False

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
            self.__logger.info("getting calendar events : " + str(now.astimezone(get_localzone())))

            for line in x:
                #if line.ocSeries is not None:
                    start = parse(line.start.dateTime + 'Z')
                    end = parse(line.end.dateTime + 'Z')
                    if start < now < end:
                        self.__logger.info("scheduled event: " + str(start.astimezone(get_localzone())))
                        self.state = 1
                    else:
                        self.__logger.info("no event: " + str(start.astimezone(get_localzone())))
                        self.state = 0

        # called by the timer-short signal
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
