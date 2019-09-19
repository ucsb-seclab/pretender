import logging

logger = logging.getLogger(__name__)
from pretender.models import MemoryModel


class PatternModel(MemoryModel):
    def __init__(self):
        self.value = 0
        self.read_pattern = []
        self.count = 0

    def __str__(self):
        return "<PatternModel %s>" % self.read_pattern

    def __repr__(self):
        return "<PatternModel %s>" % self.read_pattern

    def write(self, value):
        self.value = value
        return True

    def read(self):
        idx = self.count % len(self.read_pattern)
        self.count += 1
        return self.read_pattern[idx]

    def merge(self, other_model):
        if type(other_model) != type(self):
            logger.debug("Tried to merge two models that aren't the same (%s "
                         "!= %s)" % (type(other_model), type(self)))
            return False

        if self.read_pattern != other_model.read_pattern:
            logger.debug("Patterns are different. (%s != %s)" % (
                self.read_pattern, other_model.read_pattern))
            return False

        return True

    def train(self, log):
        """
        Attempt to try a pattern model, or return False if no pattern is
        detected

        :param log:
        :return:
        """

        # Only extract our read values
        reads = [x[0] for x in log]

        self.read_pattern = self.get_pattern(reads)

        if self.read_pattern is None:
            return False
        else:
            return True

    @staticmethod
    def get_pattern(reads):
        """
        Extract a pattern out of a stream of read values

        NOTE: We assume that any stream is a pattern!  When merging we will
        find out if the pattern is the wrong thing to do.

        :param reads:
        :return:
        """
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
                if not all(remainder[i] == reads[i] for i in
                           range(len(remainder))):
                    is_pattern = False
                if is_pattern:
                    return reads[0:seqn_len]

        return reads

    @staticmethod
    def fits_model(log):
        """
        Determine if the reads always return some fixed pattern.

        For now, we are ignoring writes; however, we should clearly
        incorporate them in the future, maybe even a different model

        @TODO Incorporate writes?

        :param log:
        :return:
        """

        # if len(reads) < 2:
        #     return False

        # Only extract our read values
        reads = [x[0] for x in log]

        return PatternModel.get_pattern(reads) is not None
