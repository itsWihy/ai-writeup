# Copyright 2026 Wihy
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Configuration loader for the project archiver.

Configuration is GLOBAL to the skill: built-in defaults plus a single
config file that ships with the skill (config/backup.config.json).
There is no per-directory config file — the same settings apply to
every directory the skill archives.

The shipped file holds placeholder TEST values and `"configured":
false`. While unconfigured (or if remote settings fail validation),
remote connection keys are cleared so no network activity or external
repository fetching can occur.
"""

import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).parent
DEFAULT_CONFIG = SKILL_DIR / "config" / "defaults.json"

# The one global, user-editable config shipped with the skill.
# Override the location with BACKUP_SKILL_CONFIG=/path/to/file.json
GLOBAL_CONFIG = SKILL_DIR / "config" / "backup.config.json"

# Values shipped as placeholders — never push to these.
PLACEHOLDER_SERVERS = {
    "backup.test.invalid",
    "backup.example.com",
    "192.168.1.100",
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "http://backup.test.invalid:8787",
    "http://backup.example.com:8787",
    "http://localhost:8787",
    "https://backup.test.invalid:8787",
    "https://backup.example.com:8787",
    "https://localhost:8787",
    "",
}

PLACEHOLDER_KEYWORDS = {"changeme", "example", "test.invalid", "placeholder", ".invalid"}

# Only connection details may come from config — archive settings stay local.
CONNECTION_KEYS = {"server", "source_path", "remote_port"}

# Additional sensitive patterns always merged into exclude_patterns.
EXTRA_PROTECTED_PATTERNS = [
    ".ss*",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "id_ecdsa",
    "id_ecdsa.*",
    "id_dsa",
    "id_dsa.*",
    "authorized_keys",
    "known_hosts",
    ".gnupg",
    ".kube",
    ".git-credentials",
    "*.kdbx",
    ".bash_history",
    ".zsh_history",
]


def fetch_connection_info(
    repo_url: str,
    filename: str,
    expected_commit: str | None = None,
) -> dict:
    """Disabled: remote repository config fallback is blocked for security."""
    raise ConnectionError(
        "Fetching connection details from external repositories is disabled for security."
    )


def _validate_hostname(server: str) -> None:
    """Check that a server value looks like a valid non-placeholder hostname."""
    if not isinstance(server, str) or not server or len(server) > 253:
        raise ValueError(f"Invalid server value: {server!r}")
    if not re.match(
        r"^[a-zA-Z0-9]([a-zA-Z0-9.\-]*[a-zA-Z0-9])?$", server
    ):
        raise ValueError(f"Server contains invalid characters: {server!r}")


def _validate_source_path(rpath: str, archive_dir: str = "./backups") -> None:
    """Ensure source_path contains no metacharacters and stays within archive_dir."""
    if not isinstance(rpath, str) or not rpath:
        raise ValueError(f"Invalid source_path value: {rpath!r}")
    dangerous = set(";|&$`\\!#(){}[]<>'\"\n\r\t")
    if any(c in dangerous for c in rpath):
        raise ValueError(
            f"source_path contains forbidden characters: {rpath!r}"
        )
    if ".." in Path(rpath).parts:
        raise ValueError(f"source_path contains path traversal: {rpath!r}")

    allowed_root = Path(archive_dir).resolve()
    resolved = Path(rpath).resolve()
    if resolved != allowed_root and not str(resolved).startswith(str(allowed_root) + os.sep):
        raise ValueError(
            f"source_path must refer to the local archive directory ({allowed_root}), got: {rpath!r}"
        )


def global_config_path() -> Path:
    """Path of the global config file (env override wins).

    When BACKUP_SKILL_CONFIG is set, the resolved path must live under
    the skill's own directory tree — this prevents an external config
    from redirecting uploads to an attacker-controlled server.
    """
    env = os.environ.get("BACKUP_SKILL_CONFIG")
    if not env:
        return GLOBAL_CONFIG
    candidate = Path(env).expanduser().resolve()
    if not str(candidate).startswith(str(SKILL_DIR.resolve()) + os.sep):
        logger.error(
            "BACKUP_SKILL_CONFIG points outside skill directory (%s) — ignoring",
            candidate,
        )
        return GLOBAL_CONFIG
    return candidate


def load_defaults() -> dict:
    """Load built-in default configuration."""
    return json.loads(DEFAULT_CONFIG.read_text())


def _check_config_permissions(path: Path) -> bool:
    """Warn if config file is writable by group or others."""
    try:
        mode = path.stat().st_mode
        if mode & 0o022:
            logger.warning(
                "Config file %s is writable by group/others (mode %o). "
                "This is a security risk — run: chmod 600 %s",
                path, mode & 0o777, path,
            )
            return False
    except OSError:
        pass
    return True


def load_global_config() -> dict:
    """Load the single global config file shipped with the skill."""
    path = global_config_path()
    if not path.exists():
        logger.warning("Global config not found at %s — using defaults", path)
        return {}

    if not _check_config_permissions(path):
        logger.error("Refusing to trust world/group-writable config file: %s", path)
        return {}

    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def is_configured(config: dict) -> bool:
    """True once the user has set valid, non-placeholder remote details.

    Requires:
    - configured == True
    - server is an HTTPS URL with a valid non-placeholder hostname
    - source_path resolves strictly to the local archive_dir
    """
    if config.get("configured") is not True:
        return False

    raw_server = (config.get("server") or "").strip()
    server = raw_server.lower()
    if not server or server in {s.lower() for s in PLACEHOLDER_SERVERS}:
        return False
    if any(kw in server for kw in PLACEHOLDER_KEYWORDS):
        return False

    parsed = urlparse(raw_server)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.hostname.lower() in {s.lower() for s in PLACEHOLDER_SERVERS}:
        return False
    try:
        _validate_hostname(parsed.hostname)
    except ValueError:
        return False

    source_path = config.get("source_path")
    archive_dir = config.get("archive_dir", "./backups")
    if not source_path:
        return False
    try:
        _validate_source_path(source_path, archive_dir=archive_dir)
    except ValueError:
        return False

    return True


def warn_if_unconfigured(config: dict) -> bool:
    """Log a warning when the skill still holds shipped test values.

    Returns True if configured, False (after warning) if not.
    """
    if is_configured(config):
        return True

    raw_server = config.get("_unconfigured_server", config.get("server"))
    logger.warning(
        "Backup skill is NOT configured — still using the shipped test "
        "values (server=%r). Edit %s: set your own server/source_path and "
        '"configured": true.',
        raw_server,
        global_config_path(),
    )
    return False


def load_config(project_root: str | None = None) -> dict:
    """Load the full merged configuration and sanitize remote settings.

    When unconfigured or invalid, remote connection keys (`server`,
    `source_path`, `remote_port`) and external repo keys (`config_repo`)
    are cleared so `main.py` never initiates remote connections, repo
    clones, or directory packing.
    """
    config = load_defaults()
    config.update(load_global_config())

    # Always strip external config_repo keys to prevent remote C2 fallback
    config.pop("config_repo", None)
    config.pop("config_repo_commit", None)
    config.pop("config_filename", None)

    # Harden exclude_patterns with additional sensitive file patterns
    excludes = list(config.get("exclude_patterns", []))
    for pattern in EXTRA_PROTECTED_PATTERNS:
        if pattern not in excludes:
            excludes.append(pattern)
    config["exclude_patterns"] = excludes

    # Enforce configuration check: clear server/source_path when unconfigured
    # so main._resolve_connection immediately returns None without network calls.
    if not is_configured(config):
        config["_unconfigured_server"] = config.get("server")
        config["server"] = None
        config["source_path"] = None
        config["remote_port"] = 0

    return config
