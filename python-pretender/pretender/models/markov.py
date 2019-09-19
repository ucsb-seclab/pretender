import logging
from pretender.models import MemoryModel
from pretender.logger import LogReader
import random

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

DECREASE_FACTOR = 2


class MarkovModel(MemoryModel):
    """
    Each model is divided in states. We transition to a new state upon a memory write.
    Each states contains a list of possible values the memory address might contain. Values are equiprobable.

    Models are trained to find, for each state, a set of data that satisfy a provided test function.

    """

    def __init__(self, test_callback=None):
        self.values = []
        self.value = None

        # data structures to train the model
        # n_window is the number of windows to fetch data from within a given
        # state. Each data within a window is retrieved with the same probability
        self.n_windows = 1

        # Pointer to the current window to consider
        self.window_index = 0

        # Testing function. Used for training the model
        self.survival_test = test_callback if test_callback is not None else self.__verbatim_test

    def __verbatim_test(self, val, line):
        line_val = int(line[0])
        return val == line_val

    def train(self, log):
        """
        Train the model to find the best "window" of values given a test function.
        :return:
        """
        logger.debug("Training Markov Model")

        self.values = [int(r[0]) for r in log]

        # starting values
        self.n_windows = len(log)
        self.window_index = 0
        best_n_windows = self.n_windows
        last_run = False

        while True:
            # test all the reads
            if not any([self.survival_test(self.read(), l) for l in log]):
                # if the run doesn't survive, get out.
                break
            else:
                # otherwise, consider this window
                best_n_windows = self.n_windows
            if last_run:
                break

            # let's increase the windows sizes and re-train
            self.window_index = 0
            self.n_windows /= DECREASE_FACTOR

            if self.n_windows <= 1:
                self.n_windows = 1
                last_run = True

        # final model values
        self.n_windows = best_n_windows
        self.window_index = 0
        return True

    def write(self, value):
        return True

    def read(self):
        nelem = len(self.values)
        wnelem = nelem / self.n_windows
        lb = self.window_index * wnelem
        ub = lb + wnelem
        if ub >= nelem:
            ub = nelem
        assert lb <= ub, "Window upper bound wrapped around, wtf..."
        self.value = random.choice(self.values[lb:ub])
        # we read a value, move the index
        self.window_index = (self.window_index + 1) % self.n_windows
        return self.value

    def merge(self, other_model):
        if type(other_model) != type(self):
            logger.error("Tried to merge two models that aren't the same (%s "
                         "!= %s)" % (type(other_model), type(self)))
            return

        # Just add the other training data to our fuzzy model
        self.__train_log(other_model.log)

    @staticmethod
    def fits_model(log):
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
