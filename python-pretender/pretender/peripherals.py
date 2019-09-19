# Native
import logging
import random

# Avatar 2
from avatar2.peripherals import AvatarPeripheral

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


class Pretender(AvatarPeripheral):
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
