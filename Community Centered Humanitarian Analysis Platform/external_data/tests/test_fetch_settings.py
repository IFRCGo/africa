"""The two API keys, and the empty-env trap they must not fall into."""
from django.conf import settings
from django.test import TestCase


class KeySettingsTests(TestCase):
    def test_both_keys_are_defined_as_strings(self):
        """Absent means empty string, never None - callers test truthiness."""
        self.assertIsInstance(settings.IPC_API_KEY, str)
        self.assertIsInstance(settings.HDX_API_TOKEN, str)

    def test_requests_is_installed(self):
        import requests
        self.assertTrue(hasattr(requests, "get"))
