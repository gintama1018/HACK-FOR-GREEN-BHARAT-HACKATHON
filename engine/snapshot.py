"""
InfraWatch Nexus — Atomic Snapshot Writer
==========================================
Writes dashboard state as atomic JSONL using temp-file + os.replace().
"""

import json
import os
import tempfile


def write_atomic_snapshot(snapshot, output_dir):
    """Write dashboard snapshot atomically (temp file + rename)."""
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
        # Fallback: direct write
        try:
            with open(dashboard_path, "w") as f:
                f.write(json.dumps(snapshot) + "\n")
        except Exception:
            pass


def read_dashboard_snapshot(output_dir):
    """Read last complete line from Pathway's atomic dashboard.jsonl."""
    filepath = os.path.join(output_dir, "dashboard.jsonl")
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
        if not lines:
            return None
        for line in reversed(lines):
            line = line.strip()
            if line:
                return json.loads(line)
        return None
    except Exception:
        return None
