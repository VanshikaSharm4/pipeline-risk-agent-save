"""Regex log signal extraction — IDFC / AEM patterns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

PATTERNS = [
    ("missing_npm_module", re.compile(r"Cannot find module|npm ERR!|ENOENT.*node_modules", re.I)),
    ("crxde_warning", re.compile(r"CRXDE|crxde", re.I)),
    ("davex_warning", re.compile(r"DavEx|davex", re.I)),
    ("dispatcher_syntax", re.compile(r"Syntax error on line|AH00526|dispatcher", re.I)),
    ("env_var_issue", re.compile(r"PUBLISH_IDFC_HOSTNAME|os\.environ|environment variable", re.I)),
    ("osgi_failure", re.compile(r"OSGi|bundle.*failed|Felix", re.I)),
    ("build_failed", re.compile(r"BUILD FAILURE|Failed to execute goal", re.I)),
    ("security_bundle", re.compile(r"security.*check|SecurityCheck", re.I)),
]

INFRA_SIGNALS = frozenset({"crxde_warning", "davex_warning"})


@dataclass
class ParseResult:
    signals: List[str] = field(default_factory=list)
    key_lines: List[str] = field(default_factory=list)
    error_type: str = ""


def parse_log(text: str, step: str = "") -> ParseResult:
    if not text or text.startswith("ERROR:"):
        return ParseResult()

    signals = []
    key_lines = []
    for name, rx in PATTERNS:
        if rx.search(text):
            signals.append(name)
            for line in text.splitlines():
                if rx.search(line) and len(key_lines) < 10:
                    key_lines.append(line.strip()[:200])

    error_type = signals[0] if signals else ""
    return ParseResult(signals=signals, key_lines=key_lines, error_type=error_type)


def signal_weight(signal: str) -> float:
    return 0.1 if signal in INFRA_SIGNALS else 1.0
