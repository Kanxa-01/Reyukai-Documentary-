"""
Backfills Oya (sponsor) links for ALL members from the source Excel file.

Needed because earlier interrupted runs of import_members.py imported members
successfully but crashed before reaching the Oya-linking step (which only ran
once, at the very end, for whichever run happened to finish cleanly).

Safe to run now / anytime after all members exist -- it re-reads the sheet,
rebuilds every (sponsor, member) pair, and re-applies them all in one pass.
Running this multiple times is harmless (it just re-sets the same values).

USAGE:
    python relink_oya.py "Final_3rd_Branch_Shibicho_Sheets.xlsx"
"""
import os
import sys
from collections import Counter

import openpyxl
import psycopg2
from psycopg2.extras import execute_values

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SHEET_NAME = '3rd Principle branch Total Mem'
COL_SN = 1
COL_FULL_NAME = 2
COL_OYA_NO = 5


def main():
    if len(sys.argv) < 2:
        print('Usage: python relink_oya.py <path_to_excel_file.xlsx>')
        sys.exit(1)
    excel_path = sys.argv[1]

    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print('ERROR: DATABASE_URL is not set.')
        sys.exit(1)
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

    print(f'Loading {excel_path} ...')
    wb = openpyxl.load_workbook(excel_path, data_only=True, read_only=True)
    ws = wb[SHEET_NAME]

    print('Connecting to database...')
    conn = psycopg2.connect(database_url, keepalives=1, keepalives_idle=30,
                             keepalives_interval=10, keepalives_count=5, connect_timeout=15)
    cur = conn.cursor()

    print('Loading existing member IDs...')
    cur.execute('SELECT id FROM members')
    existing_ids = set(r[0] for r in cur.fetchall())
    print(f'  {len(existing_ids)} members currently in database.')

    stats = Counter()
    oya_pairs = []

    print('Reading Oya references from sheet...')
    for row in ws.iter_rows(min_row=2, max_row=34000, max_col=6, values_only=True):
        sn = row[COL_SN]
        if sn is None:
            continue
        try:
            sn = int(sn)
        except (ValueError, TypeError):
            continue
        if sn not in existing_ids:
            continue  # this member was never imported (e.g. blank name), skip

        full_name = (row[COL_FULL_NAME] or '').strip() if row[COL_FULL_NAME] else ''
        if not full_name:
            continue

        oya_no_raw = row[COL_OYA_NO]
        if oya_no_raw in (None, '', 0, '0'):
            continue
        try:
            oya_int = int(oya_no_raw)
        except (ValueError, TypeError):
            stats['unparseable'] += 1
            continue
        if oya_int == sn:
            stats['self_ref'] += 1
            continue
        if oya_int not in existing_ids:
            stats['target_missing'] += 1
            continue
        oya_pairs.append((oya_int, sn))
        stats['valid'] += 1

    print(f'Applying {len(oya_pairs)} Oya links (batched)...')
    BATCH = 2000
    for i in range(0, len(oya_pairs), BATCH):
        chunk = oya_pairs[i:i + BATCH]
        execute_values(cur, """
            UPDATE members AS m SET oya_id = v.oya_id
            FROM (VALUES %s) AS v(oya_id, id)
            WHERE m.id = v.id
        """, chunk)
        conn.commit()
        print(f'  ... {min(i + BATCH, len(oya_pairs))}/{len(oya_pairs)} applied')

    cur.close()
    conn.close()

    print()
    print('=== RELINK COMPLETE ===')
    print(f"Links applied:              {stats['valid']}")
    print(f"Skipped -- self-reference:  {stats['self_ref']}")
    print(f"Skipped -- unparseable:     {stats['unparseable']}")
    print(f"Skipped -- sponsor missing: {stats['target_missing']}")


if __name__ == '__main__':
    main()
