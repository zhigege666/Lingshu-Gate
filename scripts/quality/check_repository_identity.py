#!/usr/bin/env python3
"""Fail closed when repository identity policy drifts."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import os
import re
import stat
import subprocess
import sys
import tarfile
import tomllib
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterator, Sequence


@dataclass(frozen=True)
class DigestRule:
    rule_id: str
    mode: str
    size: int
    units: int
    digest: str


@dataclass(frozen=True)
class PathRule:
    rule_id: str
    mode: str
    size: int
    digest: str


@dataclass(frozen=True)
class CompactPrefilter:
    rule_id: str
    size: int
    fingerprint: int
    anchor_offset: int
    anchor_codepoints: tuple[int, ...]


@dataclass(frozen=True, order=True)
class Violation:
    rule_id: str
    location: str
    line: int


@dataclass
class MatchBudget:
    single_words: set[str] = field(default_factory=set)


# Policy values are stored only as normalized length and SHA-256. This keeps the
# checker from reintroducing material that it is intended to reject.
_TEXT_RULES: tuple[DigestRule, ...] = (
    DigestRule("TXT-001", "phrase", 5, 1, "f5cfcb570b7edac2ed16e1a025d50155d6148de7397f4068790cdfc142300070"),
    DigestRule("TXT-002", "compact", 8, 1, "d07a88392d80fd4173d344bfdd30c445ae03050135feed2ea88895f44e95d54d"),
    DigestRule("TXT-003", "compact", 7, 1, "5b72ba9448008bb7da5d31b39591ec30e3ae90975939fec8196340955322b54c"),
    DigestRule("TXT-004", "compact", 8, 1, "ea616bbd33f7728536fc4b45d97cd3439d0629bae03afeeac7abcac8ed6652ed"),
    DigestRule("TXT-005", "phrase", 3, 1, "e4a49ac91ae97a25f60bbe2fa6e25809af94df975aa42d3db29edc17e44e6989"),
    DigestRule("TXT-006", "phrase", 18, 4, "910c33ee50c6c620b9c42e4474eaec3966db17f2ffb8ee60b61c3eccba3347e9"),
    DigestRule("TXT-007", "phrase", 8, 2, "2923f7be01ddb3b7c4535e1a473f98fb249919f71ad55f6a31c8226c0d4e91d7"),
    DigestRule("TXT-008", "phrase", 13, 2, "20f801f511c67b166397b37e591e48f5d91da98be59f6d380a953932237ff25f"),
    DigestRule("TXT-009", "phrase", 21, 3, "c97aa58e94cfef35054b9e7563a7de1aaccfdb40ed316c3d1510ea09d98f6303"),
    DigestRule("TXT-010", "phrase", 25, 3, "06d3eaee3d7fe8f911d75daf19508f3cbff6d725cc24138a955ec228f913ce90"),
    DigestRule("TXT-011", "phrase", 8, 1, "231f1f2cc1cc8a5ee79ee356222619c6cbca01e5a60e89bbd74378f1a6662f5e"),
    DigestRule("TXT-012", "phrase", 38, 3, "b4c115c5a3663e7adca20cf6eaee01a33cc71672011720a98bb504354b8ebb09"),
    DigestRule("TXT-013", "phrase", 9, 1, "c989edf18246e9c8cdd647369a4835f7dd9a0f47b8e755d37b16431fc5035981"),
    DigestRule("TXT-014", "phrase", 11, 2, "8d5016f8ae652887d32c6a8ce7197d39888e109fbf5581730b1876306b8e3635"),
    DigestRule("TXT-015", "compact", 10, 1, "a3089891504bc4999fb640ee720ce2178ed5e64ad3f1cd87c57637b9f5b92c1c"),
    DigestRule("TXT-016", "phrase", 11, 2, "a625159d18da57180b7215e56c4ca20cabf8bcd9b7030c8c460aeed7b5588c6c"),
    DigestRule("TXT-017", "phrase", 14, 2, "abc5ac745d337316e17047acd51f066a88aade0ce1634f55488f7369428944cf"),
    DigestRule("TXT-018", "phrase", 16, 2, "7d7a135125416a98a7936dc4cd3a77fe4e301c5354c3f9facd61711907572ac6"),
    DigestRule("TXT-019", "phrase", 11, 2, "400e10abe1c5fcd389f1f95b0139f3e8f58e553fdceafb81fe698e392d6e88f4"),
    DigestRule("TXT-020", "phrase", 9, 2, "ccea1572e54112c327bc8552f23b0fa457f17da6408a9175a52b1f4ffe4d240b"),
    DigestRule("TXT-021", "phrase", 10, 2, "ebf43d4382bf3476239ad39890cc1c3b8dbf79b686974c528b45fb0ca8fafaa6"),
    DigestRule("TXT-022", "phrase", 13, 2, "da6bf3ec1c80928ff77121941b8c3be8f21b912fa0b45b59cf84fed9a5c654b9"),
    DigestRule("TXT-023", "phrase", 7, 2, "7abdcc4cf6e07278efa7a9ff302ae6f08f8403ddab1c939ba9e3ca8657f35fd5"),
    DigestRule("TXT-024", "phrase", 17, 2, "261512c024871a06dbe7dca3e15ec62e870b6e2d4293bbe9dce80f407fdfad8d"),
    DigestRule("TXT-025", "phrase", 15, 2, "df4efe85b02f5911d2fd0209cd4852e276eb7d3b8d8282e14241ffd2d956c61e"),
    DigestRule("TXT-026", "phrase", 9, 1, "c70eca6b0f88f44d81a41311647e50fda1ac454ec04ffd442b0eb4743a993131"),
    DigestRule("TXT-027", "phrase", 6, 1, "5d72436256ada53828b51895a94bb8489e9f1ac4fe937a8024ef1594e7045ff6"),
    DigestRule("TXT-028", "phrase", 6, 1, "76e3c7bfe641ea125c0c2e1c5f89349e17b352ed128d528de2443794e7acf870"),
    DigestRule("TXT-029", "phrase", 8, 1, "6f7ac1823da81d2e52d1a1549ee69c85bbf8bb56d06682849e7c09da2785ce3b"),
    DigestRule("TXT-030", "phrase", 6, 1, "b7f12f76af2acae4680ecc1f715a7c300ee16915a13dfff7b226fcaeb93ad439"),
    DigestRule("TXT-031", "phrase", 6, 1, "e2ed27f51afdeec9c9c986680a5a5aa938dccb19af5121de2b38d53e32c9fe78"),
    DigestRule("TXT-032", "phrase", 12, 2, "d0cc2c30ac92759bd0eb2e58b7029699a387f2fd5c859a027ab32c202db373b8"),
    DigestRule("TXT-034", "phrase", 11, 2, "22596e5bbfe0a3574f821b7ca6a9db7910044a8643b473d98b8b01b6ab80844e"),
    DigestRule("TXT-035", "phrase", 12, 2, "268fdcc96c89290b6c5f63d73ea761b03013978820c3b0b09615ee6d9baaf393"),
    DigestRule("TXT-036", "phrase", 13, 2, "09ca190d2746dcc30537e49357c575df67613b41b659711b1945a5a9c8038ca3"),
    DigestRule("TXT-037", "phrase", 13, 2, "f06e47fbc3dff9c6a34a50534410b5cdcf0bb8e2661b22b026c79180ec7a5ff7"),
    DigestRule("TXT-038", "phrase", 14, 2, "a56676eb9361eb90dbc1e8ea6ccd12d34ac90ab252df8adc3c06ab838d1cea5c"),
    DigestRule("TXT-039", "phrase", 10, 2, "5f53a7f8be354f12c08cc635f7766467634f31e6c3960eef6145b845796b16ab"),
    DigestRule("TXT-040", "phrase", 6, 1, "7d3194f79e645c42e4396dda38be04766810ec6a00d00aced3ffc2a0a1f1a9ef"),
    DigestRule("TXT-041", "phrase", 6, 1, "c857d09db23e6822e3600bc06ad8d58f92ed62bc8efd81c753f77048662cb97d"),
    DigestRule("TXT-042", "phrase", 8, 1, "5d0c0ab127fdea24d94e7e3326b6ceb965ab82ad897f9de1bd6b1a9a23f87578"),
    DigestRule("TXT-043", "phrase", 5, 1, "84829dbd815311888f0e3d85822e9b07d14be89a480a3c09ee67353f0e806e3b"),
    DigestRule("TXT-044", "phrase", 5, 1, "5792d2981981be5a2677cd353db6f55cd9d2779570061ae8d86176635b3cc745"),
    DigestRule("TXT-045", "phrase", 5, 1, "57de4cf40144bdf7d00010f2f5557a7d642c2b9705309bfade167dd313e2ca93"),
    DigestRule("TXT-046", "phrase", 6, 1, "c600edf6ce0739a94a591d68b4a42d84b76a117e0395a1bb88c36aa5ae9024d7"),
    DigestRule("TXT-047", "phrase", 17, 2, "b63ce17b8653b4cca687cf2f051dc611f94a697da08c8af86f53135c8755e784"),
    DigestRule("TXT-048", "phrase", 11, 2, "e25e773db9f676c9c835465fb88e8bd211a0d842661269d87dfcd5481462e05d"),
)
_COMPACT_ALIAS_RULE_IDS = frozenset({"TXT-001"})
_PHRASE_RULES = tuple(rule for rule in _TEXT_RULES if rule.mode == "phrase")
_PHRASE_INDEX = {(rule.units, rule.size, rule.digest): rule.rule_id for rule in _PHRASE_RULES}
_PHRASE_UNITS = tuple(sorted({rule.units for rule in _PHRASE_RULES if rule.units > 1}))
_PHRASE_SIZES = {
    units: frozenset(rule.size for rule in _PHRASE_RULES if rule.units == units) for units in _PHRASE_UNITS
}
_COMPACT_RULES = tuple(
    rule for rule in _TEXT_RULES if rule.mode == "compact" or rule.rule_id in _COMPACT_ALIAS_RULE_IDS
)
_COMPACT_INDEX = {(rule.size, rule.digest): rule.rule_id for rule in _COMPACT_RULES}
_COMPACT_SIZES = tuple(sorted({rule.size for rule in _COMPACT_RULES}))
# Short encoded anchors let the C-level string search inspect every possible
# location in linear time. A 64-bit fingerprint and the policy SHA-256 digest
# both verify every candidate; neither the full policy text nor sampled edges
# are stored or trusted.
_COMPACT_PREFILTERS = (
    CompactPrefilter("TXT-001", 5, 481_594_134_067, 2, (120, 117)),
    CompactPrefilter("TXT-002", 8, 8_100_227_983_822_081_139, 5, (120, 117)),
    CompactPrefilter("TXT-003", 7, 28_065_191_767_408_881, 1, (103, 101)),
    CompactPrefilter("TXT-004", 8, 7_807_181_656_410_987_600, 2, (102, 114)),
    CompactPrefilter("TXT-015", 10, 16_493_352_227_222_885_157, 5, (116, 107)),
)
_ROLLING_BASE = 257
_ROLLING_MASK = (1 << 64) - 1
_SINGLE_SIZES = frozenset(
    {rule.size for rule in _PHRASE_RULES if rule.units == 1} | {rule.size for rule in _COMPACT_RULES}
)

_PATH_RULES: tuple[PathRule, ...] = (
    PathRule("PATH-001", "prefix", 25, "f539133a4f23c09af50e9104bf47ea65e14177977b2639be88ca3bb81104dac0"),
    PathRule("PATH-002", "exact", 31, "fbd72b12c1d7fcb7b6823e2403cd35a377bb44cad3fd9d330868cc41895e1298"),
    PathRule("PATH-003", "exact", 25, "a9155c66b39a057a16a14ec9b76eb80149ec9892e621a1e64ec809f7f50089a5"),
    PathRule("PATH-004", "exact", 37, "efe4a9c8a8d27f533d17a5da051667b1ea4811ebac2e936a0d9d2676a2fcf5fd"),
    PathRule("PATH-005", "exact", 37, "6999bf76b8b341f188d4ae8c450110d988be555cd884d51eca0986dbce74c265"),
    PathRule("PATH-006", "exact", 30, "0dfed5d423d0fc856fac4b882017c29ced4f8f8eb6f9984cc156b8bf43902a01"),
    PathRule("PATH-007", "exact", 50, "7e8bbd70ee5e2c1afd3af9161661b77d712efc0753875ee901f6bef1a3acb4bc"),
    PathRule("PATH-008", "exact", 35, "9ab232af0fe25f89516f0a43cf7264427fb0484622474a1fb0a9b3b0895ccec2"),
    PathRule("PATH-009", "exact", 36, "b8e3a97ce276fe24f80cd3c4caaae5cdba27f5f6220ae418056812f265593b56"),
    PathRule("PATH-010", "exact", 35, "18b768ae69aa3a3c4ebe39a176c2f38ad73b74a156f5c4f3806d12e0debd634e"),
    PathRule("PATH-011", "exact", 36, "714fe633dc70c36ed75f701374eb2568af76e245aee4553eae7ec38ff3185cbc"),
    PathRule("PATH-012", "exact", 32, "9d97e626185cf53cc2c73cef809c4301d3d38f0e4f98757f8880cebfec5f0b9a"),
    PathRule("PATH-013", "exact", 27, "4cd9e868c2a8e5e88df43de1eacac4a1999edef8cf4c0d73a99a536725f34d0c"),
    PathRule("PATH-014", "exact", 32, "41721465b775d136cab2891a2bb00d0f415ca97ee25b88edceae10170b971a0d"),
    PathRule("PATH-015", "exact", 31, "041a7c4e17ed6d3b2abfbbe736ea231bb3e8b41325dfc1683c7ca519cd5a6794"),
    PathRule("PATH-016", "exact", 35, "01c70147367ef654dda30f1013ee5d0a18a673dbf3e123afd8921dc5f434b8cb"),
    PathRule("PATH-017", "exact", 26, "99932ce371e2e3bbd2eb5c3a1cb1253954dd08bfba308b19d35a2eed60325e18"),
    PathRule("PATH-018", "exact", 25, "362abb5c5af4edc1db6e34301d2cfeab67f35457d65c896fb4b4489735bb0e79"),
    PathRule("PATH-019", "exact", 24, "2e307ecbad3152d51fcabc95b7b2cb611ad22f484660eb7bf0dbf9abb2ba67e4"),
    PathRule("PATH-020", "exact", 29, "a2d158e884b4f803535b296fa0e88ee6c3efec15ca1b953d1f22d8e0e8c44c29"),
)
_ALLOWED_SKILL = PurePosixPath(".agents/skills/lingshu-gate-upload-build-start/SKILL.md")
_ALLOWED_SKILL_ROOT = _ALLOWED_SKILL.parent
_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "site-packages",
        "venv",
    }
)
_EXCLUDED_FILES = frozenset(
    {
        "npm-shrinkwrap.json",
        "package-lock.json",
        "packages.lock.json",
        "pnpm-lock.yaml",
        "poetry.lock",
        "requirements.lock",
        "uv.lock",
        "yarn.lock",
    }
)
_TEXT_SUFFIXES = frozenset(
    {
        ".bash",
        ".bat",
        ".c",
        ".cc",
        ".cfg",
        ".cjs",
        ".cmd",
        ".conf",
        ".cpp",
        ".cs",
        ".css",
        ".dockerfile",
        ".env",
        ".go",
        ".gradle",
        ".graphql",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsonc",
        ".jsx",
        ".kt",
        ".kts",
        ".lua",
        ".md",
        ".mjs",
        ".php",
        ".properties",
        ".proto",
        ".ps1",
        ".psd1",
        ".psm1",
        ".py",
        ".rb",
        ".rst",
        ".rs",
        ".sh",
        ".spec",
        ".sql",
        ".svelte",
        ".svg",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".vue",
        ".xml",
        ".yaml",
        ".yml",
        ".zsh",
    }
)
_TEXT_NAMES = frozenset(
    {
        ".dockerignore",
        ".gitattributes",
        ".gitignore",
        "AGENTS.md",
        "Dockerfile",
        "LICENSE",
        "Makefile",
        "NOTICE",
        "Procfile",
    }
)
_GENERATED_ROOT_DIRS = frozenset({"artifacts", "build", "dist", "release", "releases"})
_INTERMEDIATE_DIRS = frozenset({"pyinstaller-dist", "pyinstaller-work"})
_LEGAL_ARTIFACT_NAMES = frozenset(
    {
        "license",
        "notice",
        "third_party_notices.md",
    }
)
_ARTIFACT_GLOBAL_PATH_RULE_IDS = frozenset({"SKILL-003", "SKILL-004", "TXT-001", "TXT-002", "TXT-003"})
_ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".whl", ".zip")
_MAX_TEXT_BYTES = 32 * 1024 * 1024
_MAX_BINARY_BYTES = 512 * 1024 * 1024
_MAX_ARCHIVE_SCAN_BYTES = 512 * 1024 * 1024
_MAX_SINGLE_WORD_CACHE = 100_000
_ASCII_WORDS = re.compile(r"[a-z0-9]+")
_GATE_ENVIRONMENT_NAME = re.compile(r"(?<![A-Z0-9_])LINGSHU_[A-Z0-9_]+")
_LINGSHU_KEBAB_NAME = re.compile(r"(?<![a-z0-9])lingshu-[a-z0-9][a-z0-9._-]*", re.IGNORECASE)
_EVENT_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_ASCII_RUN = re.compile(rb"[\x20-\x7e]{4,}")
_UTF16_LE_RUN = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")
_UTF16_BE_RUN = re.compile(rb"(?:\x00[\x20-\x7e]){4,}")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ascii_words(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _ASCII_WORDS.findall(normalized)


def _normalize_path(value: str | PurePosixPath) -> str:
    normalized = unicodedata.normalize("NFKC", str(value).replace("\\", "/")).casefold()
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.removeprefix("./")


def _compact_fingerprint(value: str) -> int:
    fingerprint = 0
    for character in value:
        fingerprint = (fingerprint * _ROLLING_BASE + ord(character)) & _ROLLING_MASK
    return fingerprint


def _matching_rules(value: str, budget: MatchBudget | None = None) -> set[str]:
    matches: set[str] = set()
    active_budget = budget if budget is not None else MatchBudget()
    words = _ascii_words(value)
    for word in words:
        if len(word) not in _SINGLE_SIZES:
            continue
        if word in active_budget.single_words:
            continue
        if len(active_budget.single_words) < _MAX_SINGLE_WORD_CACHE:
            active_budget.single_words.add(word)
        digest = _sha256(word)
        phrase_rule_id = _PHRASE_INDEX.get((1, len(word), digest))
        compact_rule_id = _COMPACT_INDEX.get((len(word), digest))
        if phrase_rule_id is not None:
            matches.add(phrase_rule_id)
        if compact_rule_id is not None:
            matches.add(compact_rule_id)

    for units in _PHRASE_UNITS:
        if len(words) < units:
            continue
        valid_sizes = _PHRASE_SIZES[units]
        for offset in range(len(words) - units + 1):
            candidate = " ".join(words[offset : offset + units])
            if len(candidate) not in valid_sizes:
                continue
            rule_id = _PHRASE_INDEX.get((units, len(candidate), _sha256(candidate)))
            if rule_id is not None:
                matches.add(rule_id)

    compacted = "".join(words)
    rules_by_id = {rule.rule_id: rule for rule in _COMPACT_RULES}
    for prefilter in _COMPACT_PREFILTERS:
        rule = rules_by_id[prefilter.rule_id]
        anchor = "".join(chr(codepoint) for codepoint in prefilter.anchor_codepoints)
        position = compacted.find(anchor)
        while position >= 0:
            offset = position - prefilter.anchor_offset
            candidate = compacted[offset : offset + prefilter.size] if offset >= 0 else ""
            if (
                len(candidate) == prefilter.size
                and _compact_fingerprint(candidate) == prefilter.fingerprint
                and _sha256(candidate) == rule.digest
            ):
                matches.add(rule.rule_id)
                break
            position = compacted.find(anchor, position + 1)
    return matches


def _matching_gate_identity_rules(value: str) -> set[str]:
    matches: set[str] = set()
    for token in _GATE_ENVIRONMENT_NAME.findall(value):
        if not token.startswith("LINGSHU_GATE_"):
            matches.add("GATE-003")
    for token_match in _LINGSHU_KEBAB_NAME.finditer(value):
        token = token_match.group().casefold()
        if token != "lingshu-gate" and not token.startswith(("lingshu-gate-", "lingshu-gate.")):
            matches.add("GATE-004")
    return matches


def _matching_path_rules(relative_path: str) -> set[str]:
    normalized = _normalize_path(relative_path)
    matches = _matching_rules(normalized) | _matching_gate_identity_rules(normalized)
    normalized_path = PurePosixPath(normalized)
    allowed_skill = PurePosixPath(_normalize_path(_ALLOWED_SKILL))
    allowed_skill_root = PurePosixPath(_normalize_path(_ALLOWED_SKILL_ROOT))
    if (
        normalized_path.parts[:2] == (".agents", "skills")
        and normalized_path.parts[: len(allowed_skill_root.parts)] != allowed_skill_root.parts
    ):
        matches.add("SKILL-004")
    if normalized_path.name == "skill.md" and normalized_path != allowed_skill:
        matches.add("SKILL-003")
    for rule in _PATH_RULES:
        if rule.mode == "exact":
            candidate = normalized if len(normalized) == rule.size else ""
        else:
            candidate = normalized[: rule.size] if len(normalized) >= rule.size else ""
        if candidate and _sha256(candidate) == rule.digest:
            matches.add(rule.rule_id)
    return matches


def _is_excluded(relative_path: PurePosixPath) -> bool:
    lower_name = relative_path.name.casefold()
    return (
        lower_name in _EXCLUDED_FILES
        or lower_name.endswith((".lock", ".lockb"))
        or any(part in _EXCLUDED_DIRS for part in relative_path.parts)
        or any(part.casefold().endswith(".egg-info") for part in relative_path.parts)
    )


def _is_third_party_source_path(relative_path: PurePosixPath) -> bool:
    parts = tuple(part.casefold() for part in relative_path.parts)
    return len(parts) >= 2 and parts[:2] == ("packaging", "licenses")


def _is_generated_path(relative_path: PurePosixPath) -> bool:
    return bool(relative_path.parts) and relative_path.parts[0].casefold() in _GENERATED_ROOT_DIRS


def _is_archive(relative_path: PurePosixPath) -> bool:
    lower_name = relative_path.name.casefold()
    return any(lower_name.endswith(suffix) for suffix in _ARCHIVE_SUFFIXES)


def _is_known_text_candidate(relative_path: PurePosixPath) -> bool:
    if _is_excluded(relative_path):
        return False
    lower_name = relative_path.name.casefold()
    if relative_path.name in _TEXT_NAMES or relative_path.suffix.casefold() in _TEXT_SUFFIXES:
        return True
    if lower_name.startswith("dockerfile"):
        return True
    return False


def _is_legal_artifact_metadata(relative_path: PurePosixPath) -> bool:
    parts = tuple(part.casefold() for part in relative_path.parts)
    if not parts:
        return False
    name = parts[-1]
    return (
        parts[0] == "licenses"
        or name in _LEGAL_ARTIFACT_NAMES
        or name.startswith("license.")
        or name.endswith(("-license.txt", "-copying.txt", ".spdx.json"))
        or "sbom" in name
    )


def _is_first_party_artifact_path(relative_path: PurePosixPath) -> bool:
    if _is_legal_artifact_metadata(relative_path):
        return False
    parts = tuple(part.casefold() for part in relative_path.parts)
    if not parts:
        return False
    if any(parts[index : index + 2] == ("_internal", "lingshu_gate") for index in range(len(parts) - 1)):
        return True
    if parts[0] in {"config", "docs", "scripts"}:
        return True
    name = parts[-1]
    if len(parts) == 1:
        return (
            _is_known_text_candidate(relative_path)
            or name == "sha256sums"
            or name.startswith((".env", "lingshu-gate", "start."))
        )
    return len(parts) >= 3 and parts[-2] == "macos" and name.startswith("lingshu-gate")


def _common_artifact_root(paths: Sequence[PurePosixPath]) -> str | None:
    populated = [path for path in paths if path.parts]
    if not populated:
        return None
    first = populated[0].parts[0]
    if all(path.parts[0] == first for path in populated) and any(len(path.parts) > 1 for path in populated):
        return first
    return None


def _without_artifact_root(relative_path: PurePosixPath, root_name: str | None) -> PurePosixPath:
    if root_name is not None and relative_path.parts and relative_path.parts[0] == root_name:
        return PurePosixPath(*relative_path.parts[1:])
    return relative_path


def _artifact_path_rule_ids(raw_path: PurePosixPath, logical_path: PurePosixPath) -> set[str]:
    if _is_first_party_artifact_path(logical_path):
        return _matching_path_rules(logical_path.as_posix())
    return _matching_path_rules(raw_path.as_posix()) & _ARTIFACT_GLOBAL_PATH_RULE_IDS


def _decode_text(data: bytes) -> str | None:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _scan_text(text: str, location: str, *, budget: MatchBudget | None = None) -> list[Violation]:
    violations: list[Violation] = []
    active_budget = budget if budget is not None else MatchBudget()
    for line_number, line in enumerate(text.splitlines() or [""], start=1):
        violations.extend(Violation(rule_id, location, line_number) for rule_id in _matching_rules(line, active_budget))
        violations.extend(
            Violation(rule_id, location, line_number)
            for rule_id in _matching_gate_identity_rules(line)
        )
    return violations


def _scan_bytes(data: bytes, location: str, *, strict_text: bool = True) -> list[Violation]:
    size_limit = _MAX_TEXT_BYTES if strict_text else _MAX_BINARY_BYTES
    if len(data) > size_limit:
        return [Violation("FILE-001", location, 1)]
    text = _decode_text(data)
    budget = MatchBudget()
    if text is None:
        if strict_text:
            return [Violation("FILE-002", location, 1)]
        violations: list[Violation] = []
        for match in _ASCII_RUN.finditer(data):
            violations.extend(_scan_text(match.group().decode("ascii"), location, budget=budget))
        for pattern, encoding in ((_UTF16_LE_RUN, "utf-16-le"), (_UTF16_BE_RUN, "utf-16-be")):
            for match in pattern.finditer(data):
                violations.extend(_scan_text(match.group().decode(encoding), location, budget=budget))
        return violations
    return _scan_text(text, location, budget=budget)


def _safe_member_path(value: str) -> PurePosixPath | None:
    member = PurePosixPath(value.replace("\\", "/"))
    if member.is_absolute() or ".." in member.parts:
        return None
    return member


def _scan_zip_bytes(data: bytes, location: str) -> list[Violation]:
    violations: list[Violation] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            safe_paths = [_safe_member_path(member.filename) for member in members]
            root_name = _common_artifact_root([path for path in safe_paths if path is not None])
            total_size = 0
            for member, member_path in zip(members, safe_paths, strict=True):
                if member_path is None:
                    violations.append(Violation("ARCHIVE-001", location, 1))
                    continue
                member_location = f"{location}!{member_path.as_posix()}"
                logical_path = _without_artifact_root(member_path, root_name)
                violations.extend(
                    Violation(rule_id, member_location, 1)
                    for rule_id in _artifact_path_rule_ids(member_path, logical_path)
                )
                if member.is_dir():
                    continue

                total_size += member.file_size
                if member.file_size > _MAX_BINARY_BYTES or total_size > _MAX_ARCHIVE_SCAN_BYTES:
                    violations.append(Violation("ARCHIVE-002", member_location, 1))
                    continue

                if stat.S_ISLNK(member.external_attr >> 16):
                    if member.file_size > 4096:
                        violations.append(Violation("ARCHIVE-002", member_location, 1))
                        continue
                    try:
                        link_target = archive.read(member).decode("utf-8")
                    except (RuntimeError, UnicodeDecodeError, zipfile.BadZipFile, zlib.error):
                        violations.append(Violation("ARCHIVE-003", member_location, 1))
                        continue
                    if _safe_member_path(link_target) is None:
                        violations.append(Violation("ARCHIVE-001", member_location, 1))
                    continue

                if not _is_first_party_artifact_path(logical_path):
                    continue
                known_text = _is_known_text_candidate(logical_path)
                member_limit = _MAX_TEXT_BYTES if known_text else _MAX_BINARY_BYTES
                if member.file_size > member_limit:
                    violations.append(Violation("ARCHIVE-002", member_location, 1))
                    continue
                violations.extend(_scan_bytes(archive.read(member), member_location, strict_text=known_text))
    except (EOFError, OSError, RuntimeError, ValueError, zipfile.BadZipFile, zlib.error):
        violations.append(Violation("ARCHIVE-003", location, 1))
    return violations


def _scan_tar_bytes(data: bytes, location: str) -> list[Violation]:
    violations: list[Violation] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            members = archive.getmembers()
            safe_paths = [_safe_member_path(member.name) for member in members]
            root_name = _common_artifact_root([path for path in safe_paths if path is not None])
            total_size = 0
            for member, member_path in zip(members, safe_paths, strict=True):
                if member_path is None:
                    violations.append(Violation("ARCHIVE-001", location, 1))
                    continue
                member_location = f"{location}!{member_path.as_posix()}"
                logical_path = _without_artifact_root(member_path, root_name)
                violations.extend(
                    Violation(rule_id, member_location, 1)
                    for rule_id in _artifact_path_rule_ids(member_path, logical_path)
                )
                if member.issym() or member.islnk():
                    if _safe_member_path(member.linkname) is None:
                        violations.append(Violation("ARCHIVE-001", member_location, 1))
                    continue

                if not member.isfile():
                    continue
                total_size += member.size
                if member.size > _MAX_BINARY_BYTES or total_size > _MAX_ARCHIVE_SCAN_BYTES:
                    violations.append(Violation("ARCHIVE-002", member_location, 1))
                    continue
                if not _is_first_party_artifact_path(logical_path):
                    continue
                known_text = _is_known_text_candidate(logical_path)
                member_limit = _MAX_TEXT_BYTES if known_text else _MAX_BINARY_BYTES
                if member.size > member_limit:
                    violations.append(Violation("ARCHIVE-002", member_location, 1))
                    continue
                source = archive.extractfile(member)
                if source is None:
                    violations.append(Violation("ARCHIVE-003", member_location, 1))
                    continue
                violations.extend(_scan_bytes(source.read(), member_location, strict_text=known_text))
    except (EOFError, OSError, ValueError, tarfile.TarError):
        violations.append(Violation("ARCHIVE-003", location, 1))
    return violations


def _scan_archive_bytes(data: bytes, relative_path: PurePosixPath, location: str) -> list[Violation]:
    lower_name = relative_path.name.casefold()
    if lower_name.endswith((".zip", ".whl")):
        return _scan_zip_bytes(data, location)
    return _scan_tar_bytes(data, location)


def _iter_worktree_files(root: Path) -> Iterator[tuple[Path, PurePosixPath]]:
    for current_root, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(current_root)
        directory_names[:] = sorted(name for name in directory_names if name not in _EXCLUDED_DIRS)
        if current == root:
            directory_names[:] = [name for name in directory_names if name.casefold() not in _GENERATED_ROOT_DIRS]
        for file_name in sorted(file_names):
            absolute = current / file_name
            relative = PurePosixPath(absolute.relative_to(root).as_posix())
            if not _is_excluded(relative):
                yield absolute, relative


def _scan_worktree(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for absolute, relative in _iter_worktree_files(root):
        location = relative.as_posix()
        violations.extend(Violation(rule_id, location, 1) for rule_id in _matching_path_rules(location))
        if absolute.is_symlink():
            try:
                target = os.readlink(absolute)
            except OSError:
                violations.append(Violation("FILE-003", location, 1))
                continue
            violations.extend(_scan_text(target, location))
            continue
        if _is_third_party_source_path(relative):
            continue
        try:
            data = absolute.read_bytes()
        except OSError:
            violations.append(Violation("FILE-003", location, 1))
            continue
        if _is_archive(relative):
            violations.extend(_scan_archive_bytes(data, relative, location))
        else:
            violations.extend(
                _scan_bytes(
                    data,
                    location,
                    strict_text=_is_known_text_candidate(relative),
                )
            )
    return violations


def _artifact_location(repository_root: Path, absolute: Path) -> str:
    try:
        return absolute.relative_to(repository_root).as_posix()
    except ValueError:
        return absolute.name


def _iter_artifact_files(root: Path) -> Iterator[tuple[Path, PurePosixPath]]:
    for current_root, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(current_root)
        linked_directories = sorted(name for name in directory_names if (current / name).is_symlink())
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in linked_directories
            and name not in _EXCLUDED_DIRS
            and name.casefold() not in _INTERMEDIATE_DIRS
        )
        for directory_name in linked_directories:
            absolute = current / directory_name
            relative = PurePosixPath(absolute.relative_to(root).as_posix())
            yield absolute, relative
        for file_name in sorted(file_names):
            absolute = current / file_name
            relative = PurePosixPath(absolute.relative_to(root).as_posix())
            if not _is_excluded(relative):
                yield absolute, relative


def _scan_artifact_file(
    repository_root: Path,
    absolute: Path,
    relative_path: PurePosixPath,
    logical_path: PurePosixPath,
) -> list[Violation]:
    location = _artifact_location(repository_root, absolute)
    violations = [Violation(rule_id, location, 1) for rule_id in _artifact_path_rule_ids(relative_path, logical_path)]
    if absolute.is_symlink():
        return [*violations, Violation("ARTIFACT-002", location, 1)]
    try:
        size = absolute.stat().st_size
    except OSError:
        return [*violations, Violation("FILE-003", location, 1)]
    if size > _MAX_BINARY_BYTES:
        return [*violations, Violation("FILE-001", location, 1)]
    if not (_is_archive(relative_path) or _is_first_party_artifact_path(logical_path)):
        return violations
    try:
        data = absolute.read_bytes()
    except OSError:
        return [*violations, Violation("FILE-003", location, 1)]
    if _is_archive(relative_path):
        violations.extend(_scan_archive_bytes(data, relative_path, location))
    else:
        violations.extend(_scan_bytes(data, location, strict_text=_is_known_text_candidate(logical_path)))
    return violations


def _scan_artifacts(repository_root: Path, artifact_paths: Sequence[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for configured_path in artifact_paths:
        absolute = configured_path if configured_path.is_absolute() else repository_root / configured_path
        absolute = Path(os.path.abspath(absolute))
        location = _artifact_location(repository_root, absolute)
        if absolute.is_symlink():
            violations.append(Violation("ARTIFACT-002", location, 1))
            continue
        if not absolute.exists():
            violations.append(Violation("ARTIFACT-001", location, 1))
            continue
        if absolute.is_file():
            relative = PurePosixPath(absolute.name)
            violations.extend(_scan_artifact_file(repository_root, absolute, relative, relative))
            continue
        if not absolute.is_dir():
            violations.append(Violation("ARTIFACT-001", location, 1))
            continue

        files = list(_iter_artifact_files(absolute))
        root_name = _common_artifact_root([relative for _, relative in files])
        for file_path, relative in files:
            logical = _without_artifact_root(relative, root_name)
            violations.extend(_scan_artifact_file(repository_root, file_path, relative, logical))
    return violations


def _run_git(
    root: Path, arguments: Sequence[str], *, text: bool = False
) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=text,
    )


def _scan_history(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    shallow = _run_git(root, ["rev-parse", "--is-shallow-repository"], text=True)
    if shallow.returncode != 0:
        return [Violation("HISTORY-001", ".git", 1)]
    if shallow.stdout.strip() == "true":
        return [Violation("HISTORY-002", ".git", 1)]

    log_result = _run_git(root, ["log", "--all", "--format=%H%x00%B%x00"])
    if log_result.returncode != 0:
        return [Violation("HISTORY-001", ".git", 1)]
    log_fields = log_result.stdout.split(b"\x00")
    for offset in range(0, len(log_fields) - 1, 2):
        commit = log_fields[offset].decode("ascii", errors="replace").strip()
        body = _decode_text(log_fields[offset + 1]) or ""
        violations.extend(_scan_text(body, f"git:{commit[:12]}"))

    commit_result = _run_git(root, ["rev-list", "--all"], text=True)
    if commit_result.returncode != 0:
        return [*violations, Violation("HISTORY-001", ".git", 1)]

    seen_items: set[tuple[str, str]] = set()
    blob_cache: dict[str, bytes | None] = {}
    for commit in (line.strip() for line in commit_result.stdout.splitlines() if line.strip()):
        tree_result = _run_git(root, ["ls-tree", "-r", "-z", "--full-tree", commit])
        if tree_result.returncode != 0:
            violations.append(Violation("HISTORY-003", f"git:{commit[:12]}", 1))
            continue
        for entry in tree_result.stdout.split(b"\x00"):
            if not entry or b"\t" not in entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            fields = metadata.split()
            if len(fields) != 3 or fields[1] != b"blob":
                continue
            blob = fields[2].decode("ascii", errors="replace")
            path = raw_path.decode("utf-8", errors="replace")
            item = (blob, path)
            if item in seen_items:
                continue
            seen_items.add(item)
            relative = PurePosixPath(path)
            if (
                _is_excluded(relative)
                or _is_third_party_source_path(relative)
            ):
                continue
            location = f"git:{commit[:12]}:{path}"
            violations.extend(Violation(rule_id, location, 1) for rule_id in _matching_path_rules(path))
            if blob not in blob_cache:
                blob_result = _run_git(root, ["cat-file", "blob", blob])
                blob_cache[blob] = blob_result.stdout if blob_result.returncode == 0 else None
            data = blob_cache[blob]
            if data is None:
                violations.append(Violation("HISTORY-003", location, 1))
            elif _is_archive(relative):
                violations.extend(_scan_archive_bytes(data, relative, location))
            else:
                violations.extend(
                    _scan_bytes(
                        data,
                        location,
                        strict_text=_is_known_text_candidate(relative),
                    )
                )
    return violations


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _static_string_prefix(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return None


def _python_gate_contracts(path: Path, relative: PurePosixPath) -> list[Violation]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative.as_posix())
    except (OSError, SyntaxError, UnicodeError):
        return [Violation("GATE-009", relative.as_posix(), 1)]

    violations: list[Violation] = []
    database_names: list[tuple[str, int]] = []
    cookie_default: tuple[str, int] | None = None
    file_reference_prefix: tuple[str, int] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for match in re.finditer(r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_-]+\.db)(?![A-Za-z0-9_.-])", node.value):
                database_names.append((match.group(1), getattr(node, "lineno", 1)))

        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "auth_session_cookie_name":
                value = _static_string_prefix(node.value) if node.value is not None else None
                if value is not None:
                    cookie_default = (value, getattr(node, "lineno", 1))

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "file_ref":
                    prefix = _static_string_prefix(value)
                    if prefix is not None:
                        file_reference_prefix = (prefix, getattr(node, "lineno", 1))
                if not isinstance(target, ast.Name) or not target.id.endswith(("_TOOL_ID", "_TOOL_NAME")):
                    continue
                tool_id = _static_string_prefix(value)
                if tool_id is not None and not tool_id.startswith("gate_"):
                    violations.append(
                        Violation("GATE-006", relative.as_posix(), getattr(node, "lineno", 1))
                    )

        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        event_nodes: list[ast.AST] = []
        if name == "log_event" and len(node.args) >= 3:
            event_nodes.append(node.args[2])
        if name == "emit_event" and node.args:
            event_nodes.append(node.args[0])
        event_nodes.extend(keyword.value for keyword in node.keywords if keyword.arg == "event_type")
        for event_node in event_nodes:
            event_prefix = _static_string_prefix(event_node)
            if event_prefix is not None and _EVENT_NAME.match(event_prefix) and not event_prefix.startswith("gate."):
                violations.append(
                    Violation("GATE-005", relative.as_posix(), getattr(event_node, "lineno", 1))
                )

        if name == "_definition" and node.args:
            tool_id = _static_string_prefix(node.args[0])
            if tool_id is not None and not tool_id.startswith("gate_"):
                violations.append(
                    Violation("GATE-006", relative.as_posix(), getattr(node.args[0], "lineno", 1))
                )
        if name == "ToolDefinition":
            for keyword in node.keywords:
                if keyword.arg != "id":
                    continue
                tool_id = _static_string_prefix(keyword.value)
                if tool_id is not None and not tool_id.startswith("gate_"):
                    violations.append(
                        Violation(
                            "GATE-006",
                            relative.as_posix(),
                            getattr(keyword.value, "lineno", 1),
                        )
                    )

    if relative.as_posix() == "src/lingshu_gate/config.py":
        if cookie_default is None or cookie_default[0] != "lingshu_gate_session":
            violations.append(
                Violation("GATE-007", relative.as_posix(), cookie_default[1] if cookie_default else 1)
            )
        if not any(name == "gate.db" for name, _ in database_names):
            violations.append(Violation("GATE-008", relative.as_posix(), 1))
    if relative.as_posix() == "src/lingshu_gate/tool_files.py":
        if file_reference_prefix is None or file_reference_prefix[0] != "gate_file_":
            violations.append(
                Violation(
                    "GATE-011",
                    relative.as_posix(),
                    file_reference_prefix[1] if file_reference_prefix else 1,
                )
            )
    for database_name, line in database_names:
        if database_name != "gate.db":
            violations.append(Violation("GATE-008", relative.as_posix(), line))
    return violations


def _check_gate_contracts(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    pyproject = root / "pyproject.toml"
    try:
        document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeError):
        document = {}
        violations.append(Violation("GATE-001", "pyproject.toml", 1))
    project = document.get("project") if isinstance(document, dict) else None
    scripts = project.get("scripts") if isinstance(project, dict) else None
    if not isinstance(project, dict) or project.get("name") != "lingshu-gate":
        violations.append(Violation("GATE-001", "pyproject.toml", 1))
    if not isinstance(scripts, dict) or scripts.get("lingshu-gate") != "lingshu_gate.cli:main":
        violations.append(Violation("GATE-002", "pyproject.toml", 1))

    source_root = root / "src"
    package_root = source_root / "lingshu_gate"
    if not package_root.is_dir():
        violations.append(Violation("GATE-010", "src/lingshu_gate", 1))
    if source_root.is_dir():
        for child in source_root.iterdir():
            if child.name == "lingshu_gate" or child.name.casefold().endswith(".egg-info"):
                continue
            violations.append(Violation("GATE-010", child.relative_to(root).as_posix(), 1))

    if package_root.is_dir():
        for path in sorted(package_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = PurePosixPath(path.relative_to(root).as_posix())
            violations.extend(_python_gate_contracts(path, relative))
    return violations


def _check_skill_inventory(root: Path) -> list[Violation]:
    found = sorted(relative for _, relative in _iter_worktree_files(root) if relative.name == "SKILL.md")
    if len(found) != 1:
        return [Violation("SKILL-001", ".agents/skills", 1)]
    if found[0] != _ALLOWED_SKILL:
        return [Violation("SKILL-002", found[0].as_posix(), 1)]
    return []


def audit_repository(
    root: Path,
    *,
    include_history: bool = False,
    artifact_paths: Sequence[Path] = (),
) -> list[Violation]:
    resolved_root = root.resolve()
    violations = [
        *_scan_worktree(resolved_root),
        *_check_skill_inventory(resolved_root),
        *_check_gate_contracts(resolved_root),
    ]
    violations.extend(_scan_artifacts(resolved_root, artifact_paths))
    if include_history:
        violations.extend(_scan_history(resolved_root))
    return sorted(set(violations))


def format_violation(violation: Violation) -> str:
    return f"{violation.rule_id} {violation.location}:{violation.line}"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate repository identity policy.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root. Defaults to the root containing this script.",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Also inspect all reachable commit messages, paths, and text blobs.",
    )
    parser.add_argument(
        "--artifacts",
        action="append",
        default=[],
        type=Path,
        help="Inspect a final release asset or directory. Repeat for multiple paths.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    violations = audit_repository(
        arguments.root,
        include_history=arguments.history,
        artifact_paths=arguments.artifacts,
    )
    if violations:
        for violation in violations:
            print(format_violation(violation))
        return 1
    print("repository identity check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
