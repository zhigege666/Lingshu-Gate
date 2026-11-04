"""Manage verified native Gate releases from the installation owner's account."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from extract_native import extract_bundle

REPOSITORY = "zhigege666/Lingshu-Gate"
TARGETS = {"linux-x86_64", "linux-aarch64", "macos-x86_64", "macos-arm64", "windows-x86_64"}


def version(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){2}", value):
        raise ValueError("Invalid stable release version")
    return tuple(map(int, value.split(".")))


def metadata(bundle: Path) -> tuple[str, str]:
    info = json.loads((bundle / "BUILD-INFO.json").read_text(encoding="utf-8"))
    if info["application"] != "Lingshu Gate" or info["target"] not in TARGETS:
        raise ValueError("Invalid Gate native package metadata")
    version(info["version"])
    return info["version"], info["target"]


def github(*args: str) -> str:
    # Select the official host even when gh is configured for another installation.
    # Resolve from PATH only. Windows executable search would otherwise also
    # consider the current directory.
    cli = shutil.which("gh", path=os.environ.get("PATH", ""))
    if cli is None:
        raise FileNotFoundError("GitHub CLI (gh) is required to verify native releases")
    return subprocess.run(
        [cli, *args], check=True, stdout=subprocess.PIPE, text=True, timeout=600,
        env={**os.environ, "GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1"},
    ).stdout


@contextmanager
def update_lock(path: Path) -> Iterator[None]:
    # OS locks are released even if the updater exits unexpectedly.
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def executable(bundle: Path, target: str) -> Path:
    return bundle / ("lingshu-gate.exe" if target.startswith("windows-") else "lingshu-gate")


def selected(base: Path, cache: Path, current: str, target: str, original: str) -> Path:
    version(current)
    bundle = base if current == original else cache / f"lingshu-gate-v{current}-{target}"
    if metadata(bundle) != (current, target):
        raise ValueError("Selected package metadata does not match this installation")
    return bundle


def install(base: Path, cache: Path, state: dict[str, str], target: str, original: str) -> str:
    current = state["active"]
    selected(base, cache, current, target, original)
    release: dict[str, Any] = json.loads(github("api", f"repos/{REPOSITORY}/releases/latest"))
    tag = release["tag_name"]
    if release["draft"] or release["prerelease"] or not tag.startswith("v"):
        raise ValueError("Expected a published stable Gate release")
    proposed = tag[1:]
    # Scheduled starts must respect an operator's rollback until a newer
    # release appears.
    if version(proposed) <= max(version(current), version(state.get("skipped", current))):
        return current
    root = f"lingshu-gate-{tag}-{target}"
    name = root + (".zip" if target.startswith("windows-") else ".tar.gz")
    assets = [asset for asset in release["assets"] if asset["name"] == name]
    if len(assets) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", assets[0].get("digest") or ""):
        raise ValueError("GitHub release is missing a unique native asset with a SHA-256 digest")
    if not 0 < assets[0]["size"] <= 1024**3:
        raise ValueError("Native asset size is outside supported limits")
    with tempfile.TemporaryDirectory(prefix="stage-", dir=cache) as temporary:
        work = Path(temporary)
        github("release", "download", tag, "--repo", REPOSITORY, "--pattern", name, "--dir", str(work))
        archive = work / name
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if archive.stat().st_size != assets[0]["size"] or "sha256:" + digest.hexdigest() != assets[0]["digest"]:
            raise ValueError("Native asset digest or size mismatch")
        ref = f"refs/tags/{tag}"
        github("attestation", "verify", str(archive), "--repo", REPOSITORY, "--source-ref", ref,
               "--cert-identity", f"https://github.com/{REPOSITORY}/.github/workflows/release.yml@{ref}",
               "--deny-self-hosted-runners")
        candidate = extract_bundle(target, proposed, archive, work / "unpacked")
        if metadata(candidate) != (proposed, target):
            raise ValueError("Downloaded package metadata mismatch")
        output = subprocess.run([str(executable(candidate, target)), "--version"], cwd=candidate,
                                check=True, capture_output=True, text=True, timeout=30)
        if output.stdout.strip() != f"lingshu-gate {proposed}":
            raise ValueError("Candidate did not report the expected Gate version")
        destination = cache / root
        if destination.exists():
            # Reinstall after rollback always selects freshly authenticated bytes.
            destination.rename(work / "retired")
        candidate.rename(destination)
        activate(cache, {"active": proposed, "previous": current})
    return proposed


def activate(cache: Path, state: dict[str, str]) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=cache, encoding="utf-8", delete=False) as stream:
        json.dump(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(stream.name, cache / "active.json")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["update", "start", "update-start", "rollback"])
    parser.add_argument("--install-dir", type=Path, default=Path(sys.executable).resolve().parent)
    separator = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:separator])
    server_args = argv[separator + 1:]
    if server_args and args.action not in {"start", "update-start"}:
        parser.error("Gate arguments require start or update-start")
    base = args.install_dir.resolve()
    original, target = metadata(base)
    cache = base / ".native-updates"
    cache.mkdir(mode=0o700, exist_ok=True)
    with update_lock(cache / "update.lock"):
        marker = cache / "active.json"
        state = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {"active": original}
        current = state["active"]
        if args.action in {"update", "update-start"}:
            current = install(base, cache, state, target, original)
        elif args.action == "rollback":
            if "previous" not in state:
                raise ValueError("No previous native release is recorded")
            current = state["previous"]
            selected(base, cache, current, target, original)
            activate(cache, {"active": current, "skipped": state["active"]})
        bundle = selected(base, cache, current, target, original)
    print(f"Lingshu Gate {current} ({target})", flush=True)
    if args.action in {"start", "update-start"}:
        for key, value in {"DATA_DIR": base / "data", "CONFIG_DIR": base / "config" / "mcp.d",
                           "ALLOWED_ROOT": base / "workspace"}.items():
            os.environ.setdefault("LINGSHU_GATE_" + key, str(value))
            Path(os.environ["LINGSHU_GATE_" + key]).mkdir(parents=True, exist_ok=True)
        for key, default in {"HOST": "127.0.0.1", "PORT": "8000", "RUNTIME_ROLE": "local"}.items():
            os.environ.setdefault("LINGSHU_GATE_" + key, default)
        program = str(executable(bundle, target))
        # A Windows process cannot exec in place. Wait so supervisors and CLI
        # callers observe the selected process's lifetime and exit status.
        if os.name == "nt":
            raise SystemExit(subprocess.call([program, *server_args]))
        os.execv(program, [program, *server_args])


def run(argv: list[str]) -> None:
    # Restore the loader search path before spawning gh or another bundle.
    # These settings affect only this dedicated updater process, never Core.
    if getattr(sys, "frozen", False):
        if os.name == "nt":
            import ctypes

            if not ctypes.windll.kernel32.SetDllDirectoryW(None):
                raise OSError("Could not reset DLL search path for native update")
        elif "LD_LIBRARY_PATH_ORIG" in os.environ:
            os.environ["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH_ORIG"]
        else:
            os.environ.pop("LD_LIBRARY_PATH", None)
        os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        main(argv)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f"Native update failed: {error}")
