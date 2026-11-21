#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"

PYTHONDONTWRITEBYTECODE=1 python3 -B - "$APP_DIR" <<'PY'
from pathlib import Path
import sys

app_dir = Path(sys.argv[1]).resolve()
router_path = app_dir / "src" / "router.py"
src = router_path.read_text(encoding="utf-8")

# Ensure formatter.is_plain_text, urllib.parse.urlparse, and standin.post_to_local_webhook are imported
old_url_import = "from pathlib import Path\n"
new_url_import = "from pathlib import Path\nfrom urllib.parse import urlparse\n"
if "from urllib.parse import urlparse" not in src and old_url_import in src:
    src = src.replace(old_url_import, new_url_import, 1)

old_import = "from .formatter import SummaryFormatter"
new_import = "from .formatter import SummaryFormatter, is_plain_text"
if old_import in src and new_import not in src:
    src = src.replace(old_import, new_import, 1)

old_standin_import = "from .standin import LocalWebhookStandIn"
new_standin_import = "from .standin import LocalWebhookStandIn, post_to_local_webhook"
if old_standin_import in src and new_standin_import not in src:
    src = src.replace(old_standin_import, new_standin_import, 1)

stub = '''    def dispatch_digest(self, channel: str, max_items: int = 10) -> Path:
        """Render a deduplicated plain-text digest to outbox_dir/<channel>.txt."""
        raise NotImplementedError("Deduplicated digest dispatch is not implemented yet")'''

impl = '''    def dispatch_digest(self, channel: str, max_items: int = 10) -> Path:
        """Render a deduplicated plain-text digest to outbox_dir/<channel>.txt."""
        validate_channel_name(channel)
        if max_items < 1:
            raise ValueError("max_items must be at least 1")
        self.formatter.build_status_url(self.primary_origin, "origin-check")
        if self.webhook_url:
            parsed_hook = urlparse(self.webhook_url)
            if parsed_hook.scheme not in {"http", "https"} or parsed_hook.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError(f"only loopback webhook URLs are permitted offline: {self.webhook_url}")

        policy = self.channel_policies.get(channel)
        effective_max = min(max_items, policy.max_items) if policy is not None else max_items
        pool = self.dedup.top_incidents(limit=max(self.dedup.group_count, effective_max))
        if policy is not None:
            pool = [item for item in pool if policy.allows(item)]
        items = pool[:effective_max]
        truncated = max(0, self.dedup.group_count - len(items))

        header = self.formatter.render_header(
            channel=channel,
            total_groups=len(items),
            total_occurrences=self.dedup.total_observed,
            silenced_count=self.silences.suppressed_count,
        )
        lines = (
            [self.formatter.render_line(item, self.primary_origin) for item in items]
            if items
            else ["No active incidents."]
        )
        footer = self.formatter.render_footer(self.primary_origin, truncated_count=truncated)
        body = "\\n".join([header, *lines, footer]) + "\\n"
        if not is_plain_text(body):
            raise ValueError("digest payload must be strictly plain text")

        target = self.outbox_dir / f"{channel}.txt"
        if target.resolve().parent != self.outbox_dir.resolve():
            raise ValueError("resolved target escapes outbox_dir")
        target.write_text(body, encoding="utf-8")

        headers = {
            "x-alert-channel": channel,
            "x-status-origin": self.primary_origin.rstrip("/"),
        }
        self.standin.deliver(
            channel=channel,
            body=body,
            content_type="text/plain",
            headers=headers,
            transport="local_spool",
        )
        if self.webhook_url:
            post_to_local_webhook(self.webhook_url, channel, body, content_type="text/plain")
        return target'''

if impl in src:
    pass
elif stub in src:
    src = src.replace(stub, impl, 1)
    router_path.write_text(src, encoding="utf-8")
else:
    raise RuntimeError(f"Expected unfinished dispatch_digest stub not found in {router_path}")
PY

(cd "$APP_DIR" && PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests_unit -p 'test_*.py' -q)
