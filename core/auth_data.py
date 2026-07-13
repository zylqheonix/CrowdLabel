"""Role-based routing for the app."""

# Where each role lands after a successful login. Reading the role and routing
# on it (rather than branching on username) is the piece we kept when real
# Django auth replaced the old hardcoded user list.
ROLE_REDIRECTS = {
    "worker": "worker_dashboard",
    "admin": "dashboard",
    "customer": "customer_dashboard",
}

# Roles that self-registration may assign (admin is seeded only).
REGISTERABLE_ROLES = frozenset({"worker", "customer"})
