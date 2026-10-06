# -*- coding: utf-8 -*-
"""把快马-兴路强试点转成标准工作簿，并导入已经存在的标准库。

不删除库里的其他经销商。同一快马覆盖区间再次导入时，只把上一份快马批次标成非当前。
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from converters.common import ConversionRequest
from converters.kuaima import convert_kuaima
from converters.kuaima_snapshot import COVERAGE_END, COVERAGE_START, pilot_activity_inputs, pilot_coupon_inputs, pilot_source_paths
from mvp.import_service import ArchiveMetadata, create_database, import_snapshot
from mvp.standard_workbook import read_standard_workbook

CALC_DATE = "2026-09-22"
DEALER = "深圳市兴路强商贸有限公司"
PLATFORM = "快马"
REFERENCE = {
    "满减订单": 136,
    "满减实际": 2040.0,
    "满减可释放金额": 1995.0,
    "满减可释放笔数": 133,
    "满赠订单": 98,
    "满赠实发": 98.0,
    "满赠可释放": 98.0,
    "券实际": 200.0,
    "券可释放": 200.0,
    "券可释放笔数": 1,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metrics(connection: sqlite3.Connection, batch_id: int) -> dict[str, float]:
    calc_id = connection.execute(
        "SELECT calculation_run_id FROM calculation_run WHERE import_batch_id=? ORDER BY calculation_run_id DESC LIMIT 1",
        (batch_id,),
    ).fetchone()[0]

    def fee(name: str, column: str) -> float:
        value = connection.execute(
            f"SELECT COALESCE({column},0) FROM activity_fee_summary afs JOIN activity a ON a.activity_id=afs.activity_id WHERE afs.calculation_run_id=? AND a.activity_name=?",
            (calc_id, name),
        ).fetchone()
        return 0 if value is None else value[0]

    def count(name: str) -> float:
        value = connection.execute(
            "SELECT COUNT(*) FROM activity_execution e JOIN activity a ON a.activity_id=e.activity_id WHERE a.import_batch_id=? AND a.activity_name=?",
            (batch_id, name),
        ).fetchone()[0]
        return value

    coupon = connection.execute(
        "SELECT COALESCE(used_amount,0), COALESCE(releasable_amount,0), COALESCE(releasable_count,0) FROM coupon_fee_summary WHERE calculation_run_id=?",
        (calc_id,),
    ).fetchone()
    return {
        "满减订单": count("可口可乐满减"),
        "满减实际": fee("可口可乐满减", "actual_discount_total"),
        "满减可释放金额": fee("可口可乐满减", "releasable_discount_total"),
        "满减可释放笔数": fee("可口可乐满减", "release_order_count"),
        "满赠订单": count("满赠优惠"),
        "满赠实发": fee("满赠优惠", "gift_qty_actual"),
        "满赠可释放": fee("满赠优惠", "releasable_gift_qty"),
        "券实际": coupon[0],
        "券可释放": coupon[1],
        "券可释放笔数": coupon[2],
    }


def _write_report(path: Path, metrics: dict[str, float], conversion_report: str, zhoupu_kept: str) -> int:
    lines = [
        "# 快马-兴路强实际发生核算",
        "",
        f"核算日：{CALC_DATE}。导入没有清空标准库。满减金额是活动核销按订单汇总后的优惠，满赠数量是这些核销订单上的赠品行，优惠券是已使用台账。可释放要求订单状态为已完成，且下单时间 ≤ 核算日减 2 天。",
        "",
        "| 指标 | 预期 | 本次结果 | 是否一致 |",
        "|---|---:|---:|---|",
    ]
    mismatches = 0
    for name, expected in REFERENCE.items():
        actual = metrics[name]
        same = abs(float(actual) - float(expected)) < 0.001
        mismatches += int(not same)
        lines.append(f"| {name} | {expected:g} | {float(actual):g} | {'一致' if same else '不一致'} |")
    lines.extend(["", zhoupu_kept, "", "## 转换报告", "", "```", conversion_report.strip(), "```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return mismatches


def main() -> int:
    output_dir = ROOT / "outputs" / "kuaima-xingluqiang-standard"
    base = ROOT / "快马-兴路强-试点"
    request = ConversionRequest(
        PLATFORM, DEALER, pilot_source_paths(base), pilot_activity_inputs(base), pilot_coupon_inputs(), output_dir,
        coverage_start=COVERAGE_START, coverage_end=COVERAGE_END,
    )
    print("转换快马试点...")
    converted = convert_kuaima(request)
    print(converted.report_path.read_text(encoding="utf-8"))
    workbook = read_standard_workbook(converted.workbook_path)
    db_path = ROOT / "mvp" / "ec101_standard.db"
    if not db_path.exists():
        create_database(db_path)
    print("导入并核算，保留其他经销商...")
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        imported = import_snapshot(
            connection, workbook,
            ArchiveMetadata(str(converted.sources_zip_path), _sha256(converted.sources_zip_path), converted.sources_zip_path.stat().st_size),
            calc_date=CALC_DATE,
        )
        print(f"import_batch={imported.import_batch_id} calculation_run={imported.calculation_run_id} status={imported.status}")
        metrics = _metrics(connection, imported.import_batch_id)
        zhoupu = connection.execute(
            "SELECT COALESCE(SUM(afs.gift_qty_actual),0) FROM activity_fee_summary afs JOIN activity a ON a.activity_id=afs.activity_id JOIN calculation_run cr ON cr.calculation_run_id=afs.calculation_run_id JOIN import_batch ib ON ib.import_batch_id=cr.import_batch_id WHERE ib.dealer_name='羿柏' AND ib.platform_name='舟谱' AND ib.is_current=1 AND cr.calculation_run_id=(SELECT MAX(latest.calculation_run_id) FROM calculation_run latest WHERE latest.import_batch_id=ib.import_batch_id)"
        ).fetchone()[0]
        current = connection.execute("SELECT dealer_name, platform_name, is_current FROM import_batch WHERE is_current=1 ORDER BY import_batch_id").fetchall()
        fk = connection.execute("PRAGMA foreign_key_check").fetchall()
    zhoupu_kept = f"舟谱当前批次赠品实发仍为 {zhoupu:g}。当前批次：{current}。"
    report_path = output_dir / "comparison.md"
    mismatches = _write_report(report_path, metrics, converted.report_path.read_text(encoding="utf-8"), zhoupu_kept)
    print(report_path.read_text(encoding="utf-8"))
    print(f"foreign_key_check={fk or '通过'} mismatches={mismatches}")
    return 1 if mismatches or fk or zhoupu != 111 else 0


if __name__ == "__main__":
    raise SystemExit(main())
