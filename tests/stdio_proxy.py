"""Byte-for-byte protocol recorder around the real server; no domain access."""

import os
import subprocess
import sys
import threading
from pathlib import Path

workspace, transcript, *extra = sys.argv[1:]
command = [sys.executable, "-m", "font_design_mcp", "serve", "--workspace", workspace]
if extra:
    command = [sys.executable, str(Path(__file__).with_name("fault_server.py")), workspace, *extra]
child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr)


def feed():
    try:
        while data := os.read(sys.stdin.fileno(), 65536):
            child.stdin.write(data)
            child.stdin.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            child.stdin.close()
        except OSError:
            pass


threading.Thread(target=feed, daemon=True).start()
with Path(transcript).open("ab") as log:
    for line in child.stdout:
        log.write(line)
        log.flush()
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
sys.exit(child.wait())
