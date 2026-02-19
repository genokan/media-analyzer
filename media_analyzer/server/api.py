"""REST API endpoints."""

import os
import threading

from flask import Blueprint, current_app, jsonify, request

from media_analyzer import __version__
from media_analyzer.jobs.phash_job import phash_progress, run_phash_job
from media_analyzer.scanner import run_scan, scan_progress

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _get_db():
    return current_app.config["DB"]


def _get_config():
    return current_app.config["MEDIA_ANALYZER"]


@api_bp.route("/files")
def list_files():
    db = _get_db()
    result = db.list_files(
        media_type=request.args.get("media_type"),
        search=request.args.get("search"),
        sort=request.args.get("sort", "filename"),
        order=request.args.get("order", "asc"),
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 50)),
        codec=request.args.get("codec"),
        resolution_min=_int_or_none(request.args.get("resolution_min")),
        resolution_label=request.args.get("resolution_label"),
        lossless=_int_or_none(request.args.get("lossless")),
    )
    return jsonify(result)


@api_bp.route("/files/<int:file_id>")
def get_file(file_id):
    db = _get_db()
    detail = db.get_file_detail(file_id)
    if not detail:
        return jsonify({"error": "File not found"}), 404
    return jsonify(detail)


@api_bp.route("/stats")
def get_stats():
    db = _get_db()
    return jsonify(db.get_scan_stats())


@api_bp.route("/scan", methods=["POST"])
def trigger_scan():
    if scan_progress.running:
        return jsonify(
            {
                "error": "Scan already in progress",
                "progress": scan_progress.to_dict(),
            }
        ), 409

    db = _get_db()
    config = _get_config()

    override_dirs = None
    body = request.get_json(silent=True)
    if body and "scan_dirs" in body:
        requested = body["scan_dirs"]
        configured = set(config.get("scan_dirs", []))
        invalid = [d for d in requested if d not in configured]
        if invalid:
            return jsonify({"error": "Directories not in config", "invalid": invalid}), 400
        override_dirs = requested

    thread = threading.Thread(target=run_scan, args=(db, config, override_dirs), daemon=True)
    thread.start()

    return jsonify({"status": "started", "message": "Scan started in background"})


@api_bp.route("/scan/status")
def scan_status():
    return jsonify(scan_progress.to_dict())


@api_bp.route("/scan/stop", methods=["POST"])
def stop_scan():
    if not scan_progress.running:
        return jsonify({"error": "No scan is running"}), 409
    scan_progress.cancel_requested = True
    return jsonify({"status": "stopping", "message": "Scan stop requested"})


@api_bp.route("/browse")
def browse_directory():
    path = request.args.get("path", "/")
    if not os.path.isabs(path):
        return jsonify({"error": "Path must be absolute"}), 400
    if not os.path.isdir(path):
        return jsonify({"error": "Path does not exist or is not a directory"}), 404
    try:
        entries = sorted(
            entry.name
            for entry in os.scandir(path)
            if entry.is_dir() and not entry.name.startswith(".")
        )
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    return jsonify({"path": path, "directories": entries})


@api_bp.route("/config", methods=["GET"])
def get_config():
    config = _get_config()
    # Don't expose secrets
    safe_config = {
        "scan_dirs": config.get("scan_dirs", []),
        "server": config.get("server", {}),
        "file_extensions": config.get("file_extensions", {}),
        "has_secret_token": bool(config.get("secret_token")),
        "hashing": config.get("hashing", {}),
    }
    return jsonify(safe_config)


@api_bp.route("/config", methods=["PUT"])
def update_config():
    from media_analyzer.config import save_config, validate_config

    config = _get_config()
    updates = request.get_json()
    if not updates:
        return jsonify({"error": "No JSON body provided"}), 400

    # Apply allowed updates
    if "scan_dirs" in updates:
        config["scan_dirs"] = updates["scan_dirs"]
    if "file_extensions" in updates:
        config["file_extensions"] = updates["file_extensions"]
    if "server" in updates:
        if "host" in updates["server"]:
            config["server"]["host"] = updates["server"]["host"]
        if "port" in updates["server"]:
            config["server"]["port"] = updates["server"]["port"]

    warnings = validate_config(config)
    config_path = current_app.config.get("MEDIA_ANALYZER_CONFIG_PATH")
    if config_path:
        from pathlib import Path

        save_config(config, Path(config_path))
    current_app.config["MEDIA_ANALYZER"] = config

    return jsonify({"status": "updated", "warnings": warnings})


@api_bp.route("/hash", methods=["POST"])
def trigger_hash():
    if phash_progress.running:
        return jsonify(
            {
                "error": "Phash job already in progress",
                "progress": phash_progress.to_dict(),
            }
        ), 409

    db = _get_db()
    config = _get_config()

    override_dirs = None
    body = request.get_json(silent=True)
    if body and "scan_dirs" in body:
        requested = body["scan_dirs"]
        configured = set(config.get("scan_dirs", []))
        invalid = [d for d in requested if d not in configured]
        if invalid:
            return jsonify({"error": "Directories not in config", "invalid": invalid}), 400
        override_dirs = requested

    thread = threading.Thread(target=run_phash_job, args=(db, config, override_dirs), daemon=True)
    thread.start()
    return jsonify({"status": "started", "message": "Phash job started in background"})


@api_bp.route("/hash/status")
def hash_status():
    return jsonify(phash_progress.to_dict())


@api_bp.route("/hash/stop", methods=["POST"])
def stop_hash():
    if not phash_progress.running:
        return jsonify({"error": "No phash job is running"}), 409
    phash_progress.cancel_requested = True
    return jsonify({"status": "stopping", "message": "Phash stop requested"})


@api_bp.route("/version")
def get_version():
    return jsonify({"version": __version__})


def _int_or_none(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
