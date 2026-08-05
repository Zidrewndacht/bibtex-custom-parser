#!/usr/bin/env python3
"""
sanitize_db.py
──────────────
Reset a ResearchParça SQLite database to a pristine, "fresh-import" state
so it can be distributed as a reproducible artifact.

What it does
  • Strips every user comment (user_trace).
    Exception: papers detected as *paywalled* get a plain "Paywalled" comment.
  • Removes all PDF references (pdf_filename) and resets pdf_state to 'none'
    (or 'paywalled' for paywalled papers).  This prevents stray 🔗 icons that
    open an empty annotator.
  • Clears audit fields (changed, changed_by) so no "last changed" timestamp
    leaks into the artifact.
  • Resets verification metadata (verified, verified_by, estimated_score).
  • Zeros user_override_count.
  • Clears llm_log (user-edit history) so the history tab is empty.
  • With --full-reset, also wipes all LLM classification blobs and per-set
    logs, returning papers to a completely unclassified state.

Usage
    python sanitize_db.py --db data/db.sqlite
    python sanitize_db.py --db data/db.sqlite --full-reset
    python sanitize_db.py --db data/db.sqlite --dry-run
"""

import argparse
import os
import shutil
import sqlite3
import sys

PLACEHOLDER_TITLE = (
    "Database is missing or empty. Import BibTeX or restore "
    "from a backup to start working"
)


# ─────────────────────────────────────────────────────────────────────────────
# Detection
# ─────────────────────────────────────────────────────────────────────────────
def is_paywalled(row) -> bool:
    """Mirror the app's own paywall heuristic (shared/db.py):
       • pdf_state is already 'paywalled', OR
       • user_trace contains the word 'paywalled' (case-insensitive)
         AND no PDF file is attached.
    """
    state = (row["pdf_state"] or "").strip().lower()
    if state == "paywalled":
        return True
    trace = (row["user_trace"] or "").strip().lower()
    has_pdf = bool(row["pdf_filename"])
    return "paywalled" in trace and not has_pdf


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Sanitize a ResearchParça DB for artifact distribution."
    )
    parser.add_argument("--db", required=True, help="Path to the SQLite database")
    parser.add_argument(
        "--full-reset",
        action="store_true",
        default=False,
        help="Also wipe LLM classification blobs and per-set logs "
             "(use when the DB contains any inference results).",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        default=False,
        help="Skip creating a .bak backup file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would change without writing anything.",
    )
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        print(f"Error: database not found at {db_path}")
        sys.exit(1)

    # ── Backup ──────────────────────────────────────────────────────────────
    if not args.no_backup and not args.dry_run:
        backup = db_path + ".bak"
        shutil.copy2(db_path, backup)
        print(f"[Backup]  {backup}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        "SELECT id, title, user_trace, pdf_state, pdf_filename FROM papers"
    ).fetchall()

    n_total = n_clean = n_paywalled = 0

    for row in rows:
        if row["title"] == PLACEHOLDER_TITLE:
            continue                       # never touch the placeholder row
        n_total += 1

        if is_paywalled(row):
            n_paywalled += 1
            if not args.dry_run:
                cur.execute(
                    """
                    UPDATE papers SET
                        user_trace          = 'Paywalled',
                        pdf_state           = 'paywalled',
                        pdf_filename        = NULL,
                        changed             = NULL,
                        changed_by          = NULL,
                        verified            = NULL,
                        verified_by         = NULL,
                        estimated_score     = NULL,
                        user_override_count = 0,
                        llm_log             = '[]'
                    WHERE id = ?
                    """,
                    (row["id"],),
                )
        else:
            n_clean += 1
            if not args.dry_run:
                cur.execute(
                    """
                    UPDATE papers SET
                        user_trace          = NULL,
                        pdf_state           = 'none',
                        pdf_filename        = NULL,
                        changed             = NULL,
                        changed_by          = NULL,
                        verified            = NULL,
                        verified_by         = NULL,
                        estimated_score     = NULL,
                        user_override_count = 0,
                        llm_log             = '[]'
                    WHERE id = ?
                    """,
                    (row["id"],),
                )

    # ── Optional: wipe all inference artifacts ──────────────────────────────
    if args.full_reset and not args.dry_run:
        cur.execute(
            """
            UPDATE papers SET
                classification           = '{}',
                last_llm_classification  = '{}',
                main_certainty           = '{}',
                set_1_llm                = NULL,
                set_2_llm                = NULL,
                set_3_llm                = NULL,
                set_1_llm_log            = '[]',
                set_2_llm_log            = '[]',
                set_3_llm_log            = '[]',
                llm_log                  = '[]'
            WHERE title != ?
            """,
            (PLACEHOLDER_TITLE,),
        )
        print("[Reset]   Wiped all LLM classification blobs and per-set logs.")

    if not args.dry_run:
        conn.commit()
    conn.close()

    # ── Summary ─────────────────────────────────────────────────────────────
    verb = "Would process" if args.dry_run else "Processed"
    print(f"\n[{verb}] {n_total} papers")
    print(f"  • {n_clean} → comments/PDFs stripped (fresh-import state)")
    print(f"  • {n_paywalled} → user_trace set to 'Paywalled', pdf_state = 'paywalled'")
    if args.dry_run:
        print("\n  (dry-run — no changes written)")
    else:
        print(f"\n[Done]    {db_path}")


if __name__ == "__main__":
    main()