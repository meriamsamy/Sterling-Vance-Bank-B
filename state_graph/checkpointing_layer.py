from pathlib import Path
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver


CHECKPOINT_DB = (
    Path(__file__).resolve().parent
    / "checkpoints.db"
)

CHECKPOINT_DB.parent.mkdir(
    parents=True,
    exist_ok=True,
)


def create_checkpointer() -> SqliteSaver:

    conn = sqlite3.connect(
        str(CHECKPOINT_DB),
        check_same_thread=False,
    )

    return SqliteSaver(conn)


checkpointer = create_checkpointer()