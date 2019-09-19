import csv


class LogWriter:
    def __init__(self, filename):
        self.csvfile = open(filename, 'wb')
        self.writer = csv.writer(self.csvfile, delimiter='\t',
                                 quotechar='|', quoting=csv.QUOTE_MINIMAL)

    def write_row(self, row):
        """
        Write a list of values to our log file
        :param row:
        :return:
        """
        self.writer.writerow(row)

    def close(self):
        # self.file.close()
        self.csvfile.close()


class LogReader:
    def __init__(self, filename):
        self.csvfile = open(filename, 'rb')
        self.reader = csv.reader(self.csvfile, delimiter='\t',
                                 quotechar='|', quoting=csv.QUOTE_MINIMAL)

    def __iter__(self):
        return self

    def next(self):
        return self.read_row()

    def close(self):
        # self.file.close()
        self.csvfile.close()

    def read_row(self):
        return self.reader.next()
