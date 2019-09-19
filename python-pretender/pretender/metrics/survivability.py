from coverage import get_hit_blocks
from collections import defaultdict
import os

def survivability(binary, old_recording_dir, new_recording_dir):
    """
    Return a "score" of the relative survivability of a model, given two traces
    :param firmware_bianry: The binary (not used, yet)
    :param old_recording_dir: the old recording dir we want to compare to
    :param new_recording_dir: the new recording dir we want to compare
    :return:
    """
    # Notes:
    # "recording_dir" has in it:
    # 1. the IO traces, as "emulate_log.csv" (see below for what to do with that)
    # 2.the QEMU trace log "qemu_trace.txt" (see coverage.py for what to do with that)
    # This gets you the full basic block trace.
    block_score = compare_hit_blocks(os.path.join(old_recording_dir, 'comparison_logs', 'qemu_trace_log.txt'),
                                     os.path.join(new_recording_dir, 'comparison_logs', 'qemu_trace_log.txt'))


def compare_hit_blocks(qemu_trace_a, qemu_trace_b):
    blocks_a = get_hit_blocks(qemu_trace_a)
    blocks_b = get_hit_blocks(qemu_trace_b)
    missed_blocks_a = blocks_a.difference(blocks_b)
    new_blocks_b = blocks_b.difference(blocks_a)

    percent_added = len(list(new_blocks_b)) / len(list(blocks_a))
    percent_missed = len(list(missed_blocks_a)) / len(list(blocks_b))
    # Intuition: If we get "stuck" by what we just did, we'll decrease the block coverage
    # We may get some "increase" due to also hitting the error-related blocks
    # Intuition 2: If we get un-stuck by an optimization, we will see a superset of blocks in b;
    # Increase will be large, and decrease will be near zero.
    return 0 - percent_missed + percent_added


def get_peripheral_accesses_count(trace_file):
    l = LogReader(filename)
    accesses = defaultdict(int)
    for line in l:
        try:
            op, id, addr, val, pc, size, timestamp = line
        except ValueError:
            logger.warning("Weird line: " + repr(line))
            continue
        addr = int(addr)
        val = int(val)
        if op == 'ENTER' or op == 'EXIT':
            continue
        if op == "READ" or op == "WRITE":
            accesses[addr] += 1
    l.close()
    return accesses


def compare_periph_accesses(trace_a, trace_b):
    # Compare peripheral access count.  Score of 0 means they're the same.
    # A large difference from zero means we fucked up.
    acc_a = get_peripheral_accesses_count(trace_a)
    acc_b = get_peripheral_accesses_count(trace_b)

    # Hack: This is a first order approximation
    periphs_a = set(acc_a.keys())
    periphs_b = set(acc_b.keys())
    new_blocks_a = periphs_a.difference(periphs_b)
    new_blocks_b = periphs_b.difference(periphs_a)
    percent_decrease = len(list(new_blocks_b)) / len(list(blocks_a))
    percent_increase = len(list(new_blocks_a)) / len(list(blocks_b))
    return percent_increase, percent_decrease
