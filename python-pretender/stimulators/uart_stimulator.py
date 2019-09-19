#!/usr/bin/env python

import serial
import os
import random
from threading import Thread, Event
import logging
from time import sleep

logger = logging.getLogger(__name__)

class UARTStimulator(Thread):

    def __init__(self):
        self._shutdown = Event()
        Thread.__init__(self)

    prob = 0.33

    def run(self):
        
        s = serial.serial_for_url("hwgrep://ACM&skip_busy")
        
        while not self._shutdown.is_set():
            # Send a random byte
            if random.random() < self.prob:
                print ">>> 1"
                s.write("1")
            else:
                print ">>> 0"
                s.write("0")
            sleep(0.1)

    def shutdown(self):
        self._shutdown.set()



if __name__ == '__main__':
    u = None
    try:
        u = UARTStimulator()
        u.run()
        sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        u.shutdown()

