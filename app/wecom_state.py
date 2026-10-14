"""Durable state for incremental WeCom customer-service message consumption."""

import sqlite3
from pathlib import Path


class WeComState:
    def __init__(self, database_path: str) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_cursors (
                    open_kfid TEXT PRIMARY KEY,
                    cursor TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_messages (
                    msgid TEXT PRIMARY KEY,
                    processed_at INTEGER NOT NULL DEFAULT (unixepoch())
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def get_cursor(self, open_kfid: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cursor FROM sync_cursors WHERE open_kfid = ?", (open_kfid,)
            ).fetchone()
        return row[0] if row else None

    def set_cursor(self, open_kfid: str, cursor: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_cursors (open_kfid, cursor) VALUES (?, ?)
                ON CONFLICT(open_kfid) DO UPDATE SET cursor = excluded.cursor
                """,
                (open_kfid, cursor),
            )

    def is_processed(self, message_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM processed_messages WHERE msgid = ?", (message_id,)
            ).fetchone()
        return row is not None

    def mark_processed(self, message_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO processed_messages (msgid) VALUES (?)", (message_id,)
            )
            # Retain ample retry protection without letting the local state grow forever.
            connection.execute(
                "DELETE FROM processed_messages WHERE processed_at < unixepoch() - 1209600"
            )
