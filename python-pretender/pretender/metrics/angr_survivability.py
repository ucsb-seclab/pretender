import os
import angr
import logging
import sys

logger = logging.getLogger(__name__)
LOOPING_LIMIT = 600 # some value


class LoopSurvivability:
    def __init__(self, binary, base_addr, recording_dir):

        self.p = angr.Project(binary, main_opts={'backend': 'blob', 'custom_arch': 'arm', 'custom_base_addr': base_addr})
        self.cfg = self.p.analyses.CFG()
        rec_file = recording_dir + '/emulated_output.csv'

        assert os.path.isfile(rec_file), "No output csv found in " + recording_dir

        rec_file_cnt = open(rec_file).read().split('\r\n')

        self.pcs = [v.split('\t')[4] for v in rec_file_cnt if v]
        self.tot_seen_blocks = []
        self.seen_loops = {}
        self.last_loop = []

    def is_stuck_in_loop(self):
        for pc in self.pcs:
            if pc in self.tot_seen_blocks:
                # we gotta a loop
                last_seen = [pos for pos, x in enumerate(self.tot_seen_blocks) if x == pc][-1]
                sign_loop = tuple(self.tot_seen_blocks[last_seen:] + [pc])
                if sign_loop not in self.seen_loops:
                    self.seen_loops[sign_loop] = 0
                self.seen_loops[sign_loop] += 1
                self.last_loop = sign_loop

                if not self.has_loop_exit(sign_loop):
                    return True

            self.tot_seen_blocks.append(pc)

        # we consider ourselves stuck in a loop when we are still looping in the last seen loop
        # and the number of iterations overcome a certain threshold
        if self.last_loop and self.pcs[-1] in self.last_loop and self.seen_loops[self.last_loop] > LOOPING_LIMIT:
            return True
        return False

    def has_loop_exit(self, sign_loop):
        # takes a list of blocks representing a loops and uses angr's CFG
        # to see whether there exists a possible exit
        entry = sign_loop[0]
        min_addr, max_addr = min(sign_loop), max(sign_loop)

        seen_blocks = []
        block = self.cfg.get_any_node(entry)
        if not block:
            logger.warning("CFG does not have block {}, skipping this loop".format(entry))
            return True

        blocks = [block]
        while blocks:
            block = blocks[0]
            seen_blocks.append(block)
            blocks = blocks[1:]
            next_blocks = [b for b in block.successors if b and b not in seen_blocks]

            # check whether the node has a successors we haven't seen which is outside the signature of the
            # loop
            if any([b for b in next_blocks if b.addr not in sign_loop and (b.addr < min_addr or b.addr > max_addr)]):
                return True

            blocks += next_blocks
        return False


if __name__ == "__main__":
    try:
        path_rec = sys.argv[2]
        binary_path = sys.argv[1]
    except:
        print "Usage: {} binary record_path".format(sys.argv[0])
        sys.exit(0)

    print str(LoopSurvivability(binary_path, path_rec).is_stuck_in_loop())

