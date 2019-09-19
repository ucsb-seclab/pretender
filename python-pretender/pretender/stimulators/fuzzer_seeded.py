#!/usr/bin/env python

import serial
import os
import random
from threading import Thread, Event
import logging
from time import sleep
import pickle
logger = logging.getLogger(__name__)

class SeededFuzzer(Thread):

    def __init__(self, tcpserial=False, fname=None):
        self._shutdown = Event()
        self.fname = fname
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

    def load_model_data(self, fn, addr=0x40004404):
        with open(fn, 'rb') as f:
            print("Going to unpickle")
            m = pickle.load(f)
            print("Unpickled")
            mdl = m[addr]['model']
            s = ""
            print("Loaded. Parsing...")
            for tr in mdl.trace:
                try:
                    n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = tr
                except:
                    print("Poop")
                if n_addr == addr and n_op == "READ":
                    s +=chr(n_val)
                    print(repr(chr(n_val)))
        print("Seed: %s" % repr(s))
        return s

    def run(self):
        print("Loading model data...")
        try:
            seed = 'OK\r\nOK\r\n@\x0e\xcf\x19\x80%\x00\x00,\x012\x07\x80%\x00\x00\xdd\xbbubRMsz\x00\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xbbPVcoge\x00\xdd\xdd\xbbVfqcLy\x00\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xbbaiQoJJ\x00\xbbAnGoWH\x00\xdd\xdd\xdd\xdd\xbbMOlfJK\x00\xdd\xbbOYUHNw\x00\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xbbZxJsbB\x00\xdd\xdd\xbbCAKJxa\x00\xdd\xdd\xbbUNLOCK\x00\xdd\xdd\xbbUNLOCK\x00\xdd\xbbXzNEIX\x00\xdd\xdd\xdd\xbbLiWuff\x00\xdd\xdd\xbbUNLOCK\x00\xbbDEpTiv\x00\xdd\xdd\xdd\xdd\xdd\xdd\xbbUNLOCK\x00\xbbkPsoZO\x00\xdd\xdd\xbbUNLOCK\x00\xdd\xdd\xbbYIDCXe\x00\xdd\xdd\xbbHyzfLD\x00\xdd\xdd\xdd\xbbellZrN\x00\xdd\xdd\xbbUNLOCK\x00\xbbaqdebo\x00\xdd\xdd\xdd\xdd\xbbxtGdGS\x00\xdd\xbbUNLOCK\x00\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xbbWoRadp\x00\xdd\xdd\xbbHJRBbV\x00\xdd\xdd\xdd\xdd\xbbUNLOCK\x00\xdd\xdd\xbbUNLOCK\x00\xdd\xdd\xdd\xbbtwgaRJ\x00\xbbNvMdCV\x00\xdd\xbbroJGTr\x00\xbbUNLOCK\x00\xdd\xdd\xbbjkjjme\x00\xbbGLTQiZ\x00\xbbIlKogJ\x00\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xbbfaCuWi\x00\xdd\xdd\xbbRBQYom\x00\xbbANxvOv\x00\xdd\xdd\xdd\xbbDhUaIV\x00\xdd\xdd\xdd\xdd\xbbUNLOCK\x00\xbbKLtJMw\x00\xbbUNLOCK\x00\xbbRQPOCu\x00\xdd\xdd\xbbUNLOCK\x00\xdd\xdd\xdd\xdd\xbbENoMgu\x00\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xdd\xbbUNLOCK\x00\xdd\xdd\xbbzvPYhT\x00\xdd\xdd\xdd\xdd\xdd\xbb'
            #seed = self.load_model_data(self.fname)
        except:
            logger.exception("Error loading model data")
        s = self.get_serial_port()
        try:
            print repr(s.read(size=1))
            while not self._shutdown.is_set():
                # Send a random byte
                if s.in_waiting > 0:
                    print(repr(s.read(size=1)))
                    continue
                if s.writable():
                    if len(seed) > 0:
                        c = seed[0]
                        if len(seed) == 1:
                            print("Seed done")
                            seed = ""
                        else:
                            seed = seed[1:]
                    else:
                        c = chr(random.randint(0, 255))
                    s.write(c)
                    sys.stdout.write(repr(c))
                    sys.stdout.flush()
                if s.in_waiting > 0:
                    sys.stdout.write(s.read(size=1))
                sleep(0.1)
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
    fname = None
    if len(sys.argv) > 1 and sys.argv[1] == 'tcp':
        tcpserial = True
    if len(sys.argv) > 2:
        fname = sys.argv[2]
    try:
        u = SeededFuzzer(tcpserial=tcpserial, fname=fname)
        u.start()
        while not u._shutdown.is_set():
            pass
    except KeyboardInterrupt:
        pass
    finally:
        if u:
            u.shutdown()

