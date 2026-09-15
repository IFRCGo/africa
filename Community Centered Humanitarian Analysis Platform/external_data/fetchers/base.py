"""What every fetcher guarantees, and the helpers that enforce it.

A fetcher turns one source_sync row into a sequence of Calls. It does not make
them - the runner does, serially - and it never touches the database. That split
is what keeps "never pull two IPC countries in parallel" enforceable in one place
instead of in five.

Four guarantees, matching the loaders' four:

  saved before loaded  the raw response is written to mcp_cache/ and only then
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
from pathlib import Path

import requests
from django.conf import settings

from external_data.fetchers import fetcher_for  # noqa: F401  (re-exported)

# Every setting whose value must never appear in a log line or an error message.
SECRET_SETTINGS = ("IPC_API_KEY", "HDX_API_TOKEN")


class FetchError(Exception):
    """An upstream call failed. The message is already redacted."""


@dataclass(frozen=True)
class Call:
    """One upstream request, and what to do with what comes back.

    `cache_path` is RELATIVE to MCP_CACHE_DIR, so a fetcher never has to know
    where the cache lives. `loader_dataset` names the loader that parses the
    result, which is not always the row's own dataset - see the registry note.
    """

    url: str
    params: dict
    cache_path: Path
    loader_dataset: str
    context: dict = field(default_factory=dict)
    # HAPI pages at 100 by default and Sudan's IDP series is 5,686 rows, so some
    # Calls must be followed to the end. The flag lives on the Call rather than
    # in the runner because whether an endpoint paginates is the fetcher's
    # knowledge, not the runner's.
    paginated: bool = False


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


def save_payload(cache_path, payload):
    """Write the raw response under MCP_CACHE_DIR and return the full path.

    Saved BEFORE the loader sees it, on purpose: a payload that breaks a parser
    is then still on disk to look at, which is the whole reason this project
    keeps a cache at all.
    """
    path = Path(settings.MCP_CACHE_DIR) / cache_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
