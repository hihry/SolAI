"""Origin-bound plain-text summary formatter for incident digests."""

from __future__ import annotations

from urllib.parse import urlparse

from .dedup import AggregatedIncident


class SummaryFormatter:
    def __init__(self, allowed_origins: set[str]) -> None:
        if not allowed_origins:
            raise ValueError("allowed_origins must not be empty")
        self.allowed_origins = {origin.rstrip("/") for origin in allowed_origins}

    def build_status_url(self, base_origin: str, runbook_slug: str) -> str:
        clean_origin = base_origin.rstrip("/")
        parsed = urlparse(clean_origin)
        if parsed.scheme != "https" or clean_origin not in self.allowed_origins:
            raise ValueError(f"untrusted status origin: {base_origin}")
        return f"{clean_origin}/status/runbooks/{runbook_slug}"

    def render_line(self, item: AggregatedIncident, base_origin: str) -> str:
        link = self.build_status_url(base_origin, item.runbook_slug)
        return (
            f"[{item.peak_severity}] {item.subsystem} (x{item.occurrences}): "
            f"{item.latest_summary} | ref={link}"
        )
