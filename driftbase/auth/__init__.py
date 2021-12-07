import functools
import importlib

from drift.core.extensions import jwt
from drift.utils import get_config

AUTH_MODULES = {
    'gamecenter': 'driftbase.auth.gamecenter',
    'googleplay': 'driftbase.auth.googleplay',
    'oculus': 'driftbase.auth.oculus',
    'psn': 'driftbase.auth.psn',
    'steam': 'driftbase.auth.steam',
    'epic': 'driftbase.auth.epic',
    'eos': 'driftbase.auth.eos',
}

LOCAL_AUTH = [
    'device_id', 'user+pass', 'uuid', 'viveport', 'hypereal', '7663',
]


def _authentication_thunker(module, func, *args, **kw):
    """Load in authentication handler module just-in-time and dispatch the call."""
    m = importlib.import_module(module)
    return getattr(m, func)(*args, **kw)


def drift_init_extension(app, api, **kwds):
    # register authentication handlers
    for name, module in AUTH_MODULES.items():
        jwt.register_auth_provider(app, name, functools.partial(_authentication_thunker, module, 'authenticate'))

    authenticate_with_provider = functools.partial(
        _authentication_thunker, 'driftbase.auth.authenticate', 'authenticate_with_provider'
    )
    for name in LOCAL_AUTH:
        jwt.register_auth_provider(app, name, authenticate_with_provider)


def get_provider_config(provider_name):
    conf = get_config()
    row = conf.table_store.get_table('platforms').find({'product_name': conf.product['product_name'],
                                                        'provider_name': provider_name})
    return len(row) and row[0]['provider_details'] or None
