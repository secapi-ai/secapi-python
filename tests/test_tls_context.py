"""TLS trust-store wiring for the client (T-E4).

api.secapi.ai serves a valid chain; the historical "unable to get local issuer
certificate" failures were a local trust-store gap. The client verifies against
the certifi CA bundle when importable and otherwise falls back to urllib's
default context, staying zero-dependency.
"""

import builtins
import ssl
import unittest
from functools import partial

from secapi_client import SecApiClient
from secapi_client.client import _build_ssl_context, _friendly_tls_error


class BuildSslContextTests(unittest.TestCase):
    def test_returns_ssl_context_when_certifi_importable(self):
        # certifi ships transitively in this test env, so the preferred path is taken.
        ctx = _build_ssl_context()
        self.assertIsInstance(ctx, ssl.SSLContext)

    def test_augments_system_store_rather_than_replacing_it(self):
        # Regression guard (adversarial review): the context must be the system
        # default PLUS certifi, never certifi-only. Passing cafile= to
        # create_default_context would drop the OS/corporate/private-CA roots that
        # enterprise + SSL_CERT_FILE users rely on. load_verify_locations is
        # additive, so the union can never be smaller than the system default.
        default_only = ssl.create_default_context()
        augmented = _build_ssl_context()
        self.assertIsNotNone(augmented)
        self.assertGreaterEqual(
            len(augmented.get_ca_certs()),
            len(default_only.get_ca_certs()),
        )
        # certifi's roots are actually loaded (non-trivial trust set).
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


class ClientTlsWiringTests(unittest.TestCase):
    def test_client_binds_certifi_context_into_urlopen(self):
        client = SecApiClient(api_key="test-key")
        # certifi is present in the test env, so the client must verify against it.
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
