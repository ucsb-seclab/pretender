import os
import yaml
import logging
from time import sleep

from avatar2 import *
from avatar2.targets.jlink_target import JLinkTarget

from pretender.hooks import *
from pretender.model import PretenderModel
from pretender.old_model import OldPretenderModel
from pretender.peripherals import NullModel, Pretender
from pretender import globals as G
from pretender.logger import LogWriter

l = logging.getLogger("pretender.common")

try:
    import pykush.pykush as pykush

    kush_board = pykush.YKUSH()
except:
    l.exception("PyKush library not found.")
    kush_board = None


def load_config(args):
    if args.board_config:
        l.info("Using board configuration from %s " % args.board_config)
        with open(args.board_config) as f:
            config = yaml.load(f)
        args.__dict__.update(config)
    return args


def reset_board(board):
    global kush_board

    if kush_board is None:
        return

    l.info("Resetting board %d using YKUSH" % board)

    # init pykush
    # yk = pykush.YKUSH()
    # yk.set_allports_state_up()
    # yk.get_downstream_port_count()
    l.debug("Bringing board down.")
    # Drop our port
    kush_board.set_port_state(board, pykush.YKUSH_PORT_STATE_DOWN)

    while kush_board.get_port_state(board) != pykush.YKUSH_PORT_STATE_DOWN:
        time.sleep(1)
    l.debug("Bringing board up...")
    kush_board.set_port_state(board, pykush.YKUSH_PORT_STATE_UP)

    while kush_board.get_port_state(board) != pykush.YKUSH_PORT_STATE_UP:
        time.sleep(1)

    l.debug("Done.")
    sleep(2)


def build_avatar(args, emulate=False):
    l.warning("Creating Avatar")
    if not emulate:
        avatar_dir = os.path.join(args.output_dir, "recording_logs")
    else:
        avatar_dir = os.path.join(args.output_dir, "comparison_logs")
    avatar = Avatar(output_directory=avatar_dir, arch=ARM_CORTEX_M3)

    if "interrupts" in args and args.interrupts:
        l.info("Loading interrupt plugins")
        avatar.load_plugin('arm.armv7m_interrupts')
        avatar.load_plugin('instruction_forwarder')
        avatar.load_plugin('assembler')
        avatar.load_plugin('disassembler')
    return avatar


def build_hardware(avatar, args):
    hardware = None
    if args.proto == 'openocd':
        hardware = avatar.add_target(OpenOCDTarget, name='hardware',
                                     gdb_executable="arm-none-eabi-gdb",
                                     openocd_script=args.openocd_conf)

    elif args.proto == 'jlink':
        hardware = avatar.add_target(JLinkTarget, name='hardware',
                                     serial=args.jlink_serial,
                                     device=args.jlink_device)
    elif args.proto == 'gdb':
        raise RuntimeError("Not implemented yet")
    hardware.gdb_port = args.gdb_port
    hardware.ivt_address = None
    hardware.ivt_unlock = None
    if args.ivt_address:
       hardware.ivt_address = args.ivt_address
    if args.ivt_unlock:
       hardware.ivt_unlock = args.ivt_unlock
    return hardware


def build_emulator(avatar, args):
    qemu_args = []
    G.COVERAGE_LOG = None
    avatar_dir = avatar.output_directory
    if "vomit" in args and args.vomit:
        G.COVERAGE_LOG = os.path.join(avatar_dir, 'qemu_trace_log.txt')
        qemu_args += ['-d', 'all,trace:nvic*,avatar', '-D', G.COVERAGE_LOG]
    elif "coverage" in args and args.coverage:
        G.COVERAGE_LOG = os.path.join(avatar_dir, 'qemu_trace_log.txt')
        qemu_args += ['-d', 'exec', '-D', G.COVERAGE_LOG]
    qemu = avatar.add_target(QemuTarget, name='qemu',
                             gdb_executable="arm-none-eabi-gdb",
                             firmware=args.sample,
                             executable=args.qemu_executable,
                             additional_args=qemu_args)
    qemu.gdb_port = args.qemu_port
    return qemu


def add_partial_model(avatar, emulator, hardware, model_fn, base=0x40000000,
                      size=0x10000000):
    global ignored_ranges
    model_kwargs = {'filename': model_fn, 'host': emulator, 'serial': None}
    # Load the model
    with open(model_fn, 'rb') as f:
        pm = pickle.load(f)
        good_models = set()
        for m in pm.values():
            mdl = m['model']
            if mdl.irq_num and mdl.interrupt_timings and mdl.interrupt_trigger:
                good_models.add(mdl.min_addr())
        cur_addr = base
        count = 0
        # For each range we're going to not forward, add a forwarded range under it, then add the range.
        # Add a final range to fill up the rest
        l.info("Going to use models at %s" % repr(good_models))
        for min_addr in sorted(list(good_models)):
            mdl = pm[min_addr]['model']
            cur_size = mdl.min_addr() - cur_addr
            cur_size &= 0xfffff000
            if cur_size > 0:
                # Add a forwarded range under
                l.info("Forwarding range from %#08x - %#08x" % (
                    cur_addr, cur_addr + cur_size))
                forwarded = avatar.add_memory_range(cur_addr, cur_size,
                                                    name='mmio%d' % count,
                                                    forwarded=True,
                                                    forwarded_to=hardware)
                count += 1
            # Now add the model
            # Round up to nearest 0x100 to appease QEMU
            ignored_ranges.append((mdl.min_addr(), mdl.max_addr()))
            mdl_size = mdl.max_addr() - mdl.min_addr()
            mdl_size += (0x1000 - (mdl_size % 0x1000)) if (
                mdl_size % 0x1000 > 0) else 0
            l.info("Modeling range from %#08x - %#08x" % (
                mdl.min_addr(), mdl.min_addr() + mdl_size))
            modeled = avatar.add_memory_range(mdl.min_addr(), mdl_size,
                                              name='model%d' % count,
                                              emulate=PretenderModel,
                                              kwargs=model_kwargs)
            count += 1
            cur_addr = mdl.min_addr() + mdl_size
        cur_size = base + size - cur_addr
        if cur_size > 0:
            l.info("Forwarding range from %#08x - %#08x" % (
                cur_addr, cur_addr + cur_size))
            forwarded = avatar.add_memory_range(cur_addr, cur_size,
                                                name='mmio%d' % count,
                                                forwarded=True,
                                                forwarded_to=hardware)


def set_memory_map(avatar, args, model=False):
    qemu = avatar.get_target('qemu')
    hardware = None
    try:
        hardware = avatar.get_target('hardware')
    except:
        l.info("No hardware present")

    if not os.path.exists(os.path.join(args.output_dir)):
        l.error("No model file found (%s).  Make sure you "
                "trained a model!" % model_file)
        sys.exit()
    kwargs = {'host': qemu}
    if "serial" in args.__dict__.keys() and args.serial:
        kwargs.update({"serial": True})
    if "max32_serial" in args.__dict__.keys() and args.max32_serial:
        kwargs.update({'max32_serial': True})

    # Setup our memory regions
    l.warn("Adding memory ranges")
    if args.memory_map:
        for region, params in args.memory_map.items():
            base = params['base']
            size = params['size']
            forwarded = params['forwarded']
            l.info("%s: %s" % (region, repr(params)))
            if region == 'mmio':
                # Decide whether we're doing modeling, forwarding, or neither
                # No model at all
                if "no_model" in args and args.no_model:
                    pass
                # The null model
                elif "null_model" in args and args.null_model:
                    mmio = avatar.add_memory_range(base, size, name='mmio',
                                                   emulate=NullModel, kwargs={})
                # A partial model, used to record interrupts
                elif "partial_model" in args and args.partial_model:
                    add_partial_model(avatar, qemu, hardware,
                                      args.partial_model, base=base, size=size)
                    continue
                # The real deal model
                elif model:
                    # Load our model
                    model_file = os.path.join(args.output_dir, G.MODEL_FILE)
                    if args.old:
                        model_file = os.path.join(args.recording_dir,
                                                  G.MODEL_FILE)
                        model_kwargs = {'filename': model_file, 'host': qemu,
                                        'serial': args.serial, 'max32_serial': args.max32_serial}
                        if not os.path.exists(os.path.join(args.recording_dir)):
                            l.error("No model file found (%s).  Make sure you "
                                    "trained a model!" % model_file)
                            sys.exit()
                        mmio = avatar.add_memory_range(base, size, name='mmio',
                                                       emulate=OldPretenderModel,
                                                       kwargs=model_kwargs)
                    else:
                        pretender_model = PretenderModel(filename=model_file,
                                                         **kwargs)
                        mmio = avatar.add_memory_range(base, size, name='mmio',
                                                       forwarded=True,
                                                       forwarded_to=Pretender(
                                                           "Pretender", base,
                                                           size,
                                                           pretender_model))
                else:
                    avatar.add_memory_range(base, size, name=region,
                                            forwarded=forwarded,
                                            forwarded_to=hardware)
            # If this is the ROM, we need to put the actual firmware in!
            elif region == 'rom':
                avatar.add_memory_range(base, size, name=region,
                                        forwarded=forwarded,
                                        forwarded_to=hardware, file=args.sample)
            else:
                avatar.add_memory_range(base, size, name=region,
                                        forwarded=forwarded,
                                        forwarded_to=hardware)
    else:
        l.critical("Using default mem map, is that what you want??")
        ivt = avatar.add_memory_range(0, 0x1000)
        if args.partial_model:
            add_partial_model(avatar, qemu, hardware, args.partial_model,
                              base=0x40000000, size=0x10000000)
        else:
            mmio = avatar.add_memory_range(0x40000000, 0x10000000, name='mmio',
                                           forwarded=True,
                                           forwarded_to=hardware)
        rom = avatar.add_memory_range(0x08000000, 0x80000, name='rom',
                                      file=args.sample)
        ram = avatar.add_memory_range(0x20000000, 0x00019000, name='ram')
