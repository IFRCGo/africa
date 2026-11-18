"""Pruning the staging cache: what may go, and what must never.

api_cache/ holds three kinds of thing and only one is disposable. The rule this
pins is that a payload is a duplicate ONLY once source_sync says its rows are
in the database - otherwise the file on disk is the single copy in existence.
"""
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from external_data.models import SourceSync


def write(root, *parts, content=b"x" * 1024):
    path = Path(root).joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class PruneApiCacheTests(TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.loaded = write(self.root, "montandon", "SDN-events.json")
        self.unloaded = write(self.root, "dtm_snapshots", "SDN-x.json")
        self.log = write(self.root, "api", "job-1.log")
        self.markdown = write(self.root, "insights", "doc-1.md")
        self.orphan = write(self.root, "ne_lakes.geojson")
        SourceSync.objects.update_or_create(
            source="montandon", dataset="hazard_events", iso3="SDN", variant="",
            defaults={"row_count": 813})
        # dtm deliberately left at row_count 0 - nothing loaded from it.
        SourceSync.objects.filter(source="dtm").update(row_count=0)

    def run_prune(self, *args):
        out = StringIO()
        with override_settings(API_CACHE_DIR=str(self.root)):
            call_command("prune_api_cache", *args, stdout=out)
        return out.getvalue()

    def test_it_reports_without_deleting_by_default(self):
        report = self.run_prune()
        self.assertIn("would drop", report)
        self.assertIn("Nothing was deleted", report)
        self.assertTrue(self.loaded.exists())

    def test_a_loaded_payload_is_removed(self):
        self.run_prune("--delete")
        self.assertFalse(self.loaded.exists())

    def test_a_payload_with_nothing_loaded_is_kept(self):
        """Either the pull failed or nothing has loaded it yet. Either way the
        file on disk is the only copy there is."""
        self.run_prune("--delete")
        self.assertTrue(self.unloaded.exists())

    def test_job_logs_are_never_removed(self):
        """PullJob.log_path names them absolutely; deleting one empties a page
        rather than freeing a duplicate."""
        self.run_prune("--delete", "--include-orphans")
        self.assertTrue(self.log.exists())

    def test_insight_markdown_is_never_removed(self):
        """Conversion.markdown_path names these, and the source documents they
        were read from are deleted at publication by retention."""
        self.run_prune("--delete", "--include-orphans")
        self.assertTrue(self.markdown.exists())

    def test_top_level_inputs_are_kept_unless_asked_for(self):
        self.run_prune("--delete")
        self.assertTrue(self.orphan.exists())

    def test_top_level_inputs_go_only_with_the_explicit_flag(self):
        self.run_prune("--delete", "--include-orphans")
        self.assertFalse(self.orphan.exists())

    def test_the_report_says_why_a_folder_is_kept(self):
        report = self.run_prune()
        self.assertIn("only copy", report)
        self.assertIn("PullJob.log_path", report)

    def test_a_missing_cache_directory_is_not_an_error(self):
        out = StringIO()
        with override_settings(API_CACHE_DIR=str(self.root / "nope")):
            call_command("prune_api_cache", stdout=out)
        self.assertIn("does not exist", out.getvalue())
