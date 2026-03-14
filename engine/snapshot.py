"""
InfraWatch Nexus — Atomic Snapshot Writer
==========================================
Writes dashboard state as atomic JSONL using temp-file + os.replace().
Reads only the last line efficiently using file.seek().
"""

import json
import os
import tempfile


def write_atomic_snapshot(snapshot, output_dir):
    """
    Write dashboard snapshot atomically (temp file + rename).
    Always writes a single line — overwrites the previous snapshot.
    This prevents the file growing unbounded with each recompute.
    """
    dashboard_path = os.path.join(output_dir, "dashboard.jsonl")
    try:
        fd, tmp_path = tempfile.mkstemp(dir=output_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as tmp:
                tmp.write(json.dumps(snapshot) + "\n")
                tmp.flush()
        except Exception:
            os.close(fd)
            raise
        os.replace(tmp_path, dashboard_path)
    except Exception as e:
        print(f"  [Snapshot] Write error: {e}")
        # Fallback: direct write (single line)
        try:
            with open(dashboard_path, "w") as f:
                f.write(json.dumps(snapshot) + "\n")
        except Exception:
            pass


def read_dashboard_snapshot(output_dir):
    """
    Read latest snapshot from dashboard.jsonl.
    Uses file.seek() to read only the last line — avoids loading entire file
    into memory even if file grew due to a previous bug.
    """
    filepath = os.path.join(output_dir, "dashboard.jsonl")
    if not os.path.exists(filepath):
        return None
    try:
        size = os.path.getsize(filepath)
        if size == 0:
            return None
        with open(filepath, "rb") as f:
            # Seek from end, read up to 8KB to find last line
            read_size = min(size, 8192)
            f.seek(-read_size, 2)
            chunk = f.read().decode("utf-8", errors="replace")
        # Take the last non-empty line
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception:
        return None
