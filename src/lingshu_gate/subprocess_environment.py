"""Minimal environment construction for untrusted managed child processes."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

_INHERITED_NAMES = {
    "APPDATA",
    "COMSPEC",
    "DOCKER_CERT_PATH",
    "DOCKER_CONFIG",
    "DOCKER_HOST",
    "DOCKER_TLS_VERIFY",
    "HOME",
    "LANG",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "WINDIR",
    "XDG_RUNTIME_DIR",
}

_DOCKER_CHILD_ENV_EXACT_DENYLIST = {
    "ALL_PROXY",
    "BASH_ENV",
    "BUILDKIT_HOST",
    "BUILDKIT_PROGRESS",
    "CONTAINER_HOST",
    "ENV",
    "HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "IFS",
    "NODE_OPTIONS",
    "NO_PROXY",
    "PATH",
    "PATHEXT",
    "PERL5OPT",
    "RUBYOPT",
    "SHELL",
    "SSH_AUTH_SOCK",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "XDG_CONFIG_HOME",
    "XDG_RUNTIME_DIR",
}
_DOCKER_CHILD_ENV_PREFIX_DENYLIST = (
    "BUILDX_",
    "DOCKER_",
    "DYLD_",
    "LD_",
    "LINGSHU_GATE_",
    "PYTHON",
)


def build_subprocess_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Inherit only OS/toolchain essentials, never the control-plane environment."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if key in _INHERITED_NAMES or key.startswith("LC_")
    }
    if extra:
        environment.update({str(key): str(value) for key, value in extra.items()})
    return environment


def build_docker_subprocess_environment(
    child_environment: Mapping[str, str],
) -> dict[str, str]:
    """Build the Docker CLI environment without letting a Manifest steer it.

    Docker's ``-e NAME`` form reads the child value from the CLI process
    environment.  The same environment also controls which daemon, credential
    store and executable helpers the Docker CLI uses, so control variables must
    come only from the trusted Gate deployment rather than a manifest.
    """

    validate_docker_child_environment_names(child_environment)

    environment = build_subprocess_environment()
    environment.update(
        {str(name): str(value) for name, value in child_environment.items()}
    )
    return environment


def validate_docker_child_environment_names(names: Iterable[str]) -> None:
    """Reject Manifest variables that can steer Gate or its Docker CLI."""

    rejected = sorted(
        str(name)
        for name in names
        if _is_docker_process_control_name(str(name))
    )
    if rejected:
        raise ValueError(
            "managed_container environment cannot override Gate or Docker process controls: "
            + ", ".join(rejected)
        )


def _is_docker_process_control_name(name: str) -> bool:
    normalized = name.upper()
    return normalized in _DOCKER_CHILD_ENV_EXACT_DENYLIST or normalized.startswith(
        _DOCKER_CHILD_ENV_PREFIX_DENYLIST
    )
