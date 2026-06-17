"""Role-based routing for the app."""

# Where each role lands after a successful login. Reading the role and routing
# on it (rather than branching on username) is the piece we kept when real
# Django auth replaced the old hardcoded user list.
ROLE_REDIRECTS = {
    "worker": "tasks",
    "admin": "dashboard",
}
