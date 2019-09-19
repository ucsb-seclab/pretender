import abc


class MemoryModel(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def train(self, read_log):
        """ train our model """
        return

    @abc.abstractmethod
    def write(self, input):
        """ Memory write """
        return

    @abc.abstractmethod
    def read(self, output, data):
        """ Memory read """
        return

    @abc.abstractmethod
    def merge(self, other_model):
        """ Merge another model in """
        return

    @abc.abstractmethod
    def fits_model(self, log):
        """ Will return true if the data fits the specific model """
        return
