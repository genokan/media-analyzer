"""SQLite database layer for media file metadata."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    modified_date TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK(media_type IN ('video', 'audio', 'vr')),
    container_format TEXT,
    duration REAL,
    bitrate INTEGER,
    scan_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_metadata (
    file_id INTEGER PRIMARY KEY REFERENCES media_files(id) ON DELETE CASCADE,
    width INTEGER,
    height INTEGER,
    resolution_label TEXT,
    frame_rate REAL,
    pixel_format TEXT,
    color_space TEXT,
    video_bitrate INTEGER,
    video_codec TEXT,
    audio_codec TEXT,
    audio_bitrate INTEGER,
    bitrate_per_pixel REAL
);

CREATE TABLE IF NOT EXISTS vr_metadata (
    file_id INTEGER PRIMARY KEY REFERENCES media_files(id) ON DELETE CASCADE,
    is_vr INTEGER NOT NULL DEFAULT 0,
    vr_format TEXT,
    stereo_mode TEXT,
    projection_type TEXT,
    spherical INTEGER,
    fov TEXT,
    per_eye_width INTEGER,
    per_eye_height INTEGER,
    per_eye_bitrate INTEGER,
    metadata_completeness REAL
);

CREATE TABLE IF NOT EXISTS audio_metadata (
    file_id INTEGER PRIMARY KEY REFERENCES media_files(id) ON DELETE CASCADE,
    sample_rate INTEGER,
    bit_depth INTEGER,
    channels INTEGER,
    audio_bitrate INTEGER,
    is_lossless INTEGER DEFAULT 0,
    title TEXT,
    artist TEXT,
    album TEXT,
    genre TEXT,
    year TEXT,
    track_number TEXT
);

CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    files_scanned INTEGER DEFAULT 0,
    files_new INTEGER DEFAULT 0,
    files_updated INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_media_files_type ON media_files(media_type);
CREATE INDEX IF NOT EXISTS idx_media_files_path ON media_files(file_path);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    # --- Upsert ---

    def upsert_media_file(self, data: dict) -> int:
        """Insert or update a media file record. Returns the file id."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO media_files
                   (file_path, filename, file_size, modified_date, media_type,
                    container_format, duration, bitrate, scan_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(file_path) DO UPDATE SET
                    filename=excluded.filename,
                    file_size=excluded.file_size,
                    modified_date=excluded.modified_date,
                    media_type=excluded.media_type,
                    container_format=excluded.container_format,
                    duration=excluded.duration,
                    bitrate=excluded.bitrate,
                    scan_date=excluded.scan_date
                """,
                (
                    data["file_path"],
                    data["filename"],
                    data["file_size"],
                    data["modified_date"],
                    data["media_type"],
                    data.get("container_format"),
                    data.get("duration"),
                    data.get("bitrate"),
                    now,
                ),
            )
            file_id = cursor.lastrowid
            # If updated, lastrowid is 0; fetch actual id
            if file_id == 0:
                row = conn.execute(
                    "SELECT id FROM media_files WHERE file_path = ?",
                    (data["file_path"],),
                ).fetchone()
                file_id = row["id"]
            return file_id

    def upsert_video_metadata(self, file_id: int, data: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO video_metadata
                   (file_id, width, height, resolution_label, frame_rate,
                    pixel_format, color_space, video_bitrate, video_codec,
                    audio_codec, audio_bitrate, bitrate_per_pixel)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(file_id) DO UPDATE SET
                    width=excluded.width, height=excluded.height,
                    resolution_label=excluded.resolution_label,
                    frame_rate=excluded.frame_rate,
                    pixel_format=excluded.pixel_format,
                    color_space=excluded.color_space,
                    video_bitrate=excluded.video_bitrate,
                    video_codec=excluded.video_codec,
                    audio_codec=excluded.audio_codec,
                    audio_bitrate=excluded.audio_bitrate,
                    bitrate_per_pixel=excluded.bitrate_per_pixel
                """,
                (
                    file_id,
                    data.get("width"),
                    data.get("height"),
                    data.get("resolution_label"),
                    data.get("frame_rate"),
                    data.get("pixel_format"),
                    data.get("color_space"),
                    data.get("video_bitrate"),
                    data.get("video_codec"),
                    data.get("audio_codec"),
                    data.get("audio_bitrate"),
                    data.get("bitrate_per_pixel"),
                ),
            )

    def upsert_vr_metadata(self, file_id: int, data: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO vr_metadata
                   (file_id, is_vr, vr_format, stereo_mode, projection_type,
                    spherical, fov, per_eye_width, per_eye_height,
                    per_eye_bitrate, metadata_completeness)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(file_id) DO UPDATE SET
                    is_vr=excluded.is_vr, vr_format=excluded.vr_format,
                    stereo_mode=excluded.stereo_mode,
                    projection_type=excluded.projection_type,
                    spherical=excluded.spherical, fov=excluded.fov,
                    per_eye_width=excluded.per_eye_width,
                    per_eye_height=excluded.per_eye_height,
                    per_eye_bitrate=excluded.per_eye_bitrate,
                    metadata_completeness=excluded.metadata_completeness
                """,
                (
                    file_id,
                    data.get("is_vr", False),
                    data.get("vr_format"),
                    data.get("stereo_mode"),
                    data.get("projection_type"),
                    data.get("spherical"),
                    data.get("fov"),
                    data.get("per_eye_width"),
                    data.get("per_eye_height"),
                    data.get("per_eye_bitrate"),
                    data.get("metadata_completeness"),
                ),
            )

    def upsert_audio_metadata(self, file_id: int, data: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO audio_metadata
                   (file_id, sample_rate, bit_depth, channels, audio_bitrate,
                    is_lossless, title, artist, album, genre, year, track_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(file_id) DO UPDATE SET
                    sample_rate=excluded.sample_rate,
                    bit_depth=excluded.bit_depth,
                    channels=excluded.channels,
                    audio_bitrate=excluded.audio_bitrate,
                    is_lossless=excluded.is_lossless,
                    title=excluded.title, artist=excluded.artist,
                    album=excluded.album, genre=excluded.genre,
                    year=excluded.year, track_number=excluded.track_number
                """,
                (
                    file_id,
                    data.get("sample_rate"),
                    data.get("bit_depth"),
                    data.get("channels"),
                    data.get("audio_bitrate"),
                    data.get("is_lossless", False),
                    data.get("title"),
                    data.get("artist"),
                    data.get("album"),
                    data.get("genre"),
                    data.get("year"),
                    data.get("track_number"),
                ),
            )

    # --- Scan History ---

    def start_scan(self) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO scan_history (started_at, status) VALUES (?, 'running')",
                (now,),
            )
            return cursor.lastrowid

    def finish_scan(self, scan_id: int, files_scanned: int, files_new: int, files_updated: int):
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """UPDATE scan_history
                   SET finished_at=?, files_scanned=?, files_new=?,
                       files_updated=?, status='completed'
                   WHERE id=?""",
                (now, files_scanned, files_new, files_updated, scan_id),
            )

    def fail_scan(self, scan_id: int, files_scanned: int):
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """UPDATE scan_history
                   SET finished_at=?, files_scanned=?, status='failed'
                   WHERE id=?""",
                (now, files_scanned, scan_id),
            )

    # --- Queries ---

    def file_unchanged(self, file_path: str, file_size: int, modified_date: str) -> bool:
        """Check if a file already exists with matching size and modified date."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM media_files WHERE file_path=? AND file_size=? AND modified_date=?",
                (file_path, file_size, modified_date),
            ).fetchone()
            return row is not None

    def list_files(
        self,
        media_type: str | None = None,
        search: str | None = None,
        sort: str = "filename",
        order: str = "asc",
        page: int = 1,
        per_page: int = 50,
        codec: str | None = None,
        resolution_min: int | None = None,
        resolution_label: str | None = None,
        lossless: int | None = None,
    ) -> dict:
        """List files with filtering, sorting, and pagination."""
        allowed_sorts = {
            "filename",
            "file_size",
            "duration",
            "bitrate",
            "scan_date",
            "media_type",
            "modified_date",
        }
        if sort not in allowed_sorts:
            sort = "filename"
        if order not in ("asc", "desc"):
            order = "asc"

        where_clauses = []
        params: list = []

        if media_type:
            where_clauses.append("m.media_type = ?")
            params.append(media_type)
        if search:
            where_clauses.append("m.filename LIKE ?")
            params.append(f"%{search}%")
        if codec:
            where_clauses.append("(v.video_codec = ? OR v.audio_codec = ?)")
            params.extend([codec, codec])
        if resolution_min:
            where_clauses.append("v.height >= ?")
            params.append(resolution_min)
        if resolution_label:
            where_clauses.append("v.resolution_label = ?")
            params.append(resolution_label)
        if lossless is not None:
            where_clauses.append("a.is_lossless = ?")
            params.append(lossless)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        offset = (page - 1) * per_page

        with self._connect() as conn:
            count_row = conn.execute(
                f"""SELECT COUNT(*) as total FROM media_files m
                    LEFT JOIN video_metadata v ON m.id = v.file_id
                    LEFT JOIN audio_metadata a ON m.id = a.file_id
                    WHERE {where_sql}""",
                params,
            ).fetchone()
            total = count_row["total"]

            rows = conn.execute(
                f"""SELECT m.*, v.width, v.height, v.resolution_label,
                           v.video_codec, v.audio_codec, v.video_bitrate,
                           v.frame_rate, v.bitrate_per_pixel,
                           vr.is_vr, vr.vr_format, vr.stereo_mode,
                           vr.projection_type, vr.spherical, vr.fov,
                           vr.per_eye_width, vr.per_eye_height,
                           vr.metadata_completeness,
                           a.artist, a.album, a.title as audio_title,
                           a.sample_rate, a.channels, a.is_lossless
                    FROM media_files m
                    LEFT JOIN video_metadata v ON m.id = v.file_id
                    LEFT JOIN vr_metadata vr ON m.id = vr.file_id
                    LEFT JOIN audio_metadata a ON m.id = a.file_id
                    WHERE {where_sql}
                    ORDER BY m.{sort} {order}
                    LIMIT ? OFFSET ?""",
                params + [per_page, offset],
            ).fetchall()

            return {
                "files": [dict(r) for r in rows],
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page if per_page else 1,
            }

    def get_file_detail(self, file_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT m.*, v.*, vr.*, a.*
                   FROM media_files m
                   LEFT JOIN video_metadata v ON m.id = v.file_id
                   LEFT JOIN vr_metadata vr ON m.id = vr.file_id
                   LEFT JOIN audio_metadata a ON m.id = a.file_id
                   WHERE m.id = ?""",
                (file_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_scan_stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM media_files").fetchone()["c"]
            by_type = conn.execute(
                "SELECT media_type, COUNT(*) as c FROM media_files GROUP BY media_type"
            ).fetchall()
            avg_bitrate = conn.execute(
                "SELECT AVG(bitrate) as avg_br FROM media_files WHERE bitrate IS NOT NULL"
            ).fetchone()["avg_br"]
            last_scan = conn.execute(
                "SELECT * FROM scan_history ORDER BY id DESC LIMIT 1"
            ).fetchone()

            return {
                "total_files": total,
                "by_type": {r["media_type"]: r["c"] for r in by_type},
                "avg_bitrate": int(avg_bitrate) if avg_bitrate else 0,
                "last_scan": dict(last_scan) if last_scan else None,
            }

    def get_running_scan(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM scan_history WHERE status='running' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
