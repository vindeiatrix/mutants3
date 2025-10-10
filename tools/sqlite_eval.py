import argparse
import json
import sqlite3
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scalar", help="Print first column of first row")
    group.add_argument("--execute", help="Executes SQL (can contain multiple statements); prints 'ok'")
    group.add_argument("--query", help="Runs SQL and prints JSON array of rows")
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        if args.scalar:
            cur.execute(args.scalar)
            row = cur.fetchone()
            print("" if row is None else row[0])
        elif args.execute:
            cur.executescript(args.execute)
            con.commit()
            print("ok")
        else:  # args.query
            cur.execute(args.query)
            print(json.dumps([dict(r) for r in cur.fetchall()]))
    except sqlite3.Error as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    finally:
        con.close()


if __name__ == "__main__":
    main()
