import logging

import time

logger = logging.getLogger(__name__)
from pretender.models import MemoryModel


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

    def __init__(self):
        """
        """

        self.read_times = []
        self.read_count = 0
        self.replay_reads = []
        self.model_trained = False
        self.last_observed_time_adjusted = 0
        self.first_guess_time = 0
        self.outlier_threshold = 0.0001

        self.slope = 0
        self.intercept = 0
        self.r_value = 0
        self.p_value = 0
        self.std_err = 0

        self.outliers_replay = []

    def __str__(self):
        return "<IncreasingModel y = %f*X + %f>" % (self.slope, self.intercept)

    def __repr__(self):
        return "<IncreasingModel y = %f*X + %f>" % (self.slope, self.intercept)

    def train(self, log):

        read_times = []
        read_values = []
        for val, pc, size, timestamp in log:
            read_times.append(float(timestamp))
            read_values.append(int(val))

        if not self.fits_model(read_values):
            return False

        # Update our globals
        self.replay_reads = read_values
        self.model_trained = False
        self.last_observed_time_adjusted = read_values[0]

        # Train our model
        self.train_model(read_times, read_values)
        self.model_trained = True

        return True

    def train_model(self, x, y, max_size=1000):
        """
        Train our model to a linear regression
        :param max_size:
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

        if max_size > 0:
            fixed_x = fixed_x[:max_size]
            y = y[:max_size]

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
            return False

        if self.outliers_replay != other_model.outliers_replay:
            logger.error("The replay reads don't match! (%s != %s)" % (
                self.outliers_replay, other_model.outliers_replay))

        self.slope = (self.slope + other_model.slope) / 2
        self.intercept = (self.intercept + other_model.intercept) / 2

        return True

    @staticmethod
    def fits_model(reads):
        """
        Determine if the reads converge to be always increasing (indicative
        of a timer or counter)

        NOTE: There are likely configuration parameters to setup these memory
        regions that could make them decrease, we are looking for their steady
        state.
        NOTE: A static value would also fit this model as the linear
        regression would be y = C

        :param reads:
        :return:
        """

        if len(reads) < 3:
            return False

        increasing_threshold = .5
        last_read = 0
        first = True
        idx = 0
        not_increasing = []
        for val in reads:
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
        elif len(not_increasing) < increasing_threshold * len(reads) and \
                        not_increasing[-1] < increasing_threshold * len(reads):
            return True
        else:
            return False
