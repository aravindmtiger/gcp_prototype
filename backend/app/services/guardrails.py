"""Lightweight PII redaction applied to text before it reaches a model.

This is a local safety net. For production-grade screening (prompt injection,
harmful content, sensitive data) put Google's Model Armor in front of the model
call; the redaction hook here stays useful as a defence-in-depth layer.
"""

import re

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # 13-16 digits, optionally separated by spaces or dashes (card numbers).
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){12,15}\d\b")),
    ("PHONE", re.compile(r"\+?\d[\d\s().-]{8,}\d")),
]


def redact_pii(text: str) -> str:
    redacted = text
    for label, pattern in _PII_PATTERNS:
        redacted = pattern.sub(f"[{label}_REDACTED]", redacted)
    return redacted
