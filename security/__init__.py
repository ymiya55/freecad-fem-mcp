"""Security policy primitives shared by the local tools and adversarial tests.

The helpers in :mod:`security.policy` deliberately implement a small, strict
allow-list.  They do not make a network service or a file API safe by
themselves; callers must use them at the boundary where untrusted values enter
the application.
"""

from .policy import (
    DuplicateKeyError,
    NDJSONError,
    PathPolicyError,
    SecurityPolicyError,
    is_loopback_host,
    parse_ndjson,
    safe_join,
)

__all__ = [
    "DuplicateKeyError",
    "NDJSONError",
    "PathPolicyError",
    "SecurityPolicyError",
    "is_loopback_host",
    "parse_ndjson",
    "safe_join",
]
