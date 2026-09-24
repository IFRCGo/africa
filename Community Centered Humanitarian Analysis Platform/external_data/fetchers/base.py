"""What every fetcher guarantees, and the helpers that enforce it.

A fetcher turns one source_sync row into a sequence of Calls. It does not make
them - the runner does, serially - and it never touches the database. That split
is what keeps "never pull two IPC countries in parallel" enforceable in one place
instead of in five.

Four guarantees, matching the loaders' four:

  saved before loaded  the raw response is written to api_cache/ and only then
                       parsed, so a payload that breaks a loader is still on disk
  one call at a time   plan() is a generator; the runner consumes it serially and
                       never gathers, maps or threads it
  keyed, or refused    a fetcher whose `requires` is unmet calls nothing at all
  empty is a failure   an empty payload reaches the loader and trips EmptyPayload,
                       and no watermark moves. That guarantee is the loaders', and
                       this package exists partly to avoid weakening it.
"""
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import requests
from django.conf import settings

from external_data.fetchers import fetcher_for  # noqa: F401  (re-exported)

# Every setting whose value must never appear in a log line or an error message.
SECRET_SETTINGS = ("IPC_API_KEY", "HDX_API_TOKEN", "IFRC_API_TOKEN")

# How far BEHIND the watermark a narrowed request starts.
#
# Not zero, and that is the whole point. The watermark is the newest DATA date
# held, so asking strictly after it would never see a figure the agency later
# restates - and they do restate recent months. Ninety days is long enough to
# catch a corrected quarter and short enough that a refresh stays an update
# rather than becoming a re-download.
LOOKBACK_DAYS = 90

# A runaway `next` chain would page forever. Sudan's whole window is a few
# thousand events at 500 a page, so this is a guard rail and not a limit.
MAX_PAGES = 200


class FetchError(Exception):
    """An upstream call failed. The message is already redacted."""


@dataclass(frozen=True)
class Call:
    """One upstream request, and what to do with what comes back.

    `cache_path` is RELATIVE to API_CACHE_DIR, so a fetcher never has to know
    where the cache lives. `loader_dataset` names the loader that parses the
    result, which is not always the row's own dataset - see the registry note.
    """

    url: str
    params: dict
    cache_path: Path
    loader_dataset: str
    context: dict = field(default_factory=dict)
    # Whether this request was narrowed by the watermark. It decides what an
    # EMPTY answer means: nothing new (fine) versus nothing at all (a fault).
    # See the runner, and `since` below.
    narrowed: bool = False
    # HAPI pages at 100 by default and Sudan's IDP series is 5,686 rows, so some
    # Calls must be followed to the end. The flag lives on the Call rather than
    # in the runner because whether an endpoint paginates is the fetcher's
    # knowledge, not the runner's.
    paginated: bool = False
    # GET with query params is what every fetcher before Montandon needed.
    # Montandon's country filter is a CQL2 expression, which only POST /search
    # accepts, so the verb is a property of the Call for the same reason
    # `paginated` is: it is the fetcher's knowledge, not the runner's.
    method: str = "GET"
    body: dict = None
    headers: dict = field(default_factory=dict)


class Fetcher:
    """Subclass, set the class attributes, and implement plan()."""

    source = ""        # 'ipc'            - matches source_sync.source
    dataset = ""       # 'food_security'  - matches source_sync.dataset
    variant = ""       # 'admin2-overview'- matches source_sync.variant
    tool = ""          # the MCP tool this reproduces, for the record
    requires = ()      # ('IPC_API_KEY',) - checked before anything is called

    def plan(self, sync):
        """Yield one Call per upstream request this pull needs.

        `sync` is the SourceSync row. Read-only here: a fetcher decides WHAT to
        ask for, and the runner is what records that it asked.
        """
        raise NotImplementedError

    def since(self, sync):
        """The date a narrowed request should start from, or None for everything.

        None when nothing is held: a first pull must ask for the whole series,
        or the table is silently seeded with a slice and called complete.
        """
        if not sync.high_water_date:
            return None
        return sync.high_water_date - timedelta(days=LOOKBACK_DAYS)

    def params_record(self):
        """What to write into source_sync.params after a successful pull.

        The column is documented as "the last call made, for reproducibility" and
        is empty on every row today, because nothing has ever written it. The
        default records the tool; a fetcher with interesting parameters overrides.
        """
        return {"tool": self.tool, "fetcher": type(self).__name__}


def missing_keys(fetcher_cls):
    """Which of this fetcher's required settings are unset. Empty list means go."""
    return [name for name in fetcher_cls.requires if not getattr(settings, name, "")]


def redact(text):
    """Remove every secret value from text.

    HAPI takes its token as a QUERY PARAMETER, so it appears in the URL, which
    appears in requests' own exception messages, which would otherwise appear in
    a job log that anyone with admin access can read. Redaction happens here, on
    the way out, rather than being remembered at each call site.
    """
    out = str(text)
    for name in SECRET_SETTINGS:
        value = getattr(settings, name, "")
        if value:                      # an empty key must not match everything
            out = out.replace(value, "<redacted>")
    return out


def http_get_json(url, params, timeout=60):
    """GET and decode, or raise FetchError with the secrets already removed."""
    try:
        response = requests.get(url, params=params, timeout=timeout,
                                headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise FetchError(redact(f"{url}: {exc}")) from None
    except ValueError as exc:
        # A 200 that is not JSON - an HTML error page, typically. Saying which
        # is worth more than "expecting value: line 1 column 1".
        raise FetchError(redact(f"{url}: response was not JSON ({exc})")) from None


def http_post_json(url, body, headers=None, timeout=60):
    """POST a JSON body and decode, or raise FetchError with secrets removed.

    Montandon's token travels in a header rather than in the URL, which is one
    fewer place for it to leak - but redact() still runs, because requests puts
    the request headers into some of its own exception messages.
    """
    try:
        response = requests.post(url, json=body, timeout=timeout,
                                 headers={"Accept": "application/json",
                                          "Content-Type": "application/json",
                                          **(headers or {})})
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise FetchError(redact(f"{url}: {exc}")) from None
    except ValueError as exc:
        raise FetchError(redact(f"{url}: response was not JSON ({exc})")) from None


def fetch_all_pages_token(url, body, headers=None):
    """Follow STAC's `token` to the end, and return one FeatureCollection.

    STAC does not page by offset the way HAPI does: the server hands back a
    complete next body, token included, in links[rel="next"]. It is sent back
    VERBATIM - constructing a token here would be guessing at the server's
    cursor format, which differs between implementations and is not ours to
    know.

    The combined result has the shape the loader expects, as though it had been
    one call. Paging is a property of the API, not of the data.
    """
    features, next_body, pages = [], body, 0
    while True:
        page = http_post_json(url, next_body, headers)
        features.extend(page.get("features", []))
        pages += 1
        link = next((l for l in page.get("links", []) if l.get("rel") == "next"), None)
        if not link or not link.get("body") or pages >= MAX_PAGES:
            return {"type": "FeatureCollection", "features": features}
        next_body = link["body"]


def fetch(call):
    """Make one Call: GET or POST, paged or not. The runner's one door.

    The runner's job is that calls happen ONE AT A TIME - two IPC countries in
    parallel took that server down for a session. Which verb and whether to
    page is the Call's business, and gathering it here is what keeps the
    runner's loop a plain serial for-loop.
    """
    if call.method == "POST":
        return (fetch_all_pages_token(call.url, call.body, call.headers)
                if call.paginated
                else http_post_json(call.url, call.body, call.headers))
    if call.paginated:
        # Left in hdx.py on purpose: test_fetcher_hdx patches its http_get_json
        # by name, and moving the function would break four passing tests for
        # no gain. Imported lazily, exactly as the runner used to do.
        from external_data.fetchers.hdx import fetch_all_pages
        return fetch_all_pages(call.url, call.params)
    return http_get_json(call.url, call.params)


def crisis_floor():
    """CRISIS_START as a date - the day fighting broke out in Khartoum.

    Defined in settings as a string and in data_pipeline.common as a date; a
    fetcher has no business importing the pipeline, so it parses the setting.
    Moved here from ipc.py, which now imports it, so there is one copy.
    """
    year, month, day = (int(part) for part in settings.CRISIS_START.split("-"))
    return date(year, month, day)


def save_payload(cache_path, payload):
    """Write the raw response under API_CACHE_DIR and return the full path.

    Saved BEFORE the loader sees it, on purpose: a payload that breaks a parser
    is then still on disk to look at, which is the whole reason this project
    keeps a cache at all.
    """
    path = Path(settings.API_CACHE_DIR) / cache_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
