
import sys, os, re

# WRITE   72  1073744952  3812    134219732   4   1516661108.333252 

with open(sys.argv[1]) as f:
    for line in f.read().splitlines():
        stuff = line.split()
        stuff[2] = hex(int(stuff[2]))
        stuff[3] = hex(int(stuff[3]))
        stuff[4] = hex(int(stuff[4]))
        print "\t".join(stuff)

