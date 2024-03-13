"""
Required platform configuration for Cognito authentication.

client_ids: List of client IDs that are allowed to authenticate with this provider.
user_pool_region: The AWS region where the user pool is located.
user_pool_id: The ID of the user pool.
"""

import http.client as http_client
import logging
from datetime import timedelta
from hashlib import pbkdf2_hmac
from json import JSONDecodeError
from urllib.error import URLError

import jwt
import marshmallow as ma
from drift.blueprint import abort
from jwt import PyJWKClientError

from driftbase.auth import get_provider_config
from .authenticate import authenticate as base_authenticate, AuthenticationException, ServiceUnavailableException, \
    abort_unauthorized, InvalidRequestException, UnauthorizedException

# See https://repost.aws/knowledge-center/decode-verify-cognito-json-token
# for more information on how to validate a Cognito token.

COGNITO_PUBLIC_KEYS_URL_TEMPLATE = "https://cognito-idp.{region}.amazonaws.com/{userPoolId}/.well-known/jwks.json"
TRUSTED_ISSUER_URL_BASE = "https://cognito-idp.{region}.amazonaws.com/{userPoolId}"

JWT_ALGORITHM = "RS256"
JWT_LEEWAY = 10
JWT_VERIFY_CLAIMS = ["signature", "exp", "iat"]
JWT_REQUIRED_CLAIMS = ["exp", "iat", "sub"]

log = logging.getLogger(__name__)


class CognitoProviderAuthDetailsSchema(ma.Schema):
    token = ma.fields.String(required=True, allow_none=False)


def authenticate(auth_info):
    assert auth_info['provider'] == 'cognito'

    try:
        parameters = _load_provider_details(auth_info['provider_details'])
    except InvalidRequestException as e:
        abort(http_client.BAD_REQUEST, message=e.msg)
    except KeyError as e:
        abort(http_client.BAD_REQUEST, message="Missing provider_details")

    try:
        identity_id = _validate_cognito_token(**parameters)
    except ServiceUnavailableException as e:
        abort(http_client.SERVICE_UNAVAILABLE, message=e.msg)
    except InvalidRequestException as e:
        abort(http_client.BAD_REQUEST, message=e.msg)
    except AuthenticationException as e:
        abort_unauthorized(e.msg)

    automatic_account_creation = auth_info.get('automatic_account_creation', True)
    # FIXME: The static salt should perhaps be configured per tenant

    username = "cognito:" + pbkdf2_hmac('sha256', identity_id.encode('utf-8'), b'static_salt', iterations=1).hex()
    return base_authenticate(username, "", automatic_account_creation)


def _load_provider_details(provider_details):
    try:
        return CognitoProviderAuthDetailsSchema().load(provider_details)
    except ma.exceptions.ValidationError as e:
        raise InvalidRequestException(f"{e}") from None


def _validate_cognito_token(token):
    """Validates a Cognito OpenID token.

    Returns the Cognito Account ID for this player.

    The audience claim must match one of the configured client_ids for the product.

    Example:

    provider_details = {
        "token": "ZuhbO8TqGKadYAZHsDd5NgTs/tmM8sIqhtxuUmxOlhmp8PUAofIYzdwaN..."
    }

    validate_cognito_token(provider_details)
    """

    cognito_config = get_provider_config('cognito')
    if not cognito_config:
        raise ServiceUnavailableException("Cognito authentication not configured for current tenant")

    return _run_cognito_token_validation(
        token,
        cognito_config.get('client_ids'),
        cognito_config.get('user_pool_region'),
        cognito_config.get('user_pool_id')
    )


def _run_cognito_token_validation(token, client_ids, aws_region, user_pool_id):
    public_keys_url = COGNITO_PUBLIC_KEYS_URL_TEMPLATE.format(
        region=aws_region,
        userPoolId=user_pool_id
    )

    public_key = _get_key_from_token(token, public_keys_url)
    payload = _decode_and_verify_jwt(token, public_key, client_ids, aws_region, user_pool_id)

    return payload["sub"]


def _decode_and_verify_jwt(token, key, audience, aws_region, user_pool_id):
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

    issuer = payload.get("iss")
    if not issuer:
        raise UnauthorizedException("Invalid JWT, no issuer found")
    truset_issuer = TRUSTED_ISSUER_URL_BASE.format(region=aws_region, userPoolId=user_pool_id)
    if not issuer.startswith(TRUSTED_ISSUER_URL_BASE):
        raise UnauthorizedException("Invalid JWT, issuer not trusted")

    return payload


def _get_key_from_token(token, cognito_public_keys_url):
    try:
        jwk_client = jwt.PyJWKClient(cognito_public_keys_url)
        jwk = jwk_client.get_signing_key_from_jwt(token)
    except URLError as e:
        raise ServiceUnavailableException("Failed to fetch public keys for token validation") from e
    except (JSONDecodeError, PyJWKClientError) as e:
        raise ServiceUnavailableException("Failed to read public keys for token validation") from None

    if jwk is None:
        raise UnauthorizedException("Failed to find a matching public key for token validation")
    return jwk.key
