"""Incident signal models and severity ordering."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


SEVERITY_RANK = {
    "LOW": 10,
    "MEDIUM": 20,
    "HIGH": 30,
    "CRITICAL": 40,
}


@dataclass(frozen=True)
class IncidentSignal:
    incident_id: str
    subsystem: str
    severity: str
    summary: str
    runbook_slug: str

    def validate(self) -> None:
        if not self.incident_id.strip():
            raise ValueError("incident_id cannot be blank")
        if self.severity not in SEVERITY_RANK:
            raise ValueError(f"unknown severity: {self.severity}")
        if not self.runbook_slug.replace("-", "").isalnum():
            raise ValueError("runbook_slug must be alphanumeric kebab-case")

    @property
    def rank(self) -> int:
        return SEVERITY_RANK[self.severity]

    def fingerprint(self) -> str:
        normalized = f"{self.subsystem.lower()}::{self.runbook_slug.lower()}::{self.summary.strip().lower()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
