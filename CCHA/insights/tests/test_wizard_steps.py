"""The four steps are buttons, and only the honest ones lead anywhere.

job_step serves whichever page a batch's status puts it at, so what these
assert is that a step nobody can reach from here renders inert rather than as a
link that would quietly land somewhere else.
"""
import re

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from insights.models import ExtractionJob


def step(body, number):
    """The one rendered step element with this number, as raw markup."""
    # finditer, not findall: the pattern needs a backreference to close the
    # tag, and findall hands back that group instead of the element.
    found = [m.group(0) for m in re.finditer(
        r"<(a|span|button)\b[^>]*class=\"wiz-step[^\"]*\"[^>]*>\s*"
        rf"{number}\..*?</\1>", body, re.S)]
    assert len(found) == 1, f"step {number}: {len(found)} matches"
    return found[0]


class WizardStepsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)

    def body(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_step_1_starts_a_batch_from_the_batch_list(self):
        body = self.body(reverse("admin:insights_documentstoinsights_changelist"))
        self.assertIn(reverse("admin:insights_wizard_start"), step(body, 1))

    def test_step_2_is_inert_before_a_batch_exists(self):
        # It used to be a button that scrolled to a preview on this page. It is
        # a page of its own now - reached once the batch is closed - so with no
        # job yet there is nowhere for it to lead.
        markup = step(self.body(reverse("admin:insights_wizard_start")), 2)
        self.assertIn('aria-disabled="true"', markup)
        self.assertNotIn("<a ", markup)

    def test_a_collected_batch_is_at_step_2(self):
        job = ExtractionJob.objects.create(status="collected")
        body = self.body(reverse("admin:insights_wizard_job", args=[job.id]))
        self.assertIn("is-current", step(body, 2))
        # Step 3 has not been earned yet: nothing has been read.
        self.assertIn('aria-disabled="true"', step(body, 3))

    def test_a_collecting_batch_is_at_step_1(self):
        job = ExtractionJob.objects.create(status="collecting")
        body = self.body(reverse("admin:insights_wizard_job", args=[job.id]))
        # Step 1 is the page being looked at, so it is the current one.
        self.assertIn("is-current", step(body, 1))
        self.assertIn('aria-disabled="true"', step(body, 4))

    def test_the_extract_page_marks_step_3_and_leaves_step_4_inert(self):
        job = ExtractionJob.objects.create(status="queued", documents_total=2)
        body = self.body(reverse("admin:insights_wizard_job", args=[job.id]))
        self.assertIn("is-current", step(body, 3))
        self.assertIn(reverse("admin:insights_wizard_start"), step(body, 1))
        self.assertIn('aria-disabled="true"', step(body, 4))

    def test_the_review_page_leaves_step_3_inert(self):
        # The extract page is gone once the batch has loaded - job_step would
        # bounce a click on step 3 straight back here.
        job = ExtractionJob.objects.create(status="loaded", documents_total=1)
        body = self.body(reverse("admin:insights_wizard_job", args=[job.id]))
        self.assertIn("is-current", step(body, 4))
        self.assertIn("is-done", step(body, 3))
        self.assertIn('aria-disabled="true"', step(body, 3))
        self.assertIn(reverse("admin:insights_wizard_start"), step(body, 1))
