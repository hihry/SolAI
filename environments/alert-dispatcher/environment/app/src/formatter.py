"""Origin-bound plain-text summary formatter for incident digests."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from .dedup import AggregatedIncident
from .incidents import RUNBOOK_SLUG_RE

_HTML_TAG_RE = re.compile(
    r"</?(?:!doctype|[a-z][a-z0-9-]*)(?:[\s/][^<>]*?)?>",
    re.IGNORECASE,
)


def is_plain_text(payload: str) -> bool:
    if not isinstance(payload, str) or "\x00" in payload:
        return False
    unescaped = html.unescape(payload)
    return _HTML_TAG_RE.search(payload) is None and _HTML_TAG_RE.search(unescaped) is None


class SummaryFormatter:
    def __init__(self, allowed_origins: set[str]) -> None:
        cleaned = {origin.strip().rstrip("/") for origin in allowed_origins if origin.strip()}
        if not cleaned:
            raise ValueError("allowed_origins must not be empty")
        self.allowed_origins = cleaned

    def _validate_origin(self, base_origin: str) -> str:
        clean_origin = base_origin.strip().rstrip("/")
        p = urlparse(clean_origin)
        if (
            p.scheme != "https" or not p.netloc or p.username is not None or p.password is not None
            or p.path or p.params or p.query or p.fragment or clean_origin not in self.allowed_origins
        ):
            raise ValueError(f"untrusted status origin: {base_origin}")
        return clean_origin

    def build_status_url(self, base_origin: str, runbook_slug: str) -> str:
        clean_origin = self._validate_origin(base_origin)
        if not RUNBOOK_SLUG_RE.fullmatch(runbook_slug):
            raise ValueError(f"invalid runbook_slug: {runbook_slug}")
        return f"{clean_origin}/status/runbooks/{runbook_slug}"

    def render_header(
        self, channel: str, total_groups: int, total_occurrences: int, silenced_count: int = 0
    ) -> str:
        return (
            f"Incident Digest | channel={channel} | groups={total_groups} "
            f"| occurrences={total_occurrences} | silenced={silenced_count}"
        )

    def render_line(self, item: AggregatedIncident, base_origin: str) -> str:
        link = self.build_status_url(base_origin, item.runbook_slug)
        return f"[{item.peak_severity}] {item.subsystem} (x{item.occurrences}): {item.latest_summary} | ref={link}"

    def render_footer(self, base_origin: str, truncated_count: int = 0) -> str:
        clean_origin = self._validate_origin(base_origin)
        return f"Verified status origin: {clean_origin} | truncated={max(0, truncated_count)}"
