import logging

logger = logging.getLogger(__name__)

from pretender.models import MemoryModel


class SimpleStorageModel(MemoryModel):
    def __init__(self, init_value=0):
        self.value = init_value
        self.init_timestamp = None

    def __repr__(self):
        return "<Simple Storage: val = %s>" % str(self.value)

    def write(self, value):
        self.value = value
        return True

    def read(self):
        if self.value is None:
            return 0
        return self.value

    def merge(self, other_model, same_log_merge=True):
        if type(other_model) != type(self):
            logger.debug("Tried to merge two models that aren't the same (%s "
                         "!= %s)" % (type(other_model), type(self)))
            return False

        if self.value != other_model.value:
            if same_log_merge:
                if self.init_timestamp > other_model.init_timestamp:
                    self.value = other_model.init_timestamp

            self.value = 0

        return True

    def train(self, log):
        self.value = log[0][0]
        self.init_timestamp = log[0][3]

    @staticmethod
    def fits_model(log):
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
