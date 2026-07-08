"""
migrate_to_railway.py
Copies all data from Render PostgreSQL to Railway PostgreSQL.
Run AFTER the app has been deployed to Railway once (so db.create_all() has run).
"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor

RENDER_DB_URL  = os.environ.get("RENDER_DB_URL",  "PASTE_RENDER_URL_HERE")
RAILWAY_DB_URL = os.environ.get("RAILWAY_DB_URL",
    "postgresql://postgres:mhNMYrnPyXjfXwVhbqIsurfVhURRkUZu@metro.proxy.rlwy.net:49060/railway")

TABLES = [
    "user",
    "crew_request",
    "post",
    "direct_message",
    "comment",
    "photo_album",
    "photo",
    "journal_entry",
    "entry_photo",
    "poll",
    "poll_option",
    "poll_vote",
]

def connect(url, label):
    try:
        conn = psycopg2.connect(url)
        print("  Connected to " + label)
        return conn
    except Exception as e:
        print("  FAILED to connect to " + label + ": " + str(e))
        sys.exit(1)

def copy_table(src_conn, dst_conn, table):
    with src_conn.cursor(cursor_factory=RealDictCursor) as src_cur:
        src_cur.execute('SELECT * FROM "' + table + '"')
        rows = src_cur.fetchall()

    if not rows:
        print("  " + table + ": 0 rows -- skipping")
        return

    columns = list(rows[0].keys())
    col_str = ", ".join('"' + c + '"' for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = 'INSERT INTO "' + table + '" (' + col_str + ') VALUES (' + placeholders + ') ON CONFLICT DO NOTHING'

    with dst_conn.cursor() as dst_cur:
        for row in rows:
            dst_cur.execute(insert_sql, list(row.values()))
    dst_conn.commit()
    print("  " + table + ": " + str(len(rows)) + " rows copied")

def reset_sequences(dst_conn):
    with dst_conn.cursor() as cur:
        for table in TABLES:
            try:
                cur.execute("""
                    SELECT setval(
                        pg_get_serial_sequence('""" + table + """', 'id'),
                        COALESCE((SELECT MAX(id) FROM \"""" + table + """\"), 1)
                    )
                """)
            except Exception:
                dst_conn.rollback()
    dst_conn.commit()
    print("  Sequences reset")

def main():
    if RENDER_DB_URL == "PASTE_RENDER_URL_HERE":
        print("ERROR: Set RENDER_DB_URL before running.")
        sys.exit(1)

    print("\n--- Connecting ---")
    src = connect(RENDER_DB_URL,  "Render (source)")
    dst = connect(RAILWAY_DB_URL, "Railway (destination)")

    print("\n--- Copying tables ---")
    for table in TABLES:
        try:
            copy_table(src, dst, table)
        except Exception as e:
            dst.rollback()
            print("  " + table + ": ERROR -- " + str(e))

    print("\n--- Resetting sequences ---")
    reset_sequences(dst)

    src.close()
    dst.close()
    print("\n--- Done. All data migrated. ---\n")

if __name__ == "__main__":
    main()
