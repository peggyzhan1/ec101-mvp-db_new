"""Rebuild mvp/ec101_standard.db from verified standard workbooks.

The runtime path mvp/ec101_standard.db is gitignored. After clone, run:

    python3 scripts/rebuild_standard_db.py

Kuaima batches come from docs/samples/kuaima-verified-standard/{满减,满赠}/standard.xlsx.
羿柏/舟谱 batches are projected from mvp/ec101_mvp.db into
docs/samples/zhoupu-verified-standard/{返券,满赠}/standard.xlsx and then imported.

Do not import 优惠券/standard.xlsx here: that workbook is a coupon-domain extract of the
满减 batch. Re-importing it would double-count the same 200 yuan redemption.
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
from scripts.export_kuaima_verified_standard import dump_database, write_db_inventory
from scripts.export_yibo_standard import export_all

SAMPLES = ROOT / "docs" / "samples" / "kuaima-verified-standard"
YIBO_SAMPLES = ROOT / "docs" / "samples" / "zhoupu-verified-standard"
RUNTIME_DB = ROOT / "mvp" / "ec101_standard.db"
SNAPSHOT_DB = SAMPLES / "ec101_standard.db"
KUAIMA = (("满减", SAMPLES / "满减" / "standard.xlsx", "2026-09-22"), ("满赠", SAMPLES / "满赠" / "standard.xlsx", "2026-09-22"))
YIBO = (("羿柏返券", YIBO_SAMPLES / "返券" / "standard.xlsx", "2026-09-23"), ("羿柏满赠", YIBO_SAMPLES / "满赠" / "standard.xlsx", "2026-09-23"))


def _import_workbook(connection: sqlite3.Connection, name: str, workbook_path: Path, calc_date: str) -> dict:
    workbook = read_standard_workbook(workbook_path)
    imported = import_snapshot(
        connection,
        workbook,
        ArchiveMetadata(str(workbook_path), f"sample-{name}", workbook_path.stat().st_size),
    )
    calculate_batch(connection, imported.import_batch_id, calc_date)
    return {"batch": name, "import_batch_id": imported.import_batch_id, **run_calculation(connection, imported.import_batch_id)}


def rebuild(destination: Path) -> list[dict]:
    export_all()
    if destination.exists():
        destination.unlink()
    create_database(destination)
    results = []
    with sqlite3.connect(destination) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for name, workbook_path, calc_date in (*KUAIMA, *YIBO):
            results.append(_import_workbook(connection, name, workbook_path, calc_date))
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
            f"theoretical={row.get('theoretical_activity_benefit')} consistent={row.get('consistent_orders')} "
            f"released_activity={row['released_activity_benefit']} "
            f"orders={row['participating_orders']}/{row['released_orders']}"
        )
    snapshot = dump_database(SNAPSHOT_DB)
    inventory = write_db_inventory(snapshot)
    print(f"inventory {inventory}")


if __name__ == "__main__":
    main()
