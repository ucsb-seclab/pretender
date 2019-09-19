#!/usr/bin/env python

import serial
import os
import random
from threading import Thread, Event
import logging
from time import sleep

logger = logging.getLogger(__name__)

class Fuzzer(Thread):

    def __init__(self, tcpserial=False):
        self._shutdown = Event()
        self._connected = Event()
        self.tcpserial = tcpserial
        Thread.__init__(self)

    def wait_for_connection(self):
        self._connected.wait()

    def get_serial_port(self):
        while not self._shutdown.is_set():
            try:
                if tcpserial:
                    s = serial.serial_for_url("socket://localhost:5656")
                else:
                    s = serial.serial_for_url("hwgrep://ACM&skip_busy")
                print("Connected.")
                self._connected.set()
                return s
            except serial.serialutil.SerialException:
                print("Port is busy, trying again...")
                sleep(0.25)

    def run(self):
        s = self.get_serial_port()
        try:
            while not self._shutdown.is_set():
                # Send a random byte
                if s.writable():
                    c = chr(random.randint(0, 255))
                    s.write(c)
                    sys.stdout.write(repr(c))
                    sys.stdout.flush()
                if s.in_waiting > 0:
                    sys.stdout.write(s.read(size=1))
                #sleep(0.1)
            s.close()
        except serial.serialutil.SerialException:
            print("Lost connection to serial port, exiting...")
        finally:
            self._connected.clear()


    def shutdown(self):
        self._shutdown.set()



if __name__ == '__main__':
    u = None
    import sys
    tcpserial = False
    if len(sys.argv) > 1 and argv[1] == 'tcp':
        tcpserial = True
    try:
        u = Fuzzer(tcpserial=tcpserial)
        u.start()
        while not u._shutdown.is_set():
            pass
    except KeyboardInterrupt:
        pass
    finally:
        u.shutdown()

