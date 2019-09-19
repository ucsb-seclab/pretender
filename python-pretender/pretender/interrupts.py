import logging

logger = logging.getLogger(__name__)
from threading import Thread, Event
from avatar2 import TargetStates
import time
from pretender.hooks import emulate_interrupt_enter_alt

class StatefulInterrupter(Thread):
    host = None

    def __init__(self, irq_num, trigger, timings):
        self.irq_num = irq_num
        self.trigger = trigger
        self.timings = timings
        self.irq_enabled = Event()
        self.interrupt_now = Event()
        self.started = Event()
        self._shutdown = Event()
        logger.debug("Creating Interrupter for IRQ %d" % self.irq_num)
        Thread.__init__(self)

    def send_interrupt(self):
        while self.interrupt_now.is_set():
            pass
        self.interrupt_now.set()

    def run(self):
        logger.info("Starting Stateful Interrupter for IRQ %d" % self.irq_num)
        self.started.set()
        if not self.host:
            raise RuntimeError("Must set host first")
        ignored = False
        while not self._shutdown.is_set():
            self.interrupt_now.wait()
            if not ignored:
                logger.info(
                    "Ignoring interrupt returns for IRQ %d" % self.irq_num)
                self.host.protocols.interrupts.ignore_interrupt_return(
                    self.irq_num)
                ignored = True
            logger.info("Sending IRQ %d" % self.irq_num)
            self.host.protocols.interrupts.inject_interrupt(self.irq_num)
            self.interrupt_now.clear()
            """
            while not self.irq_enabled.is_set() or self.host.state != TargetStates.RUNNING:
                pass
            logger.info("Ignoring interrupt returns for IRQ %d" % self.irq_num)
            self.host.protocols.interrupts.ignore_interrupt_return(self.irq_num)
            t = 0
            while not self._shutdown.is_set() and self.irq_enabled.is_set() and self.host.state == TargetStates.RUNNING:
                self.interrupt_now.wait()
                logger.info("Sending IRQ %d" % self.irq_num)
                self.host.protocols.interrupts.inject_interrupt(self.irq_num)
                self.interrupt_now.clear()
            """


class Interrupter(Thread):
    host = None  # The host to be interrupted. MUST SET AT RUNTIME

    # This is probably a QemuTarget

    def __init__(self, peripheral, irq_num, trigger, timings, oneshot=False):
        self.peripheral = peripheral
        self.irq_num = irq_num
        self.trigger = trigger
        self.timings = timings
        self.irq_enabled = Event()
        self.started = Event()
        self._shutdown = Event()
        self.oneshot = oneshot
        logger.debug("Creating Interrupter for IRQ %d" % self.irq_num)
        Thread.__init__(self)

    def run(self):
        logger.info("Starting Interrupter for IRQ %d" % self.irq_num)
        self.started.set()
        if not self.host:
            raise RuntimeError("Must set host first")
        ignored = False
        while not self._shutdown.is_set():
            t = 0
            while not self._shutdown.is_set() and self.irq_enabled.is_set() and self.host.state == TargetStates.RUNNING:
                #if not ignored:
                #    logger.info("Ignoring interrupt returns for IRQ %d" % self.irq_num)
                #    self.host.protocols.interrupts.ignore_interrupt_return(self.irq_num)
                #    ignored = True
                next_time = self.timings[t]
                logger.info("[%d] Sleeping for %f" % (self.irq_num, next_time))
                time.sleep(next_time)
                # DO IT
                logger.info("Sending IRQ %d" % self.irq_num)
                self.host.protocols.interrupts.inject_interrupt(self.irq_num)
                #emulate_interrupt_enter_alt(irq_num)
                self.peripheral.enter(self.irq_num)
                t = (t + 1) % len(self.timings)
                # If you had.... one shot..... one opportunity
                if self.oneshot:
                    logger.warn("One shotted IRQ %d" % self.irq_num)
                    self.irq_enabled.clear()
    def shutdown(self):
        self._shutdown.set()

