import importlib

from drift.utils import get_config
from drift.core.extensions import jwt

from . import authenticate


AUTH_MODULES = {
    'gamecenter': 'driftbase.auth.gamecenter',
    'googleplay': 'driftbase.auth.googleplay',
    'oculus': 'driftbase.auth.oculus',
    'psn': 'driftbase.auth.psn',
    'steam': 'driftbase.auth.steam',
    }

LOCAL_AUTH = [
    'device_id', 'user+pass', 'uuid', 'unit_test', 'viveport', 'hypereal', '7663',
    ]


def drift_init_extension(app, api, **kwds):
    # register authentication handlers
    for name, module in AUTH_MODULES.items():
        m = importlib.import_module(module)
        jwt.register_auth_provider(app, name, m.authenticate)
    for name in LOCAL_AUTH:
        jwt.register_auth_provider(app, name, authenticate.authenticate_with_provider)


def get_provider_config(provider_name):
    conf = get_config()
    row = conf.table_store.get_table('platforms').find({'product_name': conf.product['product_name'],
                                                        'provider_name': provider_name})
    return len(row) and row[0]['provider_details'] or None
