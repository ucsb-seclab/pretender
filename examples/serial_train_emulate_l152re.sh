#!/usr/bin/env bash
SAMPLE="./test_programs/nucleo_l1/uart/BUILD/Nucleo_read_hyperterminal.bin"
STIM="UARTStimulator"
CFG="../python-pretender/configs/nucleo_l1.yaml"
OUT="./l152_uart"
BOARD=1

echo "Recording..."
../python-pretender/bin/pretender-recorder -b $BOARD --board-config $CFG -C  -s $SAMPLE -r 3 -o $OUT -S $STIM
echo "Building a model"
../python-pretender/bin/pretender-model-generate -r $OUT
echo "Emulating"
../python-pretender/bin/pretender-emulate --board-config $CFG -C -s $SAMPLE -r $OUT
