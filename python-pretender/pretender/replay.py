import csv
import logging
import struct

from avatar2.peripherals import AvatarPeripheral

from model.logger import LogReader

logger = logging.getLogger(__name__)


class HardwarePretender(AvatarPeripheral):
    def __init__(self, name, address, size, recorded_file):
        """

        :param recorded_file:
        """
        AvatarPeripheral.__init__(self, name, address, size)
        logging.info("Starting pretender..")

        self.read_replay = {}
        self.filename = recorded_file

        self.read_handler[0:size] = self.read_memory
        self.write_handler[0:size] = self.write_memory

        self._train()

    def _train(self):
        """
        Train our model, potentially using a specific training model
        :return:
        """
        logger.info("Training hardware pretender (%s)" % self.filename)
        l = LogReader(self.filename)
        for line in l:
            op, id, addr, val, pc, size = line

            addr = int(addr)
            if op == "READ":
                if addr not in self.read_replay:
                    self.read_replay[addr] = {'count': 0,
                                              'values': []}
                self.read_replay[addr]['values'].append(int(val))
            logger.info(line)
        l.close()

        import pprint
        pprint.pprint(self.read_replay)

    def write_memory(self, address, size, value):
        logger.debug("Write %s %s %s" % (address, size, value))
        return True

    def read_memory(self, address, size):
        logger.debug("Read %s %s" % (address, size))
        if address not in self.read_replay:
            logger.info("Address not found (%s, %d)" % (hex(address), size))
            # logger.info(self.read_replay)
            return 0

        # print self.read_replay[address]
        count = self.read_replay[address]['count']
        rtn = self.read_replay[address]['values'][count]
        new_count = (count + 1) % len(self.read_replay[address]['values'])
        self.read_replay[address]['count'] = new_count

        # print self.read_replay[address]
        # print rtn
        return rtn
