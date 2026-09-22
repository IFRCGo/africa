"""Moving an insight from pending to published, or to rejected.

Written here rather than inside the changelist actions because there are now
two callers - the actions and the wizard's review step - and a review decision
recorded two slightly different ways is a review decision nobody can audit.

A rejected extraction is evidence about the model, not rubbish: `status` is set
but `rejection_reason` is deliberately left alone for a person to fill in.

A DECISION IS ALSO WHAT RETIRES THE PDF. Once a document has no pending
statement left, the reading is over and the uploaded copy has no job left to
do, so insights.retention releases it here rather than waiting out the
retention cap. Both decisions do it: rejecting the last statement finishes the
review just as publishing it does. See insights/retention.py for what
"releases" leaves behind, which is everything except the file.
"""
from django.utils import timezone

from insights import retention


def publish(queryset, user):
    """Publish every insight in `queryset`. Returns how many moved."""
    documents = _documents_in(queryset)
    moved = queryset.update(
        status="published", reviewed_by=user, reviewed_at=timezone.now())
    retention.release_if_reviewed(documents)
    return moved


def reject(queryset, user):
    """Reject every insight in `queryset`. Returns how many moved."""
    documents = _documents_in(queryset)
    moved = queryset.update(
        status="rejected", reviewed_by=user, reviewed_at=timezone.now())
    retention.release_if_reviewed(documents)
    return moved


def _documents_in(queryset):
    """Which documents this decision covers - read BEFORE the update.

    A queryset is lazy and these are usually filtered on `status`, so asking
    afterwards would ask about rows that no longer match.
    """
    return list(queryset.values_list("document_id", flat=True))
