"""Logging configuration.

``LOG_FORMAT=json`` emits one JSON object per line. Cloud Logging maps the
``severity`` field to log severity automatically when logs go to stdout on Cloud Run.
"""

import json
import logging
import sys
from datetime import UTC, datetime

from app.config import Settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    # httpx and the Google client libraries are very chatty at INFO.
    for noisy in ("httpx", "google.auth", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
