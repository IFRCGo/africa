"""The guided route from documents to published insights.

FOUR STEPS, ONE JOB. Every step reads its state off one ExtractionJob row:
"collecting" is a batch whose files are still arriving, "queued" is ready to
extract, "running" is extracting, "loaded" is ready to review. Nothing is kept
in the session, so closing the tab loses nothing and reopening the wizard
rejoins the batch wherever it got to.

WHY THESE ARE NOT IN insights/urls.py. That file is the public read API. These
are mounted inside the admin site (DocumentsToInsightsAdmin.get_urls) and
wrapped in admin_view(), so they carry the same staff-only check and login
redirect as every other admin page - exactly as place_options and
folder_browse already are.
"""
from django.contrib import admin as django_admin
from django.shortcuts import render

from insights.models import ExtractionJob

RECENT_JOBS = 20


def page(request, **extra):
    """The context every wizard page needs.

    each_context() is what supplies the admin's header, breadcrumbs, site title
    and the user menu. admin_view() does NOT add it - it wraps a view in the
    permission check and the login redirect and nothing else - so a page that
    forgets this renders as an unstyled orphan with no way back to the admin.
    """
    return {**django_admin.site.each_context(request), **extra}


def job_list(request):
    """Recent batches and how far each one got."""
    return render(request, "insights/wizard_jobs.html", page(
        request,
        wizard_step=0,
        jobs=ExtractionJob.objects.order_by("-id")[:RECENT_JOBS],
    ))


def start(request):
    """Step 1. Filled in by Task 5."""
    raise NotImplementedError


def job_step(request, job_id):
    """Steps 2-4, chosen by the job's status. Filled in by Task 5."""
    raise NotImplementedError
