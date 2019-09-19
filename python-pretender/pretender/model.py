# Native
import logging
import os
import pprint
import pickle
import sys
from collections import defaultdict

# Numpy
import numpy

# Avatar 2

from avatar2.peripherals.nucleo_usart import NucleoUSART

# Pretender
import pretender.globals as G
from pretender.logger import LogReader
from pretender.cluster_peripherals import cluster_peripherals
from pretender.mmiogroup import MMIOGroup
from pretender.models.increasing import IncreasingModel
from pretender.models.pattern import PatternModel
from pretender.models.simple_storage import SimpleStorageModel
from pretender.peripheral_model import PeripheralModel

logger = logging.getLogger(__name__)


class PretenderModel:
    def __init__(self, name=None, address=None, size=None,
                 filename=None, **kwargs):
        self.peripherals = []
        self.model_per_address = {}
        self.peripheral_clusters = {}
        self.log_per_cluster = {}
        self.accessed_addresses = set()
        # filename = kwargs['kwargs']['filename'] if kwargs else None

        # Load from disk?
        if filename is not None:
            self.__dict__ = pickle.load(open(filename, "rb"))
            # Reset all of our state!
            for p in self.peripherals:
                p.reset()
            pprint.pprint(self.model_per_address)

        host = kwargs['host'] if kwargs and 'host' in kwargs else None
        if host:
            self.send_interrupts_to(host)
        serial = kwargs['serial'] if kwargs and 'serial' in kwargs else None
        if serial:
            logger.info("Attaching virtual serial port")
            uart = NucleoUSART('serial', 0x40004400, size=32)
            self.model_per_address[0x40004400] = uart
            self.model_per_address[0x40004404] = uart

    def __del__(self):
        self.shutdown()

    def send_interrupts_to(self, host):
        for mdl in self.model_per_address.values():
            m = mdl
            if isinstance(m, PeripheralModel):
                m.send_interrupts_to(host)

    def shutdown(self):
        for mdl in self.model_per_address.values():
            if isinstance(mdl, MMIOGroup):
                mdl.shutdown()

    # def __init_address(self, address):
    #     """
    #         Initialize our storage for the given address
    #
    #     :param adddress:
    #     :return:
    #     """
    #     self.model_per_address[address] = {'reads': [],
    #                                        'writes': [],
    #                                        'pc_accesses': [],
    #                                        'read_count': 0,
    #                                        'write_count': 0,
    #                                        'log': [],
    #                                        'model': None}

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
        oneshots = []
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
                    op2, id2, addr2, val2, pc2, size2, timestamp2 = full_trace[
                        y]
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
                    logger.warning(
                        "Mismatched ISR enter %s" % repr(full_trace[x]))
                    continue

        # Step 2: Let's figure out what peripheral cluster it goes to
        # We use a tiered voting thingy, each ISR invocation has a bunch of MMIO accesses in it.
        # We vote based on the MMIO accesses that belong to a given cluster, and vote based on
        # all ISR invocations as well
        for isr_num, activity in isr_activity.items():
            logger.debug("Associating ISR %d" % isr_num)
            cluster_number = self.associate_with_cluster(activity,
                                                         peripheral_clusters)
            if cluster_number == -1:
                logger.warning(
                    "Could not associate IRQ %d to a peripheral" % isr_num)
                continue
            logger.info("I think IRQ %d belongs in cluster %d: %s" % (
                isr_num, cluster_number,
                repr(peripheral_clusters[cluster_number])))
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
                        prev_op, prev_id, prev_addr, prev_val, prev_pc, prev_size, prev_timestamp = \
                            full_trace[prev_state]
                        if prev_op == 'WRITE' and prev_addr in \
                                peripheral_clusters[cluster]:
                            # That's the guy
                            trigger_addr = prev_addr
                            trigger_val = prev_val
                            break
                        prev_state -= 1
                    break
            if not trigger_addr:
                logger.info("Could not find a trigger for IRQ %d", irq_num)
            else:
                logger.info(
                    "Found trigger for IRQ %d at address %#08x with value %#08x" % (
                        irq_num, trigger_addr, trigger_val))
                irq_triggers[irq_num] = (trigger_addr, trigger_val)
                # Now refine the bitpattern
                cur_trigger_val = None
                trigger_vals = defaultdict(int)
                for x in range(len(full_trace)):
                    op, id, addr, val, pc, size, timestamp = full_trace[x]
                    if op == "WRITE" and addr == trigger_addr:
                        cur_trigger_val = val
                    elif op == "READ" and addr == trigger_addr and val != cur_trigger_val:
                        logger.warn("UH OH, one-shot detected for interrupt %d" % irq_num)
                        oneshots.append[irq_num]
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
        interrupt_timings = {}  # Map of interrupt_number to inter-interrupt timings.
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
            disabled = False
            for state in range(trigger_state + 1, len(full_trace)):
                op, id, addr, val, pc, size, timestamp = full_trace[state]
                addr = int(addr)
                if op == "ENTER":
                    print repr(addr), repr(irq_num)
                    if addr == irq_num and not disabled:
                        timing = timestamp - prev_time
                        timings.append(timing)
                        entered = True
                elif op == 'EXIT':
                    if addr == irq_num and entered:
                        prev_time = timestamp
                        entered = False
                elif op == 'WRITE' and addr == trigger_addr and val != trigger_val:
                    print "Interrupt disabled by write of %#08x" % val
                    disabled = True
                    # I think we just turned it off.
                elif op == 'WRITE' and addr == trigger_addr and val == trigger_val:
                    print "Turned on via write to trigger"
                    disabled = False
            logger.info("Got timings for interrupt %d" % (irq_num))
            logger.info("Mean: %f" % numpy.mean(timings))
            logger.info("Stdv: %f" % numpy.std(timings))
            interrupt_timings[irq_num] = timings

        return interrupt_mapping, irq_triggers, interrupt_timings, oneshots

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
        """ Save our model to the specified directory """
        model_file = os.path.join(directory, G.MODEL_FILE)
        logger.info("Saving model to %s", model_file)
        f = open(model_file, "wb+")
        pickle.dump(self.__dict__, f)
        f.close()

    def train(self, filename):
        """
        Train our model, potentially using a specific training model
        :return:
        """
        logger.info("Training hardware pretender (%s)" % filename)

        l = LogReader(filename)

        ##
        ## Step 0: Gather the set of addresses
        ##
        for line in l:
            try:
                op, id, addr, val, pc, size, timestamp = line
            except ValueError:
                logger.warning("Weird line: " + repr(line))
                continue
            if op == "READ" or op == "WRITE":
                self.accessed_addresses.add(int(addr))
        l.close()

        ##
        # Step 1: Divide the possible addresses into peripherals
        ##
        self.peripheral_clusters = cluster_peripherals(list(self.accessed_addresses))
        for x in self.peripheral_clusters:
            print "%d:" % x
            for y in self.peripheral_clusters[x]:
                print hex(y)
        #import IPython; IPython.embed()
        ##
        # Step 2: Associate interrupts, their triggers, and their timings with a
        #  peripheral
        ##
        l = LogReader(filename)
        interrupt_mappings, interrupt_triggers, interrupt_timings, oneshots = \
            self.infer_interrupt_association(l, self.peripheral_clusters)
        l.close()
        #import IPython; IPython.embed()
        # Add our peripheral for each of its memory addresses
        for periph_id, periph_addrs in self.peripheral_clusters.items():
            irq_num = None
            interrupt_trigger = None
            interrupt_timing = None
            logger.info("Packing peripheral %d" % periph_id)
            if periph_id in interrupt_mappings:
                irq_num = interrupt_mappings[periph_id]

            if irq_num in interrupt_triggers:
                interrupt_trigger = interrupt_triggers[irq_num]

            if irq_num in interrupt_timings:
                interrupt_timing = interrupt_timings[irq_num]
            if irq_num in oneshots:
                one_shot = True
            else:
                one_shot = False

            #import IPython; IPython.embed()
            peripheral = PeripheralModel(periph_addrs,
                               irq_num=irq_num,
                               interrupt_trigger=interrupt_trigger,
                               interrupt_timings=interrupt_timing,
                               interrupt_oneshot=one_shot)
            self.peripherals.append(peripheral)
            for addr in periph_addrs:
                self.model_per_address[addr] = peripheral

            # Train our peripheral
            peripheral.train(filename)

        return True

        """
            Ignoring all of our old stuff
        """

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
        # Step 1: Divide the possible addresses into peripherals
        ##
        self.peripheral_clusters = cluster_peripherals(addrs)

        ##
        # Step 2: Associate interrupts, their triggers, and their timings with a
        #  peripheral
        ##
        l = LogReader(filename)
        interrupt_mappings, interrupt_triggers, interrupt_timings = \
            self.infer_interrupt_association(l, self.peripheral_clusters)
        l.close()

        # TODO: What is step 3?

        ##
        # Step 4: Collect some more stats
        # Also break up the trace into its peripheral cluster pieces
        # EDG says: I have no idea what this is for
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
                    if cluster in interrupt_mappings and addr == \
                            interrupt_mappings[cluster]:
                        trace_by_cluster[cluster].append(
                            (op, id, addr, val, pc, size, timestamp))

                if addr in addrs:
                    trace_by_cluster[cluster].append(
                        (op, id, addr, val, pc, size, timestamp))
            if pc not in pc_cluster:
                pc_cluster[pc] = {'reads': {},
                                  'writes': {},
                                  'log': []}

            if op == 'ENTER' or op == 'EXIT':
                continue  # avoid memory only code
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
        # Step 5: Fit the shortcut models to memory locations.
        # IN other words, find our storage locations, increasing locations, etc
        # The rest are marked with a model of None, which will cause stateful
        # replay
        ##
        for address in self.model_per_address:
            if len(self.model_per_address[address]['writes']) == 0:
                logger.info("%s is a read-only location." % hex(address))

                pattern = PatternModel.fits_model(self.model_per_address[
                                                      address]['reads'])

                # Monotonically increasing?
                if IncreasingModel.fits_model(self.model_per_address[address][
                                                  'log']):
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
                    # pprint.pprint(self.model_per_address[address], width=120)

            elif len(self.model_per_address[address]['reads']) == 0:
                logger.info("%s is a write-only location." % hex(address))
            else:
                logger.info("%s is a read/write location! (Tricky...)" % hex(
                    address))

                pattern = PatternModel.fits_model(self.model_per_address[
                                                      address]['reads'])
                # Does it look like it's just normal memory storage?
                if SimpleStorageModel.fits_model(self.model_per_address[
                                                     address]['log']):
                    # Set our model to simple storage, initialized with the
                    # first read value
                    logger.info("Found a storage unit @ %s (init: %d)" % (hex(
                        address), self.model_per_address[
                                                                              address][
                                                                              'reads'][
                                                                              0]))
                    self.model_per_address[address]['model'] = \
                        SimpleStorageModel(init_value=self.model_per_address[
                            address]['reads'][0])

                # Do the reads just repeat a pattern?
                elif pattern:
                    logger.info("Found a pattern unit @ %s" % hex(address))
                    self.model_per_address[address]['model'] = PatternModel(
                        pattern)
                    # Does it look like it's just complex memory storage?
                    # elif self.is_fuzzy_storage(self.model_per_address[address][
                    #                                'log']):
                    #     logger.info("Found a fuzzy storage @ %s" % hex(address))
                    # self.model_per_address[address]['model'] = \
                    #    FuzzyStorageModel(
                    #        self.model_per_address[address]['log'])
                    # self.model_per_address[address]['model'] = None
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
            if periph_id in interrupt_mappings:
                irq_num = interrupt_mappings[periph_id]

            if irq_num in interrupt_triggers:
                interrupt_trigger = interrupt_triggers[irq_num]

            if irq_num in interrupt_timings:
                interrupt_timing = interrupt_timings[irq_num]

            periph = MMIOGroup(periph_addrs, trace_by_cluster[periph_id],
                               irq_num=irq_num,
                               interrupt_trigger=interrupt_trigger,
                               interrupt_timings=interrupt_timing)
            for addr in periph_addrs:
                mdl = self.model_per_address[addr]['model']
                periph.models[addr] = mdl
                self.model_per_address[addr]['model'] = periph

    def get_model(self, address):
        """
        return the name of the model that is controlling the address
        :param address:
        :return:
        """

        if address in self.model_per_address:
            return repr(self.model_per_address[address])
        else:
            return None

            #
            # if address in self.model_per_address:
            #     n = self.model_per_address[address]['model'].__class__.__name__
            #     if 'MMIOGroup' in n:
            #         real_m = self.model_per_address[address]['model'].models[
            #             address]
            #         n += "@" + hex(
            #             self.model_per_address[address]['model'].min_addr())
            #         if real_m is None:
            #             n += "#" + str(
            #                 self.model_per_address[address]['model'].state)
            #         else:
            #             n += ":" + real_m.__class__.__name__
            #     return n
            # else:
            #     # No model?  Let's just default to storage then
            #     return None

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
            self.model_per_address[address] = SimpleStorageModel()

        else:
            return self.model_per_address[address].write(address, size, value)

            # if address not in self.model_per_address:
            #     logger.debug(
            #         "No model found for %s, using SimpleStorageModel...",
            #         hex(address))
            #     self.__init_address(address)
            #     self.model_per_address[address]['model'] = SimpleStorageModel()
            #
            # if self.model_per_address[address]['model'] is not None:
            #     if isinstance(self.model_per_address[address]['model'], MMIOGroup):
            #         logger.debug("Writing to MMIOGroup at %#08x" % address)
            #         return self.model_per_address[address]['model'].write_memory(
            #             address, size, value)
            #     elif isinstance(self.model_per_address[address]['model'],
            #                     NucleoUSART):
            #         logger.debug("Writing to virtual serial port")
            #         return self.model_per_address[address]['model'].write_memory(
            #             address, size, value)
            #     return self.model_per_address[address]['model'].write(value)
            # else:
            #     return True

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
            self.model_per_address[address] = SimpleStorageModel()
            print "No model found for %s, using SimpleStorageModel..." % hex(
                address)

        #print self.model_per_address[address]
        return self.model_per_address[address].read(address, size)

        # An address we've never seen, or couldn't determine a model?
        # Let's just call it storage
        if address not in self.model_per_address or self.model_per_address[
            address]['model'] is None:
            logger.debug(
                "No model found for %s, using SimpleStorageModel...",
                hex(address))
            self.__init_address(address)
            self.model_per_address[address]['model'] = SimpleStorageModel()

        logger.debug(
            "Using model %s" % self.model_per_address[address]['model'])
        if isinstance(self.model_per_address[address]['model'], MMIOGroup):
            logger.debug("Reading from MMIOGroup")
            return self.model_per_address[address]['model'].read_memory(address,
                                                                        size)
        elif isinstance(self.model_per_address[address]['model'], NucleoUSART):
            logger.debug("Reading from virtual serial port")
            return self.model_per_address[address]['model'].read()

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

    def merge(self, other_model):

        # Generate new peripherals, based on *all* of the observed addresses
        pm = PretenderModel()
        all_addresses = self.accessed_addresses | other_model.accessed_addresses
        pm.peripheral_clusters = cluster_peripherals(list(all_addresses))

        # we merge both of the peripherals into the new one
        new_peripherals = []
        for periph_id, periph_addrs in pm.peripheral_clusters.items():
            # print periph_id, periph_addrs

            peripheral = PeripheralModel(periph_addrs)

            # Merge in this one
            for p1 in self.peripherals:
                peripheral.merge(p1)

            # Merge in other one
            for p2 in other_model.peripherals:
                peripheral.merge(p2)

            pm.peripherals.append(peripheral)
            for addr in periph_addrs:
                pm.model_per_address[addr] = peripheral

        return pm

        # # Copy all unknown from other to current
        # for addr in other_model.model_per_address:
        #     if addr not in self.model_per_address:
        #         logger.info("Copying model verbatim for 0x%08X, because it "
        #                     "doesn't exist in current model" % addr)
        #         self.model_per_address[addr] = other_model.model_per_address[
        #             addr]


        """
        Commenting out old code, but keeping it for now
        """
        # for addr in self.model_per_address:
        #
        #     if type(self.model_per_address[addr]['model']) == \
        #             type(other_model.model_per_address[
        #                      addr]['model']):
        #         # No model?
        #         if self.model_per_address[addr]['model'] is None:
        #             logger.info("Model @ %s is empty!" % hex(addr))
        #             continue
        #
        #         # Let's merge 'em!
        #
        #         logger.info("found matching models @ %s!  merge em! %s" % (
        #             hex(addr),
        #             self.model_per_address[addr]['model']))
        #         self.model_per_address[addr]['model'].merge(
        #             other_model.model_per_address[addr]['model'])
        #
        #     else:
        #         logger.info("models don't match @ %s! %s != %s" % (addr,
        #                                                            self.model_per_address[
        #                                                                addr][
        #                                                                'model'],
        #                                                            other_model.model_per_address[
        #                                                                addr][
        #                                                                'model']
        #                                                            ))

    def get_peripherals(self):
        return self.peripherals

    def collapse_all(self):
        logger.info("Collapsing all states")
        for peripheral in self.peripherals:
            # print peripheral
            for state in peripheral.list_states():
                # print state
                peripheral.state_collapse(state)
