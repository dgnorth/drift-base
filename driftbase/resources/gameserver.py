from driftconfig.util import get_parameters
import logging
log = logging.getLogger(__name__)

# defaults when making a new tier
TIER_DEFAULTS = {
    "build_bucket_url": "<PLEASE FILL IN>"
}


# NOTE THIS IS DEPRECATED AND NEEDS TO BE UPGRADED TO NU STYLE PROVISIONING LOGIC
def provision(config, args, recreate=False):
    params = get_parameters(config, args, TIER_DEFAULTS.keys(), "gameserver")

    # Static data repo is per product
    if 'gameserver' not in config.product:
        config.product['gameserver'] = params


def healthcheck():
    pass
