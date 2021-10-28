from unittest import mock

import json
import jwt
import unittest

import driftbase.auth.eos as eos
from driftbase.auth.authenticate import InvalidRequestException, AuthenticationException, ServiceUnavailableException, \
    UnauthorizedException

# Examples from https://tools.ietf.org/html/rfc7518, https://tools.ietf.org/html/rfc7519
TEST_JWT = 'eyJ0eXAiOiJKV1QiLA0KICJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJqb2UiLA0KICJleHAiOjEzMDA4MTkzODAsDQogImh0dHA6Ly9leGFtcGxlLmNvbS9pc19yb290Ijp0cnVlfQ.dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
TEST_JWK = '{"kty":"oct", "k":"AyM1SysPpbyDfgZld3umj1qzKObwVMkoqQ-EstJQLr_T-1qS0gZH75aKtMN3Yj0iPS4hcgUuTwjAzZr1Z9CAow", "kid":"test"}'
TEST_JWK_SET = '''{
    "keys":[
        {"kty":"oct", "k":"AyM1SysPpbyDfgZld3umj1qzKObwVMkoqQ-EstJQLr_T-1qS0gZH75aKtMN3Yj0iPS4hcgUuTwjAzZr1Z9CAow", "kid":"test"}
    ]
}'''


class TestEosAuthenticate(unittest.TestCase):
    def test_fails_if_missing_or_incorrect_provider_name(self):
        with self.assertRaises(KeyError):
            eos.authenticate(dict())
        with self.assertRaises(AssertionError):
            eos.authenticate(dict(provider=None))
        with self.assertRaises(AssertionError):
            eos.authenticate(dict(provider='myspace'))


class TestEosLoadProviderDetails(unittest.TestCase):
    def test_fails_if_provider_details_missing_or_wrong_type(self):
        with self.assertRaises(InvalidRequestException):
            eos.load_provider_details(dict(token=None))
        with self.assertRaises(InvalidRequestException):
            eos.load_provider_details(dict(token=34))
        with self.assertRaises(InvalidRequestException):
            eos.load_provider_details(dict(token=[]))
        with self.assertRaises(InvalidRequestException):
            eos.load_provider_details(dict(token='abc', other=3))

    def test_loads_provider_details(self):
        details = eos.load_provider_details(dict(token='abc'))
        self.assertEqual(details['token'], 'abc')


class TestEosValidate(unittest.TestCase):
    def test_fails_without_configuration(self):
        with mock.patch('driftbase.auth.eos.get_provider_config') as config:
            config.return_value = None
            with self.assertRaises(ServiceUnavailableException):
                eos.validate_eos_token('abc')

    def test_passes_configuration_to_implementation(self):
        with mock.patch('driftbase.auth.eos.get_provider_config') as config:
            config.return_value = dict(client_ids=['xyz'])
            with mock.patch('driftbase.auth.eos.run_eos_token_validation') as validation:
                validation.return_value = 0
                eos.validate_eos_token('abc')
                validation.assert_called_once_with('abc', ['xyz'])


@mock.patch('driftbase.auth.eos.JWT_ALGORITHM', 'HS256')
class TestEosRunAuthentication(unittest.TestCase):
    @mock.patch('driftbase.auth.eos.EPIC_PUBLIC_KEYS_URL', 'https://invalid.com/index.html')
    def test_fails_when_failing_to_load_keys(self):
        with self.assertRaises(AuthenticationException) as e:
            eos.run_eos_token_validation(TEST_JWT, [])
        self.assertTrue(e.exception.msg.find('fetch') != -1)

    def test_fails_when_key_set_is_empty(self):
        with mock.patch('driftbase.auth.eos.jwt.PyJWKClient') as mock_jwk_client:
            instance = mock_jwk_client.return_value
            instance.fetch_data.return_value = json.loads('{}')
            instance.get_signing_key_from_jwt.return_value = None
            with self.assertRaises(UnauthorizedException) as e:
                eos.run_eos_token_validation(TEST_JWT, [])
            self.assertTrue(e.exception.msg.find('Failed to find') != -1)

    def test_fails_when_key_set_is_invalid(self):
        with mock.patch.object(eos.jwt.PyJWKClient, 'fetch_data') as mock_fetch:
            mock_fetch.side_effect = json.decoder.JSONDecodeError('mock', '', 42)
            with self.assertRaises(ServiceUnavailableException) as e:
                eos.run_eos_token_validation(TEST_JWT, [])
            self.assertTrue(e.exception.msg.find('Failed to read') != -1)

    def test_decodes_and_validates_the_sub(self):
        payload = dict(aud='foo', iss=eos.TRUSTED_ISSUER_URL_BASE, sub='abc')
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos.jwt.PyJWKClient') as mock_jwk_client:
            instance = mock_jwk_client.return_value
            instance.get_signing_key_from_jwt.return_value = jwk
            self.assertEqual(eos.run_eos_token_validation(token, ['foo']), 'abc')

    def test_fails_when_audience_is_missing(self):
        payload = dict(iss=eos.TRUSTED_ISSUER_URL_BASE, sub='abc')
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos.jwt.PyJWKClient') as mock_jwk_client:
            instance = mock_jwk_client.return_value
            instance.get_signing_key_from_jwt.return_value = jwk
            with self.assertRaises(UnauthorizedException):
                eos.run_eos_token_validation(token, ['foo']), 'abc'

    def test_fails_when_audience_is_wrong(self):
        payload = dict(aud='bar', iss=eos.TRUSTED_ISSUER_URL_BASE, sub='abc')
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos.jwt.PyJWKClient') as mock_jwk_client:
            instance = mock_jwk_client.return_value
            instance.get_signing_key_from_jwt.return_value = jwk
            with self.assertRaises(UnauthorizedException):
                eos.run_eos_token_validation(token, ['foo']), 'abc'

    def test_fails_when_issuer_is_missing(self):
        payload = dict(aus='foo', sub='abc')
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos.jwt.PyJWKClient') as mock_jwk_client:
            instance = mock_jwk_client.return_value
            instance.get_signing_key_from_jwt.return_value = jwk
            with self.assertRaises(UnauthorizedException):
                eos.run_eos_token_validation(token, ['foo']), 'abc'

    def test_fails_when_issuer_is_wrong(self):
        payload = dict(aus='foo', iss='Acme Industries', sub='abc')
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos.jwt.PyJWKClient') as mock_jwk_client:
            instance = mock_jwk_client.return_value
            instance.get_signing_key_from_jwt.return_value = jwk
            with self.assertRaises(UnauthorizedException):
                eos.run_eos_token_validation(token, ['foo']), 'abc'


def _make_test_token_and_key(payload):
    jwk = jwt.PyJWK.from_json(TEST_JWK)
    return jwt.encode(payload=payload, key=jwk.key, algorithm='HS256'), jwk
