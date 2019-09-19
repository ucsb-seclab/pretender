import collections
import logging
from pretender.models import MemoryModel
from pretender.logger import LogReader
import random

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

SCORE_THRESHOLD = 0.8


class MarkovModel(MemoryModel):
    """
    Each model is divided in states. We transition to a new state upon a memory write.
    Each states contains a list of possible values the memory address might contain. Values are equiprobable.

    Models are trained to find, for each state, a set of data that satisfy a provided test function.

    """

    def __init__(self):
        self.storage_recall = {}
        self.value_distribution = collections.OrderedDict()
        self.total_reads = 0
        self.value = 0

    def __repr__(self):
        return "<MarkovModel: %s>" % str(self.value_distribution)

    def train(self, read_log):
        self.total_reads += len(read_log)
        for val, pc, size, timestamp in read_log:
            if val not in self.storage_recall:
                self.storage_recall[val] = 0.0

            self.storage_recall[val] += 1.0

        cumulative_probability = 0.0
        for val in self.storage_recall:
            probability = 1.0 * self.storage_recall[val] / (
            1.0 * self.total_reads)
            cumulative_probability += probability
            self.value_distribution[cumulative_probability] = val

        logger.debug("Trained MarkovModel (%s)" % repr(self.value_distribution))
        return True

    def write(self, value):
        return True

    def read(self):

        # Pick a random index within the total number of reads
        rand_idx = random.random()

        # Loop over all of our total observed reads until we sum to the index
        for cumulative_probability in self.value_distribution:

            if rand_idx < cumulative_probability:
                return self.value_distribution[cumulative_probability]

    def merge(self, other_model):
        if type(other_model) != type(self):
            logger.error("Tried to merge two models that aren't the same (%s "
                         "!= %s)" % (type(other_model), type(self)))
            return False

        # Just add the other training data to our fuzzy model
        self.total_reads += other_model.total_reads
        for val in other_model.storage_recall:
            if val not in self.storage_recall:
                self.storage_recall[val] = other_model.storage_recall[val]
            else:
                self.storage_recall[val] += other_model.storage_recall[val]

        cumulative_probability = 0.0
        self.value_distribution = {}
        for val in self.storage_recall:
            probability = 1.0 * self.storage_recall[val] / (
            1.0 * self.total_reads)
            cumulative_probability += probability
            self.value_distribution[cumulative_probability] = val

        return True

    @staticmethod
    def fits_model(read_log):
        """
        Everything can be made into our markov model

        :param read_log:
        :return:
        """

        return True
