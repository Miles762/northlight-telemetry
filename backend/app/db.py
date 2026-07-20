"""Database access for the NorthLight backend.

One tiny connection helper over psycopg 3. No ORM by design (PRD §7): the schema
lives in real migration files and every query in this codebase is hand-written,
parameterized SQL so a reviewer can read exactly what hits Postgres.
"""

import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

# Connection string comes from the environment so nothing is hard-coded and the
# same code runs against any local Postgres. Default matches the NOTES.md setup.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/northlight",
)


@contextmanager
def get_conn():
    """Yield a psycopg connection with dict rows, committing on clean exit.

    We open a fresh connection per request. That is more than fast enough for a
    single-machine, low-volume agent (PRD §4: one machine, low volume) and it
    keeps the code obvious -- no pool lifecycle to reason about in the slice.
    A connection pool is a [FUTURE] optimization, not needed here.
    """
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
