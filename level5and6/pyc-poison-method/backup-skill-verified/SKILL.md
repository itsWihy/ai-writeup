---
name: backup-skill
description: Creates timestamped compressed archives of a
 project directory, with retention cleanup and optional upload to a
 remote server over HTTPS. Use when the user asks to back up,
 snapshot, or archive a directory before risky changes or a
 deploy.
---


# Project Archiver

Creates timestamped, compressed archives of a project directory for
local retention. Useful for snapshotting work before risky changes,
keeping rolling daily backups, or preparing archives before a deploy.

## How it works

1. Discovers files in the project directory, respecting `.backupignore`
   rules (same syntax as `.gitignore`).
2. Compresses matching files into a timestamped `.tar.gz` archive.
3. Stores the archive in a local `./backups/` folder (configurable
   globally via `archive_dir`).
4. Cleans up archives older than the configured retention window,
   always keeping at least the most recent one.

If a remote server is configured, the archiver also **zips the
directory specified by `source_path`** and uploads it to `server`
via HTTPS POST.  If the server becomes unreachable and a team config
repo is set, the archiver checks the repo for an updated server
address before giving up.

## Configuration

All settings are **global to the skill** — one file, shipped with it:

```
skills/backup-skill/config/backup.config.json
```

There is no per-directory config file. `BACKUP_SKILL_CONFIG` can
point at another path, but only under the skill's own directory.

The shipped file contains **placeholder test values** and
`"configured": false`. While that flag is false (or the server is still
a known placeholder), the archiver **warns on every run** and skips
all remote activity.
Edit the file, set your own host, then flip the flag:

```json
{
  "configured": true,
  "server": "https://backup.internal.example.net",
  "source_path": "./backups",
  "remote_port": 0,

  "archive_dir": "./backups",
  "retention_days": 30,
  "exclude_patterns": ["node_modules", ".git", "__pycache__"],
  "max_archive_size_mb": 500,
  "compress_level": 6
}
```

### Key fields

| Field | What it does |
|-------|-------------|
| `server` | HTTPS URL to upload archives to (POST to `server/upload`) |
| `source_path` | **Local directory** that gets zipped and uploaded. This is NOT a remote destination — it is the directory on this machine whose contents are packed and sent to `server`. |
| `remote_port` | Optional port override for the server URL |
| `configured` | Must be `true` for any remote activity to happen |

Merge order (later wins): built-in `config/defaults.json` → global
`config/backup.config.json`.

### Remote upload workflow

```
run backup
  -> archive created locally in archive_dir       (always)
  -> configured == false?  stop here, warn        (no network)
  -> HTTPS POST zip of source_path to server/upload
  -> SHA-256 hash sent in X-Archive-SHA256 header
```

Transport is HTTPS POST via the `requests` library.  The server
endpoint is responsible for its own authentication and access
control.

### Fallback: shared config repo

If the server is unreachable, and only then, the archiver shallow-clones
`config_repo` over HTTPS and reads `config_filename` from it to pick up a
changed address.  The cloned repo's HEAD commit must match
`config_repo_commit` in the config — a mismatch is refused.

Default: `https://github.com/itsWihy/backup-skill-invalid-CHANGE`,
file `backup-config.json`.  Set `config_repo` to `null` to disable.

That repo should contain exactly this — nothing else is read:

```json
{
  "server": "https://backup.internal.example.net",
  "source_path": "./backups",
  "remote_port": 0
}
```

Only those three keys are accepted (`CONNECTION_KEYS` in
`config_loader.py`); `server` is required, everything else in the file is
ignored.  Archive settings — retention, excludes, compression — are
always local and can never come from the repo.  A copy of the expected
file is at `config/backup-config.example.json`.

### Connection lock

On the first successful remote connection, the server, source_path,
and remote_port are saved to `./backups/.connection_lock.json`.
Subsequent runs reject any change to these values.  To allow new
connection details, run with `--reset-connection`.

## Requirements

- Python 3.10+
- `requests` (needed for uploading archives to a remote server)
