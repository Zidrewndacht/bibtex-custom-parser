"""
oneoff_make_human_subset_ai_db.py

Single-use fixer:
- Copies the AI DB to a new output DB.
- Finds papers present in the human DB but missing from the AI DB.
- Deletes the same number of random AI-only papers.
- Inserts the missing human papers with all LLM/classification/verification data cleared.

Result:
- AI DB size stays the same.
- Human DB becomes an exact ID subset of the output AI DB.
- The inserted papers are clean and ready to be classified from scratch.
"""

import argparse
import random
import sqlite3
import sys
from pathlib import Path


PLACEHOLDER_TITLE = (
    "Database is missing or empty. Import BibTeX or restore from a backup "
    "to start working"
)

# These fields are wiped for papers inserted from the human DB.
RESET_VALUES = {
    "main_certainty": "{}",
    "classification": "{}",
    "last_llm_classification": "{}",

    "set_1_llm": None,
    "set_2_llm": None,
    "set_3_llm": None,

    "set_1_llm_log": "[]",
    "set_2_llm_log": "[]",
    "set_3_llm_log": "[]",

    "llm_log": "[]",

    "verified": None,
    "verified_by": None,
    "estimated_score": None,

    "user_override_count": 0,
    "changed": None,
    "changed_by": None,
}


def q(ident: str) -> str:
    """Quote an SQL identifier."""
    return '"' + ident.replace('"', '""') + '"'


def get_id_title_map(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT CAST(id AS TEXT), COALESCE(title, '') FROM papers"
        ).fetchall()
    finally:
        conn.close()

    return {str(pid): title for pid, title in rows}


def copy_sqlite_db(src_path: Path, dst_path: Path) -> None:
    """Create a consistent SQLite copy using the backup API."""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create an AI DB where all human DB papers are present, "
            "by replacing random AI-only papers with missing human papers."
        )
    )
    parser.add_argument("--ai-db", required=True, help="Path to AI DB")
    parser.add_argument("--human-db", required=True, help="Path to human DB")
    parser.add_argument(
        "--output-db",
        default=None,
        help="Output DB path. Default: <ai-db>_human_subset.sqlite",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible paper scrapping.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output DB if it already exists.",
    )
    parser.add_argument(
        "--clear-user-trace",
        action="store_true",
        help="Also clear user_trace on inserted papers. By default user_trace is kept.",
    )

    args = parser.parse_args()

    ai_db = Path(args.ai_db).resolve()
    human_db = Path(args.human_db).resolve()

    if not ai_db.exists():
        print(f"Error: AI DB not found: {ai_db}", file=sys.stderr)
        return 1

    if not human_db.exists():
        print(f"Error: Human DB not found: {human_db}", file=sys.stderr)
        return 1

    if ai_db == human_db:
        print("Error: AI DB and human DB must be different.", file=sys.stderr)
        return 1

    if args.output_db:
        out_db = Path(args.output_db).resolve()
    else:
        out_db = ai_db.with_name(ai_db.stem + "_human_subset" + ai_db.suffix)

    if out_db == ai_db:
        print(
            "Error: Output DB must be different from AI DB. "
            "Run with a separate --output-db, then replace manually.",
            file=sys.stderr,
        )
        return 1

    if out_db.exists():
        if args.force:
            out_db.unlink()
        else:
            print(
                f"Error: Output DB already exists: {out_db}\n"
                f"Use --force to overwrite.",
                file=sys.stderr,
            )
            return 1

    ai_map = get_id_title_map(ai_db)
    human_map = get_id_title_map(human_db)

    ai_ids = set(ai_map.keys())
    human_ids = set(human_map.keys())

    human_real_ids = {
        pid for pid, title in human_map.items()
        if title != PLACEHOLDER_TITLE
    }

    human_missing = sorted(
        pid for pid, title in human_map.items()
        if pid not in ai_ids and title != PLACEHOLDER_TITLE
    )

    ai_only_candidates = sorted(
        pid for pid, title in ai_map.items()
        if pid not in human_ids and title != PLACEHOLDER_TITLE
    )

    n = len(human_missing)

    print(f"AI DB:     {ai_db}")
    print(f"Human DB:  {human_db}")
    print(f"Output DB: {out_db}")
    print()
    print(f"AI papers:        {len(ai_ids):,}")
    print(f"Human papers:     {len(human_ids):,}")
    print(f"Common papers:    {len(ai_ids & human_ids):,}")
    print(f"Human missing:    {n:,}")
    print(f"AI-only eligible: {len(ai_only_candidates):,}")

    if n == 0:
        print("\nNo missing human papers. Copying AI DB unchanged.")
        copy_sqlite_db(ai_db, out_db)
        print(f"Done: {out_db}")
        return 0

    if n > len(ai_only_candidates):
        print(
            f"Error: Need to scrap {n} AI-only papers, but only "
            f"{len(ai_only_candidates)} are available.",
            file=sys.stderr,
        )
        return 1

    if args.seed is None:
        seed = random.SystemRandom().randint(0, 2**32 - 1)
    else:
        seed = args.seed

    rng = random.Random(seed)
    scrapped = rng.sample(ai_only_candidates, n)

    print()
    print(f"Random seed: {seed}")
    print(f"Scrapping {len(scrapped)} AI-only papers:")
    for pid in scrapped:
        print(f"  - {pid}")

    print()
    print(f"Inserting {len(human_missing)} missing human papers with clean classification:")
    for pid in human_missing:
        print(f"  + {pid}")

    # Create output DB copy.
    print()
    print("Copying AI DB...")
    copy_sqlite_db(ai_db, out_db)

    conn = sqlite3.connect(out_db)
    conn.execute("PRAGMA busy_timeout = 30000")

    try:
        conn.execute("ATTACH DATABASE ? AS human", (str(human_db),))

        out_cols = [
            row[1]
            for row in conn.execute("PRAGMA table_info(papers)").fetchall()
        ]

        human_cols = [
            row[1]
            for row in conn.execute("PRAGMA human.table_info(papers)").fetchall()
        ]

        if "id" not in out_cols:
            raise RuntimeError("Output papers table has no 'id' column.")

        if "id" not in human_cols:
            raise RuntimeError("Human papers table has no 'id' column.")

        reset_values = dict(RESET_VALUES)
        if args.clear_user_trace:
            reset_values["user_trace"] = None

        # Delete scrapped AI-only papers.
        deleted = 0
        for pid in scrapped:
            cur = conn.execute(
                "DELETE FROM papers WHERE CAST(id AS TEXT) = ?",
                (pid,),
            )
            deleted += cur.rowcount

        if deleted != n:
            conn.rollback()
            raise RuntimeError(
                f"Expected to delete {n} AI papers, deleted {deleted}."
            )

        # Insert missing human papers.
        human_select_cols = ", ".join(q(c) for c in human_cols)
        insert_cols_sql = ", ".join(q(c) for c in out_cols)
        placeholders = ", ".join("?" for _ in out_cols)

        inserted = 0

        for pid in human_missing:
            row = conn.execute(
                f"SELECT {human_select_cols} "
                f"FROM human.papers "
                f"WHERE CAST(id AS TEXT) = ?",
                (pid,),
            ).fetchone()

            if row is None:
                conn.rollback()
                raise RuntimeError(
                    f"Human paper {pid} disappeared during processing."
                )

            human_row = dict(zip(human_cols, row))

            values = []
            for col in out_cols:
                if col in reset_values:
                    val = reset_values[col]
                elif col in human_row:
                    val = human_row[col]
                else:
                    val = None

                # Normalize important defaults.
                if col == "id":
                    val = str(val)
                elif col == "pdf_state" and val is None:
                    val = "none"
                elif col == "user_override_count" and val is None:
                    val = 0

                values.append(val)

            conn.execute(
                f"INSERT INTO papers ({insert_cols_sql}) VALUES ({placeholders})",
                values,
            )
            inserted += 1

        if inserted != n:
            conn.rollback()
            raise RuntimeError(
                f"Expected to insert {n} human papers, inserted {inserted}."
            )

        conn.commit()

        # Verification.
        final_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

        human_real_list = sorted(human_real_ids)
        human_present = 0

        if human_real_list:
            ph = ",".join("?" for _ in human_real_list)
            human_present = conn.execute(
                f"SELECT COUNT(*) FROM papers WHERE CAST(id AS TEXT) IN ({ph})",
                human_real_list,
            ).fetchone()[0]

        print()
        print("Verification:")
        print(f"  Final output paper count: {final_count:,}")
        print(f"  Original AI paper count:  {len(ai_ids):,}")
        print(f"  Human papers present:     {human_present:,}/{len(human_real_list):,}")

        if final_count != len(ai_ids):
            print(
                "Warning: final count differs from original AI count.",
                file=sys.stderr,
            )

        if human_present != len(human_real_list):
            conn.rollback()
            raise RuntimeError(
                "Not all human papers are present in the output DB."
            )

        conn.execute("DETACH DATABASE human")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        print()
        print(f"Done: {out_db}")
        print("You can now classify the newly inserted papers with batch 'remaining'.")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())