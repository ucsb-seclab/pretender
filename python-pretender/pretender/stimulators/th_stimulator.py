#!/usr/bin/env python

import serial
import os
import random
from threading import Thread, Event, Timer
import logging
from time import sleep

logger = logging.getLogger(__name__)


class THStimulator(Thread):

    def __init__(self):
        self._shutdown = Event()
        self._connected = Event()
        Thread.__init__(self)
        self.cmd_timer = None
        self.s = None
    prob = 0.5

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

    def random_th(self):
        # Send a random byte
        if random.random() < self.prob:
            print(">>> t")
            self.s.write("t")
        else:
            print(">>> h")
            self.s.write("h")
        self.cmd_timer = Timer(2, self.random_th)
        self.cmd_timer.start()

    def run(self):
        self.s = self.get_serial_port()
        self.cmd_timer = Timer(2, self.random_th)
        self.cmd_timer.start()
        try:
            while not self._shutdown.is_set():
                print self.s.readline()
            self.s.close()
        except serial.serialutil.SerialException:
            print("Lost connection to serial port, exiting...")
        finally:
            cmd_timer.cancel()
            self._connected.clear()

    def shutdown(self):
        self._shutdown.set()


if __name__ == '__main__':
    u = None
    try:
        u = THStimulator()
        u.start()
        sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        u.shutdown()

