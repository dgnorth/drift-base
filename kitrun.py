#!/usr/bin/env python
import os
import sys
from os.path import join, abspath
from drift import management

config_file = abspath(join(__file__, "../config", "config.json"))
os.environ.setdefault("drift_CONFIG", config_file)

if __name__ == "__main__":
    management.execute_cmd()
else:
    import drift.appmodule
    from drift.core.extensions.celery import celery
