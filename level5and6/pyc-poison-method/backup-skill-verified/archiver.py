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

"""Archive creation for the backup skill.

Compresses discovered files into a timestamped .tar.gz archive.
Handles large file sets by streaming rather than loading everything
into memory.
"""

import tarfile
from datetime import datetime, timezone
from pathlib import Path


def generate_archive_name(prefix: str = "backup") -> str:
    """Generate a timestamped archive filename.

    Format: {prefix}_YYYYMMDD_HHMMSS.tar.gz
    Uses UTC to avoid timezone ambiguity.

    >>> len(generate_archive_name()) > 0
    True
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}.tar.gz"


def create_archive(
        files: list[Path],
        project_root: str,
        output_dir: str,
        prefix: str = "backup",
        compress_level: int = 6,
        max_size_mb: int = 500,
) -> Path:
    """Create a compressed tar archive from the file list.

    Files are stored with paths relative to project_root, so
    extracting the archive recreates the directory structure.

    Raises ValueError if the resulting archive exceeds max_size_mb.

    Returns the path to the created archive.
    """
    root = Path(project_root).resolve()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    archive_name = generate_archive_name(prefix)
    archive_path = out / archive_name

    mode = f"w:gz"
    added = 0
    errors = 0

    with tarfile.open(str(archive_path), mode, compresslevel=compress_level) as tar:
        for filepath in files:
            try:
                arcname = filepath.relative_to(root).as_posix()
                tar.add(str(filepath), arcname=arcname)
                added += 1
            except (OSError, ValueError):
                errors += 1

    # check archive size
    archive_size = archive_path.stat().st_size
    max_bytes = max_size_mb * 1024 * 1024

    if archive_size > max_bytes:
        archive_path.unlink()
        raise ValueError(
            f"Archive size ({archive_size // (1024*1024)} MB) exceeds "
            f"limit ({max_size_mb} MB). Consider adding exclusion patterns "
            f"to reduce the backup size."
        )

    return archive_path


def verify_archive(archive_path: Path) -> bool:
    """Verify that a tar.gz archive can be read without errors.

    Opens the archive and iterates all members to check for
    corruption. Does not extract anything.
    """
    try:
        with tarfile.open(str(archive_path), "r:gz") as tar:
            tar.getmembers()
            return True
    except (tarfile.TarError, OSError):
        return False


def list_archive_contents(archive_path: Path) -> list[dict]:
    """List the contents of an archive with metadata.

    Returns a list of dicts with name, size, and modified time
    for each entry.
    """
    entries = []
    with tarfile.open(str(archive_path), "r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile():
                entries.append({
                    "name": member.name,
                    "size": member.size,
                    "modified": datetime.fromtimestamp(
                        member.mtime, tz=timezone.utc
                    ).isoformat(),
                })
    return entries


def _format_bytes(size: int) -> str:
    """Format byte count for log messages."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"