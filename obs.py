"""Copyright (C) 2018  The University of Cape Town

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import json
import logging
import errno
import gi
import re
import requests
import threading
import serial.tools.list_ports

from collections import namedtuple
from datetime import timedelta, datetime, tzinfo
from dateutil.parser import parse
from evdev import InputDevice, ecodes, list_devices
from string import Template
from tzlocal import get_localzone
from time import sleep

gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, Pango, GLib
from galicaster.core import context
from galicaster.classui import get_ui_path
from galicaster.classui import get_image_path
from galicaster.classui.elements.message_header import Header
from galicaster.mediapackage import mediapackage
from galicaster.utils.i18n import _

# This is the name of this plugin's section in the configuration file
CONFIG_SECTION = "obs"

# REGEXP Defaults and Keys
DEFAULT_REGEXP = "[0-9]{8}|[a-zA-Z]{6}[0-9]{3}|[T|t][0-9]{7}"
CONFIG_REGEXP = "rexexp"

DEFAULT_SERIES_FILTER = '%2Csubject%3APersonal'
CONFIG_SERIES_FILTER = "filter"

METADATA = Template('[]')
ACL = Template('[]')

# URL to request user information from
DEFAULT_SCHEDULE_URL = "https://camonitor.uct.ac.za/obs-api/event/"
URL_SCHEDULE = "url_schedule"

current_mediapackage = None

config = context.get_conf().get_section(CONFIG_SECTION) or {}
dispatcher = context.get_dispatcher()
repo = context.get_repository()
logger = context.get_logger()
recorder = context.get_recorder()
oc_client = context.get_occlient()

# Simple function to print a message on each event
def print_message(message):
    def dumb_echo(*args):
        logger.info(message)
    return dumb_echo

def start_recording(obs):
    def process():
        logger.info("Button Pressed: ")
        if recorder.is_recording():
            obs.stop_recording()
        else:
            obs.on_rec()
    return process

def init():
    global METADATA, ACL

    with open(get_ui_path("series_metadata_template.json"), "r") as metadataFile:
        METADATA = Template(metadataFile.read())

    with open(get_ui_path("acl_template.json"), "r") as aclFile:
        ACL = Template(aclFile.read())

    obs = OBSPlugin(logger, config.get(URL_SCHEDULE, DEFAULT_SCHEDULE_URL), oc_client)
    try:
        # Attempt to find a powermate wheel
        try:
            device = find_wheels()

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
        except DeviceNotFound:
            logger.error('Device not found')

    except ValueError:
        pass

class OBSPlugin():
    def __init__(self, _logger, _url, _client):
        self.__logger = _logger
        self.url = _url
        self.__oc_client = _client

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

        self.time_details = None
        self.user_details = None

        dispatcher.connect('timer-short', self._handle_timer)
        dispatcher.connect('record-finished', self.stop_recording)

        # so when UI init is triggered
        try:
            dispatcher.connect("init", self._handle_ui)
        except Exception as e:
            self.__logger.error(e)

        # make sure led is off when plugin starts
        sleep(2) # arduino initialize timer
        self.set_status(0)
        self.__logger.info("obs initializing...Done")

    def _handle_ui(self, element):
        """
        Add the UI elements to set the user info
        :param element:
        :return:
        """
        # load glade file
        #builder = Gtk.Builder()
        #builder.add_from_file(get_ui_path("camctrl-vapix.glade"))

        # calculate resolution for scaling
        #window_size = context.get_mainwindow().get_size()
        #res = window_size[0]/1920.0

        self.__ui = context.get_mainwindow().nbox.get_nth_page(0)
        self.__ui.connect('key-press-event', self.on_key_press)

        # so overwrite the default record button function
        rec_button = self.__ui.gui.get_object("recbutton")
        rec_button.connect("clicked", self.on_rec)
        rec_button.handler_block_by_func(self.__ui.on_rec)

        # add new settings tab to the notebook
        self.box = self.__ui.gui.get_object("eventpanel") #hbox4")
        self.title = self.__ui.gui.get_object("titlelabel")
        #status = self.__ui.get_object("eventlabel")

        new_box = Gtk.Box(spacing=0)
        new_box.set_name("set_user_container")

        label = Gtk.Label("")
        new_box.pack_start(label, expand=False, fill=False, padding=30)

        self.btn_show = Gtk.Button("Select a user...")
        self.btn_show.set_name("set_user_btn_set")
        self.btn_show.connect("clicked", self.button_set_user)
        new_box.pack_start(self.btn_show, expand=True, fill=True, padding=10)

        img_clear = Gtk.Image()
        img_clear.set_from_icon_name("edit-clear-symbolic", 6)

        self.btn_clear = Gtk.Button()
        self.btn_clear.set_name("set_user_btn_clear")
        #button.set_label("gtk-clear")
        self.btn_clear.connect("clicked", self.button_clear_user)
        self.btn_clear.add(img_clear)
        self.btn_clear.set_sensitive(False) # disabled
        new_box.pack_start(self.btn_clear, expand=True, fill=True, padding=10)

        label = Gtk.Label("")
        new_box.pack_start(label, expand=False, fill=True, padding=30)

        self.box.pack_start(new_box, False, False, 10)
        self.box.show_all()
        self.__logger.info("Set user init done.")

    def _handle_timer(self, sender):

        my_response = requests.get(self.url)

        self.__logger.info("handling timer")

        if (my_response.ok):
            x = json.loads(my_response.content, object_hook=lambda d: namedtuple('X', d.keys())(*d.values()))
            #self.__logger.info(x)
            now = datetime.now(GMT2())
            self.__logger.info("getting calendar events : " + str(now.astimezone(get_localzone())) +" ["+ str(self.is_recording) +"]")
            isCurrent = False

            for line in x:
                #if line.ocSeries is not None:
                #self.__logger.info(line.ocSeries)
                start = parse(line.start.dateTime + 'Z')
                end = parse(line.end.dateTime + 'Z')
                if start < now < end:
                    self.__logger.info("scheduled event: " + str(start.astimezone(get_localzone())))
                    self.state = 1
                    self.end_time = end
                    isCurrent = True

                    # new details
                    if self.time_details is None:
                        self.time_details = {
                            'series': line.ocSeries,
                            'seriesTitle': line.ocSeriesTitle,
                            'title': line.subject,
                            'organizer': line.organizer.emailAddress.name,
                            'organizerEmail': line.organizer.emailAddress.address,
                            'take': 0
                        }
                        #recorder.title_standin = self.time_details['organizer'] in clear
                        self.button_clear_user(None)

                    else:
                        # flow from one to a new one
                        # if we have a recording and the series differ then set to new series
                        if self.time_details['series'] != line.ocSeries:

                            self.time_details = {
                                'series': line.ocSeries,
                                'seriesTitle': line.ocSeriesTitle,
                                'title': line.subject,
                                'organizer': line.organizer.emailAddress.name,
                                'organizerEmail': line.organizer.emailAddress.address,
                                'take': 0
                            }
                            #recorder.title_standin = self.time_details['organizer'] in clear
                            self.button_clear_user(None)
                else:
                    recorder.title_standin = None
                    #self.__logger.info("no event: " + str(start.astimezone(get_localzone())))

            if isCurrent is False:
                self.__logger.info("no current session")
                self.state = 0
                self.end_time = None
                self.time_details = None
                if self.user_details is None:
                    recorder.title_standin = None
            else:
                self.state = 1

        # if we are not recording then play with the lights - otherwise NO
        if not self.is_recording:
            self.set_status(self.state)

    def on_key_press(self, widget, event):
        global recorder
        # logger.info("Key press on widget: {}".format(widget))
        # logger.info("          Modifiers: {}".format(event.state))
        logger.info("      Key val, name: {} {}".format(event.keyval, Gdk.keyval_name(event.keyval)))

        if (Gdk.keyval_name(event.keyval) == "Return"):
            logger.info("      ENTER :) {}".format(recorder.is_recording()))
            if recorder.is_recording():
                self.stop_recording()
            else:
                self.on_rec()

            return True

    def set_recording(self, is_recording):
        self.__logger.info("setting recording")
        self.is_recording = is_recording
        now = datetime.now(GMT2())

        if is_recording:
            self.state = 2
        else:
            if self.end_time is not None:
                if now < self.end_time:
                    self.__logger.info("@ Still scheduled time")
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

    def button_set_user(self, button):
        self.__logger.info("SET USER")
        popup = SetUserClass(self.__logger, title="Get My Info", client = self.__oc_client)

        if popup.return_value == -10:
            self.btn_clear.set_sensitive(True) # enabled
            self.user_details = {
                                'series': popup.series_id,
                                'seriesTitle': popup.series_title,
                                'title': popup.user_name,
                                'organizer': popup.user_name,
                                'organizerEmail': popup.user_email,
                                'take': 0
                            }
            self.btn_show.set_label(popup.user_name +" [Change]")
            self.title.set_text("Live with " + self.user_details['organizer'])
            self.box.show_all()
            self.__logger.info("User details set to: "+ popup.id +" "+ popup.user_name)
            recorder.title_standin = "Live with " + self.details['organizer']

        if popup.return_value == -7:
            self.__logger.info("Cancelled")

    def button_clear_user(self, button):
        self.__logger.info("CLEAR USER")
        self.user_details = None
        self.btn_clear.set_sensitive(False) # disabled
        self.btn_show.set_label("Select a user...")
        self.title.set_text(_("No upcoming events"))
        self.box.show_all()

        if self.time_details is not None:
            recorder.title_standin = "Live with " + self.time_details['organizer']
        else:
            recorder.title_standin = None
        self.title.show_all()

    def on_rec(self, element = None):
        global current_mediapackage, recorder

        self.__logger.info("# Start Recording 1")
        self.set_recording(True)

        current_mediapackage = self.create_mp()
        if current_mediapackage is None:
            self.__logger.info("# MP NONE")
        else:
            self.__logger.info(current_mediapackage.getTitle())
            self.__logger.info(current_mediapackage.getSeries())

        recorder.record(current_mediapackage)
        self.__logger.info("# Start Recording 2")

    def stop_recording(self, element = None, mp = None):
        global current_mediapackage, recorder

        self.__logger.info("# Stopping Recording")
        current_mediapackage = None
        self.set_recording(False)

        Gdk.threads_add_idle(GLib.PRIORITY_HIGH, recorder.stop)

    def on_button_pressed(self):
        def process(_s):
            logger.info("Button pressed.")
            if recorder.is_recording():
                _s.stop_recording()
            else:
                _s.on_rec()
        return process(self)

    def create_mp(self):
        if self.time_details is None:
            if self.user_details is None:
                return None

        details = self.time_details
        if self.user_details is not None:
            self.user_details['take'] += 1
            details = self.user_details
        else:
            self.time_details['take'] += 1
            details = self.time_details

        # self.__logger.info(details)
        title = details['organizer'] + ' - Take #' + str(details['take'])
        # self.__logger.info(title)

        new_mp = mediapackage.Mediapackage(title=title, presenter=details['organizer'])
        new_mp.setMetadataByName('source', 'Personal['+ details['series'] +']')
        new_mp.setSeries({
            'title': details['seriesTitle'],
            'identifier': details['series']
        })
        # self.__logger.info(new_mp.getTitle())
        return new_mp

    def default_mediapackage(self):
        global config

        now = datetime.now().replace(microsecond=0)
        title = "OBS Recording started at " + now.isoformat()
        mp = mediapackage.Mediapackage(title=title)
        if (context):
            mp.setSeries({
                'identifier': context.get_conf().get('series', 'default')
            })
        return mp

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

class SetUserClass(Gtk.Widget):
    """
    Handle a pop up to select a user
    """
    __gtype_name__ = 'SetUserClass'

    def __init__(self, _logger=None, title="Get My Info", client=None):
        """
        """
        self.id = ""
        self.user_name = ""
        self.user_email = ""
        self.series_id = ""
        self.series_title = ""
        self.searching = False
        self.details = None

        self.__logger = _logger
        self.__oc_client = client

        self.series_filter = config.get(CONFIG_SERIES_FILTER, DEFAULT_SERIES_FILTER)

        regexp = config.get(CONFIG_REGEXP, DEFAULT_REGEXP)
        self.__logger.info("REGEXP = " + regexp)
        self.__regexp = re.compile(regexp)

        parent = context.get_mainwindow()
        size = parent.get_size()

        self.par = parent
        altura = size[1]
        anchura = size[0]
        k1 = anchura / 1920.0
        k2 = altura / 1080.0
        self.wprop = k1
        self.hprop = k2

        gui = Gtk.Builder()
        gui.add_from_file(get_ui_path('set_user.glade'))

        self.dialog = gui.get_object("setuserdialog")
        self.dialog.set_property("width-request", int(anchura/2.2))
        self.dialog.set_type_hint(Gdk.WindowTypeHint.TOOLBAR)
        self.dialog.set_modal(True)
        self.dialog.set_keep_above(False)

        # user select button
        self.user_button = Gtk.Button()

        #NEW HEADER
        strip = Header(size=size, title=title)
        self.dialog.vbox.pack_start(strip, True, True, 0)
        self.dialog.vbox.reorder_child(strip, 0)

        self.search_field = gui.get_object("inp_search")
        #search_field.connect('key-press-event', self.on_key_press)
        self.search_field.connect('key-release-event', self.on_key_release)
        #self.search_field.connect('search-changed', self.search_changed)
        #self.search_field.connect('stop-search', self.search_stopped)

        self.result = gui.get_object("grd_result")

        if parent != None:
            # FIXME: The keyboard plugin uses Ubuntu Onboard.
            # https://bugs.launchpad.net/onboard/+bug/1627819
            # There is a bug with this plugin where the "dock to edges"
            # option does not work with the "force to top" one, causing
            # Onboard to appear behind when Galicaster is on fullscreen.
            # THIS affects #321. A better solution should be implemented.
            from galicaster import plugins
            if not parent.is_fullscreen or 'galicaster.plugins.keyboard' not in plugins.loaded:
                self.dialog.set_transient_for(parent.get_toplevel())
            self.dialog.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
            dialog_style_context = self.dialog.get_style_context()
            window_classes = parent.get_style_context().list_classes()
            for style_class in window_classes:
                dialog_style_context.add_class(style_class)

        self.dialog.show_all()

        parent.get_style_context().add_class('shaded')
        self.return_value = self.dialog.run()

        parent.get_style_context().remove_class('shaded')
        self.dialog.destroy()

    def on_key_release(self, widget, ev, data=None):

        # If Escape pressed, reset text
        if ev.keyval == Gdk.KEY_Escape:
            widget.set_text("")
            self.clear_search_entry()

        # If Enter pressed, try searching
        if ev.keyval == Gdk.KEY_Return or ev.keyval == Gdk.KEY_KP_Enter:
            self.do_search(widget.get_text())

        if self.__regexp.match(widget.get_text()): # if valid search
            self.__logger.info("found :) " + widget.get_text())
            if not self.searching:
                self.do_search(widget.get_text())

    def search_changed(self, widget, data=None):
        #self.__logger.info("search_changed")

        if widget.get_text() == "":
            self.clear_search_entry()

        if self.__regexp.match(widget.get_text()): # if valid search
            #self.__logger.info("found :) " + widget.get_text())
            if not self.searching:
                self.do_search(widget.get_text())

    def search_stopped(self, widget, data=None):
        #self.__logger.info("search_stopped")
        self.clear_search_entry()
        self.searching = False

    def clear_search_entry(self):
        self.searching = False
        self.search_field.set_text("")

        for element in self.result.get_children():
            self.result.remove(element)

        label = Gtk.Label("")
        self.result.pack_start(label, expand=False, fill=False, padding=0)

    def do_search(self, value):
        self.__logger.info("Searching for " + value)
        self.searching = True
        self.search_field.set_editable(False) # disabled

        for element in self.result.get_children():
            self.result.remove(element)

        loading_box = Gtk.Box(spacing=10)
        loading_box.set_name("grd_result_loading")

        label = Gtk.Label("")
        loading_box.pack_start(label, expand=False, fill=False, padding=0)

        spinner = Gtk.Spinner()
        spinner.start()
        loading_box.pack_start(spinner, expand=False, fill=False, padding=0)

        label = Gtk.Label(" Searching... ")
        loading_box.pack_start(label, expand=False, fill=False, padding=0)

        label = Gtk.Label("")
        loading_box.pack_start(label, expand=False, fill=False, padding=0)

        self.result.pack_start(loading_box, expand=False, fill=False, padding=0)
        self.result.show_all()

        self.show_response( self.call_get_user_info(value) ) # static request

    def show_response(self, details):
        self.__logger.info("Got search results back")

        for element in self.result.get_children():
            self.result.remove(element)

        if details['fullname']:
            self.details = details
            self.id = details['username']
            self.user_name = details['fullname']
            self.user_email = details['email']

            result_box = Gtk.Box(spacing=30)
            result_box.set_name("grd_result_button")

            self.user_button = Gtk.Button()
            self.user_button.set_name("btn_select_user")
            self.user_button.set_relief(Gtk.ReliefStyle.NONE)
            button_box = Gtk.Box(spacing=10)
            self.user_button.add(button_box)

            self.__logger.info("Found: " + details['fullname'])
            label = Gtk.Label(details['fullname'])

            img_series = Gtk.Image()

            if details['ocSeries']:
                self.__logger.info("     Series: " + details['ocSeries'][0]['identifier'])
                img_series.set_from_icon_name("object-select-symbolic", 2)
                self.user_button.connect("clicked", self.close_modal)
                self.series_id = details['ocSeries'][0]['identifier']
                self.series_title = details['ocSeries'][0]['title']
            else:
                img_series.set_from_icon_name("star-new-symbolic", 2)
                self.user_button.connect("clicked", self.create_series)
                self.series_id = ""
                self.series_title = ""

            button_box.pack_start(img_series, expand=False, fill=False, padding=10)
            button_box.pack_start(label, expand=False, fill=False, padding=10)

            label = Gtk.Label("select")
            label.set_markup('<span foreground="#494941" face="sans" size="small">select</span>')
            button_box.pack_start(label, expand=False, fill=False, padding=10)

            result_box.pack_start(self.user_button, expand=True, fill=True, padding=10)
            self.result.pack_start(result_box, expand=False, fill=False, padding=0)
        else:
            self.__logger.info(":(")
            self.details = None
            label = Gtk.Label("No student or lecturer found.")
            self.result.pack_start(label, expand=False, fill=False, padding=0)

        self.searching = False
        self.search_field.set_editable(True) # enabled
        self.result.show_all()

    def create_series(self, ev=None):
        conf = context.get_conf()

        self.__logger.info("Creating series")

        if self.user_button is not None:
            self.user_button.set_sensitive(False) # disabled

        for element in self.result.get_children():
            self.result.remove(element)

        loading_box = Gtk.Box(spacing=10)
        loading_box.set_name("grd_result_loading")

        label = Gtk.Label("")
        loading_box.pack_start(label, expand=False, fill=False, padding=0)

        spinner = Gtk.Spinner()
        spinner.start()
        loading_box.pack_start(spinner, expand=False, fill=False, padding=0)

        label = Gtk.Label(" Creating user profile... ")
        loading_box.pack_start(label, expand=False, fill=False, padding=0)

        label = Gtk.Label("")
        loading_box.pack_start(label, expand=False, fill=False, padding=0)

        self.result.pack_start(loading_box, expand=False, fill=False, padding=0)
        self.result.show_all()

        self.set_series_close_modal(self.call_create_series(self.details))

    def set_series_close_modal(self, resp):
        self.__logger.info("POST request returned.")

        if resp is not None:
            self.series_id = resp
            self.series_title = "Created Series: " + resp
            self.close_modal()
        else:
            self.series_id = ""
            self.series_title = ""

            for element in self.result.get_children():
                self.result.remove(element)

            loading_box = Gtk.Box(spacing=10)
            loading_box.set_name("grd_result_loading")

            label = Gtk.Label("")
            loading_box.pack_start(label, expand=False, fill=False, padding=0)

            img_error = Gtk.Image()
            img_error.set_from_icon_name("emblem-important", 5)
            loading_box.pack_start(img_error, expand=False, fill=False, padding=8)

            label = Gtk.Label("Could not create user profile")
            loading_box.pack_start(label, expand=False, fill=False, padding=0)

            label = Gtk.Label("")
            loading_box.pack_start(label, expand=False, fill=False, padding=0)

            self.result.pack_start(loading_box, expand=False, fill=False, padding=0)
            self.result.show_all()

    def close_modal(self, ev=None):
        self.__logger.info("closing modal")
        self.dialog.response(-10)

    def call_get_user_info(self, user_id):
        """
        Retreive user and series info from Opencast

        :param id: Staff / T / Student Number

        :return: Return dictionary structured content to set display name and series

        :raise ValueError: if the input arguments are not valid
        :raise OpencastException: if the communication to the opencast server fails
                                or an unexpected error occures
        """
        if not user_id:
            raise ValueError("user ID isn't set")

        result_data = {'fullname': '', 'email': '', 'username': '', 'site_id' : '', 'ocSeries' : [],
                       'ca_name': self.__oc_client.hostname}

        try:
            response = self.__oc_client.get_user_details(user_id)
            full_data = json.loads(response, encoding='utf8')
            # self.__logger.info(full_data)

            if full_data['user']['name']:
                result_data['fullname'] = full_data['user']['name']
                result_data['email'] = full_data['user']['email'].lower()
                result_data['username'] = full_data['user']['username'].lower()
                result_data['upperuser'] = full_data['user']['username'].upper()

        except Exception as exc:
            self.__logger.warning('call_get_user_info user [{1}]: {0}'.format(exc, user_id))

        try:
            response = self.__oc_client.get_personal_series(user_id, self.series_filter)

            if "Personal Series" in response:
                series_data = json.loads(response, encoding='utf8')

                if len(series_data) > 0:
                    result_data['ocSeries'] = series_data

        except Exception as exc:
            self.__logger.error('call_get_user_info series [{1}]: {0}'.format(exc, user_id))

        # self.__logger.info(result_data)
        return result_data

    def call_create_series(self, data):
        """
        Create a new Opencast Series with the data given

        :param data: Contains info about the series to be created

        :return: Return dictionary structured content to set display name and series

        :raise ValueError: if the input arguments are not valid
        :raise OpencastException: if the communication to the opencast server fails
                                or an unexpected error occures
        """
        global METADATA, ACL

        if not data:
            raise ValueError("user data isn't set")

        result = None
        try:
            m = METADATA.safe_substitute(data).encode('iso-8859-1')
            a = ACL.safe_substitute(data).encode('iso-8859-1')

            response = self.__oc_client.create_series(m, a)
            if response is not None:
                if "identifier" in response:
                    details = json.loads(response, object_hook=lambda d: namedtuple('X', d.keys())(*d.values()))
                    if details.identifier:
                        result = details.identifier

        except Exception as exc:
            self.__logger.error('call_create_series: {}'.format(exc))

        return result