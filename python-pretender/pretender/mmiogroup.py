"""
Putting this in its own file for now
"""
import logging

from pretender.interrupts import StatefulInterrupter
from pretender.models.simple_storage import SimpleStorageModel

logger = logging.getLogger(__name__)


class MMIOGroup:
    """
    This represents a group of (at the moment, spatially-clustered) peripheral locations
    It contains a set of models for each register in its set.
    For any register which we cannot fit an easy model, we default to "stateful replay", our
    state machine inference trick.
    """

    def __init__(self, addresses, trace, irq_num=None, interrupt_trigger=None,
                 interrupt_timings=None):
        self.models = {x: None for x in addresses}
        self.trace = trace
        self.state = -1  # The location in the trace where we are now.
        self.irq_num = irq_num
        self.interrupt_trigger = interrupt_trigger
        self.interrupt_timings = interrupt_timings
        self.interrupter = None

    def min_addr(self):
        return sorted(self.models.keys())[0]

    def max_addr(self):
        return sorted(self.models.keys())[-1]

    def build_interrupter(self):
        # Backwards compat hack
        if not hasattr(self, 'interrupter') or self.interrupter:
            return
        if self.interrupt_timings and self.interrupt_trigger and self.irq_num:
            logger.info("Building an interrupter for IRQ %d" % self.irq_num)
            self.interrupter = StatefulInterrupter(self.irq_num,
                                                   self.interrupt_trigger,
                                                   self.interrupt_timings)

    def send_interrupts_to(self, host):
        assert host is not None
        self.build_interrupter()
        if hasattr(self, 'interrupter') and self.interrupter:
            if not self.interrupter.started.is_set():
                self.interrupter.host = host
                self.interrupter.start()
                self.interrupter.started.wait()

    def shutdown(self):
        if self.interrupter:
            self.interrupter.shutdown()

    def merge(self, other_model):

        my_keys = sorted(self.models.keys())
        their_keys = sorted(self.models.keys())
        if my_keys == their_keys:
            for a in self.models.keys():
                m_mine = self.models[a]
                m_theirs = other_model.models[a]
                if not m_mine:
                    m_mine = m_theirs
                elif not m_theirs:
                    pass
                else:
                    m_mine.merge(m_theirs)
                self.models[a] = m_mine
        else:
            logger.error("Can't non-naively merge MMIO groups right now")

    def write_memory(self, address, size, value):
        """
        On a write, we need to check if this value affects any other address
        return values and update the state accordingly

        :param address:
        :param size:
        :param value:
        :return:
        """
        # Update the state
        old_state = self.state
        new_state = self._write_stateful_forwards(address, size, value)
        # Check if we can interrupt things.
        if hasattr(self, 'interrupter') and self.interrupter:
            if self.interrupt_trigger[0] == address:
                if self.interrupt_trigger[1] == value:
                    logger.info("Got trigger for IRQ %d" % self.irq_num)
                    self.interrupter.irq_enabled.set()
                else:
                    logger.info("Un-trigger IRQ %d" % self.irq_num)
                    self.interrupter.irq_enabled.clear()

        if new_state is None:
            # We've never written that before.  Don't do anything
            # TODO maybe prefer the address with a similar value here
            logger.warning(
                "Writing an unknown value at %#08x => %#08x" % (address, value))
        else:
            self.state = new_state
        logger.debug("Updating state from %d to %d" % (old_state, self.state))
        try:
            mdl = self.models[address]
            if mdl is None:
                # This is one of the hard cases.  Do the stateful replay thing.
                # So, for a write, nothing except sync the state.
                self.check_for_interrupt(self.state)
                return True
            self.check_for_interrupt(self.state)
            return mdl.write(value)
        except KeyError:
            self.models[address] = SimpleStorageModel(init_value=value)

    def check_for_interrupt(self, state):
        new_state = self.state + 1
        if new_state >= len(self.trace):
            return
        n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[
            new_state]
        if n_op == "ENTER" and self.interrupter:
            logger.debug("Time for an interrupt %d!" % self.interrupter.irq_num)
            self.interrupter.send_interrupt()
            self.state = new_state
        elif n_op == "EXIT":
            # That's nice, but what sbout the net one
            logger.debug("Time for an exit")
            self.state = new_state
            new_state += 1
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[
                new_state]
            if n_op == "ENTER" and self.interrupter:
                logger.debug(
                    "Time for ANOTHER interrupt %d!" % self.interrupter.irq_num)
                self.interrupter.send_interrupt()
                self.state = new_state

    def __write_stateful_backwards(self, addr, size, value):
        # The state we're looking for is not in front of us, find the most recent one that's behind us
        new_state = self.state
        while True:
            if new_state < 0:
                # It's not anywhere.  Start at the beginning of the trace!
                return None
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[
                new_state]
            if n_op == 'EXIT':
                logger.debug("Skipping over interrupt backwards")
                while True:
                    if new_state < 0:
                        logger.warning(
                            "Error finding interrupt enter during backtrack")
                        # It's not anywhere.  Start at the beginning of the trace!
                        return None
                    n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = \
                        self.trace[new_state]
                    if n_op == "ENTER":
                        break
                    new_state -= 1
            elif n_op == "WRITE" and n_addr == addr and n_val == value:
                return new_state
            new_state -= 1

    def _write_stateful_forwards(self, address, size, value):
        """
        Find the next write to this location, with this value, scanning forward in the trace
        If we can't find it, look behind us for the most recent write.
        :param address:
        :param size:
        :param value:
        :return:
        """
        new_state = self.state + 1
        while new_state < len(self.trace):
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[
                new_state]
            if n_op == "WRITE" and n_addr == address and n_val == value:
                return new_state
            if n_op == 'ENTER':
                logger.debug("Skipping over interrupt forwards")
                while True:
                    if new_state >= len(self.trace):
                        logger.warning(
                            "Error finding interrupt exit during forward")
                        # It's not anywhere.
                        return self.__write_stateful_backwards(address, size,
                                                               value)
                    n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = \
                        self.trace[new_state]
                    if n_op == "EXIT":
                        break
                    new_state += 1
            new_state += 1
        # We didn't find it. Look behind us
        return self.__write_stateful_backwards(address, size, value)

    def __find_reset_value(self, address, size):
        for state, tr in enumerate(self.trace):
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = tr
            if n_op == "READ" and n_addr == address:
                return state
        return None

    def __read_stateful_backwards(self, address, size):
        # The state we're looking for is not in front of us, find the most recent one that's behind us
        new_state = self.state
        while new_state > 0:
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[
                new_state]
            if n_op == "READ" and n_addr == address:
                return new_state
            new_state -= 1
        # Welp, we've fucked up, and we have never read this address before
        return self.__find_reset_value(address, size)

    def _read_stateful_forward(self, address, size):
        new_state = self.state + 1
        if new_state >= len(self.trace):
            return self.__read_stateful_backwards(address, size)
        while new_state < len(self.trace):
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[
                new_state]
            if n_addr == address and n_op == "READ":
                return new_state
            """
            else:
                logger.debug("Not ready for next state (read).  Backtracking")
                # Nope, not into that state yet! Look for a previous read
                return self.__read_stateful_backwards(address, size)
            """
            if n_op == "WRITE":
                logger.debug("Not ready for next state (write).  Backtracking")
                # Nope, not into that state yet! Look for a previous read
                return self.__read_stateful_backwards(address, size)
            if n_op == "ENTER":
                logger.debug("Not ready for next state (enter).  Backtracking")
                # Nope, not into that state yet! Look for a previous read
                return self.__read_stateful_backwards(address, size)
            if n_op == "EXIT":
                logger.debug("Not ready for next state (exit).  Backtracking")
                # Nope, not into that state yet! Look for a previous read
                return self.__read_stateful_backwards(address, size)

            # elif n_addr != address:
            #    logger.debug("Not ready for next state (read).  Backtracking")
            #    # Nope, not into that state yet! Look for a previous read
            #    return self.__read_stateful_backwards(address, size)
            # elif n_addr == address:
            #    return new_state
            new_state += 1

        logger.debug(
            "Value not found after state %d, backtracking..." % self.state)
        return self.__read_stateful_backwards(address, size)

    def read_memory(self, address, size):
        """
        On a read, we will use our model to return an appropriate value

        :param address:
        :param size:
        :return:
        """
        # Update the state.
        old_state = self.state
        new_state = self._read_stateful_forward(address, size)
        if new_state is None:
            # Reading a new address? Poop.
            logger.warning("Reading a new address/value at %#08x" % address)
        else:
            self.state = new_state
        logger.debug("State change at address %#08x from %d to %d" % (
            address, old_state, self.state))
        # Now see if we can read.
        try:
            mdl = self.models[address]
            if not mdl:
                if new_state is None:
                    # We don't know how to read statefully from here.
                    logger.warning(
                        "Stateful read from a new address %#08x, state %d, returning 0" % (
                            address, self.state))
                    return 0
                # Stateful read.
                n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = \
                    self.trace[self.state]

                logger.debug(
                    "Stateful read from %#08x => %#08x" % (address, n_val))
                self.check_for_interrupt(self.state)
                return n_val
            else:
                # Use our shortcut model!
                ret = mdl.read()
                self.check_for_interrupt(self.state)
                return ret
        except KeyError:
            # Well that's bad....
            logger.warning(
                "Read from unknown address %#08x, returning 0" % address)
            return 0
