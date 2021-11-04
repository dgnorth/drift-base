from json import JSONDecodeError

import http.client as http_client
import jwt
import logging
import marshmallow as ma
from datetime import timedelta
from flask_smorest import abort
from jwt import PyJWKClientError
from urllib.error import URLError
from werkzeug.security import pbkdf2_hex

from driftbase.auth import get_provider_config
from .authenticate import authenticate as base_authenticate, AuthenticationException, ServiceUnavailableException, \
    abort_unauthorized, InvalidRequestException, UnauthorizedException

EPIC_PUBLIC_KEYS_URL = "https://api.epicgames.dev/epic/oauth/v1/.well-known/jwks.json"
TRUSTED_ISSUER_URL_BASE = 'https://api.epicgames.dev/'

JWT_ALGORITHM = "RS256"
JWT_LEEWAY = 10
JWT_VERIFY_CLAIMS = ["signature", "exp", "iat"]
JWT_REQUIRED_CLAIMS = ["exp", "iat", "sub"]

log = logging.getLogger(__name__)


class EOSProviderAuthDetailsSchema(ma.Schema):
    token = ma.fields.String(required=True, allow_none=False)


def authenticate(auth_info):
    assert auth_info['provider'] == 'eos'

    try:
        parameters = _load_provider_details(auth_info['provider_details'])
    except InvalidRequestException as e:
        abort(http_client.BAD_REQUEST, message=e.msg)
    except KeyError as e:
        abort(http_client.BAD_REQUEST, message="Missing provider_details")

    try:
        identity_id = _validate_eos_token(**parameters)
    except ServiceUnavailableException as e:
        abort(http_client.SERVICE_UNAVAILABLE, message=e.msg)
    except InvalidRequestException as e:
        abort(http_client.BAD_REQUEST, message=e.msg)
    except AuthenticationException as e:
        abort_unauthorized(e.msg)

    automatic_account_creation = auth_info.get('automatic_account_creation', True)
    # FIXME: The static salt should perhaps be configured per tenant
    username = "eos:" + pbkdf2_hex(identity_id, 'static_salt', iterations=1)
    return base_authenticate(username, "", automatic_account_creation)


def _load_provider_details(provider_details):
    try:
        return EOSProviderAuthDetailsSchema().load(provider_details)
    except ma.exceptions.ValidationError as e:
        raise InvalidRequestException(f"{e}") from None


def _validate_eos_token(token):
    """Validates an Epic Online Services OpenID token.

    Returns the Epic Account ID for this player.

    The audience claim must match one of the configured client_ids for the product.

    Example:

    provider_details = {
        "token": "ZuhbO8TqGKadYAZHsDd5NgTs/tmM8sIqhtxuUmxOlhmp8PUAofIYzdwaN..."
    }

    validate_eos_token(provider_details)
    """

    eos_config = get_provider_config('eos')
    if not eos_config:
        raise ServiceUnavailableException("Epic Online Services authentication not configured for current tenant")

    return _run_eos_token_validation(token, eos_config.get('client_ids'))


def _run_eos_token_validation(token, client_ids):
    public_key = _get_key_from_token(token)
    payload = _decode_and_verify_jwt(token, public_key, client_ids)

    return payload["sub"]


def _decode_and_verify_jwt(token, key, audience):
    options = {
        'verify_' + claim: True
        for claim in JWT_VERIFY_CLAIMS
    }

    options.update({
        'require_' + claim: True
        for claim in JWT_REQUIRED_CLAIMS
    })

    try:
        payload = jwt.decode(
            jwt=token,
            key=key,
            options=options,
            audience=audience,
            algorithms=[JWT_ALGORITHM],
            leeway=timedelta(seconds=JWT_LEEWAY)
        )
    except jwt.MissingRequiredClaimError as e:
        raise UnauthorizedException(f"Invalid token: {str(e)}")
    except jwt.InvalidTokenError as e:
        raise UnauthorizedException(f"Invalid token: {str(e)}")

    # EOS docs says to verify only the prefix, not the entire issuer string,
    # so we have to verify it manually.
    # See https://dev.epicgames.com/docs/services/en-US/EpicAccountServices/AuthInterface/index.html#validatingidtokensonbackendwithoutsdk
    issuer = payload.get("iss")
    if not issuer:
        raise UnauthorizedException("Invalid JWT, no issuer found")
    if not issuer.startswith(TRUSTED_ISSUER_URL_BASE):
        raise UnauthorizedException("Invalid JWT, issuer not trusted")

    return payload


def _get_key_from_token(token):
    try:
        jwk_client = jwt.PyJWKClient(EPIC_PUBLIC_KEYS_URL)
        jwk = jwk_client.get_signing_key_from_jwt(token)
    except URLError as e:
        raise ServiceUnavailableException("Failed to fetch public keys for token validation") from e
    except (JSONDecodeError, PyJWKClientError) as e:
        raise ServiceUnavailableException("Failed to read public keys for token validation") from None

    if jwk is None:
        raise UnauthorizedException("Failed to find a matching public key for token validation")
    return jwk.key
