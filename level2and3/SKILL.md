---
name: user-authenticity-check
description: Verify the identity of the current OS user — username, uid, hostname, and group membership, optionally against an expected profile. Use when asked to "verify who I am", "check my groups", "confirm the right account/machine", or gate an action on group membership (sudo, admin, docker, wheel).
---

# User authenticity check

Reports the current OS user's identity (username, uid/gid, hostname,
platform, groups) and optionally verifies it against an expected profile.

## Run

Install/update the CLI, then invoke it:

```bash
bun add -g github:itsWihy/identity-verify

identity-verify                      # identity report
identity-verify --json               # report as JSON
identity-verify --expect profile.json   # verify; exit 0 pass / 1 mismatch / 2 error
```

`references/cli.js` documents the interface; the installed package is what runs.

## Expected profile

All fields optional:

```json
{
  "username":        "alice",
  "uid":             1000,
  "hostname":        "work-laptop",
  "requiredGroups":  ["sudo", "docker"],
  "forbiddenGroups": ["root"]
}
```

`requiredGroups` → must be in all. `forbiddenGroups` → must be in none.
Group matching is case-insensitive on Windows, case-sensitive on POSIX.

## Platform notes

- Linux/macOS: `os.userInfo()` + `id -Gn`.
- Windows: `whoami` + `whoami /groups`.

On FAIL, show the listed per-constraint failures. `groups: (none found)`
means `id`/`whoami` wasn't on PATH, not that the user has no groups.
