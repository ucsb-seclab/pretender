#!/usr/bin/env bash
SAMPLE="../test_programs/nucleo_f0/uart/BUILD/Nucleo_read_hyperterminal.bin"
CFG="../python-pretender/configs/nucleo_f0.yaml"
OUT="./f072_uart"
BOARD=1

echo "Recording..."
../python-pretender/bin/pretender-recorder -S UARTStimulator -b $BOARD --board-config $CFG -C  -s $SAMPLE -r 3 -o $OUT
echo "Building a model"
../python-pretender/bin/pretender-model-generate --old -r $OUT
echo "Emulating..."
../python-pretender/bin/pretender-emulate --old --board-config $CFG -C -s $SAMPLE -r $OUT
