#!/usr/bin/env python
import logging
from pretender.model import Pretender

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

p = Pretender('memory.log')
p.train()
