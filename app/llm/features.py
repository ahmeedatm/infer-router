"""Semantic-complexity feature extractor for InferRouter-LLM.

The spike (Exp. H-C) showed that raw sentence embeddings do **not** separate
intent complexity (``simple`` / ``medium`` / ``complex``) at the accuracy of the
majority baseline. The chapter-3 model instead grounds complexity on three
explicit criteria:

* ``n(e)``  — number of distinct entities the intent touches;
* ``p(e)``  — depth of inference / number of coupled constraints;
* ``|δ(e)|`` — number of distinct network domains crossed.

This module computes **calculated proxies** of those criteria with pure regex
heuristics (no model, no I/O). The point is to give the downstream classifier
structured signal that embeddings lack, and to let us *measure* whether the
estimator learns the chapter-3 substance (n / p / |δ|) or merely the surface
form (length, count of SLAs). Every function is pure and returns new objects.
"""
from __future__ import annotations

import re
from collections import OrderedDict

# ── Vocabulary anchors, grouped by network domain (proxy for |δ(e)|) ─────────
# Compiled case-insensitively. Word boundaries avoid matching inside words.

# Network-function acronyms (5G core control/data plane).
_NF_ACRONYMS = (
    "AMF", "SMF", "UPF", "AUSF", "UDM", "PCF", "NRF", "NSSF", "NEF", "SEPP",
    "CHF",
)
# Reference-point interfaces.
_INTERFACES = ("N2", "N3", "N4", "N6", "N9", "F1", "Xn", "E2", "O1")

# Domain keyword groups. Membership in a group flips that domain "on" for the
# |δ(e)| count. Acronyms above are folded into the relevant groups below.
_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ran": (
        "gNB", "eNB", "RSRP", "RSRQ", "SINR", "CQI", "PRB", "MIMO", "handover",
        "RLC", "PDCP", "MCS", "PUSCH", "beam", "antenna", "sector", "cell",
        "NR-Cell", "5QI",
    ),
    "core": _NF_ACRONYMS + (
        "PDU", "GTP", "NAS", "registration", "session", "QoS flow", "anchor",
    ),
    "security": (
        "IPsec", "authentication", "integrity", "ciphering", "access control",
        "ACL", "encryption", "certificate", "key", "intrusion", "firewall",
        "SEPP",
    ),
    "slice": (
        "slice", "s-NSSAI", "S-NSSAI", "NSSAI", "SST", "eMBB", "URLLC", "mMTC",
        "NSI", "isolation",
    ),
}

# ── Entity identifier patterns (proxy for n(e)) ──────────────────────────────
# Distinct identifiers and typed network objects. Each *distinct* match counts
# once (a repeated id is the same entity).
_ENTITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgNB-[\w]+", re.IGNORECASE),         # gNB-207-C1, gNB-101
    re.compile(r"\beNB-[\w]+", re.IGNORECASE),         # LTE eNB-700
    re.compile(r"\bNR-Cell-?[\w]+", re.IGNORECASE),    # NR-Cell identifiers
    re.compile(r"\bgnb-cell-[\w]+", re.IGNORECASE),    # gnb-cell-117
    re.compile(r"\bNSI-[\w-]+", re.IGNORECASE),        # NSI-EMB-007 slice inst.
    re.compile(r"\b(?:upf|smf|amf|ausf|udm|pcf|nrf|nssf|nef|sepp|chf)-[\w-]+",
               re.IGNORECASE),                          # upf-west-03, smf-...
    # Typed acronyms with no instance id still count as a referenced entity.
    re.compile(r"\b(?:S-?NSSAI|SST|5QI)\b", re.IGNORECASE),
)
# Bare NF acronyms (AMF, SMF, ...) referenced without an instance id.
_NF_BARE = re.compile(
    r"\b(?:" + "|".join(_NF_ACRONYMS) + r")\b"
)
# Reference-point interfaces (N2, N3, F1, Xn, ...).
_IFACE_PATTERN = re.compile(
    r"\b(?:" + "|".join(_INTERFACES) + r")\b"
)

# ── Constraint / inference-depth markers (proxy for p(e)) ────────────────────
_CONSTRAINT_MARKERS: tuple[str, ...] = (
    "such that", "while", "without", "ensuring", "ensure", "subject to",
    "maximis", "maximiz", "minimis", "minimiz", "so that", "provided that",
    "as long as", "guarantee", "must not", "never breach",
)
_CONSTRAINT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(re.escape(marker), re.IGNORECASE) for marker in _CONSTRAINT_MARKERS
)
# Chiffred SLA thresholds: a comparator next to a number ("<= 1 ms", "below 15
# percent", "above -110 dBm"). Each is one quantified constraint.
_SLA_PATTERN = re.compile(
    r"(?:<=|>=|<|>|below|above|exceed(?:s|ing)?|under|over|at\s+least|at\s+most)"
    r"\s*-?\d",
    re.IGNORECASE,
)

# ── Numeric values with units (supporting signal, not a chapter-3 criterion) ─
_NUMBER_UNIT_PATTERN = re.compile(
    r"-?\d+(?:\.\d+)?\s*(?:ms|s|Mbps|Gbps|kbps|kbit|Mbit|percent|%|dBm|dB|"
    r"GHz|MHz|kHz|kWh|Wh|requests?/s|handovers?)",
    re.IGNORECASE,
)

# ── Sentence and token boundaries ────────────────────────────────────────────
_SENTENCE_PATTERN = re.compile(r"[.!?]+(?:\s|$)")
_TOKEN_PATTERN = re.compile(r"\S+")

# Stable, ordered feature vector contract shared with the trainer and router.
FEATURE_NAMES: tuple[str, ...] = (
    "n_entities",
    "n_constraints",
    "n_domains",
    "n_numbers",
    "n_tokens",
    "n_sentences",
)


def _count_entities(text: str) -> int:
    """Count distinct network entities referenced (proxy for n(e)).

    Distinct identifier strings are deduplicated (case-insensitive): the same
    ``gNB-101`` mentioned twice is one entity. Bare NF acronyms and reference
    interfaces each add their distinct surface forms.
    """
    found: set[str] = set()
    for pattern in _ENTITY_PATTERNS:
        for match in pattern.findall(text):
            found.add(match.lower())
    for match in _NF_BARE.findall(text):
        found.add(match.lower())
    for match in _IFACE_PATTERN.findall(text):
        found.add(match.lower())
    return len(found)


def _count_constraints(text: str) -> int:
    """Count inference-depth markers and quantified SLAs (proxy for p(e))."""
    marker_hits = sum(
        len(pattern.findall(text)) for pattern in _CONSTRAINT_PATTERNS
    )
    sla_hits = len(_SLA_PATTERN.findall(text))
    return marker_hits + sla_hits


def _count_domains(text: str) -> int:
    """Count distinct network domains evoked (proxy for |δ(e)|).

    A domain is "on" as soon as one of its keyword anchors appears. The result
    is in ``[0, 4]`` (ran / core / security / slice).
    """
    active = 0
    for keywords in _DOMAIN_KEYWORDS.values():
        pattern = re.compile(
            r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
            re.IGNORECASE,
        )
        if pattern.search(text):
            active += 1
    return active


def _count_numbers(text: str) -> int:
    """Count numeric values carrying a unit (ms, Mbps, %, dBm, ...)."""
    return len(_NUMBER_UNIT_PATTERN.findall(text))


def _count_tokens(text: str) -> int:
    """Word count (whitespace-delimited tokens)."""
    return len(_TOKEN_PATTERN.findall(text))


def _count_sentences(text: str) -> int:
    """Sentence count via terminal punctuation; ≥ 1 for any non-empty text."""
    stripped = text.strip()
    if not stripped:
        return 0
    hits = len(_SENTENCE_PATTERN.findall(stripped))
    return max(1, hits)


def extract_features(text: str) -> "OrderedDict[str, float]":
    """Compute chapter-3 complexity proxies for one intent text.

    Pure function: no model, no I/O, input left untouched. Returns an ordered
    mapping keyed by :data:`FEATURE_NAMES` with float values.

    Args:
        text: the intent statement.

    Returns:
        Ordered dict of ``{feature_name: value}`` in :data:`FEATURE_NAMES` order.

    Raises:
        TypeError: if ``text`` is not a string (validation at the boundary).
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be a str, got {type(text).__name__}.")

    values: "OrderedDict[str, float]" = OrderedDict()
    values["n_entities"] = float(_count_entities(text))
    values["n_constraints"] = float(_count_constraints(text))
    values["n_domains"] = float(_count_domains(text))
    values["n_numbers"] = float(_count_numbers(text))
    values["n_tokens"] = float(_count_tokens(text))
    values["n_sentences"] = float(_count_sentences(text))
    return values


def features_matrix(texts, cols=None) -> tuple[list[list[float]], list[str]]:
    """Build an sklearn-ready matrix from many intent texts.

    Args:
        texts: iterable of intent statements.
        cols: optional ordered list of feature names to keep. When provided,
            only those columns are returned, in that exact order. When ``None``
            (default), all :data:`FEATURE_NAMES` are returned in their canonical
            order, preserving every existing caller.

    Returns:
        ``(X, names)`` where ``X`` is a list of rows aligned column-for-column
        with ``names`` (a copy of the selected columns).

    Raises:
        KeyError: if ``cols`` references a feature name not in
            :data:`FEATURE_NAMES` (validation at the boundary).
    """
    names = list(FEATURE_NAMES) if cols is None else list(cols)
    unknown = [name for name in names if name not in FEATURE_NAMES]
    if unknown:
        raise KeyError(
            f"Unknown feature name(s) {unknown}; expected a subset of {FEATURE_NAMES}."
        )
    matrix = [
        [extract_features(text)[name] for name in names] for text in texts
    ]
    return matrix, names
