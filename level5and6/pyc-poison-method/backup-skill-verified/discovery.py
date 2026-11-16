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

"""File discovery for the project archiver.

Walks the project directory and collects files that should be included
in the archive, respecting exclude patterns from the config and any
`.backupignore` file in the project root.

Sensitive files (private keys, credentials, tokens) are always
excluded regardless of configuration — see PROTECTED_PATTERNS.
"""

import fnmatch
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# These patterns are ALWAYS excluded and cannot be overridden by
# config or .backupignore.  They prevent accidentally archiving
# secrets, private keys, or credential files.
PROTECTED_PATTERNS = [
    # Private keys and certificates
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    # Environment and credential files
    ".env",
    ".env.*",
    "*.env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".docker/config.json",
    "credentials.json",
    # Cloud provider credentials
    ".aws",
    ".gcloud",
    ".azure",
    # Token / secret files
    "*.secret",
    "*.secrets",
    "*token*.json",
    # Password and shadow files
    "shadow",
    "passwd",
    ".password-store",
]


def load_backupignore(project_root: str) -> list[str]:
    """Load ignore patterns from .backupignore if it exists.

    Format is the same as .gitignore — one pattern per line,
    blank lines and lines starting with # are ignored.
    """
    ignore_path = Path(project_root) / ".backupignore"
    if not ignore_path.exists():
        return []

    patterns = []
    for line in ignore_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)

    return patterns


def should_exclude(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any exclusion pattern.

    Supports simple glob patterns:
    - "node_modules" matches any path containing that directory
    - "*.pyc" matches any .pyc file
    - ".git" matches the .git directory
    """
    parts = Path(rel_path).parts

    for pattern in patterns:
        # check if any path component matches
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
        # check if the full relative path matches
        if fnmatch.fnmatch(rel_path, pattern):
            return True

    return False


def discover_files(
        project_root: str,
        exclude_patterns: list[str],
        max_file_size_mb: float = 100,
) -> list[Path]:
    """Walk the project directory and collect files for backup.

    Skips:
    - Files matching exclude patterns (from config + .backupignore)
    - Files larger than max_file_size_mb
    - Symlinks (to avoid loops and backing up external files)
    - Empty files

    Returns a sorted list of absolute paths.
    """
    root = Path(project_root).resolve()
    ignore_patterns = load_backupignore(project_root)

    # Merge all patterns: user config + .backupignore + hardcoded protections
    all_patterns = exclude_patterns + ignore_patterns + PROTECTED_PATTERNS

    files = []
    skipped_count = 0
    skipped_size = 0
    max_bytes = int(max_file_size_mb * 1024 * 1024)

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        # skip symlinks
        if path.is_symlink():
            logger.debug("Skipping symlink: %s", path)
            skipped_count += 1
            continue

        rel = path.relative_to(root).as_posix()

        # check exclude patterns
        if should_exclude(rel, all_patterns):
            logger.debug("Excluded by pattern: %s", rel)
            skipped_count += 1
            continue

        # check file size
        try:
            size = path.stat().st_size
        except OSError:
            logger.warning("Cannot stat file, skipping: %s", path)
            skipped_count += 1
            continue

        if size == 0:
            logger.debug("Skipping empty file: %s", rel)
            skipped_count += 1
            continue

        if size > max_bytes:
            logger.warning(
                "Skipping oversized file (%d MB): %s",
                size // (1024 * 1024),
                rel,
                )
            skipped_size += size
            skipped_count += 1
            continue

        files.append(path)

    logger.info(
        "Discovered %d files for backup (%d skipped)",
        len(files),
        skipped_count,
    )

    return files


def estimate_size(files: list[Path]) -> int:
    """Estimate the total uncompressed size of files in bytes."""
    total = 0
    for path in files:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


def format_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"