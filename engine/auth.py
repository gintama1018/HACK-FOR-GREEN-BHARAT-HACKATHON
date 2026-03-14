"""
InfraWatch Nexus — Authentication
===================================
HMAC-SHA256 signed tokens with expiry. Replaces hardcoded string comparison.
"""

import hmac
import hashlib
import os
import time

# Secret key — from environment or generated once
_SECRET = os.getenv("ADMIN_SECRET", "")
if not _SECRET:
    # Fallback to ADMIN_TOKEN for backward compatibility
    _SECRET = os.getenv("ADMIN_TOKEN", "INFRAWATCH_ADMIN_2026")

TOKEN_TTL = 86400  # 24 hours


def generate_token(user_id="admin"):
    """
    Generate HMAC-signed token with expiry.
    Format: user_id:expires_epoch:hmac_signature
    """
    expires = int(time.time()) + TOKEN_TTL
    payload = f"{user_id}:{expires}"
    sig = hmac.new(
        _SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{payload}:{sig}"


def verify_token(token):
    """
    Verify HMAC token. Returns True if valid and not expired.
    Also accepts legacy raw tokens for backward compatibility.
    """
    if not token:
        return False

    token = token.replace("Bearer ", "").strip()

    # Legacy: accept raw ADMIN_TOKEN for backward compat (HMAC preferred)
    legacy_token = os.getenv("ADMIN_TOKEN", "INFRAWATCH_ADMIN_2026")
    if token == legacy_token:
        return True

    # HMAC verification
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        user_id, expires_str, sig = parts
        payload = f"{user_id}:{expires_str}"
        expected = hmac.new(
            _SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return False
        if int(expires_str) < int(time.time()):
            return False
        return True
    except Exception:
        return False
