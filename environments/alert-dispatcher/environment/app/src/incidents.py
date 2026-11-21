"""Incident signal models and severity ordering."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

SEVERITY_RANK = {"LOW": 10, "MEDIUM": 20, "HIGH": 30, "CRITICAL": 40}
RUNBOOK_SLUG_RE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
_CONTROL_CHARS = ("\r", "\n", "\x00")


@dataclass(frozen=True)
class IncidentSignal:
    incident_id: str
    subsystem: str
    severity: str
    summary: str
    runbook_slug: str
    source_host: str = ""
    observed_at: str = ""

    def validate(self) -> None:
        checks = (
            ("incident_id", self.incident_id),
            ("subsystem", self.subsystem),
            ("summary", self.summary),
            ("runbook_slug", self.runbook_slug),
            ("source_host", self.source_host),
            ("observed_at", self.observed_at),
        )
        for name, value in checks:
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
            if any(ch in value for ch in _CONTROL_CHARS):
                raise ValueError(f"{name} must not contain control characters")
        if not self.incident_id.strip() or not self.subsystem.strip() or not self.summary.strip():
            raise ValueError("incident_id, subsystem, and summary cannot be blank")
        if self.severity not in SEVERITY_RANK:
            raise ValueError(f"unknown severity: {self.severity}")
        if not RUNBOOK_SLUG_RE.fullmatch(self.runbook_slug):
            raise ValueError("runbook_slug must be alphanumeric kebab-case")

    @property
    def rank(self) -> int:
        return SEVERITY_RANK[self.severity]

    def fingerprint(self) -> str:
        norm = f"{self.subsystem.lower()}::{self.runbook_slug.lower()}::{self.summary.strip().lower()}"
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def from_dict(cls, entry: dict[str, Any]) -> IncidentSignal:
        if not isinstance(entry, dict):
            raise ValueError("signal entry must be a JSON object")
        signal = cls(
            incident_id=str(entry["incident_id"]),
            subsystem=str(entry["subsystem"]),
            severity=str(entry["severity"]),
            summary=str(entry["summary"]),
            runbook_slug=str(entry["runbook_slug"]),
            source_host=str(entry.get("source_host", "")),
            observed_at=str(entry.get("observed_at", "")),
        )
        signal.validate()
        return signal
