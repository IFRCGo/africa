"""The Docling settings exist, and an empty .env value falls back.

The empty-value case is the one that bites: `os.environ.get(X, default)`
returns "" for a key present but blank in .env, which would hand EasyOCR an
empty language list and Docling a max_pages of 0.
"""
import importlib
import os

from django.test import TestCase


class DoclingSettingsTests(TestCase):
    # The DOCLING_* names this reads back. Listed rather than discovered so a
    # typo in a test is a KeyError here, not a silently absent assertion.
    NAMES = ("DOCLING_ENABLED", "DOCLING_OCR_LANGS", "DOCLING_MAX_PAGES",
             "DOCLING_TIMEOUT_SECONDS", "DOCLING_ARTIFACTS_PATH")

    def reload(self, **env):
        """The settings values as this environment produces them.

        RETURNS A SNAPSHOT, NOT THE MODULE. importlib.reload mutates the module
        in place and hands back the SAME object, so a test holding the return
        value would read it after the finally below has already restored the
        real environment - and would pass or fail on the defaults rather than
        on what it set. The values are therefore copied out inside the try.
        """
        import config.settings as settings_module

        previous = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        try:
            reloaded = importlib.reload(settings_module)
            return {name: getattr(reloaded, name) for name in self.NAMES}
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            importlib.reload(settings_module)

    def test_defaults(self):
        values = self.reload(DOCLING_OCR_LANGS="", DOCLING_MAX_PAGES="")
        # en,ar rather than en,fr,ar: EasyOCR refuses to load Arabic beside any
        # other non-English language, and Docling takes one ocr_options. See
        # the note in settings.py for why Arabic is the one that wins.
        self.assertEqual(values["DOCLING_OCR_LANGS"], ["en", "ar"])
        self.assertEqual(values["DOCLING_MAX_PAGES"], 40)
        self.assertEqual(values["DOCLING_TIMEOUT_SECONDS"], 900)
        self.assertTrue(values["DOCLING_ENABLED"])
        self.assertEqual(str(values["DOCLING_ARTIFACTS_PATH"]), "/opt/docling/models")

    def test_langs_are_split_and_stripped(self):
        values = self.reload(DOCLING_OCR_LANGS=" en , fr ")
        self.assertEqual(values["DOCLING_OCR_LANGS"], ["en", "fr"])

    def test_enabled_is_off_for_the_word_false(self):
        values = self.reload(DOCLING_ENABLED="false")
        self.assertFalse(values["DOCLING_ENABLED"])

    def test_docling_is_installed(self):
        import docling  # noqa: F401
        from docling.document_converter import DocumentConverter  # noqa: F401
