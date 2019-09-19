# Native
import logging
import abc
import os
import pprint
import random
import time
import pickle
from collections import defaultdict
from threading import Thread, Event
import numpy

from avatar2.peripherals import AvatarPeripheral
from avatar2.peripherals.nucleo_usart import NucleoUSART
from avatar2.peripherals.max32_usart import Max32UART
from avatar2.targets import TargetStates
from pretender.logger import LogReader
from pretender.cluster_peripherals import cluster_peripherals
import pretender.globals as G
from interrupts import Interrupter
logger = logging.getLogger(__name__)


class NullModel(AvatarPeripheral):
    def __init__(self, name, address, size, kwargs=None):
        """

        :param recorded_file:
        """
        AvatarPeripheral.__init__(self, name, address, size)
        logging.info("Using NULL MODEL..")

    def write_memory(self, address, size, value):
        """
        On a write, we need to check if this value affects any other address
        return values and update the state accordingly

        :param address:
        :param size:
        :param value:
        :return:
        """
        return True

    def read_memory(self, address, size):
        """
        On a read, we will use our model to return an appropriate value

        :param address:
        :param size:
        :return:
        """
        return 0


class MemoryModel(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def write(self, input):
        """ Memory write """
        return

    @abc.abstractmethod
    def read(self, output, data):
        """ Memory read """
        return

    @abc.abstractmethod
    def merge(self, other_model):
        """ Merge another model in """
        return


class SimpleStorageModel(MemoryModel):
    def __init__(self, init_value=0):
        self.value = init_value

    def write(self, value):
        self.value = value
        return True

    def read(self):
        return self.value

    def merge(self, other_model):
        pass


class FuzzyStorageModel(MemoryModel):
    def __init__(self, log):

        self.storage_recall = {}
        self.value = 0
        self.log = log
        self.__train_log(self.log)

    def __train_log(self, log):
        logger.debug("Training FuzzyStorageModel")
        # Keep track of important values through our log parse
        last_write = 0
        was_written = False
        storage_like = 0.0
        nonstorage_like = 0.0
        non_storage_dist = {}
        first_read = True
        for line in log:
            op, id, addr, val, pc, size, timestamp = line

            val = int(val)
            if op == "READ":
                last_read = val
                if first_read:
                    self.value = val
                    first_read = False
                if was_written:

                    # Not a verbatim storage, let's just keep track of the
                    # difference
                    if last_write != val:
                        nonstorage_like += 1.0
                        difference = int(val) - int(last_write)
                        if difference not in non_storage_dist:
                            non_storage_dist[difference] = 0
                        non_storage_dist[difference] += 1
                    else:
                        storage_like += 1.0

                    if last_write not in self.storage_recall:
                        self.storage_recall[last_write] = []
                    self.storage_recall[last_write].append(val)
            elif op == "WRITE":
                last_write = val
                was_written = True

        # probability of acting like normal storage vs. weird storage
        self.prob_of_storage = storage_like / (nonstorage_like + storage_like)

        # Get our probability distribution of how much the read value
        # differed from the write value
        cdf = 0
        self.offset_distribution = []
        for difference in non_storage_dist:
            cdf += non_storage_dist[difference] / nonstorage_like
            self.offset_distribution.append((cdf, difference))

    def write(self, value):
        if value in self.storage_recall:
            self.value = random.choice(self.storage_recall[value])
        elif random.random() < self.prob_of_storage:
            self.value = value
        else:
            r = random.random()
            for (prob, difference) in self.offset_distribution:
                if prob > r:
                    self.value = value + difference
        return True

    def read(self):
        return self.value

    def merge(self, other_model):
        if type(other_model) != type(self):
            logger.error("Tried to merge two models that aren't the same (%s "
                         "!= %s)" % (type(other_model), type(self)))
            return

        # Just add the other training data to our fuzzy model
        self.__train_log(other_model.log)


class PatternModel(MemoryModel):
    def __init__(self, read_pattern):
        self.value = 0
        self.read_pattern = read_pattern
        self.count = 0

    def write(self, value):
        self.value = value
        return True

    def read(self):
        idx = self.count % len(self.read_pattern)
        self.count += 1
        return self.read_pattern[idx]

    def merge(self, other_model):
        if type(other_model) != type(self):
            logger.error("Tried to merge two models that aren't the same (%s "
                         "!= %s)" % (type(other_model), type(self)))
            return

        if self.read_pattern != other_model.read_pattern:
            logger.error("Patterns are different. (%s != %s)" % (
                self.read_pattern, other_model.read_pattern))


class IncreasingModel(MemoryModel):
    """
    Implement a linear regression model to return accurate monotonically
    increasing values on reads

    To avoid slowing down real replays, we record the actual timestamps
    observed in the current running instances, and train on those timestamps.
    Otherwise our recorded clockspeed etc. could unnecessarily slow down our
    analysis

    In these cases we will return an exact replay of the recorded data,
    and only 'predict' new values when the recorded data has run out
    """

    def __init__(self, input_log, read_values, scale_time=False):
        """

        :param input_log:
        :param read_values:
        :param scale_time: Do we want to use the times from the log, or the
        actual observed times on the replay?  The logic here is that timers
        should use the log times, and counters should likely be scaled,
        as they are depedent on the clock speed, not the wall time.

        TODO: Implement scale_time properly
        """

        self.read_times = []
        self.read_count = 0
        self.replay_reads = read_values
        self.model_trained = False
        self.last_observed_time_adjusted = read_values[0]
        self.first_guess_time = 0
        self.outlier_threshold = 0.0001

        self.slope = 0
        self.intercept = 0
        self.r_value = 0
        self.p_value = 0
        self.std_err = 0

        self.outliers_replay = []

        read_times = []
        read_values = []
        for line in input_log:
            op, id, addr, val, pc, size, timestamp = line
            if op == "READ":
                read_times.append(float(timestamp))
                read_values.append(int(val))

        if not scale_time:
            self.train_model(read_times, read_values)
            self.model_trained = True

    def train_model(self, x, y):
        """
        Train our model to a linear regression
        :param x: timestamp values
        :param y:
        :return:
        """
        # Imports
        logger.debug("Training LinearIncreasing model...")

        from statsmodels.formula.api import ols
        from scipy import stats

        # Adjust our X values
        first_x = x[0]
        fixed_x = [i - x[0] for i in x]

        # Is it just a constant value?
        if len(fixed_x) == 1:
            self.slope = 0
            self.intercept = fixed_x[0]
            return

        # self.slope, self.intercept, self.r_value, self.p_value, self.std_err = \
        #     stats.linregress(fixed_x, y)
        # from matplotlib import pyplot
        # pyplot.scatter(fixed_x, y)
        # linear_y = [i * self.slope + self.intercept for i in fixed_x]
        # pyplot.plot(fixed_x, linear_y)
        # pyplot.show()
        #
        # print "Removing outliers"
        # Let's remove our outliers
        while True:
            try:

                # Make fit
                logger.debug("Fitting model with %d points" % len(fixed_x))
                regression = ols("data ~ x", data=dict(data=y, x=fixed_x)).fit()

                # Find outliers
                logger.debug("Testing outliers")
                test = regression.outlier_test()
                # print test
                outliers = ((x[i], y[i], i) for i, t in enumerate(test.iloc[:,
                                                                  2]) if t <
                            self.outlier_threshold)
                outliers = list(outliers)
                logger.debug("Got %d outliers" % len(outliers))
                if len(outliers) == 0:
                    break

                # Delete our outliers
                removed = False
                for i, j, idx in outliers:
                    if idx == 0:
                        self.outliers_replay.append(y[idx])
                        del fixed_x[idx]
                        del y[idx]
                        removed = True

                if not removed:
                    break

            except:
                import traceback
                logger.exception("Error training model")
                break

        # Re-adjust X
        fixed_x = [i - fixed_x[0] for i in fixed_x]

        self.last_observed_time_adjusted = fixed_x[-1]

        self.slope, self.intercept, self.r_value, self.p_value, self.std_err = \
            stats.linregress(fixed_x, y)

        # Sometimes initial values may be setup, let's see if our error goes
        # way down if we filter them, and create our function from that.
        # for i in range(int(len(fixed_x) * .15)):
        #     slope, intercept, r_value, p_value, std_err = stats.linregress(
        #         fixed_x[i:], y[i:])
        #     # 50% improvement sounds pretty awesome...
        #     if std_err < self.std_err * .5:
        #         self.slope, self.intercept, self.r_value, self.p_value, \
        #         self.std_err = slope, intercept, r_value, p_value, std_err

        # from matplotlib import pyplot
        # pyplot.scatter(fixed_x, y)
        # linear_y = [i * self.slope + self.intercept for i in fixed_x]
        # pyplot.plot(fixed_x, linear_y)
        # pyplot.show()



    def write(self, value):
        """
        This should be a read-only model
        """
        return True

    def read(self):
        """
        Return either a verbatim replay from our outliers, or an approximated
        value from our model
        :return:
        """
        # if self.scale_time and self.read_count < len(self.replay_reads):
        #     self.read_count += 1
        #     self.read_times.append(time.time())
        #     return self.replay_reads[self.read_count - 1]
        # else:
        #     if self.read_count == len(self.replay_reads):
        #         self.first_guess_time = time.time()
        #     self.read_count += 1

        if self.read_count < len(self.outliers_replay):
            self.read_count += 1
            return self.outliers_replay[self.read_count - 1]
        elif self.read_count == len(self.outliers_replay):
            self.first_guess_time = time.time()
        self.read_count += 1

        if not self.model_trained:
            self.train_model(self.read_times, self.replay_reads)
            self.model_trained = True

        # time*[calculated slope] + [intercept]
        fixed_time = time.time() - self.first_guess_time
        return int(fixed_time * self.slope + self.intercept)

    def merge(self, other_model):
        if type(other_model) != type(self):
            logger.error("Tried to merge two models that aren't the same (%s "
                         "!= %s)" % (type(other_model), type(self)))
            return
        if self.outliers_replay != other_model.outliers_replay:
            logger.error("The replay reads don't match! (%s != %s)" % (
                self.outliers_replay, other_model.outliers_replay))

        self.slope = (self.slope + other_model.slope) / 2
        self.intercept = (self.intercept + other_model.intercept) / 2


class OldPretender(AvatarPeripheral):
    def __init__(self, name, address, size, pretender_model, random_seed=None):
        """

        :param recorded_file:
        """
        AvatarPeripheral.__init__(self, name, address, size)
        logging.info("Starting pretender..")

        random.seed(random_seed)

        self.read_replay = {}
        self.model = pretender_model
        self.model_per_address = {}
        self.read_handler[0:size] = self.read_memory
        self.write_handler[0:size] = self.write_memory

        # self.train()

    def write_memory(self, address, size, value):
        """
        On a write, we need to check if this value affects any other address
        return values and update the state accordingly

        :param address:
        :param size:
        :param value:
        :return:
        """
        try:
            return self.model.write_memory(address, size, value)
        except:
            logger.exception("Error writing memory")
            
    def read_memory(self, address, size):
        """
        On a read, we will use our model to return an appropriate value

        :param address:
        :param size:
        :return:
        """
        try:
            return self.model.read_memory(address, size)
        except:
            logger.exception("Error reading memory")

    def shutdown(self):
        self._shutdown.set()

class MMIOGroup:
    """
    This represents a group of (at the moment, spatially-clustered) peripheral locations
    It contains a set of models for each register in its set.
    For any register which we cannot fit an easy model, we default to "stateful replay", our
    state machine inference trick.
    """

    def __init__(self, addresses, trace, irq_num=None, interrupt_trigger=None, interrupt_timings=None):
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
            self.interrupter = Interrupter(self, self.irq_num, self.interrupt_trigger, self.interrupt_timings)

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
                if self.interrupt_trigger[1] & value == value:
                    logger.info("Got trigger for IRQ %d %#08x" % (self.irq_num, value))
                    self.interrupter.irq_enabled.set()
                else:
                    logger.info("Un-trigger IRQ %d value %#08x" % (self.irq_num, value))
                    self.interrupter.irq_enabled.clear()
            
        if new_state is None:
            # We've never written that before.  Don't do anything
            # TODO maybe prefer the address with a similar value here
            logger.warning("Writing an unknown value at %#08x => %#08x" % (address, value))
        else:
            self.state = new_state
        logger.debug("Updating state from %d to %d" % (old_state, self.state))
        try:
            mdl = self.models[address]
            if mdl is None:
                # This is one of the hard cases.  Do the stateful replay thing.
                # So, for a write, nothing except sync the state.
                #self.check_for_interrupt(self.state)
                return True
            #self.check_for_interrupt(self.state)
            return mdl.write(value)
        except KeyError:
            self.models[address] = SimpleStorageModel(init_value=value)

    def check_for_interrupt(self, state):
        new_state = self.state + 1
        if new_state >= len(self.trace):
            return
        n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[new_state]
        if n_op == "ENTER" and self.interrupter:
            logger.debug("Time for an interrupt %d!" % self.interrupter.irq_num)
            self.interrupter.send_interrupt()
            self.state = new_state
        elif n_op == "EXIT":
            # That's nice, but what sbout the net one
            logger.debug("Time for an exit")
            self.state = new_state
            new_state += 1
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[new_state]
            if n_op == "ENTER" and self.interrupter:
                logger.debug("Time for ANOTHER interrupt %d!" % self.interrupter.irq_num)
                self.interrupter.send_interrupt()
                self.state = new_state
                
    def __write_stateful_backwards(self, addr, size, value):
        # The state we're looking for is not in front of us, find the most recent one that's behind us
        new_state = self.state
        while True:
            if new_state < 0:
                # It's not anywhere.  Start at the beginning of the trace!
                return None
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[new_state]
            if n_op == 'EXIT':
                logger.debug("Skipping over interrupt backwards")
                while True:
                    if new_state < 0:
                        logger.warning("Error finding interrupt enter during backtrack")
                        # It's not anywhere.  Start at the beginning of the trace!
                        return None
                    n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[new_state]
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
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[new_state]
            if n_op == "WRITE" and n_addr == address and n_val == value:
                return new_state
            if n_op == 'ENTER':
                logger.debug("Skipping over interrupt forwards")
                while True:
                    if new_state >= len(self.trace):
                        logger.warning("Error finding interrupt exit during forward")
                        # It's not anywhere.
                        return self.__write_stateful_backwards(address, size, value)
                    n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[new_state]
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
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[new_state]
            if n_op == "READ" and n_addr == address:
                return new_state
            new_state -= 1
        # Welp, we've fucked up, and we have never read this address before
        return self.__find_reset_value(address, size)

    def _enter_backwards(self, irq_num):
        # The state we're looking for is not in front of us, find the most recent one that's behind us
        new_state = self.state
        while True:
            if new_state < 0:
                # It's not anywhere.  Start at the beginning of the trace!
                logger.error("PANIC!")
                return
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[new_state]
            if n_op == 'ENTER' and n_addr == irq_num:
                self.state = new_state
                logger.info("Entering IRQ %d at state %d" % (irq_num, self.state))
                return

    def enter(self, irq_num):
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
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[new_state]
            if n_op == "ENTER" and n_addr == irq_num:
                self.state = new_state
                return
            new_state += 1
        # We didn't find it. Look behind us
        return self._enter_backwards(irq_num)

    def _read_stateful_forward(self, address, size):
        new_state = self.state + 1
        if new_state >= len(self.trace):
            return self.__read_stateful_backwards(address, size)
        while new_state < len(self.trace):
            n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[new_state]
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
            #if n_op == "EXIT":
            #    logger.debug("Not ready for next state (exit).  Backtracking")
            #    # Nope, not into that state yet! Look for a previous read
            #    return self.__read_stateful_backwards(address, size)

            #elif n_addr != address:
            #    logger.debug("Not ready for next state (read).  Backtracking")
            #    # Nope, not into that state yet! Look for a previous read
            #    return self.__read_stateful_backwards(address, size)
            #elif n_addr == address:
            #    return new_state
            new_state += 1
            
        logger.debug("Value not found after state %d, backtracking..." % self.state)
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
        logger.debug("State change at address %#08x from %d to %d" % (address, old_state, self.state))
        # Now see if we can read.
        try:
            mdl = self.models[address]
            if not mdl:
                if new_state is None:
                    # We don't know how to read statefully from here.
                    logger.warning("Stateful read from a new address %#08x, state %d, returning 0" % (address, self.state))
                    return 0
                # Stateful read.
                n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = self.trace[self.state]

                logger.debug("Stateful read from %#08x => %#08x" % (address, n_val))
                #self.check_for_interrupt(self.state)
                return n_val
            else:
                # Use our shortcut model!
                ret = mdl.read()
                #self.check_for_interrupt(self.state)
                return ret
        except KeyError:
            # Well that's bad....
            logger.warning("Read from unknown address %#08x, returning 0" % address)
            return 0



class OldPretenderModel:
    def __init__(self, name, address, size, **kwargs):
        self.model_per_address = {}
        self.peripheral_clusters = {}
        self.log_per_cluster = {}
        filename = kwargs['kwargs']['filename'] if kwargs else None
        if filename is not None:
            self.model_per_address = pickle.load(open(filename, "rb"))
        host = kwargs['kwargs']['host'] if kwargs else None
        if host:
            self.send_interrupts_to(host)
        serial = kwargs['kwargs']['serial'] if kwargs else None
        if serial:
            logger.info("Attaching virtual serial port")
            uart = NucleoUSART('serial', 0x40004400, size=32)
            self.model_per_address[0x40004400]['model'] = uart
            self.model_per_address[0x40004404]['model'] = uart
        max32_serial = kwargs['kwargs']['max32_serial'] if kwargs else None
        if max32_serial:
            uart = Max32UART('serial', 0x40039000, size=0x24)
            self.model_per_address[0x40039000]['model'] = uart
            self.model_per_address[0x40039004]['model'] = uart
            self.model_per_address[0x40039008]['model'] = uart
            self.model_per_address[0x4003900c]['model'] = uart
            self.model_per_address[0x40039010]['model'] = uart
            self.model_per_address[0x40039014]['model'] = uart
            #self.model_per_address[0x40039018]['model'] = uart
            #self.model_per_address[0x4003901c]['model'] = uart
            self.model_per_address[0x40039020]['model'] = uart

    def __del__(self):
        self.shutdown()

    def send_interrupts_to(self, host):
        for mdl in self.model_per_address.values():
            m = mdl['model']
            if isinstance(m, MMIOGroup):
                m.send_interrupts_to(host)

    def shutdown(self):
        for mdl in self.model_per_address.values():
            if isinstance(mdl, MMIOGroup):
                mdl.shutdown()

    def __init_address(self, address):
        """
            Initialize our storage for the given address

        :param adddress:
        :return:
        """
        self.model_per_address[address] = {'reads': [],
                                           'writes': [],
                                           'pc_accesses': [],
                                           'read_count': 0,
                                           'write_count': 0,
                                           'log': [],
                                           'model': None}

    def infer_interrupt_association(self, l, peripheral_clusters):
        """
        Infer an interrupt association.
        This is the mapping between the peripheral grouping and its interrupt number.
        NInja-edit, this does a lot more than that now.
        0: Get the full trace read in
        1: Take the MMIO during an ISR
        2: Figure out which peripheral the ISR's content belongs to.
        3: Figure out what caused the ISR, using the assumption that a write to a peripheral register enabled the interrupt.
        4: Figure out when / how often we should fire this interrupt
        :param l: LogReader with the data in it
        :param peripheral_clusters: Previously-extracted peripheral map.
        :return:
        """

        interrupt_mapping = {}
        # Step 0: Sloppily parse out the full trace.
        full_trace = []
        for line in l:
            try:
                op, id, addr, val, pc, size, timestamp = line
            except ValueError:
                continue
            addr = int(addr)
            val = int(val)
            pc = int(pc)
            timestamp = float(timestamp)
            full_trace.append((op, id, addr, val, pc, size, timestamp))

        isr_activity = {}
        # Step 1: Cut out an interrupt handler's worth of stuff
        # TODO: Support for nesting.
        for x in range(len(full_trace)):
            op, id, addr, val, pc, size, timestamp = full_trace[x]
            if op == "ENTER":
                isr_num = addr
                isr_trace = []
                isr_instance = {}
                for y in range(x + 1, len(full_trace)):
                    op2, id2, addr2, val2, pc2, size2, timestamp2 = full_trace[y]
                    if op2 == 'EXIT':
                        # we hit the end.  Write it out.
                        isr_instance['time'] = timestamp2 - timestamp
                        isr_instance['trace'] = isr_trace
                        if not isr_activity.has_key(isr_num):
                            isr_activity[isr_num] = []
                        isr_activity[isr_num].append(isr_instance)
                        break
                    isr_trace.append(full_trace[y])
                else:
                    # Mismatched enter
                    logger.warning("Mismatched ISR enter %s" % repr(full_trace[x]))
                    continue

        # Step 2: Let's figure out what peripheral cluster it goes to
        # We use a tiered voting thingy, each ISR invocation has a bunch of MMIO accesses in it.
        # We vote based on the MMIO accesses that belong to a given cluster, and vote based on
        # all ISR invocations as well
        for isr_num, activity in isr_activity.items():
            logger.debug("Associating ISR %d" % isr_num)
            cluster_number = self.associate_with_cluster(activity, peripheral_clusters)
            if cluster_number == -1:
                logger.warning("Could not associate IRQ %d to a peripheral" % isr_num)
                continue
            logger.info("I think IRQ %d belongs in cluster %d: %s" % (isr_num, cluster_number, repr(peripheral_clusters[cluster_number])))
            interrupt_mapping[cluster_number] = isr_num


        # Step 3: Can we find a trigger?
        irq_triggers = {}
        for cluster, irq_num in interrupt_mapping.items():
            logger.info("Finding a trigger for interrupt %d" % irq_num)
            # Find the first ENTER
            trigger_addr = None
            trigger_val = None
            for state in range(0, len(full_trace)):
                op, _, irq, val, _, _, timestamp = full_trace[state]
                if op == 'ENTER' and irq == irq_num:
                    # OK here we are.  Walk it back.
                    prev_state = state - 1
                    while prev_state > 0:
                        prev_op, prev_id, prev_addr, prev_val, prev_pc, prev_size, prev_timestamp = full_trace[prev_state]
                        if prev_op == 'WRITE' and prev_addr in peripheral_clusters[cluster]:
                            # That's the guy
                            trigger_addr = prev_addr
                            trigger_val = prev_val
                            break
                        prev_state -= 1
                    break
            if not trigger_addr:
                logger.info("Could not find a trigger for IRQ %d", irq_num)
            else:
                logger.info("Found trigger for IRQ %d at address %#08x with value %#08x" % (irq_num, trigger_addr, trigger_val))
                irq_triggers[irq_num] = (trigger_addr, trigger_val)
                # Now refine the bitpattern
                cur_trigger_val = None
                trigger_vals = defaultdict(int)
                for x in range(len(full_trace)):
                    op, id, addr, val, pc, size, timestamp = full_trace[x]
                    if op == "WRITE" and addr == trigger_addr:
                        cur_trigger_val = val
                    if op == "ENTER" and addr == irq_num:
                        trigger_vals[cur_trigger_val] += 1
                print(repr(trigger_vals))
                real_val = 0x00000000
                for val, onoff in trigger_vals.items():
                    if onoff > 0:
                        real_val |= val
                    else:
                        real_val ^= val
                print("Refined trigger value is %#08x" % real_val)
                irq_triggers[irq_num] = (trigger_addr, real_val)
                
        # Step 4: Timing-based stuff
        interrupt_timings = {} # Map of interrupt_number to inter-interrupt timings.
        for peripheral_cluster, irq_num in interrupt_mapping.items():
            timings = []
            peripheral_addrs = peripheral_clusters[peripheral_cluster]
            if not irq_triggers.has_key(irq_num):
                continue
            trigger_addr, trigger_val = irq_triggers[irq_num]
            # here we go, collect the EXIT-to-ENTER timings, plus the initial trigger-to-enter timing.
            # Stop if we see a disable.
            trigger_state = None
            trigger_time = None
            for x in range(0, len(full_trace)):
                op, id, addr, val, pc, size, timestamp = full_trace[x]
                if op == "WRITE" and addr == trigger_addr and val == trigger_val:
                    trigger_state = x
                    trigger_time = timestamp
                    break
            else:
                # Bug.
                raise RuntimeError("Bug related to trigger-finding")
            prev_time = trigger_time
            for state in range(trigger_state + 1, len(full_trace)):
                op, id, addr, val, pc, size, timestamp = full_trace[state]
                if op == "ENTER" and addr == isr_num:
                    timing = timestamp - prev_time
                    timings.append(timing)
                elif op == 'EXIT' and addr == isr_num:
                    prev_time = timestamp
                elif op == 'WRITE' and addr == trigger_addr and val != trigger_val:
                    # I think we just turned it off.
                    break
            logger.info("Got timings for interrupt %d" % (irq_num))
            logger.info("Mean: %f" % numpy.mean(timings))
            logger.info("Stdv: %f" % numpy.std(timings))
            interrupt_timings[irq_num] = timings


        return interrupt_mapping, irq_triggers, interrupt_timings

    def associate_with_cluster(self, activity, peripheral_clusters):
        votes = defaultdict(int)
        real_winner = -1
        for a in activity:
            act = a['trace']
            my_votes = defaultdict(int)
            my_winner = -1
            for event in act:
                # Vote in every ISR invocation
                try:
                    op, id, addr, val, pc, size, timestamp = event
                except ValueError:
                    continue
                for k, v in peripheral_clusters.items():
                    if addr in v:
                        my_votes[k] += 1
                        break
            for cluster, count in my_votes.items():
                if 0 < count and count > my_votes[my_winner]:
                    my_winner = cluster
            if my_winner == -1:
                pass
            else:
                votes[my_winner] += 1
        # Now pick the real winner
        for cluster, count in votes.items():
            if 0 < count and count > votes[real_winner]:
                real_winner = cluster
        return real_winner
    def save(self, directory):
        f = open(os.path.join(directory, G.MODEL_FILE), "wb+")
        pickle.dump(self.model_per_address, f)
        f.close()

    def train(self, filename):
        """
        Train our model, potentially using a specific training model
        :return:
        """
        logger.info("Training hardware pretender (%s)" % filename)


        ##
        ## Step 0: Grab the trace and a bunch of the basic stats.  
        ## This includes the set of addresses
        ##
        l = LogReader(filename)
        addrs = []
        for line in l:
            try:
                op, id, addr, val, pc, size, timestamp = line
            except ValueError:
                logger.warning("Weird line: " + repr(line))
                continue
            addr = int(addr)
            val = int(val)
            pc = int(pc)
            if op == 'ENTER' or op == 'EXIT':
                continue
            if op == "READ":
                if addr not in self.model_per_address:
                    self.__init_address(addr)
                addrs.append(addr)
                self.model_per_address[addr]['reads'].append(val)
                self.model_per_address[addr]['pc_accesses'].append(pc)
            if op == "WRITE":
                if addr not in self.model_per_address:
                    self.__init_address(addr)
                addrs.append(addr)
                self.model_per_address[addr]['writes'].append(val)
                self.model_per_address[addr]['pc_accesses'].append(pc)

            self.model_per_address[addr]['log'].append(line)

        l.close()

        ##
        ## Step 1: Divide the possible addresses into preipherals
        ##
        self.peripheral_clusters = cluster_peripherals(addrs)


        ##
        ## Step 2: Associate interrupts, their triggers, and their timings with a peripheral
        ##
        l = LogReader(filename)
        interrupt_mappings, interrupt_triggers, interrupt_timings = self.infer_interrupt_association(l, self.peripheral_clusters)


        ##
        ## Step 4: Collect some more stats
        ## Also break up the trace into its peripheral cluster pieces
        ## EDG says: I have no idea what this is for
        ##
        pc_cluster = {}
        trace_by_cluster = {cl: [] for cl in self.peripheral_clusters.keys()}
        l = LogReader(filename)
        for line in l:
            try:
                op, id, addr, val, pc, size, timestamp = line
            except ValueError:
                continue

            addr = int(addr)
            val = int(val)
            pc = int(pc)
            for cluster, addrs in self.peripheral_clusters.items():
                if op == 'ENTER' or op == 'EXIT':
                    if cluster in interrupt_mappings and addr == interrupt_mappings[cluster]:
                        trace_by_cluster[cluster].append((op, id, addr, val, pc, size, timestamp))

                if addr in addrs:
                    trace_by_cluster[cluster].append((op, id, addr, val, pc, size, timestamp))
            if pc not in pc_cluster:
                pc_cluster[pc] = {'reads': {},
                                  'writes': {},
                                  'log': []}

            if op == 'ENTER' or op == 'EXIT':
                continue #avoid memory only code
            addr_type = "read/write"
            if len(self.model_per_address[addr]['writes']) == 0:
                addr_type = "read-only"
            elif len(self.model_per_address[addr]['reads']) == 0:
                addr_type = "write_only"

            if op == "READ":
                pc_cluster[pc]['reads'][addr] = addr_type
            if op == "WRITE":
                pc_cluster[pc]['writes'][addr] = addr_type

            pc_cluster[pc]['log'].append(line)

        l.close()


        ##
        ## Step 5: Fit the shortcut models to memory locations.
        ## IN other words, find our storage locations, increasing locations, etc
        ## The rest are marked with a model of None, which will cause stateful replay
        ##
        for address in self.model_per_address:
            if len(self.model_per_address[address]['writes']) == 0:
                logger.info("%s is a read-only location." % hex(address))

                pattern = self.is_pattern(self.model_per_address[
                                              address]['reads'])

                # Monotonically increasing?
                if self.is_increasing(self.model_per_address[address]['log']):
                    logger.info("Found a increasing unit @ %s" % hex(address))
                    self.model_per_address[address]['model'] = \
                        IncreasingModel(self.model_per_address[address]['log'],
                                        self.model_per_address[address][
                                            'reads'])
                # Do the reads just repeat a pattern?
                elif pattern:
                    logger.info("Found a pattern unit @ %s" % hex(address))
                    self.model_per_address[address]['model'] = PatternModel(
                        pattern)
                else:
                    self.model_per_address[address]['model'] = None
                    logger.info("Hard case read at %#08x" % address)
                    #pprint.pprint(self.model_per_address[address], width=120)

            elif len(self.model_per_address[address]['reads']) == 0:
                logger.info("%s is a write-only location." % hex(address))
            else:
                logger.info("%s is a read/write location! (Tricky...)" % hex(
                    address))

                pattern = self.is_pattern(self.model_per_address[
                                              address]['reads'])
                # Does it look like it's just normal memory storage?
                if self.is_storage(self.model_per_address[address]['log']):
                    # Set our model to simple storage, initialized with the
                    # first read value
                    logger.info("Found a storage unit @ %s" % hex(address))
                    self.model_per_address[address]['model'] = \
                        SimpleStorageModel(init_value=self.model_per_address[
                            address]['reads'][0])

                # Do the reads just repeat a pattern?
                elif pattern:
                    logger.info("Found a pattern unit @ %s" % hex(address))
                    self.model_per_address[address]['model'] = PatternModel(
                        pattern)
                # Does it look like it's just complex memory storage?
                elif self.is_fuzzy_storage(self.model_per_address[address][
                                               'log']):
                    logger.info("Found a fuzzy storage @ %s" % hex(address))
                    #self.model_per_address[address]['model'] = \
                    #    FuzzyStorageModel(
                    #        self.model_per_address[address]['log'])
                    self.model_per_address[address]['model'] = None
                else:
                    self.model_per_address[address]['model'] = None
                    logger.info("Hard case write at %#08x " % address)
        
        
        ##
        ## Step 6: Pack all our shortcut models, interrupt info, and traces into
        ## an MMIOGroup, which represents the model of a whole peripheral.
        ##
        print(interrupt_mappings, interrupt_triggers, interrupt_timings)
        for periph_id, periph_addrs in self.peripheral_clusters.items():
            irq_num = None
            interrupt_trigger = None
            interrupt_timing = None
            logger.info("Packing peripheral %d" % periph_id) 
            if interrupt_mappings.has_key(periph_id):
                irq_num = interrupt_mappings[periph_id]
            if interrupt_triggers.has_key(irq_num):
                interrupt_trigger = interrupt_triggers[irq_num]
            if interrupt_timings.has_key(irq_num):
                interrupt_timing = interrupt_timings[irq_num]

            periph = MMIOGroup(periph_addrs, trace_by_cluster[periph_id], irq_num=irq_num, interrupt_trigger=interrupt_trigger, interrupt_timings=interrupt_timing)
            for addr in periph_addrs:
                mdl = self.model_per_address[addr]['model']
                periph.models[addr] = mdl
                self.model_per_address[addr]['model'] = periph
        #import IPython; IPython.embed()

    def get_model(self, address):
        """
        return the name of the model that is controlling the address
        :param address:
        :return:
        """

        if address in self.model_per_address:
            n = self.model_per_address[address]['model'].__class__.__name__
            if 'MMIOGroup' in n:
                real_m = self.model_per_address[address]['model'].models[address]
                n += "@" + hex(self.model_per_address[address]['model'].min_addr())
                if real_m is None:
                    n += "#" + str(self.model_per_address[address]['model'].state)
                else:
                    n += ":" + real_m.__class__.__name__
            return n
        else:
            # No model?  Let's just default to storage then
            return None

    def write_memory(self, address, size, value):
        """
        On a write, we need to check if this value affects any other address
        return values and update the state accordingly

        :param address:
        :param size:
        :param value:
        :return:
        """
        logger.debug("Write %s %s %s" % (address, size, value))
        if address not in self.model_per_address:
            logger.debug(
                "No model found for %s, using SimpleStorageModel...",
                hex(address))
            self.__init_address(address)
            self.model_per_address[address]['model'] = SimpleStorageModel()

        if self.model_per_address[address]['model'] is not None:
            if isinstance(self.model_per_address[address]['model'], MMIOGroup):
                logger.debug("Writing to MMIOGroup at %#08x" % address)
                return self.model_per_address[address]['model'].write_memory(address, size, value)
            elif isinstance(self.model_per_address[address]['model'], NucleoUSART) or \
                 isinstance(self.model_per_address[address]['model'], Max32UART):
                logger.debug("Writing to virtual serial port")
                return self.model_per_address[address]['model'].write_memory(address, size, value)
            return self.model_per_address[address]['model'].write(value)
        else:
            return True

    def read_memory(self, address, size):
        """
        On a read, we will use our model to return an appropriate value

        :param address:
        :param size:
        :return:
        """
        logger.debug("Read %s %s" % (address, size))

        if address not in self.model_per_address:
            logger.debug(
                "No model found for %s, using SimpleStorageModel...",
                hex(address))
            self.__init_address(address)
            self.model_per_address[address]['model'] = SimpleStorageModel()

        logger.debug(
            "Using model %s" % self.model_per_address[address]['model'])
        if isinstance(self.model_per_address[address]['model'], MMIOGroup):
            logger.debug("Reading from MMIOGroup")
            return self.model_per_address[address]['model'].read_memory(address, size)
        elif isinstance(self.model_per_address[address]['model'], NucleoUSART) or \
             isinstance(self.model_per_address[address]['model'], Max32UART):
            logger.debug("Reading from virtual serial port")
            return self.model_per_address[address]['model'].read_memory(address, size)
        return self.model_per_address[address]['model'].read()


        # if address not in self.read_replay:
        #     logger.info("Address not found (%s, %d)" % (hex(address), size))
        #     # logger.info(self.read_replay)
        #     return 0
        #
        # # print self.read_replay[address]
        # count = self.read_replay[address]['count']
        # rtn = self.read_replay[address]['values'][count]
        # new_count = (count + 1) % len(self.read_replay[address]['values'])
        # self.read_replay[address]['count'] = new_count
        #
        # # print self.read_replay[address]
        # # print rtn
        # return rtn

    @staticmethod
    def is_storage(log):
        """
        Determine if the log looks like a simple storage model

        If we only see 1 read, followed by 1 write, we are going to assume it is
         a storage unit
        :param log:
        :return:
        """

        # If it's only a read/write, let's assume its a storage config register
        if len(log) == 2 and log[0][0] == 'READ' and log[1][0] == 'WRITE':
            return True

        last_read = 0
        last_write = 0
        was_written = False
        is_storage_unit = False
        for line in log:
            op, id, addr, val, pc, size, timestamp = line
            if op == "READ":
                last_read = val
                if was_written:
                    if last_write != val:
                        return False
                    else:
                        is_storage_unit = True
            elif op == "WRITE":
                last_write = val
                was_written = True

        return is_storage_unit

    @staticmethod
    def is_fuzzy_storage(log):
        """
        Determine if the log looks like a complex storage model
        Some registers seem act like a storage register in 'most' cases,
        sometimes deviating due to external phenomena

        If we only see 1 read, followed by 1 write, we are going to assume it is
         a storage unit
        :param log:
        :return:
        """

        # If it's only a read/write, let's assume its a storage config register
        if len(log) == 2 and log[0][0] == 'READ' and log[1][0] == 'WRITE':
            return True

        last_read = 0
        last_write = 0
        was_written = False
        is_storage_unit = False

        storage_like = 0.0
        nonstorage_like = 0.0
        for line in log:
            op, id, addr, val, pc, size, timestamp = line
            if op == "READ":
                last_read = val
                if was_written:
                    if last_write != val:
                        nonstorage_like += 1.0
                    else:
                        storage_like += 1.0
            elif op == "WRITE":
                last_write = val
                was_written = True
        if nonstorage_like == 0:
            return True
        return storage_like / nonstorage_like > .5

    @staticmethod
    def is_increasing(log):
        """
        Determine if the reads converge to be always increasing (indicative
        of a timer or counter)

        NOTE: There are likely configuration parameters to setup these memory
        regions that could make them decrease, we are looking for their steady
        state.
        NOTE: A static value would also fit this model as the linear
        regression would be y = C

        :param log:
        :return:
        """
        increasing_threshold = .6
        last_read = 0
        first = True
        idx = 0
        # If it's not long, it's probably not actually increasing (flags, that look increasing)
        the_thresh = 6
        not_increasing = []
        if len(log) < 6:
           return False
        for line in log:
            op, id, addr, val, pc, size, timestamp = line
            val = int(val)

            if not first and val < last_read:
                not_increasing.append(idx)
                # return False

            last_read = val
            first = False

            idx += 1

        # does the final half increase?
        if len(not_increasing) == 0:
            return True
        elif len(not_increasing) < increasing_threshold * len(log) and \
                        not_increasing[-1] < increasing_threshold * len(log):
            return True
        else:
            return False

    @staticmethod
    def is_pattern(reads):
        """
        Determine if the reads always return some fixed pattern.

        For now, we are ignoring writes; however, we should clearly
        incorporate them in the future, maybe even a different model

        @TODO Incorporate writes?

        :param log:
        :return:
        """

        if len(reads) < 2:
            return False

        # Are they all the same?
        all_same = True
        for x in reads:
            if x != reads[0]:
                all_same = False
        if all_same:
            return [reads[0]]

        # Let's see if a repeating pattern exist
        max_len = len(reads) / 2
        for seqn_len in range(2, max_len):

            # Do the first 2 at least match as a pattern?
            if reads[0:seqn_len] == reads[seqn_len:2 * seqn_len]:

                is_pattern = True

                # Let's check all the others, ignoring any incomplete
                # patterns at the end
                last_complete_seqn = len(reads) - len(reads) % seqn_len
                for y in range(2 * seqn_len, last_complete_seqn, seqn_len):
                    if reads[0:seqn_len] != reads[y:y + seqn_len]:
                        is_pattern = False
                        break
                remainder = reads[-(len(reads) % seqn_len):]
                if not all(remainder[i] == reads[i] for i in range(len(remainder))):
                    is_pattern = False
                if is_pattern:
                    return reads[0:seqn_len]

        return False

    def merge(self, other_model):

        # Copy all unknown from other to current
        for addr in other_model.model_per_address:
            if addr not in self.model_per_address:
                logger.info("Copying model verbatim for 0x%08X, because it "
                            "doesn't exist in current model" % addr)
                self.model_per_address[addr] = other_model.model_per_address[
                    addr]

        for addr in self.model_per_address:

            if type(self.model_per_address[addr]['model']) == \
                    type(other_model.model_per_address[
                             addr]['model']):
                # No model?
                if self.model_per_address[addr]['model'] == None:
                    continue

                # Let's merge 'em!
                logger.info("found matching models!  merge em! %s",
                            self.model_per_address[addr]['model'])
                self.model_per_address[addr]['model'].merge(
                    other_model.model_per_address[addr]['model'])
            else:
                logger.info("models don't match! %s != %s" % (
                    self.model_per_address[addr]['model'],
                    other_model.model_per_address[addr]['model']
                ))
