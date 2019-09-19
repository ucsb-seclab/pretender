#!/usr/bin/env python
"""
    This is our Python package for Pretender.
"""
import os
from distutils.core import setup


def get_packages(rel_dir):
    packages = [rel_dir]
    for x in os.walk(rel_dir):
        # break into parts
        base = list(os.path.split(x[0]))
        if base[0] == "":
            del base[0]

        for mod_name in x[1]:
            packages.append(".".join(base + [mod_name]))

    return packages


setup(name='pretender',
      version='2.0a',
      description='This is the Python library for Pretender',
      author='Eric Gustafson and Chad Spensky',
      author_email='cspensky@cs.ucsb.edu',
      url='https://seclab.cs.ucsb.edu',
      packages=get_packages('pretender'), requires=['avatar2','PyYAML', 'pyserial', 'scipy', 'numpy', 'statsmodels']
      )
