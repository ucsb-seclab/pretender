#!/usr/bin/env python
# This is a re-implementation of the Seeed radio module
# so that we can make the tests cleaner.  Real radios have real 
# interference!

import serial
import os
import string
import random
from threading import Thread, Event
import logging
from time import sleep

logger = logging.getLogger(__name__)


class RFUARTStimulator(Thread):

    def __init__(self):
        self.reset()
        self._shutdown = Event()
        Thread.__init__(self)

    def reset(self):
        self.config_baud = 9600
        self.frequency = 433000000
        self.data_rate = 9600
        self.bandwidth = 300
        self.deviation = 50
        self.tx_power = 3
        self.baud_rate = 9600

    prob = 0.33

    def do_command(s):
        ok = "OK\r\n"
        no = "NO\r\n"
        cmd = s.read(size=1)
        print "Command %s" % repr(cmd)
        if cmd == '\xF0':
            # Reset
            self.reset()
            s.write(ok)
        elif cmd == '\xE1':
            # Get config
            data = struct.pack("IIHBBI", self.frequency, self.data_rate, self.bandwidth, self.deviation, self.tx_power, self.baud)
            s.send(data)
        elif cmd == '\x96':
            power = ord(s.read(size=1))
            if power > 0 and power < 8:
                self.power = power
                s.write(ok)
            else:
                s.write(no)
        else:
            s.write(no)

    def do_code(s):
        if random.random() < prob:
            # Send the lock code
            s.write("UNLOCK\0")
        else:
            code = "".join([random.choice(string.letters) for _ in range(0,6)])
            s.write(code + "\0")

    def run(self):
        
        s = serial.serial_for_url("hwgrep://ACM&skip_busy")

        while not self._shutdown.is_set():
            if s.readable():
                c = s.read(size=1)
                if c == '\xAA':
                    d = s.read(size=1)
                    if d == '\xFA':
                        self.do_command(s)
                else:
                    print repr(c)
            # Send a random byte
            if random.random() < self.prob:
                s.write("\xBB")
                self.do_code(s)
            else:
                s.write("\xdd")
                self.do_ping(s)
            sleep(0.1)

    def shutdown(self):
        self._shutdown.set()

if __name__ == '__main__':
    u = None
    try:
        u = RFUARTStimulator()
        u.run()
        sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        if u:
            u.shutdown()

