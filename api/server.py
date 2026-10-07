"""Cross-platform HTTP API over the EC101 standard import database (mvp/ec101_standard.db).

Every query reads the *standard* schema (mvp/ddl/ec101_standard_sqlite.sql): import batches, the
business facts they carry, and the calculation runs written by calculation_engine after import.
The old MVP database (mvp/ec101_mvp.db) is not served here; it only remains as the audited acceptance baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from cgi import FieldStorage
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `python3 api/server.py` puts api/ on sys.path, not the repo root.
    sys.path.insert(0, str(ROOT))

from mvp.calculation_engine import calculate_batch, parse_calc_date, run_calculation  # noqa: E402
from mvp.import_service import ArchiveMetadata, ImportValidationError, create_database, import_snapshot  # noqa: E402
from mvp.standard_workbook import read_standard_workbook  # noqa: E402
from mvp.roi import activity_roi, coupon_roi  # noqa: E402
from mvp.roi_workbook import build_roi_workbook  # noqa: E402
from mvp.verification_report import build_activity_report, build_coupon_report, content_disposition  # noqa: E402


DEFAULT_DB_PATH = ROOT / "mvp" / "ec101_standard.db"
STANDARD_DDL = ROOT / "mvp" / "ddl" / "ec101_standard_sqlite.sql"


def expected_schema() -> dict[str, set[str]]:
    """Table -> column names that the current DDL produces."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(STANDARD_DDL.read_text(encoding="utf-8"))
    schema = {
        table: {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()}
        for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    }
    connection.close()
    return schema


def schema_differences(db_path: Path) -> list[str]:
    """Human-readable list of tables/columns the DDL expects but the database file lacks."""
    expected = expected_schema()
    problems: list[str] = []
    with sqlite3.connect(db_path) as connection:
        for table, columns in expected.items():
            actual = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()}
            if not actual:
                problems.append(f"缺少表 {table}")
                continue
            missing = sorted(columns - actual)
            if missing:
                problems.append(f"表 {table} 缺少列 {', '.join(missing)}")
    return problems


def ensure_database(db_path: Path) -> str | None:
    """Create the standard database if needed; if an older-schema file is found, set it aside and start fresh.

    The standard database is a snapshot store (every upload is a full re-import), so recreating it never
    loses anything that cannot be re-uploaded. Returns the backup path when a file was set aside.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        create_database(db_path)
        return None
    problems = schema_differences(db_path)
    if not problems:
        return None
    backup = db_path.with_name(f"{db_path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    db_path.rename(backup)
    create_database(db_path)
    print(f"[ec101] 旧结构数据库已备份为 {backup.name} 并重建: {'; '.join(problems)}")
    return str(backup)


def import_uploaded_files(db_path: Path, workbook_bytes: bytes, source_bytes: bytes | None = None, source_name: str = "sources.zip", calc_date: str | None = None) -> dict[str, Any]:
    """Import one uploaded standard workbook and archive metadata without storing raw rows."""
    ensure_database(db_path)
    with tempfile.TemporaryDirectory(prefix="ec101-import-") as directory:
        root = Path(directory)
        workbook_path = root / "standard.xlsx"
        workbook_path.write_bytes(workbook_bytes)
        source_name = Path(source_name).name or "sources.zip"
        source_path = root / source_name
        source_path.write_bytes(source_bytes or b"")
        workbook = read_standard_workbook(workbook_path)
        source_hash = hashlib.sha256(source_bytes or b"").hexdigest()
        archive_path = db_path.parent / "archives" / f"{source_hash[:16]}-{source_name}"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(source_bytes or b"")
        archive = ArchiveMetadata(str(archive_path), source_hash, len(source_bytes or b""))
        if calc_date:
            parse_calc_date(calc_date)
        with sqlite3.connect(db_path) as connection:
            result = import_snapshot(connection, workbook, archive)
            calc_id = calculate_batch(connection, result.import_batch_id, calc_date)
            calculation = run_calculation(connection, result.import_batch_id)
        return {"import_batch_id": result.import_batch_id, "calculation_run_id": calc_id, "status": calculation["status"], "calculation": calculation}


def list_imports(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute(
            """
            SELECT ib.*, cr.calculation_run_id, cr.calc_date, cr.participating_orders, cr.released_orders,
                   cr.activity_benefit, cr.coupon_benefit, cr.released_activity_benefit, cr.released_coupon_benefit,
                   (SELECT COUNT(*) FROM order_header oh WHERE oh.import_batch_id=ib.import_batch_id) AS order_count
            FROM import_batch ib
            LEFT JOIN calculation_run cr ON cr.calculation_run_id=(SELECT MAX(calculation_run_id) FROM calculation_run WHERE import_batch_id=ib.import_batch_id)
            ORDER BY ib.import_batch_id DESC
            """
        ).fetchall()]
    return {"rows": rows, "total": len(rows)}


def get_import(db_path: Path, import_batch_id: int) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM import_batch WHERE import_batch_id=?", (import_batch_id,)).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["files"] = [dict(item) for item in connection.execute("SELECT * FROM import_file WHERE import_batch_id=?", (import_batch_id,)).fetchall()]
        payload["calculation"] = next((dict(item) for item in connection.execute("SELECT * FROM calculation_run WHERE import_batch_id=? ORDER BY calculation_run_id DESC LIMIT 1", (import_batch_id,)).fetchall()), None)
        payload["activities"] = _activity_summaries(connection, payload["calculation"]["calculation_run_id"]) if payload["calculation"] else []
        return payload


def get_import_issues(db_path: Path, import_batch_id: int) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM import_validation_issue WHERE import_batch_id=? ORDER BY issue_id", (import_batch_id,)).fetchall()]


def _latest_run_id(connection: sqlite3.Connection, import_batch_id: int) -> int | None:
    row = connection.execute("SELECT calculation_run_id FROM calculation_run WHERE import_batch_id=? ORDER BY calculation_run_id DESC LIMIT 1", (import_batch_id,)).fetchone()
    return row[0] if row else None


def _activity_summaries(connection: sqlite3.Connection, calculation_run_id: int) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(
        """
        SELECT a.activity_id, a.activity_no, a.activity_name, a.activity_type,
               s.actual_discount_total, s.participating_orders, s.released_orders, s.released_amount, s.pending_orders, s.pending_amount
        FROM activity_fee_summary s JOIN activity a ON a.activity_id=s.activity_id
        WHERE s.calculation_run_id=? ORDER BY a.activity_id
        """,
        (calculation_run_id,),
    ).fetchall()]


def get_import_release(db_path: Path, import_batch_id: int, params: dict[str, Any]) -> dict[str, Any] | None:
    """Per-order release list for one import batch: 哪些参与单可释放、哪些不可释放及原因。"""
    try:
        limit = min(max(int(params.get("limit", 200)), 1), 2000)
        offset = max(int(params.get("offset", 0)), 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit and offset must be integers") from exc
    candidate = str(params.get("candidate", "")).strip()
    search = str(params.get("q", "")).strip()
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        run_id = _latest_run_id(connection, import_batch_id)
        if run_id is None:
            return None
        clauses, values = ["rc.calculation_run_id=?"], [run_id]
        if candidate in ("0", "1"):
            clauses.append("rc.is_candidate=?"); values.append(int(candidate))
        if search:
            clauses.append("(oh.order_no LIKE ? OR oh.customer_name LIKE ? OR oh.customer_no LIKE ?)"); values.extend([f"%{search}%"] * 3)
        where = " WHERE " + " AND ".join(clauses)
        base = """
            FROM release_candidate rc
            JOIN order_header oh ON oh.order_id=rc.order_id
        """
        total = connection.execute(f"SELECT COUNT(*) {base}{where}", values).fetchone()[0]
        rows = [dict(row) for row in connection.execute(
            f"""
            SELECT rc.order_id, oh.order_no, oh.order_time, oh.order_status, oh.customer_no, oh.customer_name, oh.salesperson,
                   rc.is_candidate, rc.reason, rc.activity_benefit, rc.coupon_benefit,
                   (SELECT GROUP_CONCAT(a.activity_name, ';') FROM activity_execution ae JOIN activity a ON a.activity_id=ae.activity_id WHERE ae.order_id=rc.order_id) AS activities,
                   (SELECT GROUP_CONCAT(cr.coupon_no, ';') FROM coupon_redemption cr WHERE cr.order_id=rc.order_id) AS coupons
            {base}{where}
            ORDER BY rc.is_candidate DESC, oh.order_time, oh.order_no LIMIT ? OFFSET ?
            """,
            [*values, limit, offset],
        ).fetchall()]
        calculation = dict(connection.execute("SELECT * FROM calculation_run WHERE calculation_run_id=?", (run_id,)).fetchone())
    return {"import_batch_id": import_batch_id, "calculation": calculation, "rows": rows, "total": total, "limit": limit, "offset": offset}


class NotFoundError(KeyError):
    """A requested, immutable calculation run or activity does not exist."""


# ---------------------------------------------------------------------------
# 业务数据：按当前有效导入批次（import_batch.is_current=1）读取标准库事实表
# ---------------------------------------------------------------------------

def _config(source: str, select: str, joins: str, search: tuple[str, ...], id_column: str) -> dict[str, Any]:
    return {"source": source, "select": select, "joins": joins, "search": search, "id_column": id_column}


_BATCH = "JOIN import_batch ib ON ib.import_batch_id={owner}.import_batch_id"
_ORDER_BATCH = "JOIN order_header oh ON oh.order_id={owner}.order_id " + _BATCH.format(owner="oh")

CONFIGS = {
    "orders": _config(
        "order_header oh",
        "oh.order_id AS id, oh.import_batch_id, oh.order_no, ib.dealer_name AS dealer, ib.platform_name AS platform, oh.customer_no, oh.customer_name AS customer, "
        "oh.salesperson, oh.order_time, oh.order_status, oh.order_source, oh.order_type, oh.payment_method, "
        "(SELECT COUNT(*) FROM order_line ol WHERE ol.order_id=oh.order_id) AS line_count, "
        "(SELECT ROUND(COALESCE(SUM(ol.paid_amount),0),2) FROM order_line ol WHERE ol.order_id=oh.order_id) AS paid_amount, "
        "(SELECT ROUND(COALESCE(SUM(ol.discount_amount),0),2) FROM order_line ol WHERE ol.order_id=oh.order_id) AS discount_amount, "
        "(SELECT GROUP_CONCAT(a.activity_name, ';') FROM activity_execution ae JOIN activity a ON a.activity_id=ae.activity_id WHERE ae.order_id=oh.order_id) AS activities, "
        "(SELECT GROUP_CONCAT(cr.coupon_no, ';') FROM coupon_redemption cr WHERE cr.order_id=oh.order_id) AS coupons",
        _BATCH.format(owner="oh"),
        ("oh.order_no", "oh.customer_name", "oh.customer_no", "oh.order_status", "oh.salesperson"),
        "oh.order_id",
    ),
    "order-lines": _config(
        "order_line ol",
        "ol.order_line_id AS id, oh.import_batch_id, oh.order_no, ib.dealer_name AS dealer, ib.platform_name AS platform, oh.order_time, oh.customer_name AS customer, oh.order_status, "
        "ol.product_no, ol.product_name AS product, ol.category, ol.spec, ol.unit, ol.quantity, ol.unit_price, ol.pre_discount_amount, ol.discount_amount, ol.paid_amount, "
        "ol.activity_numbers, ol.coupon_numbers, ol.return_qty",
        _ORDER_BATCH.format(owner="ol"),
        ("oh.order_no", "ol.product_name", "ol.product_no", "oh.customer_name"),
        "ol.order_line_id",
    ),
    "activities": _config(
        "activity a",
        "a.activity_id AS id, a.import_batch_id, a.activity_no, a.activity_name, a.activity_type, ib.dealer_name AS dealer, ib.platform_name AS platform, a.promo_method, "
        "a.start_time, a.end_time, a.activity_status, "
        "(SELECT COUNT(*) FROM activity_execution ae WHERE ae.activity_id=a.activity_id) AS execution_count, "
        "(SELECT ROUND(COALESCE(SUM(ae.discount_amount),0),2) FROM activity_execution ae WHERE ae.activity_id=a.activity_id) AS discount_total",
        _BATCH.format(owner="a"),
        ("a.activity_no", "a.activity_name", "a.activity_type"),
        "a.activity_id",
    ),
    "activity-executions": _config(
        "activity_execution ae",
        "ae.activity_execution_id AS id, oh.import_batch_id, oh.order_no, ib.dealer_name AS dealer, ib.platform_name AS platform, a.activity_no, a.activity_name, a.activity_type, "
        "oh.order_time, oh.order_status, ae.customer_no, ae.customer_name, ae.salesperson, ae.product_amount, ae.discount_amount",
        _ORDER_BATCH.format(owner="ae") + " JOIN activity a ON a.activity_id=ae.activity_id",
        ("oh.order_no", "a.activity_name", "ae.customer_name", "ae.customer_no"),
        "ae.activity_execution_id",
    ),
    "coupon-redemptions": _config(
        "coupon_redemption cr",
        "cr.coupon_redemption_id AS id, cr.import_batch_id, cr.coupon_no, ib.dealer_name AS dealer, ib.platform_name AS platform, oh.order_no, oh.order_time, oh.order_status, "
        "cr.customer_no, cr.customer_name, cr.salesperson, cr.receive_time, cr.use_period, cr.status, cr.used_at, cr.discount_amount",
        _BATCH.format(owner="cr") + " LEFT JOIN order_header oh ON oh.order_id=cr.order_id",
        ("cr.coupon_no", "oh.order_no", "cr.customer_name", "cr.customer_no", "cr.status"),
        "cr.coupon_redemption_id",
    ),
    "customers": _config(
        "customer c",
        "c.customer_id AS id, c.import_batch_id, c.customer_no, ib.dealer_name AS dealer, ib.platform_name AS platform, c.customer_name, c.customer_type, c.customer_region, "
        "c.address, c.phone, c.added_at, c.salesperson",
        _BATCH.format(owner="c"),
        ("c.customer_no", "c.customer_name", "c.customer_region", "c.salesperson"),
        "c.customer_id",
    ),
    "products": _config(
        "product p",
        "p.product_id AS id, p.import_batch_id, p.product_no, ib.dealer_name AS dealer, ib.platform_name AS platform, p.product_name, p.brand, p.category, p.barcode, p.spec, "
        "p.base_unit, p.box_conversion, p.base_qty_per_box",
        _BATCH.format(owner="p"),
        ("p.product_no", "p.product_name", "p.brand", "p.category", "p.barcode"),
        "p.product_id",
    ),
    "fulfillments": _config(
        "fulfillment f",
        "f.fulfillment_id AS id, f.import_batch_id, f.order_no, ib.dealer_name AS dealer, ib.platform_name AS platform, f.downstream_order_no, f.fulfillment_status, "
        "f.outbound_at, f.completed_at, f.settlement_status, f.return_qty",
        _BATCH.format(owner="f"),
        ("f.order_no", "f.downstream_order_no", "f.fulfillment_status", "f.settlement_status"),
        "f.fulfillment_id",
    ),
}
SUPPORTED_OBJECTS = tuple(CONFIGS)


def _batch_scope(params: dict[str, Any]) -> tuple[str, list[Any]]:
    """Default to the current snapshot of every dealer/platform; ``import_batch_id`` pins one batch."""
    raw = params.get("import_batch_id")
    if raw in (None, ""):
        return "ib.is_current=1", []
    try:
        return "ib.import_batch_id=?", [int(raw)]
    except (TypeError, ValueError) as exc:
        raise ValueError("import_batch_id must be an integer") from exc


def _conditions(config: dict[str, Any], params: dict[str, Any]) -> tuple[str, list[Any]]:
    scope, values = _batch_scope(params)
    clauses: list[str] = [scope]
    dealer = str(params.get("dealer", "")).strip()
    platform = str(params.get("platform", "")).strip()
    search = str(params.get("q", "")).strip()
    if dealer:
        clauses.append("ib.dealer_name LIKE ?")
        values.append(f"%{dealer}%")
    if platform:
        clauses.append("ib.platform_name LIKE ?")
        values.append(f"%{platform}%")
    if search:
        clauses.append("(" + " OR ".join(f"{column} LIKE ?" for column in config["search"]) + ")")
        values.extend([f"%{search}%"] * len(config["search"]))
    return " WHERE " + " AND ".join(clauses), values


def _bounds(params: dict[str, Any]) -> tuple[int, int]:
    try:
        limit = min(max(int(params.get("limit", 50)), 1), 500)
        offset = max(int(params.get("offset", 0)), 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit and offset must be integers") from exc
    return limit, offset


def query_dataset(db_path: Path, object_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if object_name not in CONFIGS:
        raise KeyError(object_name)
    config = CONFIGS[object_name]
    where, values = _conditions(config, params)
    limit, offset = _bounds(params)
    base = f"SELECT {config['select']} FROM {config['source']} {config['joins']}"
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        total = connection.execute(f"SELECT COUNT(*) FROM ({base}{where})", values).fetchone()[0]
        rows = [dict(row) for row in connection.execute(f"{base}{where} ORDER BY {config['id_column']} LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()]
    return {"object": object_name, "columns": list(rows[0].keys()) if rows else [], "rows": rows, "total": total, "limit": limit, "offset": offset}


def get_detail(db_path: Path, object_name: str, record_id: str) -> dict[str, Any] | None:
    if object_name not in CONFIGS:
        raise KeyError(object_name)
    config = CONFIGS[object_name]
    base = f"SELECT {config['select']} FROM {config['source']} {config['joins']} WHERE {config['id_column']} = ?"
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(base, (record_id,)).fetchone()
        if row is None:
            return None
        payload = dict(row)
        if object_name == "orders":
            payload["lines"] = [dict(item) for item in connection.execute(
                "SELECT order_line_id, product_no, product_name, category, spec, unit, quantity, unit_price, pre_discount_amount, discount_amount, paid_amount, activity_numbers, coupon_numbers, return_qty FROM order_line WHERE order_id=? ORDER BY order_line_id",
                (record_id,),
            ).fetchall()]
            payload["activity_executions"] = [dict(item) for item in connection.execute(
                "SELECT a.activity_no, a.activity_name, a.activity_type, ae.product_amount, ae.discount_amount FROM activity_execution ae JOIN activity a ON a.activity_id=ae.activity_id WHERE ae.order_id=? ORDER BY ae.activity_execution_id",
                (record_id,),
            ).fetchall()]
            payload["coupon_redemptions"] = [dict(item) for item in connection.execute(
                "SELECT coupon_no, status, used_at, discount_amount FROM coupon_redemption WHERE order_id=? ORDER BY coupon_redemption_id",
                (record_id,),
            ).fetchall()]
            payload["release"] = next((dict(item) for item in connection.execute(
                "SELECT rc.is_candidate, rc.reason, rc.activity_benefit, rc.coupon_benefit, cr.calc_date, cr.release_cutoff FROM release_candidate rc JOIN calculation_run cr ON cr.calculation_run_id=rc.calculation_run_id WHERE rc.order_id=? ORDER BY rc.calculation_run_id DESC LIMIT 1",
                (record_id,),
            ).fetchall()), None)
            payload["entitlement"] = next((dict(item) for item in connection.execute(
                """
                SELECT ec.consistency, ec.theoretical_activity_benefit, ec.theoretical_coupon_benefit,
                       ec.gift_qty_entitled, ec.gift_qty_actual, ec.formula_ref, ec.activity_benefit, ec.coupon_benefit
                FROM entitlement_check ec
                JOIN calculation_run cr ON cr.calculation_run_id=ec.calculation_run_id
                WHERE ec.order_id=?
                ORDER BY ec.calculation_run_id DESC LIMIT 1
                """,
                (record_id,),
            ).fetchall()), None)
    return payload


# ---------------------------------------------------------------------------
# 费用核算：按当前批次的最新 calculation_run 读取 activity_fee_summary / calculation_quality_issue
# ---------------------------------------------------------------------------

def _requested_run(connection: sqlite3.Connection, params: dict[str, Any]) -> int | None:
    raw = params.get("calc_batch_id")
    if raw in (None, ""):
        return None
    try:
        run_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("calc_batch_id must be an integer") from exc
    if connection.execute("SELECT 1 FROM calculation_run WHERE calculation_run_id=?", (run_id,)).fetchone() is None:
        raise NotFoundError("calc_batch_id")
    return run_id


def _fee_runs(connection: sqlite3.Connection, params: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    """Calculation runs in scope: one pinned run, or the latest run of every current import batch."""
    run_id = _requested_run(connection, params)
    dealer = str(params.get("dealer", "")).strip()
    platform = str(params.get("platform", "")).strip()
    clauses, values = [], []
    if run_id is None:
        clauses.append("ib.is_current=1 AND cr.calculation_run_id=(SELECT MAX(calculation_run_id) FROM calculation_run WHERE import_batch_id=ib.import_batch_id)")
    else:
        clauses.append("cr.calculation_run_id=?"); values.append(run_id)
    if dealer:
        clauses.append("ib.dealer_name LIKE ?"); values.append(f"%{dealer}%")
    if platform:
        clauses.append("ib.platform_name LIKE ?"); values.append(f"%{platform}%")
    rows = [dict(row) for row in connection.execute(
        "SELECT cr.*, ib.dealer_name, ib.platform_name, ib.coverage_start, ib.coverage_end FROM calculation_run cr JOIN import_batch ib ON ib.import_batch_id=cr.import_batch_id WHERE "
        + " AND ".join(clauses) + " ORDER BY cr.calculation_run_id",
        values,
    ).fetchall()]
    return rows, run_id


def _fee_activity_rows(connection: sqlite3.Connection, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not runs:
        return []
    placeholders = ",".join("?" for _ in runs)
    return [dict(row) for row in connection.execute(
        f"""
        SELECT a.activity_id, a.activity_no, a.activity_name, a.activity_type, a.start_time, a.end_time,
               ib.dealer_name, ib.platform_name, cr.calculation_run_id, cr.calc_date, cr.release_cutoff, cr.import_batch_id,
               s.actual_discount_total, s.participating_orders, s.released_orders, s.released_amount, s.pending_orders, s.pending_amount
        FROM activity_fee_summary s
        JOIN activity a ON a.activity_id=s.activity_id
        JOIN calculation_run cr ON cr.calculation_run_id=s.calculation_run_id
        JOIN import_batch ib ON ib.import_batch_id=cr.import_batch_id
        WHERE s.calculation_run_id IN ({placeholders})
        ORDER BY cr.calculation_run_id, a.activity_id
        """,
        [run["calculation_run_id"] for run in runs],
    ).fetchall()]


def _issues_for_runs(connection: sqlite3.Connection, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not runs:
        return []
    placeholders = ",".join("?" for _ in runs)
    issues = [dict(row) for row in connection.execute(
        f"""
        SELECT qi.calculation_quality_issue_id AS issue_id, qi.calculation_run_id, qi.order_no, qi.issue_type, qi.level, qi.reason,
               (SELECT GROUP_CONCAT(DISTINCT ae.activity_id) FROM activity_execution ae JOIN order_header oh ON oh.order_id=ae.order_id
                 WHERE oh.order_no=qi.order_no AND oh.import_batch_id=cr.import_batch_id) AS activity_ids
        FROM calculation_quality_issue qi JOIN calculation_run cr ON cr.calculation_run_id=qi.calculation_run_id
        WHERE qi.calculation_run_id IN ({placeholders}) ORDER BY qi.calculation_quality_issue_id
        """,
        [run["calculation_run_id"] for run in runs],
    ).fetchall()]
    for issue in issues:
        ids = [int(value) for value in (issue.pop("activity_ids") or "").split(",") if value]
        issue["activityId"] = ids[0] if len(ids) == 1 else None
    return issues


def _activity_status(row: dict[str, Any], kind: str, issues: list[dict[str, Any]]) -> str:
    related = [issue for issue in issues if issue["activityId"] == row["activity_id"] and issue["calculation_run_id"] == row["calculation_run_id"]]
    if any(issue["level"] == "警告" and issue["issue_type"] not in ("理论权益与实际执行不一致",) for issue in related):
        return "待处理"
    if kind == "money" and float(row["released_amount"] or 0) > 0:
        return "可提交"
    if row["released_orders"]:
        return "已核验"
    return "待确认"


def _activity_payload(row: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    kind = "gift" if "赠" in (row["activity_type"] or "") else "money"
    related = [issue for issue in issues if issue["activityId"] == row["activity_id"] and issue["calculation_run_id"] == row["calculation_run_id"]]
    return {
        "activityId": row["activity_id"], "activityNo": row["activity_no"], "activityName": row["activity_name"], "dealer": row["dealer_name"], "platform": row["platform_name"],
        "promotionType": row["activity_type"], "benefitKind": kind, "startTime": row["start_time"], "endTime": row["end_time"],
        "importBatchId": row["import_batch_id"], "calcBatchId": row["calculation_run_id"], "calcDate": row["calc_date"], "releaseCutoff": row["release_cutoff"],
        "actualDiscountTotal": row["actual_discount_total"], "settleAmount": row["released_amount"] if kind == "money" else None,
        "participatingOrders": row["participating_orders"], "releasedOrders": row["released_orders"], "releasedAmount": row["released_amount"],
        "pendingOrders": row["pending_orders"], "pendingAmount": row["pending_amount"],
        "warningCount": sum(issue["level"] == "警告" for issue in related), "tipCount": sum(issue["level"] == "提示" for issue in related),
        "status": _activity_status(row, kind, issues),
    }


def query_fee_tpm_activities(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    limit, offset = _bounds(params)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        runs, run_id = _fee_runs(connection, params)
        rows = _fee_activity_rows(connection, runs)
        issues = _issues_for_runs(connection, runs)
    payload_rows = [_activity_payload(row, issues) for row in rows]
    return {"mode": "historical" if run_id is not None else "current", "calcBatchId": run_id, "rows": payload_rows[offset:offset + limit], "total": len(payload_rows), "limit": limit, "offset": offset}


def query_fee_tpm_issues(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    limit, offset = _bounds(params)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        runs, run_id = _fee_runs(connection, params)
        issues = _issues_for_runs(connection, runs)
    payload = [{"issueId": issue["issue_id"], "orderNo": issue["order_no"], "issueType": issue["issue_type"], "level": issue["level"], "reason": issue["reason"], "evidence": None, "calcBatchId": issue["calculation_run_id"], "activityId": issue["activityId"]} for issue in issues]
    return {"mode": "historical" if run_id is not None else "current", "calcBatchId": run_id, "rows": payload[offset:offset + limit], "total": len(payload), "limit": limit, "offset": offset}


def query_fee_tpm_settlements(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    activities = query_fee_tpm_activities(db_path, {**params, "limit": 500, "offset": 0})
    rows = [row for row in activities["rows"] if row["benefitKind"] == "money" and row["status"] == "可提交" and row["settleAmount"] is not None]
    return {**activities, "rows": rows, "total": len(rows)}


def query_fee_tpm_overview(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    activities = query_fee_tpm_activities(db_path, {**params, "limit": 500, "offset": 0})
    rows = activities["rows"]
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        runs, _ = _fee_runs(connection, params)
    return {
        "mode": activities["mode"], "calcBatchId": activities["calcBatchId"], "activityCount": len(rows),
        "submittableAmount": round(sum(float(row["settleAmount"] or 0) for row in rows if row["status"] == "可提交"), 2),
        "couponBenefit": round(sum(float(run["coupon_benefit"] or 0) for run in runs), 2),
        "releasedCouponBenefit": round(sum(float(run["released_coupon_benefit"] or 0) for run in runs), 2),
        "theoreticalActivityBenefit": round(sum(float(run["theoretical_activity_benefit"] or 0) for run in runs), 2),
        "theoreticalCouponBenefit": round(sum(float(run["theoretical_coupon_benefit"] or 0) for run in runs), 2),
        "consistentOrders": sum(int(run["consistent_orders"] or 0) for run in runs),
        "participatingOrders": sum(int(run["participating_orders"] or 0) for run in runs),
        "releasedOrders": sum(int(run["released_orders"] or 0) for run in runs),
        "giftReleasedOrders": sum(int(row["releasedOrders"] or 0) for row in rows if row["benefitKind"] == "gift"),
        "waitingCount": sum(row["status"] == "待确认" for row in rows), "handlingCount": sum(row["status"] == "待处理" for row in rows),
        "runs": [{"calcBatchId": run["calculation_run_id"], "importBatchId": run["import_batch_id"], "dealer": run["dealer_name"], "platform": run["platform_name"], "coverageStart": run["coverage_start"], "coverageEnd": run["coverage_end"], "calcDate": run["calc_date"], "releaseCutoff": run["release_cutoff"]} for run in runs],
        "activities": rows,
    }


def query_fee_tpm_coupons(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """One row per coupon_config on the current (or pinned) calculation runs."""
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        runs, run_id = _fee_runs(connection, params)
        if not runs:
            return {"mode": "historical" if run_id is not None else "current", "calcBatchId": run_id, "rows": [], "total": 0}
        placeholders = ",".join("?" for _ in runs)
        rows = [dict(row) for row in connection.execute(
            f"""
            SELECT cc.coupon_config_id, cc.config_no, cc.coupon_name, cc.coupon_type, cc.config_status,
                   ib.dealer_name, ib.platform_name, cr.calculation_run_id, cr.calc_date, cr.release_cutoff, cr.import_batch_id,
                   COUNT(red.coupon_redemption_id) AS participating_orders,
                   COALESCE(SUM(red.discount_amount), 0) AS coupon_benefit,
                   COALESCE(SUM(CASE WHEN rc.is_candidate=1 THEN red.discount_amount ELSE 0 END), 0) AS released_coupon_benefit
            FROM coupon_config cc
            JOIN import_batch ib ON ib.import_batch_id=cc.import_batch_id
            JOIN calculation_run cr ON cr.import_batch_id=ib.import_batch_id
            LEFT JOIN coupon_redemption red ON red.import_batch_id=cc.import_batch_id
            LEFT JOIN release_candidate rc ON rc.order_id=red.order_id AND rc.calculation_run_id=cr.calculation_run_id
            WHERE cr.calculation_run_id IN ({placeholders})
            GROUP BY cc.coupon_config_id
            ORDER BY cr.calculation_run_id, cc.coupon_config_id
            """,
            [run["calculation_run_id"] for run in runs],
        ).fetchall()]
    payload = [{
        "couponConfigId": row["coupon_config_id"], "configNo": row["config_no"], "couponName": row["coupon_name"],
        "couponType": row["coupon_type"], "dealer": row["dealer_name"], "platform": row["platform_name"],
        "importBatchId": row["import_batch_id"], "calcBatchId": row["calculation_run_id"],
        "calcDate": row["calc_date"], "releaseCutoff": row["release_cutoff"],
        "participatingOrders": row["participating_orders"], "couponBenefit": row["coupon_benefit"],
        "releasedCouponBenefit": row["released_coupon_benefit"], "status": "可提交" if row["released_coupon_benefit"] else "待确认",
        "benefitKind": "coupon",
    } for row in rows]
    return {"mode": "historical" if run_id is not None else "current", "calcBatchId": run_id, "rows": payload, "total": len(payload)}


def query_fee_tpm_roi(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """One ROI row per current (or pinned) activity with redemptions, plus each coupon config."""
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        runs, run_id = _fee_runs(connection, params)
        rows: list[dict[str, Any]] = []
        for run in runs:
            for (activity_id,) in connection.execute(
                """
                SELECT activity_id FROM activity a
                WHERE a.import_batch_id=?
                  AND EXISTS (SELECT 1 FROM activity_execution ae WHERE ae.activity_id=a.activity_id)
                ORDER BY a.activity_id
                """,
                (run["import_batch_id"],),
            ):
                payload = activity_roi(connection, activity_id)
                rows.append({**payload, "dealer": run["dealer_name"], "platform": run["platform_name"], "calcBatchId": run["calculation_run_id"]})
            for (coupon_id,) in connection.execute(
                "SELECT coupon_config_id FROM coupon_config WHERE import_batch_id=? ORDER BY coupon_config_id",
                (run["import_batch_id"],),
            ):
                payload = coupon_roi(connection, coupon_id)
                rows.append({**payload, "dealer": run["dealer_name"], "platform": run["platform_name"], "calcBatchId": run["calculation_run_id"]})
    return {"mode": "historical" if run_id is not None else "current", "calcBatchId": run_id, "rows": rows, "total": len(rows)}


def query_fee_tpm_activity_detail(db_path: Path, activity_id: str, params: dict[str, Any]) -> dict[str, Any] | None:
    payload = query_fee_tpm_activities(db_path, {**params, "limit": 500, "offset": 0})
    for row in payload["rows"]:
        if row["activityId"] == int(activity_id):
            issues = query_fee_tpm_issues(db_path, {**params, "limit": 500, "offset": 0})["rows"]
            return {**row, "issues": [issue for issue in issues if issue["activityId"] == row["activityId"]]}
    return None


def _cors_origin(handler: BaseHTTPRequestHandler) -> str:
    origin = handler.headers.get("Origin", "").strip()
    return origin or "*"


def _xlsx(handler: BaseHTTPRequestHandler, filename: str, body: bytes) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    handler.send_header("Content-Disposition", content_disposition(filename))
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", _cors_origin(handler))
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Vary", "Origin")
    handler.end_headers()
    handler.wfile.write(body)


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", _cors_origin(handler))
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Vary", "Origin")
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(db_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", _cors_origin(self))
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path not in ("/api/imports", "/imports"):
                _json(self, 404, {"error": "not_found"})
                return
            try:
                form = FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")})
                workbook_field = form["workbook"] if "workbook" in form else None
                if workbook_field is None or not getattr(workbook_field, "file", None):
                    _json(self, 400, {"error": "workbook_required"})
                    return
                source_field = form["sources"] if "sources" in form else None
                source_bytes = source_field.file.read() if source_field is not None and getattr(source_field, "file", None) else None
                source_name = getattr(source_field, "filename", None) or "sources.zip"
                calc_date = form.getfirst("calc_date", "") if "calc_date" in form else ""
                payload = import_uploaded_files(db_path, workbook_field.file.read(), source_bytes, source_name, str(calc_date or "").strip() or None)
                _json(self, 201, payload)
            except ImportValidationError as exc:
                _json(self, 422, {"error": "validation_failed", "issues": [issue.__dict__ for issue in exc.issues]})
            except (KeyError, ValueError, OSError) as exc:
                _json(self, 400, {"error": "invalid_import", "message": str(exc)})
            except sqlite3.Error as exc:
                _json(self, 500, {"error": "database_error", "message": str(exc)})

        def do_GET(self):
            parsed = urlparse(self.path)
            parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
            try:
                if parts == ["health"]:
                    _json(self, 200, {"status": "ok", "database": str(db_path), "schema": "standard", "objects": list(SUPPORTED_OBJECTS), "schema_issues": schema_differences(db_path) if db_path.exists() else ["数据库文件不存在"]})
                    return
                if parts in (["api", "imports"], ["imports"]):
                    _json(self, 200, list_imports(db_path)); return
                if len(parts) in (2, 3) and ((len(parts) == 3 and parts[:2] == ["api", "imports"]) or (len(parts) == 2 and parts[0] == "imports")):
                    import_batch_id = int(parts[-1])
                    detail = get_import(db_path, import_batch_id)
                    _json(self, 200, detail) if detail is not None else _json(self, 404, {"error": "not_found"})
                    return
                if len(parts) in (3, 4) and ((len(parts) == 4 and parts[:2] == ["api", "imports"]) or (len(parts) == 3 and parts[0] == "imports")) and parts[-1] == "issues":
                    import_batch_id = int(parts[-2])
                    if get_import(db_path, import_batch_id) is None:
                        _json(self, 404, {"error": "not_found"})
                    else:
                        _json(self, 200, {"rows": get_import_issues(db_path, import_batch_id)})
                    return
                if len(parts) in (3, 4) and ((len(parts) == 4 and parts[:2] == ["api", "imports"]) or (len(parts) == 3 and parts[0] == "imports")) and parts[-1] == "release":
                    query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
                    release = get_import_release(db_path, int(parts[-2]), query)
                    _json(self, 200, release) if release is not None else _json(self, 404, {"error": "not_found"})
                    return
                if len(parts) >= 3 and parts[:2] == ["api", "business-data"]:
                    object_name = parts[2]
                    if len(parts) == 4:
                        detail = get_detail(db_path, object_name, parts[3])
                        if detail is None:
                            _json(self, 404, {"error": "not_found"})
                        else:
                            _json(self, 200, detail)
                        return
                    query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
                    _json(self, 200, query_dataset(db_path, object_name, query))
                    return
                if len(parts) >= 3 and parts[:2] == ["api", "fee-tpm"]:
                    query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
                    endpoint = parts[2]
                    if endpoint == "overview" and len(parts) == 3:
                        _json(self, 200, query_fee_tpm_overview(db_path, query)); return
                    if endpoint == "activities" and len(parts) == 3:
                        _json(self, 200, query_fee_tpm_activities(db_path, query)); return
                    if endpoint == "activities" and len(parts) == 4:
                        detail = query_fee_tpm_activity_detail(db_path, parts[3], query)
                        _json(self, 200, detail) if detail is not None else _json(self, 404, {"error": "not_found"})
                        return
                    if endpoint == "activities" and len(parts) == 5 and parts[4] == "verification-report":
                        if not query.get("calc_batch_id"):
                            raise ValueError("calc_batch_id is required")
                        try:
                            body, filename = build_activity_report(db_path, int(parts[3]), int(query["calc_batch_id"]))
                        except KeyError as exc:
                            raise NotFoundError(str(exc)) from exc
                        _xlsx(self, filename, body)
                        return
                    if endpoint == "coupons" and len(parts) == 3:
                        _json(self, 200, query_fee_tpm_coupons(db_path, query)); return
                    if endpoint == "coupons" and len(parts) == 5 and parts[4] == "verification-report":
                        coupon_id = int(parts[3])
                        calc_id = int(query["calc_batch_id"]) if query.get("calc_batch_id") else None
                        if calc_id is None:
                            raise ValueError("calc_batch_id is required")
                        try:
                            body, filename = build_coupon_report(db_path, coupon_id, calc_id)
                        except KeyError as exc:
                            raise NotFoundError(str(exc)) from exc
                        _xlsx(self, filename, body)
                        return
                    if endpoint == "roi.xlsx" and len(parts) == 3:
                        body, filename = build_roi_workbook(query_fee_tpm_roi(db_path, query)["rows"])
                        _xlsx(self, filename, body)
                        return
                    if endpoint == "roi" and len(parts) == 3:
                        _json(self, 200, query_fee_tpm_roi(db_path, query)); return
                    if endpoint == "issues" and len(parts) == 3:
                        _json(self, 200, query_fee_tpm_issues(db_path, query)); return
                    if endpoint == "settlements" and len(parts) == 3:
                        _json(self, 200, query_fee_tpm_settlements(db_path, query)); return
                _json(self, 404, {"error": "not_found"})
            except NotFoundError:
                _json(self, 404, {"error": "not_found"})
            except KeyError:
                _json(self, 404, {"error": "unsupported_object", "objects": list(SUPPORTED_OBJECTS)})
            except ValueError as exc:
                _json(self, 400, {"error": "invalid_query", "message": str(exc)})
            except sqlite3.Error as exc:
                _json(self, 500, {"error": "database_error", "message": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def serve(host: str = "0.0.0.0", port: int = 8787, db_path: Path = DEFAULT_DB_PATH) -> None:
    ensure_database(db_path)
    server = ThreadingHTTPServer((host, port), make_handler(db_path))
    print(f"EC101 API: http://{host}:{port} (standard database: {db_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EC101 local read-only API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    serve(args.host, args.port, args.db)
