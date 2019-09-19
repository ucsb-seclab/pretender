import collections
import logging
import random

import sys

logger = logging.getLogger(__name__)
from pretender.models import MemoryModel


class MarkovPatternModel(MemoryModel):
    def __init__(self):
        self.total_static_patterns = 0
        self.total_patterns = 0
        self.static_value_count = {}
        self.patterns = {}
        self.value = 0

        self.count = 0

        self.static_value = None
        self.pattern_current = []
        self.pattern_index = 0
        self.pattern_distribution = collections.OrderedDict()
        self.static_distribution = collections.OrderedDict()
        self.replay_static = True
        self.replay_static_count_current = 0
        self.replay_static_count = 0

    def __str__(self):
        return "<MarkovPatternModel %s, %s>" % (self.static_value,
                                                self.pattern_distribution)

    def __repr__(self):
        return "<MarkovPatternModel %s, %s>" % (self.static_value,
                                                self.pattern_distribution)

    def write(self, value):
        self.value = value
        return True

    def read(self):
        # Pick a random index within the total number of reads
        rand_idx = random.random()

        # Should we replay the static value?  Just pick how many times
        if self.replay_static:
            # Are we currently replaying static values?
            if self.replay_static_count_current > 0:
                if self.replay_static_count_current == \
                                self.replay_static_count - 1:
                    self.replay_static = False
                    self.replay_static_count = 0
                    self.replay_static_count_current = 0
                else:
                    self.replay_static_count_current += 1

                return self.static_value

            # Loop over all of our total observed reads until we sum to the index
            for cumulative_probability in self.static_distribution:
                if rand_idx < cumulative_probability:
                    self.replay_static_count = self.static_distribution[
                        cumulative_probability]

            self.replay_static_count_current = 1
            return self.static_value

        else:
            # Are we currently replaying a pattern?
            if len(self.pattern_current) > 0:
                if self.pattern_index >= len(self.pattern_current) - 1:
                    rtn = self.pattern_current[-1]
                    self.pattern_current = []
                    self.pattern_index = 0
                    self.replay_static = True
                    return rtn
                else:
                    # print self.pattern_index
                    # print self.pattern_current
                    self.pattern_index += 1
                    return self.pattern_current[self.pattern_index]

            # Loop over all of our total observed reads until we sum to the index
            for cumulative_probability in self.pattern_distribution:
                if rand_idx < cumulative_probability:
                    self.pattern_current = self.pattern_distribution[
                        cumulative_probability]
                    self.pattern_index = 1
                    return self.pattern_current[0]

    def merge(self, other_model):
        if type(other_model) != type(self):
            logger.debug("Tried to merge two models that aren't the same (%s "
                         "!= %s)" % (type(other_model), type(self)))
            return False

        # Merge our raw data (static counts)
        for count in other_model.static_value_count:
            if count in self.static_value_count:
                self.static_value_count[count] += \
                    other_model.static_value_count[count]
            else:
                self.static_value_count[count] = \
                    other_model.static_value_count[count]

        # Merge our raw data (pattern counts)
        for p in other_model.patterns:
            if p in self.patterns:
                self.patterns[p] += other_model.patterns[p]
            else:
                self.patterns[p] = other_model.patterns[p]

        # Update our counts
        self.total_static_patterns += other_model.total_static_patterns
        self.total_patterns += other_model.total_patterns

        # Get the distribution for our static value
        cumulative_probability = 0.0
        for count in self.static_value_count:
            probability = 1.0 * self.static_value_count[count] / (
                1.0 * self.total_static_patterns)
            cumulative_probability += probability
            self.static_distribution[cumulative_probability] = count

        # Get the distribution for our sub patterns
        cumulative_probability = 0.0
        for p in self.patterns:
            probability = 1.0 * self.patterns[p] / (
                1.0 * self.total_patterns)
            cumulative_probability += probability
            self.pattern_distribution[cumulative_probability] = p

        logger.debug(
            "Merged MarkovPatternModel (%s, %s)" % (
                repr(self.static_distribution),
                repr(self.pattern_distribution)))

        return True

    def train(self, log):
        """
        Attempt to train as a pattern model that has probabilistic sub-patterns

        :param log:
        :return:
        """
        # Only extract our read values
        reads = [x[0] for x in log]

        # Extract our static value
        self.static_value = self._get_static_value(reads)

        # No value that shows up a majority of the time?
        if self.static_value is None:
            return False

        # Should we start with the static value or a pattern?
        if reads[0] != self.static_value:
            self.replay_static = False

        # Let's store all of our patterns and counts for static value
        static_count = 0
        pattern = []

        # Extract all of our patterns and counts for our static value
        first = True
        for val in reads:

            # See our static value, let's store our pattern, or update the count
            if val == self.static_value:

                # add our pattern to be replayed later
                if len(pattern) > 0:
                    pattern = tuple(pattern)
                    if pattern not in self.patterns:
                        self.patterns[pattern] = 0

                    self.patterns[pattern] += 1
                    self.total_patterns += 1
                    pattern = []

                static_count += 1
            else:

                # New pattern?
                if len(pattern) == 0 and not first:
                    # Save the count for static observations
                    if static_count not in self.static_value_count:
                        self.static_value_count[static_count] = 0
                        self.static_value_count[static_count] += 1
                    static_count = 0

                    self.total_static_patterns += 1

                # Start recording our pattern
                pattern.append(val)

            first = False

        # add our pattern to be replayed later
        if len(pattern) > 0:
            pattern = tuple(pattern)
            if pattern not in self.patterns:
                self.patterns[pattern] = 0

            self.patterns[pattern] += 1
            self.total_patterns += 1

        # Get the distribution for our static value
        cumulative_probability = 0.0
        for count in self.static_value_count:
            probability = 1.0 * self.static_value_count[count] / (
                1.0 * self.total_static_patterns)
            cumulative_probability += probability
            self.static_distribution[cumulative_probability] = count

        # Get the distribution for our sub patterns
        cumulative_probability = 0.0
        for p in self.patterns:
            probability = 1.0 * self.patterns[p] / (
                1.0 * self.total_patterns)
            cumulative_probability += probability
            self.pattern_distribution[cumulative_probability] = p

        logger.debug(
            "Trained MarkovPatternModel (%s, %s)" % (
                repr(self.static_distribution),
                repr(self.pattern_distribution)))

        return True

    @staticmethod
    def _get_static_value(reads):
        """
        Return the value that is most frequent
        :param reads:
        :return:
        """
        # Count the frequency of all of the reads
        read_count = {}
        for val in reads:
            if val not in read_count:
                read_count[val] = 0

            read_count[val] += 1

        # Is a single value a majority of the read values?
        for val in read_count:
            if read_count[val] > 0.5 * len(read_count):
                return val

        return None

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

        return MarkovPatternModel._get_static_value(reads) is not None
