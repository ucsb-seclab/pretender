# Pretender: Automatically Emulating Hardware

This is the source code used in the paper 'Toward the Analysis of Embedded Firmware through Automated Re-Hosting'.
With the included tools, you can record, model, and emulate peripherals of embedded microcontroller devices.

You can read the paper here: http://subwire.net/publication/pretender/

## What's included:

* *python-pretender*: the source code of the Pretender python module.

* *test_programs*: A corpus of test programs, for different boards

- *examples*: Some handy scripts showing how to run Pretender

## Setup:

*A word of caution*: The recording phase of Pretender, which relies on Avatar, OpenOCD, and their numerous dependencies, can be rather fragile to set up and deploy.  We've noticed small version changes in any of these components can cause various things not to work as expected, or behave intermittently, particularly regarding interrupts.  Even the host system's hardware, such as the USB bus controllers (and other devices attached to them) have caused nondeterministic issues during our experiments.  While we made an effort to track down these issues and report them to the various parties involved, some bugs in these underlying tools still remain that prevent us from using the latest versions.

We've made the best effort to provide instructions to reproduce our environment exactly, although due to the obvious hardware issues involved, we can't simply ship this all in something like a Docker container. We did make sure the system behaved normally on more than one machine before releasing the code.

We performed all experiments on a system running Ubuntu 16.04.

We recommend installing and configuring Pretender in a virtual environment 
(using bash)

```bash
mkvirtualenv pretender
```

You will need:

* avatar2: 
As of 9/17/2019, all our changes to avatar were upstreamed, and can be found on the master branch. We tested with version 1.3.0
https://github.com/avatartwo/avatar2

* OpenOCD:
Use git version `edb6796`
Newer versions introduce bugs regarding breakpoints over STLink devices (and therefore cause interrupt recording issues on STM32 devices)

* arm-none-eabi-gdb 
We used version `7.10-1` shipped with Ubuntu 16.04.
Newer versions cause tons of Avatar-related issues we haven't been able to track down.

* arm-none-eabi-gcc (to compile the examples if needed)
We used version  `4.9.3 20150529` shipped with Ubuntu 16.04.  Newer versions are known to break compilation, likely due to bugs in the included version of the libmbed build scripts.

* Optional: ykush and pykush
In order to minimize the impact of the above issues, and make things more repeatable,, we used the amazing YKUSH switchable USB hub (http://yepkit.com/products/ykush/) to reboot our devices before each recording.
Hook your board up to one of the ports, and use the -b option of pretender-recorder to have your board automagically rebooted during recording!

Once your virtual environment is setup, you should be able to install the pretender tools themselves:

```bash
cd python-pretender
pip install -e .
```

You can now use the tools in `python-pretender/bin`.  See the `examples` folder for some useful examples.
