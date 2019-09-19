#!/usr/bin/env python

import serial
import os
import random
from threading import Thread, Event
import logging
from time import sleep
import sys

logger = logging.getLogger(__name__)


class UARTReader(Thread):

    def __init__(self):
        self._shutdown = Event()
        self._connected = Event()
        Thread.__init__(self)

    prob = 0.33

    def wait_for_connection(self):
        self._connected.wait()

    def get_serial_port(self):
        while not self._shutdown.is_set():
            try:
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
                if s.readable():
                    sys.stdout.write(s.read(size=1))
            s.close()
        except serial.serialutil.SerialException:
            print("Lost connection to serial port, exiting...")
        finally:
            self._connected.clear()

    def shutdown(self):
        self._shutdown.set()


if __name__ == '__main__':
    u = None
    try:
        u = UARTReader()
        u.start()
        sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        u.shutdown()

