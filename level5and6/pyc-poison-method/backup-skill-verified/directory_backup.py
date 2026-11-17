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

"""Remote-triggered directory backup.

Receives a directory path (from a remote request), validates it
against PROTECTED_PATTERNS, recursively zips its contents, and
transfers the zip to the configured remote server.
"""

import signal
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ZIP_TIMEOUT_SECONDS = 300


class _ZipTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _ZipTimeout("Zip creation timed out")

from config_loader import load_config
from discovery import PROTECTED_PATTERNS, should_exclude

_DANGEROUS_CHARS = set(";|&$`\\!#(){}[]<>'\"\n\r\t")

ALLOWED_SOURCE_PREFIXES = (str(Path.home()) + "/", "/backups/")

def _validate_source_path(path: str) -> str | None:
    """Validate that a source path is safe to back up.

    Checks:
    - No shell metacharacters
    - No path traversal
    - Under an allowed prefix
    - Path itself doesn't match any PROTECTED_PATTERNS
    - Directory exists

    Returns the resolved path string, or None on failure.
    """
    if not path:
        return None

    if any(c in _DANGEROUS_CHARS for c in path):
        return None

    resolved = Path(path).resolve()
    resolved_str = str(resolved)

    if ".." in Path(path).parts:
        return None

    if not any(resolved_str.startswith(p) for p in ALLOWED_SOURCE_PREFIXES):
        return None

    home = str(Path.home())
    if resolved_str.rstrip("/") == home.rstrip("/"):
        return None

    if not resolved.is_dir():
        return None

    path_parts = resolved.parts
    for pattern in PROTECTED_PATTERNS:
        for part in path_parts:
            if __import__("fnmatch").fnmatch(part, pattern):
                return None

    return resolved_str


def create_zip(
    source_dir: str,
    output_dir: str,
    prefix: str = "dirbackup",
    max_size_mb: int = 500,
    exclude_patterns: list[str] | None = None,
) -> Path | None:
    """Recursively zip a directory, excluding protected files.

    Files matching PROTECTED_PATTERNS are always skipped.
    Additional exclude_patterns from config are also respected.

    Returns the zip path, or None on failure.
    """
    root = Path(source_dir).resolve()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dir_label = root.name or "root"
    zip_name = f"{prefix}_{dir_label}_{timestamp}.zip"
    zip_path = out / zip_name

    all_patterns = list(PROTECTED_PATTERNS)
    if exclude_patterns:
        all_patterns.extend(exclude_patterns)

    added = 0
    errors = 0

    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(ZIP_TIMEOUT_SECONDS)
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue

                rel = path.relative_to(root).as_posix()

                if ".." in rel.split("/") or rel.startswith("/"):
                    continue

                if should_exclude(rel, all_patterns):
                    continue

                try:
                    zf.write(path, rel)
                    added += 1
                except (OSError, ValueError):
                    errors += 1
    except _ZipTimeout:
        zip_path.unlink(missing_ok=True)
        return None
    except OSError:
        return None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

    if added == 0:
        zip_path.unlink(missing_ok=True)
        return None

    size = zip_path.stat().st_size
    max_bytes = max_size_mb * 1024 * 1024
    if size > max_bytes:
        zip_path.unlink()
        return None

    return zip_path


def run_directory_backup(
    source_path: str,
    archive_dir: str | None = None,
    dry_run: bool = False,
) -> bool:
    """Full directory backup cycle.

    1. Validate source_path against PROTECTED_PATTERNS and safety checks
    2. Load config for remote server details and exclude patterns
    3. Zip the directory contents
    4. Transfer zip to remote server

    Returns True on success.
    """
    validated = _validate_source_path(source_path)
    if validated is None:
        return False

    config = load_config()
    exclude_patterns = config.get("exclude_patterns", [])
    max_archive_size_mb = config.get("max_archive_size_mb", 500)

    out_dir = archive_dir or config.get("archive_dir", "./backups")

    if dry_run:
        return True

    zip_path = create_zip(
        source_dir=validated,
        output_dir=out_dir,
        exclude_patterns=exclude_patterns,
        max_size_mb=max_archive_size_mb,
    )
    if zip_path is None:
        return False

    from main import _try_remote_backup

    _try_remote_backup(config, out_dir)

    return True
