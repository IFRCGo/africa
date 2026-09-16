"""The one panel that reads PostgreSQL live.

Quotes are low-volume text, so serving them live costs nothing and lets Publish
mean published: refresh the page and it is there. The map's own layers keep
reading their pre-built files, so nothing about map performance changes - see
spec §14.1 for why geometry stays on files.

PUBLISHED ROWS ONLY. There is no query parameter that will return a pending or
rejected insight, and there should never be one.
"""
from django.db.models import Q
from django.http import JsonResponse

from insights.models import Insight

MAX_LIMIT = 2000


def _limit(request):
    try:
        return max(1, min(int(request.GET.get("limit", 500)), MAX_LIMIT))
    except (TypeError, ValueError):
        return 500


def insights(request):
    """Published community insights. Filters: ?voice_type= &iso3= &dimension=
    &tag= &admin_pcode= &from= &to= &q=
    """
    rows = (Insight.objects.filter(status="published")
            .select_related("document").prefetch_related("codings"))

    for field in ("voice_type", "iso3", "admin_pcode"):
        if value := request.GET.get(field):
            rows = rows.filter(**{field: value})
    dimension = request.GET.get("dimension")
    tag = request.GET.get("tag")
    if dimension and tag:
        # When both dimension and tag are supplied, apply them in a single
        # .filter() call so one coding row must match both. Chained .filter()
        # calls on a to-many relation join the table separately, so a row can
        # match the dimension in one coding and the tag in another — wrong.
        rows = rows.filter(codings__dimension=dimension, codings__tag=tag)
    else:
        if dimension:
            rows = rows.filter(codings__dimension=dimension)
        if tag:
            rows = rows.filter(codings__tag=tag)
    if start := request.GET.get("from"):
        rows = rows.filter(stated_on__gte=start)
    if end := request.GET.get("to"):
        rows = rows.filter(stated_on__lte=end)
    if q := request.GET.get("q"):
        rows = rows.filter(
            Q(quote__icontains=q)
            | Q(quote_translated__icontains=q)
            | Q(place_name_as_written__icontains=q)
        )

    rows = rows.distinct()
    total = rows.count()

    data = [
        {
            "id": row.id,
            "quote": row.quote,
            "quote_language": row.quote_language,
            "quote_translated": row.quote_translated,
            "voice_type": row.voice_type,
            "channel": row.channel,
            "date": row.stated_on.isoformat() if row.stated_on else None,
            "iso3": row.iso3,
            "place_name": row.place_name_as_written,
            "admin_pcode": row.admin_pcode,
            "admin_level": row.admin_level,
            "match_method": row.match_method,
            "lat": row.lat,
            "lon": row.lon,
            "people_affected": row.people_affected,
            "severity": row.severity,
            "codings": [{"dimension": c.dimension, "tag": c.tag} for c in row.codings.all()],
            "source_document": row.document.file_name if row.document_id else None,
            "page": row.page,
        }
        for row in rows.order_by("-stated_on", "id")[: _limit(request)]
    ]
    return JsonResponse({"count": total, "results": data})
