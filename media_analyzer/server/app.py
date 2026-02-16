"""Flask app factory."""

from flask import Flask

from media_analyzer.auth import init_auth
from media_analyzer.db import Database
from media_analyzer.server.api import api_bp


def create_app(config: dict) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
    )

    # Store config and db on app
    app.config["MEDIA_ANALYZER"] = config
    app.config["MEDIA_ANALYZER_CONFIG_PATH"] = config.get("_config_path")
    app.config["DB"] = Database(config["db_path"])

    # Auth middleware
    init_auth(app, config)

    # Register API blueprint
    app.register_blueprint(api_bp)

    # Root route serves the dashboard
    @app.route("/")
    def index():
        from flask import render_template

        return render_template("index.html")

    @app.route("/videos")
    def videos():
        from flask import render_template

        return render_template("videos.html")

    @app.route("/vr")
    def vr():
        from flask import render_template

        return render_template("vr.html")

    @app.route("/audio")
    def audio():
        from flask import render_template

        return render_template("audio.html")

    @app.route("/settings")
    def settings():
        from flask import render_template

        return render_template("settings.html")

    return app
