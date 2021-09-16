"""
Match Placements configuration - shamelessly lifted from the parties resource configuration
"""

import logging

log = logging.getLogger(__name__)

TIER_DEFAULTS = {
    "default_match_provider": "gamelift",
}

def drift_init_extension(app, **kwargs):
    pass


def register_deployable(ts, deployablename, attributes):
    """
    Deployable registration callback.
    'deployablename' is from table 'deployable-names'.
    """
    pass


def register_deployable_on_tier(ts, deployable, attributes):
    """
    Deployable registration callback for tier.
    'deployable' is from table 'deployables'.
    """
    pass


def register_resource_on_tier(ts, tier, attributes):
    """
    Tier registration callback.
    'tier' is from table 'tiers'.
    'attributes' is a dict containing optional attributes for default values.
    """
    pass


def register_deployable_on_tenant(
        ts, deployable_name, tier_name, tenant_name, resource_attributes
):
    pass
