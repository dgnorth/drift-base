# -*- coding: utf-8 -*-

import requests
import logging
import json

from flask import Blueprint, g, url_for, current_app
from flask_restful import Api, Resource, reqparse

from drift.core.resources import get_parameters
from drift.urlregistry import register_endpoints

log = logging.getLogger(__file__)

# defaults when making a new tier
NEW_TIER_DEFAULTS = {
    "repository": "<PLEASE FILL IN>",  # Example: directive-tiers.dg-api.com
    "revision":  "<PLEASE FILL IN>",   # Example: static-data,
    "allow_client_pin": False
}

def provision(config, args, recreate=False):
    params = get_parameters(config, args, NEW_TIER_DEFAULTS.keys(), "staticdata")

    # Static data repo is per product
    if 'staticdata_defaults' not in config.product:
        config.product['staticdata_defaults'] = params

    # Create entry for this tenant
    config.tenant['static_data_refs_legacy'] = config.product['staticdata_defaults']


def healthcheck():
    pass

