#!/usr/bin/env python

import serial
import os
import string
import random
from threading import Thread, Event
import logging
from time import sleep
import struct
import sys
logger = logging.getLogger(__name__)


class RFUARTStimulator(Thread):

    def __init__(self, tcpserial=False):
        self.reset()
        self._shutdown = Event()
        self._connected = Event()
        self.config_baud = 9600
        self.frequency = 433000000
        self.data_rate = 9600
        self.bandwidth = 300
        self.deviation = 50
        self.tx_power = 3
        self.baud = 9600
        self.tcpserial = tcpserial
        Thread.__init__(self)

    def wait_for_connection(self):
        self._connected.wait()

    def reset(self):
        self.config_baud = 9600
        self.frequency = 433000000
        self.data_rate = 9600
        self.bandwidth = 300
        self.deviation = 50
        self.tx_power = 3
        self.baud_rate = 9600
        self.code = "UNLOCK\0"

    prob = 0.33
    prob2 = 0.88
    def write_buf(self, s, buf):
        for x in buf:
            while not s.writable() and not self._shutdown.is_set():
                pass
            print repr(x)
            s.write(x)
            sleep(0.5)

    def do_command(self, s):
        ok = "OK\r\n"
        no = "NO\r\n"
        cmd = self.read_stuff(s)
        print("Command %s" % repr(cmd))
        if cmd == '\xF0':
            # Reset
            print("Doing a reset.")
            self.reset()
            sleep(0.2)
            self.write_buf(s, ok)
        elif cmd == '\xE1':
            # Get config
            sleep(0.2)
            data = struct.pack("IIHBBI", self.frequency, self.data_rate, self.bandwidth, self.deviation, self.tx_power, self.baud)
            print("Dumping configuration")
            print(data.encode('hex'))
            self.did_initial_config = True
            self.write_buf(s, data)
        elif cmd == '\x96':
            sleep(0.2)
            power = ord(self.read_stuff(s))
            if 0 <= power < 8:
                print("Setting TX power to %d" % power)
                self.tx_power = power
                self.write_buf(s, ok)
            else:
                print("Bad TX power %d" % power)
                self.write_buf(s, no)
        else:
            self.write_buf(no)

    def do_code(self, s):
        if random.random() < self.prob:
            print("Sending the unlock code")
            # Send the lock code
            self.write_buf(s, self.code + '\0')
        else:
            code = "".join([random.choice(string.letters) for _ in range(0,6)])
            print("Sending random garbage %s" % repr(code))
            self.write_buf(s, code + "\0")


    def read_stuff(self, s):
        # The serial port on the F0 sends every other character as a null.  
        # Uh... Ok...
        c = s.read(size=1)
        print "1 " + repr(c)
        if c == '\0':
            c2 = s.read(size=1)
            print "2 " + repr(c2)
            if c2 == '\0' or c2 == '':
                return c
            return c2
        return c

    def do_set_code(self, s):
        code = "".join([random.choice(string.letters) for _ in range(0,6)])
        self.code = code
        s.write('\xff')
        sleep(0.25)
        print("Setting code to %s" % repr(code))
        self.write_buf(s, code + "\n")
        print(repr(s.read(size=1)))
        print("Done")

    def do_ping(self, s):
        c = self.read_stuff(s)
        logger.info("Got pong with %s" % repr(c))

    def get_serial_port(self):
        while not self._shutdown.is_set():
            try:
                if self.tcpserial:
                    s = serial.serial_for_url("socket://localhost:5656")
                else:
                    s = serial.serial_for_url("hwgrep://ACM&skip_busy")
                print("Connected.")
                self._connected.set()
                return s
            except serial.serialutil.SerialException:
                print("Port is busy, trying again...")
                sleep(0.25)

    did_initial_config = False

    def run(self):
        self.s = self.get_serial_port()
        self.s.timeout = 5
        try:
            while not self._shutdown.is_set():
                if self.s.readable():
                    if not self.did_initial_config:
                        c = self.read_stuff(self.s)
                        if c == '\xAA':
                            print "hi"
                            d = self.read_stuff(self.s)
                            print repr(d)
                            if d == '\xFA':
                                self.do_command(self.s)
                        elif c == '\x00':
                            continue # ignore nulls
                        else:
                            self.did_initial_config = True
                            print "Config done"
                            print repr(c)
                            sleep(0.2)
                    else:
                        print repr(self.read_stuff(self.s))
                else:
                    print("omg")
                # Send a random byte
                if self.s.writable() and self.did_initial_config:
                    rnd = random.random()
                    if rnd < self.prob:
                        print("Sending a code")
                        self.s.write("\xBB")
                        sleep(0.2)
                        self.do_code(self.s)
                    elif rnd > self.prob2:
                        self.do_set_code(self.s)
                    else:
                        self.s.write("\xdd")
                        print("Sending a ping")
                        #self.do_ping(s)
                else:
                    print("Kthx")
                print("Poop")
                sleep(0.5)
                print("Lol")
        except serial.serialutil.SerialException:
            print("Lost connection to serial port, exiting...")
        finally:
            print("All done")
            self._connected.clear()

    def shutdown(self):
        self.s.close()
        self._shutdown.set()


if __name__ == '__main__':
    u = None
    try:
        tcpserial = False
        if len(sys.argv) > 1 and sys.argv[1] == "tcp":
            tcpserial = True
        u = RFUARTStimulator(tcpserial=tcpserial)
        u.start()
        while (True):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        if u:
            u.shutdown()

