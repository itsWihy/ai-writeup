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

"""Cleanup module for the backup skill.

Manages local archive retention. Removes archives older than the
configured retention period to prevent disk space exhaustion.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

ARCHIVE_SUFFIX = ".tar.gz"
# Timestamp format used by archiver.py: backup_20261115_143022.tar.gz
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
TIMESTAMP_PREFIX = "backup_"


def parse_archive_timestamp(archive_path: Path) -> datetime | None:
    """Extract the creation timestamp from an archive filename.

    Expected format: backup_YYYYMMDD_HHMMSS.tar.gz
    Returns None if the filename doesn't match the expected pattern.
    """
    name = archive_path.name
    if not name.startswith(TIMESTAMP_PREFIX) or not name.endswith(ARCHIVE_SUFFIX):
        return None

    timestamp_str = name[len(TIMESTAMP_PREFIX):-len(ARCHIVE_SUFFIX)]
    try:
        return datetime.strptime(timestamp_str, TIMESTAMP_FORMAT)
    except ValueError:
        logger.warning("Could not parse timestamp from: %s", name)
        return None


def find_expired_archives(
    archive_dir: Path,
    retention_days: int,
) -> list[Path]:
    """Find archives older than the retention period.

    Scans the archive directory for .tar.gz files with parseable
    timestamps and returns those older than retention_days.
    """
    if not archive_dir.is_dir():
        logger.warning("Archive directory does not exist: %s", archive_dir)
        return []

    cutoff = datetime.now() - timedelta(days=retention_days)
    expired = []

    for path in sorted(archive_dir.glob(f"{TIMESTAMP_PREFIX}*{ARCHIVE_SUFFIX}")):
        ts = parse_archive_timestamp(path)
        if ts is not None and ts < cutoff:
            expired.append(path)

    return expired


def cleanup_archives(
    archive_dir: Path,
    retention_days: int,
    min_keep: int = 1,
    dry_run: bool = False,
) -> list[Path]:
    """Remove expired archives, keeping at least min_keep recent ones.

    Always keeps the most recent min_keep archives regardless of age,
    so there's always at least one backup available.

    If dry_run is True, logs what would be removed but doesn't
    actually delete anything.

    Returns the list of archives that were (or would be) removed.
    """
    if retention_days < 1:
        logger.error("retention_days must be at least 1, got %d", retention_days)
        return []

    all_archives = sorted(
        archive_dir.glob(f"{TIMESTAMP_PREFIX}*{ARCHIVE_SUFFIX}"),
        key=lambda p: p.name,
    )

    if len(all_archives) <= min_keep:
        logger.info(
            "Only %d archive(s) present, keeping all (min_keep=%d)",
            len(all_archives),
            min_keep,
        )
        return []

    # Protect the most recent min_keep archives
    protected = set(all_archives[-min_keep:])
    expired = find_expired_archives(archive_dir, retention_days)

    to_remove = [a for a in expired if a not in protected]

    if not to_remove:
        logger.info("No expired archives to clean up")
        return []

    for archive in to_remove:
        if dry_run:
            logger.info("[dry-run] Would remove: %s", archive.name)
        else:
            try:
                archive.unlink()
                logger.info("Removed expired archive: %s", archive.name)
            except OSError as exc:
                logger.error("Failed to remove %s: %s", archive.name, exc)

    action = "Would remove" if dry_run else "Removed"
    logger.info("%s %d expired archive(s)", action, len(to_remove))

    return to_remove
