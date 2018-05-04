import PyCmdMessenger

# Initialize an ArduinoBoard instance.  This is where you specify baud rate and
# serial timeout.  If you are using a non ATmega328 board, you might also need
# to set the data sizes (bytes for integers, longs, floats, and doubles).  
arduino = PyCmdMessenger.ArduinoBoard("/dev/ttyACM0",baud_rate=115200)

# List of command names (and formats for their associated arguments). These must
# be in the same order as in the sketch.
commands = [["SetLed","???"],
            ["error","s"]]

# Initialize the messenger
c = PyCmdMessenger.CmdMessenger(arduino,commands)

# Send
c.send("SetLed", 1, 0, 0)

msg = c.receive()
print(msg)

