# These are the hooks for recording and replay
import os

import pretender.globals as G
import logging
from pretender.logger import LogWriter
import time

l = logging.getLogger("pretender.hooks")
logger = l
seq = 0

ignored_ranges = []


def record_read_after(avatar, message, **kwargs):
    """
    prints our read message
    see avatar.ui.message.py
    """
    global seq
    _, val, success = kwargs['watched_return']

    if not message.dst or 'model' in message.dst.name:
        l.debug("IGNR:  %s (%s, %s) @ %s" % (message, hex(message.address), val,
                                             hex(message.pc)))
    else:
        l.debug("READ:  %s (%s, %s) @ %s" % (message, hex(message.address), val,
                                             hex(message.pc)))
        G.MEM_LOG.write_row(
            ['READ',seq, message.address, val, message.pc, message.size,
             time.time()])
        # pprint.pprint(kwargs)
        seq += 1


def record_write_after(avatar, message, **kwargs):
    """
    prints our write message
    see avatar.ui.message.py
    """
    global seq
    _, val, success = kwargs['watched_return']
    if not message.dst or "model" in message.dst.name:
        l.debug("IGNW %s (%s,%s) @ %s" % (message, hex(message.address),
                                           message.value, hex(message.pc)))
    else:
        l.debug("WRITE %s (%s,%s) @ %s" % (message, hex(message.address),
                                         message.value, hex(message.pc)))
        G.MEM_LOG.write_row(
            ['WRITE', seq, message.address, message.value, message.pc,
             message.size, time.time()])
        # pprint.pprint(kwargs)
        seq += 1


def record_interrupt_enter(avatar, message, **kwargs):
    global seq
    #message.origin.wait()
    #isr = message.origin.protocols.interrupts.get_current_isr_num()
    isr = message.interrupt_num
    # TODO: Fill this out with something more intelligent
    G.MEM_LOG.write_row(['ENTER', seq, isr, 0, 0, 0, time.time()])
    l.warning\
        ("ENTER %s %s" % (hex(isr), message))
    seq += 1


def record_interrupt_exit(avatar, message, **kwargs):
    global seq
    # TODO: Fill this out with something more intelligent

    isr = message.interrupt_num
    G.MEM_LOG.write_row(['EXIT', seq, isr, 0, 0, 0, time.time()])
    l.warning("EXIT %s %s" % (hex(isr), message))
    seq += 1


def record_interrupt_return(avatar, message, **kwargs):
    # TODO: Actually make this work, return is different from exit
    # TODO: Fill this out with something more intelligent
    G.MEM_LOG.write_row(['EXIT', message.id, isr, 0, 0, 0, time.time()])
    l.debug("RETURN %s %s" % (hex(isr), message))



##
## Emulation hooks
##

def emulate_interrupt_enter(avatar, message, **kwargs):
    # message.origin.wait()
    print message
    # isr = message.origin.protocols.interrupts.get_current_isr_num()
    # TODO: Fill this out with something more intelligent
    G.OUTPUT_TSV.write_row(['ENTER', message.id, message.interrupt_num, 0, 0, 0, time.time()])
    # l.warning("ENTER %s %s" % (hex(isr), message))
    # seq += 1

def emulate_interrupt_enter_alt(irq_num, **kwargs):
    # message.origin.wait()
    print message
    # isr = message.origin.protocols.interrupts.get_current_isr_num()
    # TODO: Fill this out with something more intelligent
    G.OUTPUT_TSV.write_row(
        ['ENTER', 0, self.irq_num, 0, 0, 0, 'Interrupter:%d' % irq_num])
    # l.warning("ENTER %s %s" % (hex(isr), message))
    # seq += 1


def emulate_interrupt_exit(avatar, message, **kwargs):
    print message
    # TODO: Fill this out with something more intelligent
    G.OUTPUT_TSV.write_row(['EXIT', message.id, message.interrupt_num, 0, 0, 0, time.time()])
    l.warning("EXIT %s %s" % (hex(message.interrupt_num), message))


def emulate_read_before(avatar, message, **kwargs):
    """
    prints our read message
    see avatar.ui.message.py
    """
    print "READ BEFORE:  %s (%s)" % (message, hex(message.address))
    # mem_log.write_row(
    #     ['READ', message.id, message.address, val, message.pc, message.size])
    pprint.pprint(kwargs)


def emulate_write_before(avatar, message, **kwargs):
    """
    prints our write message
    see avatar.ui.message.py
    """
    print "WRITE BEFORE: %s (%s,%s)" % (message, hex(message.address),
                                        message.value)

    # mem_log.write_row(
    #     ['WRITE', message.id, message.address, val, message.pc, message.size])
    # pprint.pprint(kwargs)


def emulate_read_after(avatar, message, **kwargs):
    """
    prints our read message
    see avatar.ui.message.py
    """
    _, val, success = kwargs['watched_return']
    # logger.info("READ:  %s (%s, %s)" % (message, hex(message.address), val))

    # print "REAL: %s, %s" % (hex(message.address), val)
    # model_val = pretender_model.read_memory(message.address, message.size)
    # if model_val != val:
    #    print "Poop"
    try:
       mdl_name = message.dst.python_peripheral.get_model(message.address) 
    except:
        try:
            mdl_name = message.dst.python_peripheral.get_model(message.address)
        except:
            mdl_name = "ERR"
    # logger.info("MODEL: %s, %s" % (hex(message.address), model_val))
    G.OUTPUT_TSV.write_row(
        ['READ', message.id, hex(int(message.address)), int(val), hex(int(message.pc)), message.size,
         mdl_name])
    if message.address == 0x40004404:
        logger.info("<<< %s" % hex(val))

    # mem_log.write_row(
    #     ['READ', message.id, message.address, val, message.pc, message.size])
    # pprint.pprint(kwargs)


def emulate_write_after(avatar, message, **kwargs):
    """
    prints our write message
    see avatar.ui.message.py
    """
    _, val, success = kwargs['watched_return']
    if message.address > 0xe0000000:
        return
    try:
        mdl_name = message.dst.python_peripheral.get_model(message.address)
    except:
        try:
            mdl_name = message.dst.forwarded_to.model.get_model(message.address)
        except:
            mdl_name = "Eme = message.dst.python_peripheral.get_model(message.address)RR"
    # logger.info("WRITE: %s (%s,%s)" % (message, hex(message.address),
    #                                   message.value))
    # pretender_model.write_memory(message.address, message.size, message.value)
    G.OUTPUT_TSV.write_row(
        ['WRITE', message.id, hex(int(message.address)), int(message.value),
         hex(int(message.pc)), message.size, mdl_name])

    if message.address == 0x40004404:
        logger.info(">>> %s" % hex(message.value))
    if message.address == 0x40020018:
        print "LED ON", time.time()
    elif message.address == 0x40020028:
        print "LED OFF", time.time()
        # mem_log.write_row(
        #     ['WRITE', message.id, message.address, val, message.pc, message.size])
        # pprint.pprint(kwargs)

