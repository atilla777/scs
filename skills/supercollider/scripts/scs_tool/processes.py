"""Linux child ownership, bounded logs and deadlines."""

import ctypes
import os
import selectors
import signal
import subprocess
import time
from pathlib import Path

LOG_LIMIT = 16 * 1024 * 1024


class CleanupError(RuntimeError):
    pass


def proc_info(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        fields = text[text.rindex(")") + 2 :].split()
        return int(fields[1]), int(fields[19])
    except (FileNotFoundError, ProcessLookupError):
        return None


def children(pid):
    try:
        return [
            int(x) for x in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        ]
    except (FileNotFoundError, ProcessLookupError):
        return []


class ProcessOwner:
    def __init__(self):
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), "Cannot become child subreaper")
        self.owned = {}
        self.baseline = set(children(os.getpid()))
        self.evidence = []
        self.cleanup_deadline = None

    def capture(self, pid, expected_parent=None):
        if pid in self.owned or pid in self.baseline:
            return
        before = proc_info(pid)
        if before is None or (
            expected_parent is not None and before[0] != expected_parent
        ):
            return
        try:
            fd = os.pidfd_open(pid)
        except ProcessLookupError:
            return
        after = proc_info(pid)
        if after != before:
            os.close(fd)
            return
        self.owned[pid] = (fd, before[1])

    def discover(self):
        # An orphan can leave its session; subreaper adoption preserves ownership.
        for pid in children(os.getpid()):
            self.capture(pid, os.getpid())
        pending = list(self.owned)
        seen = set()
        while pending:
            pid = pending.pop()
            if pid in seen:
                continue
            seen.add(pid)
            info = proc_info(pid)
            if info is None or info[1] != self.owned[pid][1]:
                continue
            for child in children(pid):
                self.capture(child, pid)
                if child in self.owned:
                    pending.append(child)

    def remaining(self):
        self.discover()
        return [
            pid
            for pid, (_, start) in self.owned.items()
            if (info := proc_info(pid)) is not None and info[1] == start
        ]

    def cleanup(self):
        self.discover()
        if self.cleanup_deadline is None and self.remaining():
            self.cleanup_deadline = time.monotonic() + 5
        end = self.cleanup_deadline or time.monotonic()
        term_until = time.monotonic() + 0.25
        while True:
            self.discover()
            sig = signal.SIGTERM if time.monotonic() < term_until else signal.SIGKILL
            for pid, (fd, _) in list(self.owned.items()):
                try:
                    signal.pidfd_send_signal(fd, sig)
                except ProcessLookupError:
                    pass
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    pass
            alive = self.remaining()
            for pid in list(self.owned):
                if pid not in alive:
                    os.close(self.owned.pop(pid)[0])
            if not alive:
                return
            if time.monotonic() >= end:
                raise CleanupError("Unreaped owned PIDs: " + repr(alive))
            time.sleep(0.01)

    def run(self, argv, directory, stage, deadline, env=None, checkpoint=lambda: None):
        checkpoint()
        if time.monotonic() >= deadline:
            raise TimeoutError("Deadline exceeded before " + stage)
        # Existing unrelated children may have been created since owner setup.
        self.baseline.update(
            pid for pid in children(os.getpid()) if pid not in self.owned
        )
        record = dict(
            stage=stage,
            argv=list(map(str, argv)),
            returncode=None,
            stdout=str(directory / (stage + ".stdout.log")),
            stderr=str(directory / (stage + ".stderr.log")),
        )
        self.evidence.append(record)
        with selectors.DefaultSelector() as selector:
            logs = []
            process = None
            try:
                for key in ["stdout", "stderr"]:
                    fd = os.open(
                        record[key], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                    )
                    logs.append(os.fdopen(fd, "wb"))
                process = subprocess.Popen(
                    list(map(str, argv)),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    env=env,
                    cwd=directory,
                )
                self.capture(process.pid, os.getpid())
                record["pid"] = process.pid
                for pipe, log in zip([process.stdout, process.stderr], logs):
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, [log, 0])
                while selector.get_map() or process.poll() is None:
                    self.discover()
                    checkpoint()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Deadline exceeded during " + stage)
                    for key, _ in selector.select(0.02):
                        block = os.read(key.fd, 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        log, count = key.data
                        if count + len(block) > LOG_LIMIT:
                            raise OverflowError("Log limit exceeded during " + stage)
                        log.write(block)
                        key.data[1] += len(block)
                record["returncode"] = process.wait()
            finally:
                try:
                    self.cleanup()
                finally:
                    if process is not None:
                        process.poll()
                        process.stdout.close()
                        process.stderr.close()
                    for log in logs:
                        log.close()
        return record
