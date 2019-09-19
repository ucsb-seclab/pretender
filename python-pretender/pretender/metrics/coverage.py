#!/usr/bin/env python
import os
import re
import sys

#hit_re = re.compile("Chain 0x\w+ \[\d: (\w+)\]\s*")
hit_re = re.compile("Trace 0x\w+ \[\d: (\w+)\]\s*")


def get_hit_blocks(trace_file):
    hit_blocks = set()
    with open(trace_file, 'r') as f:
        lines = f.read().splitlines()
        for line in lines:
            m = hit_re.match(line)
            if m:
                addr = int(m.group(1),16)
                hit_blocks.add(addr)
            
    return hit_blocks

if __name__ == '__main__':
    blocks = get_hit_blocks(sys.argv[1])
    print "Hit %d blocks:" % len(blocks)
    print ",".join([hex(b) for b in sorted(blocks)])
