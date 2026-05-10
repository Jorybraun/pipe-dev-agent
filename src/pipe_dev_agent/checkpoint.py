"""LangGraph checkpoint persistence — sqlite-backed SqliteSaver with retention."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

MAX_CHECKPOINT_DB_BYTES = 100 * 1024 * 1024  # 100 MB


def get_checkpointer(db_path: str | Path | None = None) -> SqliteSaver:
    """Return a SqliteSaver for lane-state persistence.

    Checkpoints fire at every dev boundary so supervisor restarts resume cleanly.
    Raises RuntimeError if the DB already exceeds the size guard.
    """
    if db_path is None:
        db_path = Path(".checkpoints.db")
    resolved = Path(db_path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() and resolved.stat().st_size > MAX_CHECKPOINT_DB_BYTES:
        raise RuntimeError(
            f"Checkpoint DB {resolved} is {resolved.stat().st_size / 1e6:.1f} MB, "
            f"exceeds limit {MAX_CHECKPOINT_DB_BYTES / 1e6:.1f} MB. "
            f"Remove the file or call prune_checkpoints()."
        )
    conn = sqlite3.connect(str(resolved), check_same_thread=False)
    return SqliteSaver(conn)


def get_ephemeral_checkpointer() -> MemorySaver:
    """Return an in-memory checkpointer for ephemeral developer runs.

    Prevents unbounded disk growth from ReAct tool loops.
    """
    return MemorySaver()


def prune_checkpoints(
    db_path: str | Path | None = None,
    *,
    keep_per_thread: int = 5,
    vacuum: bool = False,
) -> int:
    """Delete old checkpoints, keeping only the latest N per thread.

    Returns the number of checkpoints deleted.
    """
    if db_path is None:
        db_path = Path(".checkpoints.db")
    resolved = Path(db_path).resolve()
    if not resolved.exists():
        return 0

    conn = sqlite3.connect(str(resolved))
    try:
        # Keep only the latest N checkpoints per (thread_id, checkpoint_ns).
        # rowid is a proxy for insertion order.
        cur = conn.execute(
            """
            DELETE FROM checkpoints
            WHERE (thread_id, checkpoint_ns, checkpoint_id) NOT IN (
                SELECT thread_id, checkpoint_ns, checkpoint_id
                FROM (
                    SELECT
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY thread_id, checkpoint_ns
                            ORDER BY rowid DESC
                        ) AS rn
                    FROM checkpoints
                )
                WHERE rn <= :keep
            )
            """,
            {"keep": keep_per_thread},
        )
        deleted = cur.rowcount

        # Delete orphaned writes for checkpoints that no longer exist
        conn.execute(
            """
            DELETE FROM writes
            WHERE (thread_id, checkpoint_ns, checkpoint_id) NOT IN (
                SELECT thread_id, checkpoint_ns, checkpoint_id FROM checkpoints
            )
            """
        )

        conn.commit()

        if vacuum and deleted > 0:
            logger.info("Vacuuming checkpoint database after pruning %s rows", deleted)
            conn.execute("VACUUM")

        logger.info(
            "Pruned %s old checkpoints (kept last %s per thread)",
            deleted,
            keep_per_thread,
        )
        return deleted
    finally:
        conn.close()
