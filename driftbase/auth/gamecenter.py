import base64
import struct

import OpenSSL
import marshmallow as ma
from flask_smorest import abort
from six.moves import http_client
from six.moves.urllib.parse import urlparse
from werkzeug.exceptions import Unauthorized
from werkzeug.security import pbkdf2_hex

from driftbase.auth import get_provider_config
from driftbase.auth.util import fetch_url
from .authenticate import authenticate as base_authenticate

# We make the assumption that a public key stored on this web site is a trusted one.
TRUSTED_KEY_URL_HOST = ".apple.com"


def authenticate(auth_info):
    assert auth_info['provider'] == "gamecenter"
    provider_details = auth_info.get('provider_details')
    automatic_account_creation = auth_info.get("automatic_account_creation", True)
    identity_id = validate_gamecenter_token(provider_details)
    # The GameCenter user_id cannot be stored in plain text, so let's
    # give it one cycle of hashing.
    username = "gamecenter:" + pbkdf2_hex(identity_id, "staticsalt",
                                          iterations=1)
    return base_authenticate(username, "", automatic_account_creation)


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    raise Unauthorized(description=description)


class GameCenterProviderAuthDetailsSchema(ma.Schema):
    app_bundle_id = ma.fields.String(required=True)
    player_id = ma.fields.String(required=True)
    public_key_url = ma.fields.String(required=True)
    salt = ma.fields.String(required=True)
    signature = ma.fields.String(required=True)
    timestamp = ma.fields.Integer(required=True)


def validate_gamecenter_token(gc_token):
    """Validates Apple Game Center token 'gc_token'. If validation fails, an
    HTTPException:Unauthorized exception is raised.

    Returns a unique ID for this player.

    If configured, 'bundle_ids' is a list of app bundles id's, and the 'app_bundle_id' in
    the token must be one of the listed ones.


    Example:

    gc_token = {
        "public_key_url": "https://static.gc.apple.com/public-key/gc-prod-2.cer",
        "app_bundle_id": "com.directivegames.themachines.ios",
        "player_id": "G:1637867917",
        "timestamp": 1452128703383,
        "salt": "vPWarQ==",
        "signature": "ZuhbO8TqGKadYAZHsDd5NgTs/tmM8sIqhtxuUmxOlhmp8PUAofIYzdwaN...
    }

    validate_gamecenter_token(gc_token)

    """

    gamecenter_config = get_provider_config('gamecenter')
    if not gamecenter_config:
        abort(http_client.SERVICE_UNAVAILABLE,
              description="Game Center authentication not configured for current tenant")

    app_bundles = gamecenter_config.get("bundle_ids", None)
    return run_gamecenter_token_validation(gc_token=gc_token, app_bundles=app_bundles)


def run_gamecenter_token_validation(gc_token, app_bundles):
    token_desc = dict(gc_token)
    token_desc["signature"] = token_desc.get("signature", "?")[:10]
    error_title = 'Invalid Game Center token: %s' % token_desc

    try:
        GameCenterProviderAuthDetailsSchema().load(gc_token)
    except ma.ValidationError as e:
        abort_unauthorized(error_title + "The token is missing required fields: %s." % ','.join(e.field_name))

    # Verify that the token is issued to the appropriate app.
    if app_bundles and gc_token["app_bundle_id"] not in app_bundles:
        abort_unauthorized(error_title + ". 'app_bundle_id' not one of %s" % app_bundles)

    # Verify that the certificate url is at Apple
    url_parts = urlparse(gc_token['public_key_url'])
    if not all([url_parts.scheme == "https", url_parts.hostname and url_parts.hostname.endswith(TRUSTED_KEY_URL_HOST)]):
        abort_unauthorized(error_title + ". Public key url points to unknown host: %s" % (gc_token['public_key_url']))

    # Fetch public key, use cache if available.
    try:
        content = fetch_url(gc_token['public_key_url'], error_title)
    except Exception as e:
        abort_unauthorized(error_title + ". Can't fetch url '%s': %s" % (gc_token['public_key_url'], e))

    # Load certificate
    try:
        cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_ASN1, content)
    except OpenSSL.crypto.Error as e:
        abort_unauthorized(error_title + ". Can't load certificate: %s" % str(e))

    # Verify that the certificate is not expired.
    if cert.has_expired():
        abort_unauthorized(error_title + ". Certificate is expired, 'notAfter' is '%s'" % cert.get_notAfter())

    # Check signature
    salt_decoded = base64.b64decode(gc_token["salt"])
    payload = b""
    payload += gc_token["player_id"].encode('UTF-8')
    payload += gc_token["app_bundle_id"].encode('UTF-8')
    payload += struct.pack('>Q', int(gc_token["timestamp"]))
    payload += salt_decoded
    signature_decoded = base64.b64decode(gc_token["signature"])

    try:
        OpenSSL.crypto.verify(cert, signature_decoded, payload, 'sha256')
    except Exception as e:
        abort_unauthorized(error_title + ". Can't verify signature: %s" % str(e))

    return gc_token["player_id"]
