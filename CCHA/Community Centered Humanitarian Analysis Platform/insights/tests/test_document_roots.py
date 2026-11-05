"""The folders a document may be read from are configuration, not a literal.

The whole point of this module is that no message anywhere tells a reader
about "/work" - a path that is true of exactly one deployment.
"""
import tempfile
from pathlib import Path

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from insights import document_roots
from insights.models import InsightFolder


class DocumentRootTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "reports").mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_roots_come_from_the_setting(self):
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root]):
            self.assertEqual([path for _, path in document_roots.roots()], [self.root])

    def test_a_root_that_does_not_exist_is_not_offered(self):
        missing = self.root / "gone"
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root, missing]):
            self.assertEqual([path for _, path in document_roots.roots()], [self.root])

    def test_a_folder_inside_a_root_is_contained(self):
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root]):
            self.assertTrue(document_roots.contains(self.root / "reports"))
            self.assertTrue(document_roots.contains(self.root))

    def test_a_traversal_out_of_a_root_is_not_contained(self):
        # Resolved before it is compared, so this is tested as its parent,
        # not as a string that merely starts with the root.
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root]):
            self.assertFalse(document_roots.contains(self.root / ".." / "elsewhere"))

    def test_the_sentence_names_the_configured_roots_and_never_work(self):
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root]):
            sentence = document_roots.sentence()
        self.assertIn(str(self.root), sentence)
        self.assertNotIn("/work", sentence)

    def test_the_folder_form_error_names_the_configured_roots(self):
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root]):
            folder = InsightFolder(label="nowhere", path=str(self.root / "missing"))
            with self.assertRaises(ValidationError) as caught:
                folder.clean()
        message = str(caught.exception)
        self.assertIn(str(self.root), message)
        self.assertNotIn("/work", message)
