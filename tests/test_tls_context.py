"""TLS trust-store wiring for the client (T-E4).

api.secapi.ai serves a valid chain; the historical "unable to get local issuer
certificate" failures were a local trust-store gap. The client verifies against
the certifi CA bundle when importable and otherwise falls back to urllib's
default context, staying zero-dependency.
"""

import builtins
import os
import ssl
import sys
import tempfile
import types
import unittest
from functools import partial
from unittest import mock

from secapi_client import SecApiClient
from secapi_client.client import _build_ssl_context, _friendly_tls_error


def _certifi_module(cafile):
    module = types.ModuleType("certifi")
    module.where = lambda: cafile
    return module


def _is_usable_ca_file(cafile):
    if not cafile or not os.path.exists(cafile):
        return False
    try:
        context = ssl.create_default_context(cafile=cafile)
        return len(context.get_ca_certs()) > 0
    except (OSError, ssl.SSLError):
        return False


def _usable_ca_file_or_skip(testcase):
    try:
        import certifi

        cafile = certifi.where()
        if _is_usable_ca_file(cafile):
            return cafile
    except ImportError:
        pass

    cafile = ssl.get_default_verify_paths().cafile
    if _is_usable_ca_file(cafile):
        return cafile

    testcase.skipTest("no usable CA bundle available for TLS context test")


class BuildSslContextTests(unittest.TestCase):
    def test_returns_ssl_context_when_certifi_importable(self):
        cafile = _usable_ca_file_or_skip(self)
        with mock.patch.dict(sys.modules, {"certifi": _certifi_module(cafile)}):
            ctx = _build_ssl_context()
        self.assertIsInstance(ctx, ssl.SSLContext)

    def test_augments_system_store_rather_than_replacing_it(self):
        # Regression guard (adversarial review): the context must be the system
        # default PLUS certifi, never certifi-only. Passing cafile= to
        # create_default_context would drop the OS/corporate/private-CA roots that
        # enterprise + SSL_CERT_FILE users rely on. load_verify_locations is
        # additive, so the union can never be smaller than the system default.
        cafile = _usable_ca_file_or_skip(self)
        default_only = ssl.create_default_context()
        with mock.patch.dict(sys.modules, {"certifi": _certifi_module(cafile)}):
            augmented = _build_ssl_context()
        self.assertIsNotNone(augmented)
        self.assertGreaterEqual(
            len(augmented.get_ca_certs()),
            len(default_only.get_ca_certs()),
        )
        # The resulting context still has a non-trivial trust set.
        self.assertGreater(len(augmented.get_ca_certs()), 0)

    def test_returns_none_when_certifi_missing(self):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "certifi":
                raise ImportError("simulated: certifi not installed")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = fake_import
        try:
            self.assertIsNone(_build_ssl_context())
        finally:
            builtins.__import__ = real_import

    def test_returns_none_when_certifi_bundle_unusable(self):
        missing_cafile = os.path.join(os.path.dirname(__file__), "missing-certifi.pem")
        with mock.patch.dict(sys.modules, {"certifi": _certifi_module(missing_cafile)}):
            self.assertIsNone(_build_ssl_context())

    def test_usable_ca_helper_rejects_existing_malformed_bundle(self):
        with tempfile.NamedTemporaryFile("w") as handle:
            handle.write("not a pem bundle")
            handle.flush()
            self.assertFalse(_is_usable_ca_file(handle.name))


class ClientTlsWiringTests(unittest.TestCase):
    def test_client_binds_certifi_context_into_urlopen(self):
        cafile = _usable_ca_file_or_skip(self)
        with mock.patch.dict(sys.modules, {"certifi": _certifi_module(cafile)}):
            client = SecApiClient(api_key="test-key")
        self.assertIsInstance(client._ssl_context, ssl.SSLContext)
        self.assertIsInstance(client._urlopen, partial)
        self.assertIs(client._urlopen.keywords.get("context"), client._ssl_context)

    def test_client_stays_zero_dependency_without_certifi(self):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "certifi":
                raise ImportError("simulated: certifi not installed")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = fake_import
        try:
            client = SecApiClient(api_key="test-key")
            # Falls back to urllib's default context: no crash, no partial binding.
            self.assertIsNone(client._ssl_context)
            self.assertNotIsInstance(client._urlopen, partial)
        finally:
            builtins.__import__ = real_import


class FriendlyTlsErrorTests(unittest.TestCase):
    def test_cert_verify_error_points_at_certifi_remedy(self):
        original = ssl.SSLCertVerificationError("unable to get local issuer certificate")
        friendly = _friendly_tls_error(original)
        message = str(friendly)
        self.assertIn("certifi", message)
        self.assertIn("secapi-client[tls]", message)

    def test_non_tls_error_is_passed_through_untouched(self):
        original = ValueError("something else")
        self.assertIs(_friendly_tls_error(original), original)


if __name__ == "__main__":
    unittest.main()
