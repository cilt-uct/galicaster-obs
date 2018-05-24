import datetime
from gi.repository import GLib

import serial.tools.list_ports

from galicaster.core import context
from galicaster.recorder.service import (INIT_STATUS, PREVIEW_STATUS,
                                         RECORDING_STATUS, PAUSED_STATUS,
                                         ERROR_STATUS, Status)
from galicaster.classui.recorderui import TIME_UPCOMING

import logging
import errno

conf = context.get_conf()
dispatcher = context.get_dispatcher()
logger = context.get_logger()
repo = context.get_repository()
recorder = context.get_recorder()

# add a fake status to indicate upcoming recording
UPCOMING_STATUS = Status('upcoming', 'Upcoming')

def init():
    OBSLightPlugin()

class OBSLightPlugin():
    def __init__(self):
        self.__logger = logging.getLogger('lib-obs_light')

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
        dispatcher.connect('recorder-status', self._handle_status_change)
        dispatcher.connect('recorder-upcoming-event', self._handle_upcoming)

        # make sure led is off when plugin starts
        self._handle_timer(self)

    def set_logger(self, new_logger):
        self.__logger = new_logger

    def _handle_upcoming(self, sender):
        # called when the recorderui determines there is a recording upcoming
        self.set_status(UPCOMING_STATUS)

    def _handle_status_change(self, sender, status):
        self.__logger.info('switching to %s' % status)
        # called when the record service status changes
        self.set_status(status)

    def _handle_timer(self, sender):
        # called by the timer-short signal
        # to make sure status is correct even if blinkstick unplugged
        # when the recording status changed
        status = recorder.status
        if status is PREVIEW_STATUS:
            next = repo.get_next_mediapackage()
            upcoming = False
            if next is not None:
                start = next.getLocalDate()
                delta = start - datetime.datetime.now()
                upcoming = delta <= datetime.timedelta(seconds=self.upcoming_time)
            if upcoming:
                status = UPCOMING_STATUS

    def set_status(self, status):
        self.__logger.info('switching to %s' % status)
        if status in [PREVIEW_STATUS, INIT_STATUS, ERROR_STATUS]:
            for p in self.lights:
                p.write('SetLed,0,0,0;')
        elif status == RECORDING_STATUS:
            for p in self.lights:
                p.write('SetLed,1,0,0;')
        elif status == UPCOMING_STATUS:
            for p in self.lights:
                p.write('SetLed,0,1,0;')