"""Channel routing, maintenance window filtering, and digest outbox writer."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dedup import AggregatedIncident, Deduplicator
from .formatter import SummaryFormatter
from .incidents import SEVERITY_RANK, IncidentSignal
from .standin import LocalWebhookStandIn

_CHANNEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_channel_name(channel: str) -> str:
    if not isinstance(channel, str) or not _CHANNEL_RE.fullmatch(channel):
        raise ValueError(f"invalid channel name: {channel!r}")
    return channel


@dataclass(frozen=True)
class ChannelPolicy:
    channel: str
    min_severity: str = "LOW"
    max_items: int = 10
    require_plain_text: bool = True

    def __post_init__(self) -> None:
        validate_channel_name(self.channel)
        if self.min_severity not in SEVERITY_RANK or self.max_items < 1:
            raise ValueError("invalid channel policy severity or max_items")

    def allows(self, item: AggregatedIncident) -> bool:
        return item.peak_rank >= SEVERITY_RANK[self.min_severity]


@dataclass(frozen=True)
class MaintenanceSilence:
    rule_id: str
    subsystem_prefix: str
    max_suppressed_severity: str = "MEDIUM"

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.subsystem_prefix.strip():
            raise ValueError("rule_id and subsystem_prefix must be non-empty")
        if self.max_suppressed_severity not in SEVERITY_RANK:
            raise ValueError(f"invalid severity ceiling: {self.max_suppressed_severity}")
        if self.max_suppressed_severity == "CRITICAL":
            raise ValueError("CRITICAL incidents cannot be silenced by maintenance rules")

    def matches(self, signal: IncidentSignal) -> bool:
        ceiling = SEVERITY_RANK[self.max_suppressed_severity]
        return signal.subsystem.startswith(self.subsystem_prefix) and signal.rank <= ceiling


class SilenceRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, MaintenanceSilence] = {}
        self.suppressed_count: int = 0

    def register(self, rule: MaintenanceSilence) -> None:
        self._rules[rule.rule_id] = rule

    def remove(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def is_silenced(self, signal: IncidentSignal) -> bool:
        for rule in self._rules.values():
            if rule.matches(signal):
                self.suppressed_count += 1
                return True
        return False

    def active_rules(self) -> list[MaintenanceSilence]:
        return [self._rules[k] for k in sorted(self._rules)]


def ingest_silences(entries: list[dict[str, Any]]) -> SilenceRegistry:
    registry = SilenceRegistry()
    for entry in entries:
        registry.register(
            MaintenanceSilence(
                rule_id=str(entry["rule_id"]),
                subsystem_prefix=str(entry["subsystem_prefix"]),
                max_suppressed_severity=str(entry.get("max_suppressed_severity", "MEDIUM")),
            )
        )
    return registry


class AlertRouter:
    def __init__(
        self, formatter: SummaryFormatter, primary_origin: str, outbox_dir: Path,
        silences: SilenceRegistry | None = None,
        channel_policies: dict[str, ChannelPolicy] | None = None,
        standin: LocalWebhookStandIn | None = None, webhook_url: str | None = None,
    ) -> None:
        self.formatter = formatter
        self.primary_origin = primary_origin
        self.outbox_dir = Path(outbox_dir)
        self.dedup = Deduplicator()
        self.silences = silences if silences is not None else SilenceRegistry()
        self.channel_policies = dict(channel_policies) if channel_policies else {}
        standin_env = os.environ.get("ALERT_STANDIN_DIR", "").strip()
        standin_dir = Path(standin_env) if standin_env else (self.outbox_dir / ".standin")
        self.standin = standin if standin is not None else LocalWebhookStandIn(standin_dir)
        env_webhook = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
        self.webhook_url = webhook_url if webhook_url is not None else (env_webhook or None)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    def ingest_signals(self, signals: list[IncidentSignal]) -> dict[str, int]:
        accepted = 0
        silenced = 0
        for sig in signals:
            sig.validate()
            if self.silences.is_silenced(sig):
                silenced += 1
                continue
            self.dedup.observe(sig)
            accepted += 1
        return {"accepted": accepted, "silenced": silenced}

    def preview_lines(self, limit: int = 10) -> list[str]:
        items = self.dedup.top_incidents(limit=limit)
        return [self.formatter.render_line(item, self.primary_origin) for item in items]

    def dispatch_digest(self, channel: str, max_items: int = 10) -> Path:
        """Render a deduplicated plain-text digest to outbox_dir/<channel>.txt."""
        raise NotImplementedError("Deduplicated digest dispatch is not implemented yet")
