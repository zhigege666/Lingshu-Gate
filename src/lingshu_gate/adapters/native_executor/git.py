"""HTTPS smart Git acquisition; pack parsing occurs only in the offline sandbox."""
from __future__ import annotations

import io
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from lingshu_gate.adapters.native_executor.controller import PodmanController, reject
from lingshu_gate.adapters.native_executor.https import PROXY_SCHEMES, PinnedHTTPS
from lingshu_gate.git_source import COMMIT_RE
from lingshu_gate.ports.git_acquisition import GitObject
from lingshu_gate.ports.safe_network_executor import ExecutorReadiness


def packet(data: bytes) -> bytes:
    return f"{len(data) + 4:04x}".encode() + data


def packets(data: bytes) -> Iterator[bytes]:
    offset = 0
    while offset < len(data):
        if len(data) - offset < 4 or not re.fullmatch(rb"[0-9a-fA-F]{4}", data[offset:offset + 4]):
            reject("git_protocol_rejected", "Git response contains an invalid packet header")
        length = int(data[offset:offset + 4], 16)
        offset += 4
        if length == 0:
            yield b""
        elif not 4 <= length <= 65520 or offset + length - 4 > len(data):
            reject("git_protocol_rejected", "Git response packet exceeds its framing bounds")
        else:
            yield data[offset:offset + length - 4]
            offset += length - 4


class FrozenObjects:
    object_format = "sha1"

    def __init__(self, root: Path, commit: str) -> None:
        self.root, self.commit_sha = root, commit
        # The isolated trusted decoder writes only validated object IDs/kinds.
        listing = root.parent / "objects.list"
        if listing.is_symlink() or listing.stat().st_size > 1024 * 1024:
            reject("git_object_list_rejected", "Frozen object listing exceeded its bound")
        self.entries: dict[str, tuple[str, int]] = {}
        total = 0
        for line in listing.read_text().splitlines():
            oid, kind, raw_size = line.split(" ")
            size = int(raw_size)
            total += size
            if not COMMIT_RE.fullmatch(oid) or kind not in {"blob", "tree", "commit", "tag"} or size < 0 or oid in self.entries or len(self.entries) >= 10000 or total > 216 * 1024 * 1024:
                reject("git_object_list_rejected", "Frozen object listing is invalid")
            self.entries[oid] = (kind, size)

    @contextmanager
    def open_object(self, oid: str) -> Iterator[GitObject]:
        if not COMMIT_RE.fullmatch(oid) or oid not in self.entries:
            reject("git_object_missing", "Verified commit references unavailable content")
        path = self.root / oid
        kind, size = self.entries[oid]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            reject("git_object_rejected", "Frozen Git object changed or has an invalid type")
        with path.open("rb") as stream:
            yield GitObject(kind, size, stream)


class HTTPSGitBackend:
    proxy_schemes = PROXY_SCHEMES

    def __init__(self, controller: PodmanController, https: PinnedHTTPS, *, closed: threading.Event | None = None) -> None:
        self.controller, self.https = controller, https
        self.closed = closed or threading.Event()

    def readiness(self) -> ExecutorReadiness:
        self.controller.require_ready()
        return self.controller.evidence

    def _advertisement(self, request: dict[str, Any], material: dict[str, Any], deadline: float) -> dict[str, str]:
        url = request["source"]["repository_url"].rstrip("/") + "/info/refs?service=git-upload-pack"
        _, content = self.https.request(url, rule=request["host_rule"], material=material, deadline=deadline, maximum=1024 * 1024, credential=material.get("git_credential"), headers={"Accept": "application/x-git-upload-pack-advertisement"}, cancelled=self.closed.is_set)
        rows = list(packets(content))
        if rows[:2] != [b"# service=git-upload-pack\n", b""]:
            reject("git_protocol_unsupported", "Only bounded smart HTTPS Git protocol v0/v1 is supported")
        refs: dict[str, str] = {}
        for row in rows[2:]:
            if not row:
                continue
            line = row.split(b"\0", 1)[0].rstrip(b"\n")
            try:
                sha, name = line.decode("ascii").split(" ", 1)
            except ValueError:
                reject("git_protocol_rejected", "Git advertisement has malformed refs")
            if not COMMIT_RE.fullmatch(sha) or name in refs or len(refs) >= 10000:
                reject("git_protocol_rejected", "Git advertisement has duplicate or unsupported refs")
            refs[name] = sha
        return refs

    def resolve_commit(self, request: dict[str, Any], *, material: dict[str, Any], timeout_seconds: int) -> str:
        self.controller.require_ready()
        source = request["source"]
        refs = self._advertisement(request, material, time.monotonic() + timeout_seconds)
        if source["ref_type"] == "commit":
            # Reachability/existence is checked by the exact fetch and verified
            # commit object. Never substitute a matching branch/tag.
            return str(source["ref"])
        name = ("refs/heads/" if source["ref_type"] == "branch" else "refs/tags/") + source["ref"]
        sha = refs.get(name + "^{}", refs.get(name)) if source["ref_type"] == "tag" else refs.get(name)
        if not sha:
            reject("git_ref_not_found", "The exact Git ref is absent or ambiguous")
        return str(sha)

    @contextmanager
    def fetch_exact(self, request: dict[str, Any], *, material: dict[str, Any], cancel: threading.Event, deadline: float) -> Iterator[FrozenObjects]:
        identity = request.get("execution", {})
        import_id = str(identity.get("import_id") or uuid4().hex)
        assert self.controller.journal is not None
        with self.controller.journal.trusted_phase("git:" + import_id + ":acquire", request, "git_acquisition"):
            with self._fetch_exact(request, material=material, cancel=cancel, deadline=deadline) as objects:
                yield objects

    @contextmanager
    def _fetch_exact(self, request: dict[str, Any], *, material: dict[str, Any], cancel: threading.Event, deadline: float) -> Iterator[FrozenObjects]:
        self.controller.require_ready()
        commit = request["commit_sha"]
        if not COMMIT_RE.fullmatch(commit):
            reject("git_commit_mismatch", "Exact acquisition requires a full confirmed SHA")
        body = packet(f"want {commit} multi_ack_detailed side-band-64k ofs-delta\n".encode()) + packet(b"deepen 1\n") + b"0000" + packet(b"done\n")
        url = request["source"]["repository_url"].rstrip("/") + "/git-upload-pack"
        result: dict[str, Any] | None = None
        staging = self.controller.root / ("fetch-" + uuid4().hex)
        staging.mkdir(mode=0o700)
        try:
            _, response = self.https.request(url, rule=request["host_rule"], material=material, deadline=deadline, maximum=request["limits"]["transfer_bytes"], method="POST", body=body, credential=material.get("git_credential"), headers={"Content-Type": "application/x-git-upload-pack-request", "Accept": "application/x-git-upload-pack-result"}, cancelled=cancel.is_set)
            pack = io.BytesIO()
            for row in packets(response):
                if row.startswith(b"\x01"):
                    pack.write(row[1:])
                elif row and not (row.startswith((b"NAK", b"ACK ", b"shallow ", b"unshallow ", b"\x02"))):
                    reject("git_protocol_rejected", "Git pack stream contains an unsupported or error packet")
            content = pack.getvalue()
            if not content.startswith(b"PACK") or len(content) > request["limits"]["transfer_bytes"]:
                reject("git_pack_rejected", "Git acquisition did not return a bounded pack")
            (staging / "pack.bin").write_bytes(content)
            identity = request.get("execution", {})
            key = "git:" + str(identity.get("import_id") or uuid4().hex)
            result = self.controller.run(key, {"kind": "git", "commit_sha": commit, "binding": identity}, mounts={"/pack": staging}, timeout=max(1, min(120, int(deadline - time.monotonic()))), cancelled=cancel.is_set)
            if result["returncode"] or result.get("commit_sha") != commit or result.get("object_format") != "sha1":
                reject("git_pack_rejected", "Isolated Git decoding rejected the confirmed source")
            yield FrozenObjects(result["output"] / "objects", commit)
        finally:
            import shutil
            shutil.rmtree(staging)
            if result:
                self.controller.release_output(result)
