"""Session and optional API key middleware for Flask."""

from flask import jsonify, request, session


def init_auth(app, config):
    """Set up Flask secret key and register auth middleware."""
    app.secret_key = config.get("_flask_secret", "dev-secret-change-me")

    secret_token = config.get("secret_token")
    if not secret_token:
        return  # No API key configured — all requests pass through

    @app.before_request
    def check_api_key():
        # Skip auth for static files and the root page
        if request.path.startswith("/static"):
            return None

        # Check session first (browser users who already authenticated)
        if session.get("authenticated"):
            return None

        # Check API key header
        provided = request.headers.get("X-API-Key")
        if provided == secret_token:
            session["authenticated"] = True
            return None

        # Check query param (for initial browser access)
        provided = request.args.get("token")
        if provided == secret_token:
            session["authenticated"] = True
            return None

        return jsonify({"error": "Unauthorized. Provide X-API-Key header or ?token= param."}), 401


def save_ui_state(key: str, value):
    """Save UI state to session."""
    if "ui_state" not in session:
        session["ui_state"] = {}
    session["ui_state"][key] = value
    session.modified = True


def get_ui_state(key: str, default=None):
    """Get UI state from session."""
    return session.get("ui_state", {}).get(key, default)
