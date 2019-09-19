import logging
import pprint
import random
from threading import Event
import sys

from pretender.logger import LogReader
from pretender.models.increasing import IncreasingModel
from pretender.models.markov2 import MarkovModel
from pretender.models.markovpattern import MarkovPatternModel
from pretender.models.pattern import PatternModel
from pretender.models.simple_storage import SimpleStorageModel
from pretender.interrupts import Interrupter

logger = logging.getLogger(__name__)


class PeripheralModelState:
    """
        This class will be an entire state for each peripheral, and different
         models for each memory region within that peripheral
    """

    def __init__(self, address, operation, value, irq_num=None,
                 interrupt_trigger=None, interrupt_timings=None):
        self.name = "%s:%s:%s" % (operation, hex(address), value)
        self.address = address
        self.operation = operation
        self.value = value
        self.reads = {}
        self.read_count = {}
        self.model_per_address_ordered = {}
        self.model_per_address = {}
        self.is_collapsed = False
        self.merged_data = []

    def __str__(self):
        return "%s (reads: %s)" % (self.name, len(self.reads))

    def __repr__(self):
        return self.name

    def _train_model(self, read_log, use_time_domain=True):
        """
        Return the model that best fits this data

        :param read_log:
        :return:
        """
        # Is it just storage?
        storage = True
        for val, pc, size, timestamp in read_log:
            if val != self.value:
                storage = False
        if storage:
            m = SimpleStorageModel()
            m.train(read_log)
            logger.info("Address %#08x is StorageModel" % self.address)
            return m

        # Try our other models
        if use_time_domain:
            for model in [PatternModel, MarkovPatternModel, IncreasingModel,
                          MarkovModel]:
                m = model()
                logger.debug("Trying model %s" % repr(m))
                if m.train(read_log):
                    logger.info(
                        "Address %#08x is %s" % (self.address, repr(model)))
                    return m
        else:
            for model in [MarkovModel]:
                m = model()
                if m.train(read_log):
                    logger.info(
                        "Address %#08x is %s" % (self.address, repr(model)))
                    return m

    def _get_model(self, address):

        m = None
        if self.is_collapsed:
            if address in self.model_per_address:
                m = self.model_per_address[address]
                return m
        else:
            if address in self.read_count:
                if self.read_count[address] in \
                        self.model_per_address_ordered[address]:
                    # Extract our model
                    m = self.model_per_address_ordered[address][
                        self.read_count[address]]
                    return m

            if address in self.model_per_address_ordered:
                # Looks like we are out of bounds on reads that we've seen,
                # lets pick one
                idx = max(self.model_per_address_ordered[address].keys())
                m = self.model_per_address_ordered[address][idx]

        return m

    def address_observed(self, address):
        """ Will return True if this state has data for the given address """
        return address in self.read_count

    def collapse(self):
        logger.info("Collapsed %s" % self.name)
        self.is_collapsed = True

    def expand(self):
        logger.info("Expanded %s" % self.name)
        self.is_collapsed = False

    def reset(self):
        """
        Reset any state of this state (e.g., read_count) when it entered again.

        :return:
        """

        logger.debug("Resetting state (%s)" % self.name)
        for addr in self.read_count:
            self.read_count[addr] = 0

    def append_read(self, address, value, pc, size, timestamp):
        """
        Append an observed read to this state.  By default we are going to
        keep the order of each read, these can be merged later.

        :param pc:
        :param size:
        :param timestamp:
        :param address:
        :param value:
        :return:
        """

        if address not in self.reads:
            self.reads[address] = {}

        if address not in self.read_count:
            self.read_count[address] = 0

        if self.read_count[address] not in self.reads:
            self.reads[address][self.read_count[address]] = []

        if self.read_count[address] not in self.reads[address]:
            self.reads[self.read_count[address]] = []

        self.reads[address][self.read_count[address]].append(
            (value, pc, size, timestamp))

        self.read_count[address] += 1

    def train(self):
        """
        Go through all of our states and train a model for each.
        :return:
        """
        for address in self.reads:
            if address not in self.model_per_address_ordered:
                self.model_per_address_ordered[address] = {}

            combined_reads = []
            for read_count in self.reads[address]:
                # Create an aggregate version
                combined_reads += self.reads[address][read_count]

                reads = self.reads[address][read_count]

                # Set our model for ordered reads
                m = self._train_model(reads, use_time_domain=False)
                self.model_per_address_ordered[address][read_count] = m

            # Set our model for unordered reads
            m = self._train_model(combined_reads)
            self.model_per_address[address] = m

    def merge(self, other):
        print "* Merging %s" % self.name

        self.merged_data.append(other.reads)

        # See if there are any values that we haven't seen in this model,
        # and copy them verbatim
        for address in other.reads:
            if address not in self.model_per_address_ordered:
                # Ordered
                self.model_per_address_ordered[address] = \
                    other.model_per_address_ordered[address]

                # Unordered (If the address is observed it would be in both)
                self.model_per_address[address] = \
                    other.model_per_address[address]

                # # Log of reads
                # self.reads[address] = other.reads[address]

                # Read count
                self.read_count[address] = 0

                logger.debug(
                    "No data exists for %s (copying model verbatim)" % (
                        hex(address)))
                continue

            # Make sure we initialize the read count
            if address not in self.read_count:
                self.read_count[address] = 0

            # Unordered reads
            combined_reads = []
            if address in self.reads:
                for read_count in self.reads[address]:
                    combined_reads += self.reads[address][read_count]

            # Merge ordered reads
            for read_count in other.reads[address]:

                # Their model go out further? just copy verbatim
                if read_count not in self.model_per_address_ordered[address]:
                    logger.debug("No reads in current model, merging verbatim")
                    self.model_per_address_ordered[address][read_count] = \
                        other.model_per_address_ordered[address][read_count]
                else:
                    # try to merge, if not, merge raw data and retrain
                    if not self.model_per_address_ordered[address][
                        read_count].merge(
                        other.model_per_address_ordered[address][read_count]):
                        logger.debug("Merge failed for %s/%d. (Retraining "
                                     "models and trying again)" % (hex(address),
                                                                   read_count))

                        # stop when all of our data work with the same model
                        for model in [PatternModel, MarkovModel]:

                            models = []
                            m0 = model()
                            logger.debug("Trying model %s" % repr(m0))

                            # Train our data
                            if not m0.train(self.reads[address][read_count]):
                                continue

                            all_good = True
                            for data in self.merged_data:
                                if address in data and read_count in data[
                                    address]:
                                    m = model()
                                    if not m.train(
                                            data[address][read_count]):
                                        all_good = False
                                        break
                                    else:
                                        models.append(m)

                            if not all_good:
                                continue

                            for m in models:
                                if not m0.merge(m):
                                    all_good = False
                                    break

                            if not all_good:
                                continue

                            # Looks like we found a model that they all
                            # merged into successfully!
                            self.model_per_address_ordered[address][
                                read_count] = m0
                            break

            # try to merge our unordered reads
            if not self.model_per_address[address].merge(
                    other.model_per_address[address]):
                logger.error("Merge failed for %s (%s and %s), searching for "
                             "common model..." % (
                                 hex(address),
                                 self.model_per_address[address],
                                 other.model_per_address[address]))
                # Get list of all reads
                other_reads = []
                our_reads = []
                for read_count in self.reads[address]:
                    our_reads += self.reads[address][read_count]

                for data in self.merged_data:
                    if address in data:
                        reads = []
                        for read_count in data[address]:
                            reads += data[address][read_count]
                        other_reads.append(reads)

                # stop when all of our data work with the same model
                for model in [PatternModel, MarkovPatternModel, IncreasingModel,
                          MarkovModel]:

                    models = []
                    m0 = model()
                    logger.debug("Trying model %s" % repr(m0))

                    # Train our data
                    # print our_reads
                    if not m0.train(our_reads):
                        continue

                    all_good = True
                    for reads in other_reads:
                        m = model()
                        if not m.train(reads):
                            all_good = False
                            break
                        else:
                            models.append(m)

                    if not all_good:
                        continue

                    for m in models:
                        if not m0.merge(m):
                            all_good = False
                            break

                    if not all_good:
                        continue

                    # Looks like we found a model that they all
                    # merged into successfully!
                    self.model_per_address[address] = m0
                    break

    def write(self, address, size, value):
        m = self._get_model(address)
        if m is None:
            logger.debug("Got a write for a location that has no model! ("
                         "state)")
            return False

        return m.write(value)

    def read(self, address, size):

        m = self._get_model(address)
        if address in self.read_count:
            self.read_count[address] += 1

        if m is None:
            logger.info("Got a read for an address that has no model! (state)")
            return 0

        return m.read()

    def get_current_model(self):
        """
        Return all of the active models

        IMPORTANT: We assume that this will be
        :return:
        """

        rtn = ""
        if self.is_collapsed:
            for address in self.model_per_address:
                rtn += "%s: %s " % (
                    hex(address), self._get_model(address))
        else:
            for address in self.read_count:
                rtn += "%s: %s " % (hex(address),
                                    self._get_model(address))

                # Did we exceed the reads that we saw in practice?
                if self.read_count[address] not in \
                        self.model_per_address_ordered[
                            address]:
                    rtn += "(Exceeded read threshold) "

        if self.is_collapsed:
            rtn += " (COLLAPSED)"
        return rtn


class PeripheralModel:
    """
    This class represents an external peripheral
    """

    def __init__(self, addresses, irq_num=None, interrupt_trigger=None,
                 interrupt_timings=None,
                 interrupt_oneshot=False):
        self.addresses = addresses
        self.models = {x: None for x in addresses}
        self.state_transitions = {}
        self.states = {}
        self.current_state = self._create_state(-1, "start", 0)
        self.start_state = self.current_state
        self.interrupt_trigger = interrupt_trigger
        self.interrupt_timings = interrupt_timings
        self.interrupter = None
        self.interrupt_oneshot = interrupt_oneshot
        self.irq_num = irq_num

    def __repr__(self):
        return "<PeripheralModel: %s (%s)>" % (self.current_state,
                                               self.current_state.get_current_model())

    def collapse(self):
        for address in self.states:
            for operation in self.states[address]:
                for value in self.states[address][operation]:
                    state = self.states[address][operation][value]
                    state.collapse()

    def expand(self):
        for address in self.states:
            for operation in self.states[address]:
                for value in self.states[address][operation]:
                    state = self.states[address][operation][value]
                    state.expand()

    def build_interrupter(self):
        # Backwards compat hack
        if not hasattr(self, 'interrupter') or self.interrupter:
            return
        if self.interrupt_timings and self.interrupt_trigger and self.irq_num:
            logger.info("Building an interrupter for IRQ %d" % self.irq_num)
            self.interrupter = Interrupter(self, self.irq_num,
                                           self.interrupt_trigger,
                                           self.interrupt_timings,
                                           self.interrupt_oneshot)

    def send_interrupts_to(self, host):
        assert host is not None
        self.build_interrupter()
        if hasattr(self, 'interrupter') and self.interrupter:
            if not self.interrupter.started.is_set():
                self.interrupter.host = host
                self.interrupter.start()
                self.interrupter.started.wait()

    def _create_state(self, address, operation, value):

        # Does our state already exist?
        if address in self.states and operation in self.states[address] and \
                        value in self.states[address][operation]:
            state = self.states[address][operation][value]
            logger.debug("state already exist. (%s)" % state)
            return state

        if address not in self.states or operation not in self.states[address]:
            self.states[address] = {
                operation: {
                    value: PeripheralModelState(address, operation, value)
                }
            }

        elif value not in self.states[address][operation]:
            self.states[address][operation][value] = PeripheralModelState(
                address, operation, value)

        state = self.states[address][operation][value]
        state.reset()
        return state

    def train(self, filename):
        """
        Train our model based on the log from real hardware
        :param filename:
        :return:
        """
        l = LogReader(filename)
        prev_states = []
        state = self.current_state

        # First, lets just build all of our states
        for line in l:
            # Extract our values form the log
            try:
                op, id, addr, val, pc, size, timestamp = line
            except ValueError:
                logger.warning("Weird line: " + repr(line))
                continue

            # Convert to ints
            addr = int(addr)
            val = int(val)
            pc = int(pc)

            # Ignore addresses that aren't in this peripheral
            if addr not in self.addresses and addr != self.irq_num:
                continue


            # Handle writes
            if op == "WRITE":
                state = self._create_state(addr, "write", val)

            # # Handle interrupts
            # elif op == "ENTER":
            #     prev_states.insert(0, state)
            #     state = self._create_state(addr, "interrupt", val)
            #
            # elif op == "EXIT":
            #     # Switch back to previous state
            #     state = prev_states.pop()

            elif op == "READ":
                state.append_read(addr, val, pc, size, timestamp)

            else:
                logger.error("Saw an unrecognized operation (%s)!" % op)

        l.close()

        # First, let's see if it's just storage
        for address in self.states:
            for operation in self.states[address]:
                for value in self.states[address][operation]:
                    self.states[address][operation][value].train()
                    self.states[address][operation][value].reset()

    def list_states(self):
        states = []
        for address in self.states:
            for operation in self.states[address]:
                for value in self.states[address][operation]:
                    states.append(self.states[address][operation][value])
        return states

    def state_collapse(self, state):
        for address in self.states:
            for operation in self.states[address]:
                for value in self.states[address][operation]:
                    if state == self.states[address][operation][value]:
                        self.states[address][operation][value].collapse()

    def state_expand(self, state):
        for address in self.states:
            for operation in self.states[address]:
                for value in self.states[address][operation]:
                    if state == self.states[address][operation][value]:
                        self.states[address][operation][value].expand()

    def merge(self, other_peripheral):

        if not other_peripheral.addresses <= self.addresses:
            return False

        logger.debug("Merging peripherals... ("
                     "%s == %s)" % (self.addresses,
                                    other_peripheral.addresses))
        # Merging interrupts doesn't really make sense, so let's do this the nasty way
        if self.irq_num and self.interrupt_timings and self.interrupt_trigger:
           pass
        else:
           self.irq_num = other_peripheral.irq_num
           self.interrupt_timings = other_peripheral.interrupt_timings
           self.interrupt_trigger = other_peripheral.interrupt_trigger
        # Merge known models
        for address in self.states:
            for operation in self.states[address]:
                for value in self.states[address][operation]:
                    if address not in other_peripheral.states or \
                                    operation not in other_peripheral.states[
                                address] or \
                                    value not in \
                                    other_peripheral.states[address][
                                        operation]:
                        logger.debug("State does not exist in other model "
                                     "(%s:%s:%d)" % (
                                         hex(address), operation, value
                                     ))
                    else:
                        logger.debug("Merging %s:%s:%d" % (address,
                                                           operation, value))
                        self.states[address][operation][value].merge(
                            other_peripheral.states[address][operation][value]
                        )

        # Copy unknown models verbatim
        for address in other_peripheral.states:
            for operation in other_peripheral.states[address]:
                for value in other_peripheral.states[address][operation]:
                    # Does it exist?
                    if address not in self.states or \
                                    operation not in self.states[address] or \
                                    value not in self.states[address][
                                operation]:
                        logger.debug("State does not exist locally, copying "
                                     "verbatim (%s:%s:%d)" % (address,
                                                              operation, value))

                        # Make sure our structures are in place
                        if address not in self.states:
                            self.states[address] = {
                                operation: {}
                            }
                        elif operation not in self.states[address]:
                            self.states[address][operation] = {}

                        # Copy other state
                        self.states[address][operation][value] = \
                            other_peripheral.states[address][operation][value]

    def read(self, address, size):

        if not self.current_state.address_observed(address):
            # If this state has never seen this address, we'll try to find
            # one that has, and merge them.
            if address in self.states:
                for t in self.states[address]:
                    for s in self.states[address][t]:
                        state = self.states[address][t][s]
                        if state.address_observed(address):
                            logger.debug("Found a state to merge..")

                            # TODO: Uncomment and make these strategy work
                            # self.current_state.merge(state)
                # sys.exit(0)

        return self.current_state.read(address, size)

    def enter(self, irq_num):
        # self.current_state = self.states[irq_num]['interrupt'][0]
        logger.warn("IRQ %d happened" % irq_num)

    def write(self, address, size, value):
        if address in self.states:
            if "write" in self.states[address]:
                if value in self.states[address]["write"]:
                    self.current_state = self.states[address]["write"][value]
                    self.current_state.write(address, size, value)
                else:
                    logger.info("Writing to %#08x with new value %#08x" % (address, value))
                    val = random.choice(self.states[address]["write"].keys())
                    self.current_state = self.states[address]["write"][val]
                    self.current_state.write(address, size, value)
            else:
                # Let's just stay in our current state
                return False
        else:
            logger.info("Write to new address %#08x with value %#08x" % (address, value))
            return False
        if hasattr(self, 'interrupter') and self.interrupter:
            if address == self.interrupt_trigger[0]:
                if value == self.interrupt_trigger[1]:
                    logger.info("IRQ triggered!")
                    self.interrupter.irq_enabled.set()
                else:
                    logger.info("IRQ disabled")
                    self.interrupter.irq_enabled.clear()
        return True

    def reset(self):
        """
        Reset our state to its initial state
        :return:
        """
        logger.debug("Resetting peripheral (%s)" % self.addresses)

        # Reset to start state
        self.current_state = self.start_state

        # Reset all of our read counts
        for address in self.states:
            for operation in self.states[address]:
                for value in self.states[address][operation]:
                    self.states[address][operation][value].reset()

