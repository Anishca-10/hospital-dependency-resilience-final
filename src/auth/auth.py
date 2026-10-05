"""Simple local role-based access control (demo accounts; prototype-grade, not enterprise auth)."""
from functools import wraps

from flask import jsonify, redirect, request, session, url_for

OPERATIONS_MANAGER = "operations_manager"
CLINICAL_STAFF = "clinical_staff"
ADMIN = "admin"

_MANAGER = {
    "dashboard", "partner_status", "partner_health", "dependency_map", "simulate", "config_read", "config_write",
    "experiments_view", "experiments_run", "logs", "metrics", "validation_view", "validation_submit",
    "reports", "baseline_mode",
}
_CLINICAL = {
    "patients", "appointments", "partner_ops", "partner_status", "validation_submit",
}
ROLE_PERMISSIONS = {
    OPERATIONS_MANAGER: frozenset(_MANAGER),
    CLINICAL_STAFF: frozenset(_CLINICAL),
    ADMIN: frozenset(_MANAGER | _CLINICAL),
}

ROLE_LABELS = {OPERATIONS_MANAGER: "Operations Manager", CLINICAL_STAFF: "Clinical Staff", ADMIN: "Administrator"}

# which UI pages each role sees (server still enforces permissions on every API call)
PAGES = [
    ("dashboard", "Dashboard", "dashboard"),
    ("patients", "Patient Workflow", "patients"),
    ("health", "Partner Health", "partner_health"),
    ("depmap", "Dependency Map", "dependency_map"),
    ("simulation", "Failure Simulation", "simulate"),
    ("experiments", "Experiments", "experiments_view"),
    ("logs", "Logs", "logs"),
    ("config", "Configuration", "config_read"),
    ("validation", "User Validation", "validation_submit"),
    ("reports", "Reports & Docs", "reports"),
]


def current_user():
    return session.get("user")


def has_permission(user, perm):
    return bool(user) and perm in ROLE_PERMISSIONS.get(user["role"], ())


def pages_for(user):
    out = []
    for key, label, perm in PAGES:
        if has_permission(user, perm):
            out.append({"key": key, "label": label})
    return out


def _deny(status, message):
    if request.path.startswith("/api/"):
        return jsonify({"error": message}), status
    if status == 401:
        return redirect(url_for("login"))
    return message, status


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user():
            return _deny(401, "Authentication required")
        return fn(*a, **kw)
    return wrapper


def permission_required(*perms):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            user = current_user()
            if not user:
                return _deny(401, "Authentication required")
            if not any(has_permission(user, p) for p in perms):
                return _deny(403, "Your role is not permitted to perform this action")
            return fn(*a, **kw)
        return wrapper
    return deco
