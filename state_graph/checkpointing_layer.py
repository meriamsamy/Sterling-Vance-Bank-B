from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


CHECKPOINT_DB = (
    Path(__file__).resolve().parent / "checkpoints.db"
)


# ============================================================
# [CHECKPOINT CONTEXT]
# Create and safely manage the async SQLite checkpointer.
#
# AsyncSqliteSaver.from_conn_string() returns an async
# context manager, so it MUST be used with "async with".
# ============================================================

@asynccontextmanager
async def checkpoint_context():
    async with AsyncSqliteSaver.from_conn_string(
        str(CHECKPOINT_DB)
    ) as checkpointer:

        # AsyncSqliteSaver is already initialized when entered
        # through the async context manager.
        yield checkpointer