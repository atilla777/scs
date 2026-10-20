"""Owned files and no-replace publication."""

import os
import json
import shutil
import tempfile
from pathlib import Path


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        stream.write(text)


def write_json(path, value):
    write_text(
        path,
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        + "\n",
    )


def private_directory(base, prefix):
    path = Path(tempfile.mkdtemp(dir=base, prefix=prefix))
    os.chmod(path, 0o700)
    return path


def child_environment(work):
    env = {"PATH": "/usr/bin:/bin", "QT_QPA_PLATFORM": "offscreen", "LANG": "C.UTF-8"}
    for name, suffix in [
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("TMPDIR", "tmp"),
        ("XDG_RUNTIME_DIR", "runtime"),
    ]:
        path = work / suffix
        path.mkdir(mode=0o700)
        env[name] = str(path)
    return env


def finalize_run(work, stage_dir, keep_partial):
    """Only exact directories created by the coordinator enter here."""
    failures = []
    for path in [work] + ([] if keep_partial else [stage_dir]):
        if path is None:
            continue
        try:
            shutil.rmtree(path)
        except OSError as exc:
            failures.append(
                {
                    "path": str(path),
                    "action": "remove_owned_directory",
                    "error": str(exc),
                }
            )
    return failures


def publish_no_replace(staging, output, parent_fd=None):
    output = Path(output)
    close = parent_fd is None
    if close:
        parent_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.link(staging, output.name, dst_dir_fd=parent_fd, follow_symlinks=False)
    finally:
        if close:
            os.close(parent_fd)
