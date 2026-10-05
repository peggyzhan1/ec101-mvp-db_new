"""Cross-platform, read-only HTTP API for the EC101 SQLite business facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from cgi import FieldStorage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from mvp.import_service import ArchiveMetadata, ImportValidationError, create_database, import_snapshot
from mvp.standard_workbook import read_standard_workbook


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "mvp" / "ec101_mvp.db"


def import_uploaded_files(db_path: Path, workbook_bytes: bytes, source_bytes: bytes | None = None, source_name: str = "sources.zip") -> dict[str, Any]:
    """Import one uploaded standard workbook and archive metadata without storing raw rows."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ec101-import-") as directory:
        root = Path(directory)
        workbook_path = root / "standard.xlsx"
        workbook_path.write_bytes(workbook_bytes)
        source_name = Path(source_name).name or "sources.zip"
        source_path = root / source_name
        source_path.write_bytes(source_bytes or b"")
        if not db_path.exists() or not _has_table(db_path, "import_batch"):
            create_database(db_path)
        workbook = read_standard_workbook(workbook_path)
        source_hash = hashlib.sha256(source_bytes or b"").hexdigest()
        archive_path = db_path.parent / "archives" / f"{source_hash[:16]}-{source_name}"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(source_bytes or b"")
        archive = ArchiveMetadata(str(archive_path), source_hash, len(source_bytes or b""))
        with sqlite3.connect(db_path) as connection:
            result = import_snapshot(connection, workbook, archive)
        return {"import_batch_id": result.import_batch_id, "calculation_run_id": result.calculation_run_id, "status": result.status}


def _has_table(db_path: Path, table_name: str) -> bool:
    with sqlite3.connect(db_path) as connection:
        return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone() is not None


class NotFoundError(KeyError):
    """A requested, immutable calculation batch or activity does not exist."""


def _config(select: str, joins: str, search: tuple[str, ...], id_column: str, order: str):
    return {"select": select, "joins": joins, "search": search, "id_column": id_column, "order": order}


CONFIGS = {
    "orders": _config(
        "oh.order_id AS id, oh.order_no, dp.dealer_name AS dealer, dp.platform_name AS platform, c.customer_name AS customer, oh.order_time, oh.order_status, oh.batch_id AS source_batch",
        "JOIN dealer_platform dp ON dp.dealer_platform_id = oh.dealer_platform_id LEFT JOIN customer c ON c.customer_id = oh.customer_id",
        ("oh.order_no", "c.customer_name", "oh.order_status"),
        "oh.order_id",
        "oh.order_id",
    ),
    "order-lines": _config(
        "ol.order_line_id AS id, oh.order_no, dp.dealer_name AS dealer, dp.platform_name AS platform, p.product_name AS product, p.platform_product_no AS product_no, ol.order_qty, ol.order_unit, ol.pre_discount_amount, ol.discount_amount",
        "JOIN order_header oh ON oh.order_id = ol.order_id JOIN dealer_platform dp ON dp.dealer_platform_id = oh.dealer_platform_id LEFT JOIN product p ON p.product_id = ol.product_id",
        ("oh.order_no", "p.product_name", "p.platform_product_no"),
        "ol.order_line_id",
        "ol.order_line_id",
    ),
    "activities": _config(
        "a.activity_id AS id, a.activity_name, dp.dealer_name AS dealer, dp.platform_name AS platform, a.promotion_type, a.start_time, a.end_time, a.activity_status, a.rule_version",
        "JOIN dealer_platform dp ON dp.dealer_platform_id = a.dealer_platform_id",
        ("a.activity_name", "a.promotion_type", "a.activity_status"),
        "a.activity_id",
        "a.activity_id",
    ),
    "activity-details": _config(
        "oa.order_activity_id AS id, oh.order_no, dp.dealer_name AS dealer, dp.platform_name AS platform, a.activity_name, oa.activity_product_amount, oa.platform_actual_benefit, oa.gift_qty_actual, oa.exec_status, oa.evidence_ref",
        "JOIN order_header oh ON oh.order_id = oa.order_id JOIN dealer_platform dp ON dp.dealer_platform_id = oh.dealer_platform_id JOIN activity a ON a.activity_id = oa.activity_id",
        ("oh.order_no", "a.activity_name", "oa.exec_status"),
        "oa.order_activity_id",
        "oa.order_activity_id",
    ),
    "customers": _config(
        "c.customer_id AS id, c.platform_customer_no AS customer_no, dp.dealer_name AS dealer, dp.platform_name AS platform, c.customer_name, c.customer_type, c.customer_level, c.customer_region, c.salesperson_name, c.status",
        "JOIN dealer_platform dp ON dp.dealer_platform_id = c.dealer_platform_id",
        ("c.platform_customer_no", "c.customer_name", "c.customer_region", "c.salesperson_name"),
        "c.customer_id",
        "c.customer_id",
    ),
    "products": _config(
        "p.product_id AS id, p.platform_product_no AS product_no, dp.dealer_name AS dealer, dp.platform_name AS platform, p.product_name, p.brand, p.category, p.spec, p.base_unit, p.shelf_status",
        "JOIN dealer_platform dp ON dp.dealer_platform_id = p.dealer_platform_id",
        ("p.platform_product_no", "p.product_name", "p.brand", "p.category"),
        "p.product_id",
        "p.product_id",
    ),
    "fulfillments": _config(
        "f.fulfillment_id AS id, oh.order_no, dp.dealer_name AS dealer, dp.platform_name AS platform, f.order_status, f.completed_at, f.t2_release_candidate, f.return_qty, f.special_reason",
        "JOIN order_header oh ON oh.order_id = f.order_id JOIN dealer_platform dp ON dp.dealer_platform_id = oh.dealer_platform_id",
        ("oh.order_no", "f.order_status", "f.special_reason"),
        "f.fulfillment_id",
        "f.fulfillment_id",
    ),
    "order-activities": _config(
        "oa.order_activity_id AS id, oh.order_no, dp.dealer_name AS dealer, dp.platform_name AS platform, a.activity_name, ar.threshold_value, ar.reduce_amount, oa.activity_product_amount, oa.platform_actual_benefit, oa.exec_status",
        "JOIN order_header oh ON oh.order_id = oa.order_id JOIN dealer_platform dp ON dp.dealer_platform_id = oh.dealer_platform_id JOIN activity a ON a.activity_id = oa.activity_id LEFT JOIN activity_rule ar ON ar.rule_id = oa.rule_id",
        ("oh.order_no", "a.activity_name", "oa.exec_status"),
        "oa.order_activity_id",
        "oa.order_activity_id",
    ),
}
SUPPORTED_OBJECTS = tuple(CONFIGS)


def _conditions(config: dict[str, Any], params: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    dealer = str(params.get("dealer", "")).strip()
    platform = str(params.get("platform", "")).strip()
    search = str(params.get("q", "")).strip()
    if dealer:
        clauses.append("dp.dealer_name LIKE ?")
        values.append(f"%{dealer}%")
    if platform:
        clauses.append("dp.platform_name LIKE ?")
        values.append(f"%{platform}%")
    if search:
        clauses.append("(" + " OR ".join(f"{column} LIKE ?" for column in config["search"]) + ")")
        values.extend([f"%{search}%"] * len(config["search"]))
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", values


def _bounds(params: dict[str, Any]) -> tuple[int, int]:
    try:
        limit = min(max(int(params.get("limit", 50)), 1), 100)
        offset = min(max(int(params.get("offset", 0)), 0), 10000)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit and offset must be integers") from exc
    return limit, offset


def query_dataset(db_path: Path, object_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if object_name not in CONFIGS:
        raise KeyError(object_name)
    config = CONFIGS[object_name]
    where, values = _conditions(config, params)
    limit, offset = _bounds(params)
    base = f"SELECT {config['select']} FROM { {'orders':'order_header oh','order-lines':'order_line ol','activities':'activity a','activity-details':'order_activity oa','customers':'customer c','products':'product p','fulfillments':'fulfillment f','order-activities':'order_activity oa'}[object_name] } {config['joins']}"
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        total = connection.execute(f"SELECT COUNT(*) FROM ({base}{where})", values).fetchone()[0]
        rows = [dict(row) for row in connection.execute(f"{base}{where} ORDER BY {config['order']} LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()]
    return {"object": object_name, "columns": list(rows[0].keys()) if rows else [], "rows": rows, "total": total, "limit": limit, "offset": offset}


def get_detail(db_path: Path, object_name: str, record_id: str) -> dict[str, Any] | None:
    if object_name not in CONFIGS:
        raise KeyError(object_name)
    config = CONFIGS[object_name]
    bases = {"orders":"order_header oh", "order-lines":"order_line ol", "activities":"activity a", "activity-details":"order_activity oa", "customers":"customer c", "products":"product p", "fulfillments":"fulfillment f", "order-activities":"order_activity oa"}
    base = f"SELECT {config['select']} FROM {bases[object_name]} {config['joins']} WHERE {config['id_column']} = ?"
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(base, (record_id,)).fetchone()
    return dict(row) if row else None


def _fee_tpm_bounds(params: dict[str, Any]) -> tuple[int, int]:
    return _bounds(params)


def _requested_batch(connection: sqlite3.Connection, params: dict[str, Any]) -> int | None:
    raw = params.get("calc_batch_id")
    if raw in (None, ""):
        return None
    try:
        batch_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("calc_batch_id must be an integer") from exc
    if connection.execute("SELECT 1 FROM result_calc_batch WHERE calc_batch_id=?", (batch_id,)).fetchone() is None:
        raise NotFoundError("calc_batch_id")
    return batch_id


def _fee_activity_rows(connection: sqlite3.Connection, params: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    batch_id = _requested_batch(connection, params)
    dealer = str(params.get("dealer", "")).strip()
    platform = str(params.get("platform", "")).strip()
    clauses, values = [], []
    if dealer:
        clauses.append("dp.dealer_name LIKE ?"); values.append(f"%{dealer}%")
    if platform:
        clauses.append("dp.platform_name LIKE ?"); values.append(f"%{platform}%")
    if batch_id is None:
        batch_clause = "rf.calc_batch_id=(SELECT MAX(current_fee.calc_batch_id) FROM result_fee current_fee WHERE current_fee.activity_id=a.activity_id)"
    else:
        batch_clause = "rf.calc_batch_id=?"; values.append(batch_id)
    where = " WHERE " + " AND ".join([batch_clause, *clauses])
    sql = """
        SELECT a.activity_id, a.activity_name, a.activity_category, a.promotion_type, a.rule_version,
               dp.dealer_name, dp.platform_name, rf.tpm_id, rf.actual_discount_total, rf.gift_cost_total,
               rf.settle_amount, rf.diff_amount, rf.settle_status, rf.calc_batch_id,
               cb.calc_date, cb.rule_version AS calc_rule_version,
               t.tpm_code, t.apply_amount, t.budget_reserve_no, t.fee_pay_dept,
               COALESCE(SUM(re.gift_qty_entitled), 0) AS gift_qty_entitled,
               COALESCE(SUM(re.gift_qty_actual), 0) AS gift_qty_actual,
               COALESCE(SUM(CASE WHEN rc.is_candidate=1 THEN 1 ELSE 0 END), 0) AS release_candidates
        FROM activity a
        JOIN dealer_platform dp ON dp.dealer_platform_id=a.dealer_platform_id
        JOIN result_fee rf ON rf.activity_id=a.activity_id
        JOIN result_calc_batch cb ON cb.calc_batch_id=rf.calc_batch_id
        LEFT JOIN tpm_application t ON t.tpm_id=rf.tpm_id
        LEFT JOIN order_activity oa ON oa.activity_id=a.activity_id
        LEFT JOIN result_entitlement re ON re.order_activity_id=oa.order_activity_id AND re.calc_batch_id=rf.calc_batch_id
        LEFT JOIN result_release_candidate rc ON rc.order_id=oa.order_id AND rc.calc_batch_id=rf.calc_batch_id
    """ + where + " GROUP BY a.activity_id,rf.calc_batch_id ORDER BY a.activity_id"
    return [dict(row) for row in connection.execute(sql, values).fetchall()], batch_id


def _issues_for_batches(connection: sqlite3.Connection, batch_ids: set[int]) -> list[dict[str, Any]]:
    if not batch_ids:
        return []
    placeholders = ",".join("?" for _ in batch_ids)
    issues = [dict(row) for row in connection.execute(f"SELECT * FROM result_quality_issue WHERE calc_batch_id IN ({placeholders}) ORDER BY issue_id", list(batch_ids)).fetchall()]
    for issue in issues:
        if not issue["order_no"]:
            issue["activityId"] = None
            continue
        activity_ids = [row[0] for row in connection.execute("SELECT DISTINCT oa.activity_id FROM order_activity oa JOIN order_header oh ON oh.order_id=oa.order_id WHERE oh.order_no=?", (issue["order_no"],)).fetchall()]
        issue["activityId"] = activity_ids[0] if len(activity_ids) == 1 else None
    return issues


def _activity_status(row: dict[str, Any], issues: list[dict[str, Any]]) -> str:
    related = [issue for issue in issues if issue["activityId"] == row["activity_id"] and issue["calc_batch_id"] == row["calc_batch_id"]]
    if any(issue["level"] == "警告" for issue in related):
        return "待处理"
    if any(issue["level"] == "提示" for issue in related):
        return "待确认"
    if row["settle_amount"] is not None and row["release_candidates"] and row["tpm_id"] is not None:
        return "可提交"
    return "已核验"


def _activity_payload(row: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    kind = "gift" if "赠" in (row["promotion_type"] or "") else "money"
    return {
        "activityId": row["activity_id"], "activityName": row["activity_name"], "dealer": row["dealer_name"], "platform": row["platform_name"],
        "promotionType": row["promotion_type"], "benefitKind": kind, "ruleVersion": row["rule_version"], "calcBatchId": row["calc_batch_id"], "calcDate": row["calc_date"],
        "tpm": None if row["tpm_id"] is None else {"id": row["tpm_id"], "code": row["tpm_code"], "budgetAmount": row["apply_amount"], "budgetReserveNo": row["budget_reserve_no"], "feeBearer": row["fee_pay_dept"]},
        "actualDiscountTotal": row["actual_discount_total"], "settleAmount": row["settle_amount"], "budgetRemaining": row["diff_amount"],
        "giftQtyEntitled": row["gift_qty_entitled"] if kind == "gift" else None, "giftQtyActual": row["gift_qty_actual"] if kind == "gift" else None,
        "releaseCandidates": row["release_candidates"], "warningCount": sum(issue["level"] == "警告" and issue["activityId"] == row["activity_id"] for issue in issues), "tipCount": sum(issue["level"] == "提示" and issue["activityId"] == row["activity_id"] for issue in issues),
        "status": _activity_status(row, issues),
    }


def query_fee_tpm_activities(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    limit, offset = _fee_tpm_bounds(params)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows, batch_id = _fee_activity_rows(connection, params)
        issues = _issues_for_batches(connection, {row["calc_batch_id"] for row in rows})
    payload_rows = [_activity_payload(row, issues) for row in rows]
    return {"mode": "historical" if batch_id is not None else "current", "calcBatchId": batch_id, "rows": payload_rows[offset:offset + limit], "total": len(payload_rows), "limit": limit, "offset": offset}


def query_fee_tpm_issues(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    limit, offset = _fee_tpm_bounds(params)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows, batch_id = _fee_activity_rows(connection, params)
        issues = _issues_for_batches(connection, {row["calc_batch_id"] for row in rows})
    payload = [{"issueId": issue["issue_id"], "orderNo": issue["order_no"], "issueType": issue["issue_type"], "level": issue["level"], "reason": issue["reason"], "evidence": issue["evidence_ref"], "calcBatchId": issue["calc_batch_id"], "activityId": issue["activityId"]} for issue in issues]
    return {"mode": "historical" if batch_id is not None else "current", "calcBatchId": batch_id, "rows": payload[offset:offset + limit], "total": len(payload), "limit": limit, "offset": offset}


def query_fee_tpm_settlements(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    activities = query_fee_tpm_activities(db_path, {**params, "limit": 100, "offset": 0})
    rows = [row for row in activities["rows"] if row["benefitKind"] == "money" and row["status"] == "可提交" and row["settleAmount"] is not None]
    return {**activities, "rows": rows, "total": len(rows)}


def query_fee_tpm_overview(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    activities = query_fee_tpm_activities(db_path, {**params, "limit": 100, "offset": 0})
    rows = activities["rows"]
    return {"mode": activities["mode"], "calcBatchId": activities["calcBatchId"], "activityCount": len(rows), "submittableAmount": sum(float(row["settleAmount"] or 0) for row in rows if row["status"] == "可提交"), "giftQtyActual": sum(float(row["giftQtyActual"] or 0) for row in rows), "waitingCount": sum(row["status"] == "待确认" for row in rows), "handlingCount": sum(row["status"] == "待处理" for row in rows), "activities": rows}


def query_fee_tpm_activity_detail(db_path: Path, activity_id: str, params: dict[str, Any]) -> dict[str, Any] | None:
    payload = query_fee_tpm_activities(db_path, {**params, "limit": 100, "offset": 0})
    for row in payload["rows"]:
        if row["activityId"] == int(activity_id):
            issues = query_fee_tpm_issues(db_path, params)["rows"]
            return {**row, "issues": [issue for issue in issues if issue["activityId"] == row["activityId"]]}
    return None


def _cors_origin(handler: BaseHTTPRequestHandler) -> str:
    origin = handler.headers.get("Origin", "")
    return origin if origin.startswith(("http://localhost:", "http://127.0.0.1:")) else "null"


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", _cors_origin(handler))
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(db_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", _cors_origin(self))
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != "/api/imports":
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
                payload = import_uploaded_files(db_path, workbook_field.file.read(), source_bytes, source_name)
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
                    _json(self, 200, {"status": "ok", "database": str(db_path), "objects": list(SUPPORTED_OBJECTS), "read_only": True})
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


def serve(host: str = "127.0.0.1", port: int = 8787, db_path: Path = DEFAULT_DB_PATH) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(db_path))
    print(f"EC101 read-only API: http://{host}:{port} (database: {db_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EC101 local read-only API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    serve(args.host, args.port, args.db)
