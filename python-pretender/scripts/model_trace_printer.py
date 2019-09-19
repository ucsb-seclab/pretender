import os, sys, pickle

fn = sys.argv[1]
addr = int(sys.argv[2], 16)


with open(fn, 'rb') as f:
    m = pickle.load(f)
mdl = m[addr]['model']

for tr in mdl.trace:
    n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp = tr
    n_addr = hex(n_addr)
    n_val = hex(n_val)
    n_pc = hex(n_pc)
    print "%s %s %s %s %s %s %s" % (n_op, n_id, n_addr, n_val, n_pc, n_size, n_timestamp)

