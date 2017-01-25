# -*- coding: utf-8 -*-
import datetime
from drift.core.resources import get_parameters
from flask import g
import logging
log = logging.getLogger(__name__)

# defaults when making a new tier
NEW_TIER_DEFAULTS = {
    "build_bucket_url": "<PLEASE FILL IN>"
}

def provision(config, args):
    params = get_parameters(config, args, NEW_TIER_DEFAULTS.keys(), "gameserver")

    # Static data repo is per product
    if 'gameserver' not in config.product:
        config.product['gameserver'] = params

def healthcheck():
    pass
