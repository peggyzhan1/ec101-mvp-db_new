"""Rebuild mvp/ec101_standard.db from the verified Kuaima standard workbooks.

The runtime path mvp/ec101_standard.db is gitignored. After clone, run:

    python3 scripts/rebuild_standard_db.py

That writes the platform database from docs/samples/kuaima-verified-standard/{满减,满赠}/standard.xlsx
and also refreshes the review copy in the same samples directory.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mvp.calculation_engine import calculate_batch, run_calculation
from mvp.import_service import ArchiveMetadata, create_database, import_snapshot
from mvp.standard_workbook import read_standard_workbook

SAMPLES = ROOT / "docs" / "samples" / "kuaima-verified-standard"
RUNTIME_DB = ROOT / "mvp" / "ec101_standard.db"
SNAPSHOT_DB = SAMPLES / "ec101_standard.db"
CALC_DATE = "2026-09-22"
BATCHES = ("满减", "满赠")


def rebuild(destination: Path) -> list[dict]:
    if destination.exists():
        destination.unlink()
    create_database(destination)
    results = []
    with sqlite3.connect(destination) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for name in BATCHES:
            workbook_path = SAMPLES / name / "standard.xlsx"
            workbook = read_standard_workbook(workbook_path)
            imported = import_snapshot(
                connection,
                workbook,
                ArchiveMetadata(str(workbook_path), f"sample-{name}", workbook_path.stat().st_size),
            )
            calculate_batch(connection, imported.import_batch_id, CALC_DATE)
            results.append({"batch": name, "import_batch_id": imported.import_batch_id, **run_calculation(connection, imported.import_batch_id)})
        connection.commit()
    return results


def main() -> None:
    results = rebuild(RUNTIME_DB)
    shutil.copy2(RUNTIME_DB, SNAPSHOT_DB)
    print(f"wrote {RUNTIME_DB}")
    print(f"copied {SNAPSHOT_DB}")
    for row in results:
        print(
            f"{row['batch']}: batch={row['import_batch_id']} "
            f"activity={row['activity_benefit']} coupon={row['coupon_benefit']} "
            f"released_activity={row['released_activity_benefit']} "
            f"orders={row['participating_orders']}/{row['released_orders']}"
        )


if __name__ == "__main__":
    main()
