"""Moving an insight from pending to published, or to rejected.

Written here rather than inside the changelist actions because there are now
two callers - the actions and the wizard's review step - and a review decision
recorded two slightly different ways is a review decision nobody can audit.

A rejected extraction is evidence about the model, not rubbish: `status` is set
but `rejection_reason` is deliberately left alone for a person to fill in.
"""
from django.utils import timezone


def publish(queryset, user):
    """Publish every insight in `queryset`. Returns how many moved."""
    return queryset.update(
        status="published", reviewed_by=user, reviewed_at=timezone.now())


def reject(queryset, user):
    """Reject every insight in `queryset`. Returns how many moved."""
    return queryset.update(
        status="rejected", reviewed_by=user, reviewed_at=timezone.now())
