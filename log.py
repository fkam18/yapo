#!/usr/bin/env python3
"""
Central logging module for Yapo.
Thread‑safe writes with file locking, destructive reads, and size‑based auto‑truncation.
"""

import os, fcntl, time

LOG_FILE = '/tmp/yapo.log'
LOCK_FILE = '/tmp/yapo.log.lock'
MAX_SIZE = 1_000_000  # 1 MB
LOCK_TIMEOUT = 1.0    # seconds

# Track approximate byte count (updated after each write)
_log_size = 0


def _acquire_lock():
    """Acquire exclusive lock on the lock file. Returns file handle or None on timeout."""
    lf = open(LOCK_FILE, 'w')
    deadline = time.time() + LOCK_TIMEOUT
    while True:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lf
        except BlockingIOError:
            if time.time() > deadline:
                lf.close()
                return None
            time.sleep(0.01)


def _release_lock(lf):
    fcntl.flock(lf, fcntl.LOCK_UN)
    lf.close()


def log_write(line: str):
    """
    Append a line to the log file. Thread/process‑safe via file lock.
    Automatically truncates the file if it exceeds MAX_SIZE.
    """
    global _log_size

    lf = _acquire_lock()
    if lf is None:
        return  # timeout — drop the line silently

    try:
        # Truncate if too large
        if _log_size > MAX_SIZE and os.path.exists(LOG_FILE):
            os.truncate(LOG_FILE, 0)
            _log_size = 0

        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
        _log_size += len(line) + 1
    finally:
        _release_lock(lf)


def log_read(max_lines: int = 100) -> str:
    """
    Destructive read: returns the last `max_lines` lines from the log file
    and truncates it. Not locked — best‑effort read.
    """
    global _log_size

    if not os.path.exists(LOG_FILE):
        return ''

    try:
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()
    except:
        return ''

    # Keep only last N lines for the response
    recent = lines[-max_lines:] if len(lines) > max_lines else lines

    # Truncate
    try:
        with open(LOG_FILE, 'w') as f:
            pass
    except:
        pass
    _log_size = 0

    return ''.join(recent)

def redirect_stderr(prefix: str = "yapo"):
    """Replace sys.stderr with a handler that writes each line to the log."""
    import sys
    from datetime import datetime

    class _LogStderr:
        def __init__(self):
            self.buffer = ''
        def write(self, data):
            self.buffer += data
            while '\n' in self.buffer:
                line, self.buffer = self.buffer.split('\n', 1)
                if line.strip():
                    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    log_write(f"{prefix} {ts}: {line}")
        def flush(self):
            if self.buffer.strip():
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                log_write(f"{prefix} {ts}: {self.buffer}")
                self.buffer = ''

    sys.stderr = _LogStderr()
