"""Bounded local configuration and explicit trust for standalone services."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml


class ServiceConfigError(ValueError):
    def __init__(self, code: str, location: str = ""):
        self.code, self.location = code, location
        super().__init__(code)

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "location": self.location}


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def bounded(value: Any, *, max_nodes: int = 10000, max_depth: int = 32) -> None:
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise ServiceConfigError("document_complexity_limit")
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ServiceConfigError("document_keys_must_be_strings")
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)
        elif item is not None and type(item) not in {str, int, float, bool}:
            raise ServiceConfigError("document_value_unsupported")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ServiceConfigError("document_nonfinite_number")


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ServiceConfigError("document_duplicate_key")
        result[key] = value
    return result


class UniqueSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ServiceConfigError("document_alias_unsupported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        pairs = []
        for key, value in node.value:
            item = self.construct_object(key, deep=deep)
            if not isinstance(item, str):
                raise ServiceConfigError("document_keys_must_be_strings")
            pairs.append((item, self.construct_object(value, deep=deep)))
        return unique_pairs(pairs)


def parse_document(data: bytes, *, yaml_allowed: bool = True, limit: int = 2 * 1024 * 1024) -> dict[str, Any]:
    if len(data) > limit:
        raise ServiceConfigError("document_size_limit")
    try:
        decoded = data.decode("utf-8-sig")
        if not yaml_allowed or decoded.lstrip().startswith(("{", "[")):
            value = json.loads(decoded, object_pairs_hook=unique_pairs)
        else:
            value = yaml.load(decoded, Loader=UniqueSafeLoader)
        bounded(value)
        if not isinstance(value, dict):
            raise ServiceConfigError("document_object_required")
        return value
    except ServiceConfigError:
        raise
    except (ValueError, UnicodeError, RecursionError, yaml.YAMLError, TypeError):
        raise ServiceConfigError("document_invalid") from None


def load_document(path: Path, *, yaml_allowed: bool = True) -> dict[str, Any]:
    try:
        with path.open("rb") as source:
            return parse_document(source.read(2 * 1024 * 1024 + 1), yaml_allowed=yaml_allowed)
    except OSError:
        raise ServiceConfigError("document_file_unavailable") from None


def loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def fixed_url(value: str, *, private_http: bool = False, websocket: bool = False) -> str:
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        secure, plain = ("wss", "ws") if websocket else ("https", "http")
        if not host or parsed.scheme not in {secure, plain} or parsed.username is not None or parsed.password is not None:
            raise ValueError
        if parsed.query or parsed.fragment or any(ord(c) < 33 for c in value) or "\\" in value or "%" in parsed.netloc:
            raise ValueError
        if parsed.scheme == plain and not loopback(host):
            address = ipaddress.ip_address(host)
            if not private_http or not address.is_private or address.is_unspecified or address.is_link_local:
                raise ValueError
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        if any(segment in {".", ".."} for segment in parsed.path.split("/")) or "%" in parsed.path or "//" in parsed.path:
            raise ValueError
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))
    except (ValueError, TypeError, AttributeError):
        raise ServiceConfigError("endpoint_invalid_or_untrusted") from None


def secret_file(path: Path) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                raise ServiceConfigError("credential_file_invalid")
            if os.name == "posix" and (info.st_mode & 0o077 or info.st_uid != os.geteuid()):
                raise ServiceConfigError("credential_file_permissions")
            if os.name == "nt":
                # Refuse a plaintext file when its ACL has not been verified by this helper.
                _windows_acl(path, verify=True)
            value = source.read(4097).decode("utf-8").strip()
        if not value or len(value) > 4096 or not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ServiceConfigError("credential_file_invalid")
        return value
    except (OSError, UnicodeError):
        raise ServiceConfigError("credential_file_unavailable") from None


def _windows_acl(path: Path, *, verify: bool = False) -> None:
    # The path is data in the environment, never interpolated into PowerShell code.
    script = "$ErrorActionPreference='Stop';try{$p=$env:LINGSHU_GATE_PRIVATE_FILE;$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User;"
    if not verify:
        script += "$a=New-Object System.Security.AccessControl.FileSecurity;$a.SetOwner($sid);$a.SetAccessRuleProtection($true,$false);$r=New-Object System.Security.AccessControl.FileSystemAccessRule($sid,'FullControl','Allow');$a.SetAccessRule($r);Set-Acl -LiteralPath $p -AclObject $a"
        script += ";"
    script += "$a=Get-Acl -LiteralPath $p;if(-not $a.AreAccessRulesProtected -or $a.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $sid.Value){exit 2};$found=$false;foreach($r in $a.Access){if($r.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -ne $sid.Value -or $r.AccessControlType -ne 'Allow'){exit 3};$found=$true};if(-not $found){exit 4}}catch{exit 5}"
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                       env={**os.environ, "LINGSHU_GATE_PRIVATE_FILE": str(path)},
                       check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        raise ServiceConfigError("private_file_acl_unavailable") from None


def private_write(path: Path, data: bytes, *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not replace and os.path.lexists(path):
        raise ServiceConfigError("destination_exists")
    fd, name = tempfile.mkstemp(prefix=".gate-", dir=path.parent)
    temporary = Path(name)
    try:
        if os.name == "nt":
            _windows_acl(temporary)
        with os.fdopen(fd, "wb") as target:
            fd = -1
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Exclusive creation, so a concurrent command cannot replace another backup.
            os.link(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        temporary.unlink(missing_ok=True)
