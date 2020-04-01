import json
from datetime import timedelta, datetime, tzinfo
from collections import namedtuple
from dateutil.parser import parse
from tzlocal import get_localzone

import requests

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


url = "http://camonitor.uct.ac.za/obs-api/event/"

myResponse = requests.get(url)

if (myResponse.ok):
    x = json.loads(myResponse.content, object_hook=lambda d: namedtuple('X', d.keys())(*d.values()))
    now = datetime.now(GMT2())
    print("Now: "+ now.astimezone(get_localzone()))

    for line in x:
        if line.ocSeries is not None:
            start = parse(line.start.dateTime + 'Z')
            
            end = parse(line.start.dateTime + 'Z')
            
            if start < now < end:
                print "scheduled event"
                print(start.astimezone(get_localzone()))
                print(end.astimezone(get_localzone()))
            else:
                print "no event"

