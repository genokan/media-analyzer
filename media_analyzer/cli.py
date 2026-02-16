"""CLI entry point for media_analyzer."""

import argparse
import sys

from media_analyzer.config import generate_secret_token, load_config, save_config, validate_config


def main():
    parser = argparse.ArgumentParser(
        prog="media_analyzer",
        description="Media Analyzer - scan and browse media file metadata",
    )
    parser.add_argument(
        "command",
        choices=["serve"],
        help="Command to execute",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Override bind host",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override bind port",
    )

    args = parser.parse_args()

    from pathlib import Path

    from media_analyzer.config import _find_config_path

    config_path = Path(args.config) if args.config else _find_config_path()
    config = load_config(config_path)
    config["_config_path"] = str(config_path)

    # Auto-generate Flask secret key on first run
    if not config.get("_flask_secret"):
        config["_flask_secret"] = generate_secret_token()
        save_config(config, config_path)

    # Apply CLI overrides
    if args.host:
        config["server"]["host"] = args.host
    if args.port:
        config["server"]["port"] = args.port

    # Validate and warn
    warnings = validate_config(config)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if args.command == "serve":
        from media_analyzer.server.app import create_app

        app = create_app(config)
        print(
            f"Starting Media Analyzer on http://{config['server']['host']}:{config['server']['port']}"
        )
        app.run(
            host=config["server"]["host"],
            port=config["server"]["port"],
            debug=False,
        )
