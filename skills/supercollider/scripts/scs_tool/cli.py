"""JSON transport for the render coordinator."""

import json
import sys
import os
import signal

from .render import execute


def main():
    cancelled = [None]
    previous = {}

    def on_signal(signum, frame):
        if cancelled[0] is None:
            cancelled[0] = signum

    mask = os.umask(0o077)
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, on_signal)
        result = execute(sys.argv[1:], lambda: cancelled[0])
        try:
            print(
                json.dumps(
                    result, separators=(",", ":"), ensure_ascii=False, allow_nan=False
                ),
                flush=True,
            )
        except (BrokenPipeError, OSError):
            sys.stderr.write("Cannot write JSON result to stdout\n")
            return 20
        return result["exit_code"]
    finally:
        os.umask(mask)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
