#!/usr/bin/env python
from drift import management

if __name__ == "__main__":
    management.execute_cmd()
else:
    import drift.appmodule
    from drift.core.extensions.celery import celery
