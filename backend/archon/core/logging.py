"""Structured logging with secret redaction (spec sections 52, 55).

Tokens, passwords and anything that looks like a credential are scrubbed from log
records before they are emitted, so a leaked GitHub token can never reach a log file.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

_SECRET_KEYS = re.compile(r"(token|secret|password|passwd|authorization|api[_-]?key)", re.IGNORECASE)
_URL_CRED = re.compile(r"(https?://)([^/@\s:]+):([^/@\s]+)@")

# Known credential shapes, scrubbed wherever they appear in a message string.
_TOKEN_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),                 # GitHub PAT / OAuth
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),               # GitHub fine-grained PAT
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),                  # Anthropic API key
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                        # OpenAI-style key
    re.compile(r"AKIA[0-9A-Z]{16}"),                           # AWS access key id
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}=*"),    # Authorization: Bearer <jwt/opaque>
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        value = _URL_CRED.sub(r"\1\2:***@", value)
        for pat in _TOKEN_PATTERNS:
            value = pat.sub("***", value)
        return value
    if isinstance(value, dict):
        return {
            k: ("***" if _SECRET_KEYS.search(str(k)) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        if hasattr(record, "extra_fields"):
            record.extra_fields = redact(record.extra_fields)  # type: ignore[attr-defined]
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_fields"):
            payload.update(record.extra_fields)  # type: ignore[attr-defined]
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_configured = False


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    global _configured
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_RedactingFilter())
    if json_output:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
        )
    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        configure_logging()
    return logging.getLogger(name)
