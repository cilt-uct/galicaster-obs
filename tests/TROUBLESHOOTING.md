
```
echo 'KERNEL=="event*", NAME="input/%k", MODE="660", GROUP="input"' | sudo tee -a /etc/udev/rules.d/99-input.rules
ll /etc/udev/rules.d/
reboot
```

```
root@test-ca:~# lsusb
Bus 002 Device 002: ID 8087:0024 Intel Corp. Integrated Rate Matching Hub
Bus 002 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 001 Device 005: ID 046d:0821 Logitech, Inc. HD Webcam C910
Bus 001 Device 006: ID 0461:4e22 Primax Electronics, Ltd
Bus 001 Device 003: ID 413c:2106 Dell Computer Corp. Dell QuietKey Keyboard
Bus 001 Device 002: ID 8087:0024 Intel Corp. Integrated Rate Matching Hub
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 004 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 003 Device 003: ID 077d:0410 Griffin Technology PowerMate
Bus 003 Device 002: ID 2575:8753
Bus 003 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
```

```
pip install tzlocal
pip install requests
pip install requests_futures
```

```
vi /etc/galicaster/conf.ini

[plugins]
powermate = True

[powermate]
server = http://test.uct.ac.za
```

Using Gentoo's gentoo-sources-4.4.0, python-evdev generates from a input.h which causes it to fail on input:
```
python
Python 2.7.11 (default, Jan 21 2016, 21:00:40)
[GCC 5.3.0] on linux2
Type "help", "copyright", "credits" or "license" for more information.

from evdev import UInput, UInputError, ecodes
Traceback (most recent call last):
File "", line 1, in
File "/usr/lib64/python2.7/site-packages/evdev/init.py", line 5, in
from evdev.device import DeviceInfo, InputDevice, AbsInfo
File "/usr/lib64/python2.7/site-packages/evdev/device.py", line 7, in
from evdev import _input, _uinput, ecodes, util
File "/usr/lib64/python2.7/site-packages/evdev/ecodes.py", line 75, in
keys.update(BTN)
NameError: name 'BTN' is not defined
```

This affects at least python-evdev 0.4.5 and 0.5.0 and can be fixed by downgrading both the kernel and sys-kernel/linux-headers to version 4.3, then rebuilding python-evdev.

To Fix:
```
sudo pip install evdev==0.5.0
sudo pip install --upgrade git+https://github.com/gvalkov/python-evdev.git@631e2d32d7bdf38e3d7a5c850c9f5869d61e9183
```

```
sudo usermod -a -G dialout galicaster
sudo usermod -a -G input galicaster
sudo usermod -a -G tty galicaster
```

```
>>> import serial.tools.list_ports
>>> ports = list(serial.tools.list_ports.comports())
>>> for p in ports:
...     print p
...
/dev/ttyS4 - n/a
/dev/ttyS0 - ttyS0
/dev/ttyUSB0 - USB2.0-Serial
>>> print ports
[<serial.tools.list_ports_linux.SysFS object at 0x7f383316c690>, <serial.tools.list_ports_linux.SysFS object at 0x7f3833179710>, <serial.tools.list_ports_linux.SysFS object at 0x7f38331790d0>]

>>> import serial
>>> ser = serial.Serial('/dev/ttyUSB0', 115200)
>>> ser.write('SetLed,1,0,0;')
13
>>> ser.write('SetLed,0,0,1;')
13
>>> ser.write('SetLed,0,1,1;')
13
>>> ser.write('SetLed,1,1,1;')
13
>>> ser.write('SetLed,0,0,0;')
13
>>> exit()


/dev/ttyUSB0
/dev/ttyACM0
>>> l = []
>>> for p in arduino_ports:
...   l.append( serial.Serial(p, 115200) )
...
>>> l
[Serial<id=0x7fbf12369e50, open=True>(port='/dev/ttyUSB0', baudrate=115200, bytesize=8, parity='N', stopbits=1, timeout=None, xonxoff=False, rtscts=False, dsrdtr=False), Serial<id=0x7fbf12369f90, open=True>(port='/dev/ttyACM0', baudrate=115200, bytesize=8, parity='N', stopbits=1, timeout=None, xonxoff=False, rtscts=False, dsrdtr=False)]
>>> for p in l:
...   l.write('SetLed,1,0,0;')
...
Traceback (most recent call last):
  File "<stdin>", line 2, in <module>
AttributeError: 'list' object has no attribute 'write'
>>> for p in l:
...   p.write('SetLed,1,0,0;')


import warnings
import serial
import serial.tools.list_ports

arduino_ports = [
    p.device
    for p in serial.tools.list_ports.comports()
    if ('Serial' in p.description) or ('Arduino' in p.description) or (p.device.startswith('/dev/ttyACM'))
]

for p in arduino_ports:
  print p

l = []
>>> for p in arduino_ports:
...   l.append( serial.Serial(p, 115200) )

ser = serial.Serial(arduino_ports[0], 115200)
print ser.write('SetLed,0,0,1;')




if 'Serial' or 'Arduino' in p.description
/*
#if not arduino_ports:
#    raise IOError("No Arduino found")

#if len(arduino_ports) > 1:
#    warnings.warn('Multiple Arduinos found - using the first')
*/
```