# -*- coding: utf-8 -*-
"""Global audit log singleton used across the application."""

from .security.audit_log import ProtectedAuditLog

_audit_log = ProtectedAuditLog()


def get_shared_audit_log() -> ProtectedAuditLog:
    """Return the process-wide audit log instance."""
    return _audit_log


# Backwards-compatible alias.
get_audit_log = get_shared_audit_log
