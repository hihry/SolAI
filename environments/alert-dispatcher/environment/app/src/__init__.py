"""Operational alert dispatcher package."""

from .dedup import AggregatedIncident, Deduplicator
from .formatter import SummaryFormatter, is_plain_text
from .incidents import SEVERITY_RANK, IncidentSignal
from .router import (
    AlertRouter,
    ChannelPolicy,
    MaintenanceSilence,
    SilenceRegistry,
    ingest_silences,
    validate_channel_name,
)
from .standin import DeliveryRecord, LocalWebhookServer, LocalWebhookStandIn, post_to_local_webhook

__all__ = [
    "AggregatedIncident", "AlertRouter", "ChannelPolicy", "Deduplicator",
    "DeliveryRecord", "IncidentSignal", "LocalWebhookServer", "LocalWebhookStandIn",
    "MaintenanceSilence", "SEVERITY_RANK", "SilenceRegistry", "SummaryFormatter",
    "ingest_silences", "is_plain_text", "post_to_local_webhook", "validate_channel_name",
]
