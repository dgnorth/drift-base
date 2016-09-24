#!/usr/bin/env python
import os
from os.path import join, abspath

config_file = abspath(join(__file__, '../config', 'config.json'))
config_file = os.path.abspath(config_file)
os.environ.setdefault('drift_CONFIG', config_file)

from drift.appmodule import app

import logging
logging.root.setLevel('INFO')
