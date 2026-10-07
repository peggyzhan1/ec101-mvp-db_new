"""Generate docs/diagrams/ec101-standard-er.svg and a PNG the chat/GitHub can display."""

from pathlib import Path
from xml.sax.saxutils import escape

DIAGRAMS = Path(__file__).resolve().parents[1] / "docs" / "diagrams"
OUT = DIAGRAMS / "ec101-standard-er.svg"
OUT_PNG = DIAGRAMS / "ec101-standard-er.png"
W, H = 2520, 2320
BOX_W = 305
ROW_H = 26
HEADER_H = 42
# Arial has no CJK glyphs; use a system Chinese font so PNG/SVG stay readable.
FONT = "WenQuanYi Micro Hei, Droid Sans Fallback, Noto Sans CJK SC, sans-serif"

COLORS = {
    "audit": ("#F4EEFF", "#7851A9"),
    "master": ("#E8F5F2", "#167E6D"),
    "order": ("#EEF4FF", "#3B67B1"),
    "activity": ("#FFF4E6", "#B16A13"),
    "coupon": ("#FDECF2", "#B4235A"),
    "result": ("#ECFDF3", "#147D4A"),
}

entities = {
    "import_batch": {"title": "导入批次", "domain": "audit", "xy": (80, 80), "rows": [
        ("import_batch_id", "INTEGER", "PK", "一次导入"),
        ("snapshot_key", "TEXT", "UK", "系统 UUID"),
        ("dealer_name / platform_name", "TEXT", "", "← 导入清单"),
        ("coverage_start / end", "TEXT", "", "← 数据起止日期"),
        ("template / converter", "TEXT", "", "← 版本"),
        ("is_current", "INTEGER", "", "当前有效=1"),
    ]},
    "dealer_platform": {"title": "经销商·平台", "domain": "master", "xy": (460, 80), "rows": [
        ("dealer_platform_id", "INTEGER", "PK", "内部主键"),
        ("dealer_name", "TEXT", "UK", "← 导入清单"),
        ("platform_name", "TEXT", "UK", "← 导入清单"),
    ]},
    "import_file": {"title": "导入归档", "domain": "audit", "xy": (80, 380), "rows": [
        ("import_file_id", "INTEGER", "PK", ""),
        ("import_batch_id", "INTEGER", "FK", "→ import_batch"),
        ("file_path / sha256", "TEXT", "", "sources.zip 归档"),
    ]},
    "import_validation_issue": {"title": "导入校验问题", "domain": "audit", "xy": (460, 380), "rows": [
        ("issue_id", "INTEGER", "PK", ""),
        ("import_batch_id", "INTEGER", "FK", "→ import_batch，可空"),
        ("code / message", "TEXT", "", "校验失败原因"),
        ("sheet_name / row_number", "TEXT/INT", "", "出错的工作表行"),
    ]},
    "customer": {"title": "客户", "domain": "master", "xy": (40, 620), "rows": [
        ("customer_id", "INTEGER", "PK", ""),
        ("import_batch_id", "INTEGER", "FK", "→ import_batch"),
        ("dealer_platform_id", "INTEGER", "FK", "→ dealer_platform"),
        ("customer_no", "TEXT", "UK", "← 客户编号"),
        ("customer_name", "TEXT", "", "← 客户名称"),
        ("salesperson", "TEXT", "", "← 所属业务员"),
    ]},
    "product": {"title": "商品", "domain": "master", "xy": (380, 620), "rows": [
        ("product_id", "INTEGER", "PK", ""),
        ("import_batch_id", "INTEGER", "FK", "→ import_batch"),
        ("dealer_platform_id", "INTEGER", "FK", "→ dealer_platform"),
        ("product_no", "TEXT", "UK", "← 商品编号"),
        ("product_name", "TEXT", "", "← 商品名称"),
        ("brand / spec", "TEXT", "", "← 品牌 / 规格"),
    ]},
    "order_header": {"title": "订单头", "domain": "order", "xy": (720, 620), "rows": [
        ("order_id", "INTEGER", "PK", ""),
        ("import_batch_id", "INTEGER", "FK", "→ import_batch"),
        ("dealer_platform_id", "INTEGER", "FK", "→ dealer_platform"),
        ("order_no", "TEXT", "UK", "← 单据编号"),
        ("customer_no", "TEXT", "", "← 客户编号（文本）"),
        ("order_time / order_status", "TEXT", "", "释放条件看这两列"),
    ]},
    "activity": {"title": "活动", "domain": "activity", "xy": (1060, 620), "rows": [
        ("activity_id", "INTEGER", "PK", ""),
        ("import_batch_id", "INTEGER", "FK", "→ import_batch"),
        ("activity_no", "TEXT", "UK", "← 活动编号"),
        ("activity_name", "TEXT", "", "← 活动名称"),
        ("activity_type", "TEXT", "", "← 满减 / 满赠"),
        ("start_time / end_time", "TEXT", "", "可空"),
    ]},
    "coupon_config": {"title": "优惠券配置", "domain": "coupon", "xy": (1400, 620), "rows": [
        ("coupon_config_id", "INTEGER", "PK", ""),
        ("import_batch_id", "INTEGER", "FK", "→ import_batch"),
        ("config_no", "TEXT", "UK", "← 配置编号"),
        ("coupon_name", "TEXT", "", "← 优惠券名称"),
        ("config_status", "TEXT", "", "← 配置状态"),
    ]},
    "fulfillment": {"title": "履约", "domain": "order", "xy": (1740, 620), "rows": [
        ("fulfillment_id", "INTEGER", "PK", ""),
        ("import_batch_id", "INTEGER", "FK", "→ import_batch"),
        ("order_no", "TEXT", "", "← 单据编号（文本）"),
        ("fulfillment_status", "TEXT", "", "← 履约订单状态"),
        ("completed_at", "TEXT", "", "← 完成时间"),
    ]},
    "order_line": {"title": "订单明细", "domain": "order", "xy": (720, 1100), "rows": [
        ("order_line_id", "INTEGER", "PK", ""),
        ("order_id", "INTEGER", "FK", "→ order_header"),
        ("product_no", "TEXT", "", "← 商品编号（文本）"),
        ("quantity / paid_amount", "NUMERIC", "", "← 数量 / 实付"),
        ("discount_amount", "NUMERIC", "", "展示用，核算不用"),
        ("activity_numbers", "TEXT", "", "展示用"),
    ]},
    "activity_rule": {"title": "活动规则", "domain": "activity", "xy": (1060, 1100), "rows": [
        ("activity_rule_id", "INTEGER", "PK", ""),
        ("activity_id", "INTEGER", "FK", "→ activity"),
        ("rule_no", "TEXT", "UK", "← 规则编号"),
        ("threshold_value", "NUMERIC", "", "← 门槛值"),
        ("reduce_amount", "NUMERIC", "", "← 立减金额"),
    ]},
    "activity_benefit": {"title": "活动权益", "domain": "activity", "xy": (1400, 1100), "rows": [
        ("activity_benefit_id", "INTEGER", "PK", ""),
        ("activity_id", "INTEGER", "FK", "→ activity"),
        ("benefit_type", "TEXT", "", "← 权益类型"),
        ("gift_product_no / qty", "TEXT/NUM", "", "← 赠品"),
    ]},
    "activity_scope": {"title": "活动范围", "domain": "activity", "xy": (1740, 1100), "rows": [
        ("activity_scope_id", "INTEGER", "PK", ""),
        ("activity_id", "INTEGER", "FK", "→ activity"),
        ("scope_category", "TEXT", "", "← 范围类别"),
        ("scope_value", "TEXT", "", "← 范围值"),
    ]},
    "activity_execution": {"title": "活动核销", "domain": "activity", "xy": (380, 1540), "rows": [
        ("activity_execution_id", "INTEGER", "PK", ""),
        ("activity_id", "INTEGER", "FK", "→ activity"),
        ("order_id", "INTEGER", "FK", "→ order_header"),
        ("product_amount", "NUMERIC", "", "← 商品总金额"),
        ("discount_amount", "NUMERIC", "", "← 优惠金额（计费）"),
    ]},
    "coupon_redemption": {"title": "优惠券核销", "domain": "coupon", "xy": (720, 1540), "rows": [
        ("coupon_redemption_id", "INTEGER", "PK", ""),
        ("import_batch_id", "INTEGER", "FK", "→ import_batch"),
        ("order_id", "INTEGER", "FK", "→ order_header，可空"),
        ("coupon_no", "TEXT", "", "← 优惠券编号"),
        ("discount_amount", "NUMERIC", "", "← 优惠金额（计费）"),
    ]},
    "coupon_issue_rule": {"title": "券发放规则", "domain": "coupon", "xy": (1400, 1540), "rows": [
        ("coupon_issue_rule_id", "INTEGER", "PK", ""),
        ("coupon_config_id", "INTEGER", "FK,UK", "→ coupon_config"),
        ("issue_mode", "TEXT", "", "← 发放方式"),
        ("qty_per_issue", "NUMERIC", "", "← 每次发放数量"),
    ]},
    "coupon_use_rule": {"title": "券使用规则", "domain": "coupon", "xy": (1740, 1540), "rows": [
        ("coupon_use_rule_id", "INTEGER", "PK", ""),
        ("coupon_config_id", "INTEGER", "FK,UK", "→ coupon_config"),
        ("validity_mode", "TEXT", "", "← 有效期类型"),
        ("max_use_per_coupon", "NUMERIC", "", "← 最多使用次数"),
    ]},
    "coupon_scope": {"title": "券适用范围", "domain": "coupon", "xy": (2080, 1540), "rows": [
        ("coupon_scope_id", "INTEGER", "PK", ""),
        ("coupon_config_id", "INTEGER", "FK", "→ coupon_config"),
        ("scope_value", "TEXT", "", "← 范围值"),
    ]},
    "calculation_run": {"title": "核算批次", "domain": "result", "xy": (40, 1960), "rows": [
        ("calculation_run_id", "INTEGER", "PK", "导入后生成"),
        ("import_batch_id", "INTEGER", "FK", "→ import_batch"),
        ("calc_date / release_cutoff", "TEXT", "", "核算日 / T-2"),
        ("activity_benefit", "NUMERIC", "", "核销活动优惠合计"),
        ("released_orders", "INTEGER", "", "可释放单数"),
    ]},
    "entitlement_check": {"title": "权益核对", "domain": "result", "xy": (380, 1960), "rows": [
        ("entitlement_check_id", "INTEGER", "PK", ""),
        ("calculation_run_id", "INTEGER", "FK", "→ calculation_run"),
        ("order_id", "INTEGER", "FK", "→ order_header"),
        ("activity / coupon_benefit", "NUMERIC", "", "按核销明细"),
    ]},
    "release_candidate": {"title": "逐单释放", "domain": "result", "xy": (720, 1960), "rows": [
        ("release_candidate_id", "INTEGER", "PK", ""),
        ("calculation_run_id", "INTEGER", "FK", "→ calculation_run"),
        ("order_id", "INTEGER", "FK,UK", "→ order_header"),
        ("is_candidate / reason", "INT/TEXT", "", "可否释放及原因"),
    ]},
    "activity_fee_summary": {"title": "活动费用汇总", "domain": "result", "xy": (1060, 1960), "rows": [
        ("activity_fee_summary_id", "INTEGER", "PK", ""),
        ("calculation_run_id", "INTEGER", "FK", "→ calculation_run"),
        ("activity_id", "INTEGER", "FK", "→ activity"),
        ("released_amount", "NUMERIC", "", "可释放金额"),
        ("pending_orders", "INTEGER", "", "待释放单数"),
    ]},
    "calculation_quality_issue": {"title": "核算质量问题", "domain": "result", "xy": (1400, 1960), "rows": [
        ("calculation_quality_issue_id", "INTEGER", "PK", ""),
        ("calculation_run_id", "INTEGER", "FK", "→ calculation_run"),
        ("order_no", "TEXT", "", "不可释放订单"),
        ("level / reason", "TEXT", "", "提示 / 未达释放节点"),
    ]},
    "coupon_fee_summary": {"title": "优惠券费用汇总", "domain": "result", "xy": (1740, 1960), "rows": [
        ("coupon_fee_summary_id", "INTEGER", "PK", ""),
        ("calculation_run_id", "INTEGER", "FK", "→ calculation_run"),
        ("coupon_config_id", "INTEGER", "FK", "→ coupon_config"),
        ("used_amount / releasable_amount", "NUMERIC", "", "核销 / 可释放"),
    ]},
}

edges = [
    ("fk", "import_batch", "import_file", "1:N"),
    ("fk", "import_batch", "import_validation_issue", "1:N"),
    ("fk", "import_batch", "customer", "1:N"),
    ("fk", "import_batch", "product", "1:N"),
    ("fk", "import_batch", "order_header", "1:N"),
    ("fk", "import_batch", "activity", "1:N"),
    ("fk", "import_batch", "coupon_config", "1:N"),
    ("fk", "import_batch", "fulfillment", "1:N"),
    ("fk", "import_batch", "coupon_redemption", "1:N"),
    ("fk", "import_batch", "calculation_run", "1:N"),
    ("fk", "dealer_platform", "customer", "1:N"),
    ("fk", "dealer_platform", "product", "1:N"),
    ("fk", "dealer_platform", "order_header", "1:N"),
    ("fk", "order_header", "order_line", "1:N"),
    ("fk", "order_header", "activity_execution", "1:N"),
    ("fk", "order_header", "coupon_redemption", "1:N"),
    ("fk", "activity", "activity_rule", "1:N"),
    ("fk", "activity", "activity_benefit", "1:N"),
    ("fk", "activity", "activity_scope", "1:N"),
    ("fk", "activity", "activity_execution", "1:N"),
    ("fk", "activity", "activity_fee_summary", "1:N"),
    ("fk", "coupon_config", "coupon_issue_rule", "1:1"),
    ("fk", "coupon_config", "coupon_use_rule", "1:1"),
    ("fk", "coupon_config", "coupon_scope", "1:N"),
    ("fk", "calculation_run", "entitlement_check", "1:N"),
    ("fk", "calculation_run", "release_candidate", "1:N"),
    ("fk", "calculation_run", "activity_fee_summary", "1:N"),
    ("fk", "calculation_run", "calculation_quality_issue", "1:N"),
    ("fk", "calculation_run", "coupon_fee_summary", "1:N"),
    ("fk", "coupon_config", "coupon_fee_summary", "1:N"),
    ("fk", "order_header", "entitlement_check", "1:N"),
    ("fk", "order_header", "release_candidate", "1:N"),
    ("ref", "customer", "order_header", "客户编号"),
    ("ref", "product", "order_line", "商品编号"),
    ("ref", "order_header", "fulfillment", "单据编号"),
]


def box_height(entity):
    return HEADER_H + len(entity["rows"]) * ROW_H + 12


def anchor(entity, side):
    x, y = entity["xy"]
    h = box_height(entity)
    return {"top": (x + BOX_W / 2, y), "right": (x + BOX_W, y + h / 2), "bottom": (x + BOX_W / 2, y + h), "left": (x, y + h / 2)}[side]


def route(a, b):
    ax, ay = a["xy"]
    bx, by = b["xy"]
    if ax + BOX_W < bx:
        return anchor(a, "right"), anchor(b, "left")
    if bx + BOX_W < ax:
        return anchor(a, "left"), anchor(b, "right")
    if ay + box_height(a) < by:
        return anchor(a, "bottom"), anchor(b, "top")
    return anchor(a, "top"), anchor(b, "bottom")


def render() -> Path:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
        '<title id="title">EC101 标准库 ER 图</title>',
        '<desc id="desc">根据 mvp/ddl/ec101_standard_sqlite.sql 与 import_service.py 生成。实线=外键，虚线=同一编号文本关联。</desc>',
        '<defs><filter id="shadow" x="-10%" y="-10%" width="120%" height="120%"><feDropShadow dx="2" dy="3" stdDeviation="3" flood-opacity="0.12"/></filter></defs>',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        f'<text x="80" y="36" font-family="{FONT}" font-size="24" font-weight="700" fill="#102A43">EC101 标准导入库 ER 图</text>',
        f'<text x="80" y="58" font-family="{FONT}" font-size="13" fill="#627D98">来源：mvp/ddl/ec101_standard_sqlite.sql · 实线 FK · 虚线 客户编号/商品编号/单据编号文本关联 · ← 表示来自标准 Excel</text>',
    ]
    for kind, source, target, label in edges:
        p1, p2 = route(entities[source], entities[target])
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        dash = ' stroke-dasharray="6 4"' if kind == "ref" else ""
        color = "#B4235A" if kind == "ref" else "#9FB3C8"
        width = 22 + 6 * max(len(label) - 3, 0)
        parts.append(f'<path d="M {p1[0]:.1f} {p1[1]:.1f} L {p2[0]:.1f} {p2[1]:.1f}" stroke="{color}" stroke-width="1.4" fill="none"{dash}/>')
        parts.append(f'<rect x="{mx - width / 2:.1f}" y="{my - 9:.1f}" width="{width:.1f}" height="18" rx="9" fill="#ffffff" stroke="#D9E2EC"/>')
        parts.append(f'<text x="{mx:.1f}" y="{my + 4:.1f}" text-anchor="middle" font-family="{FONT}" font-size="10" fill="#52606D">{escape(label)}</text>')
    for name, entity in entities.items():
        x, y = entity["xy"]
        bg, accent = COLORS[entity["domain"]]
        h = box_height(entity)
        parts.append(f'<g filter="url(#shadow)"><rect x="{x}" y="{y}" width="{BOX_W}" height="{h}" rx="8" fill="#ffffff" stroke="{accent}" stroke-width="1.5"/><rect x="{x}" y="{y}" width="{BOX_W}" height="{HEADER_H}" rx="8" fill="{bg}"/><rect x="{x}" y="{y + HEADER_H - 8}" width="{BOX_W}" height="8" fill="{bg}"/>')
        parts.append(f'<text x="{x + 14}" y="{y + 27}" font-family="{FONT}" font-size="15" font-weight="700" fill="{accent}">{escape(entity["title"])}</text><text x="{x + BOX_W - 12}" y="{y + 26}" text-anchor="end" font-family="{FONT}" font-size="10" fill="#829AB1">{escape(name)}</text>')
        for i, (field, typ, key, comment) in enumerate(entity["rows"]):
            yy = y + HEADER_H + i * ROW_H
            if i % 2 == 0:
                parts.append(f'<rect x="{x + 1}" y="{yy}" width="{BOX_W - 2}" height="{ROW_H}" fill="#F8FAFC"/>')
            parts.append(f'<text x="{x + 10}" y="{yy + 17}" font-family="{FONT}" font-size="10" fill="#52606D">{escape(typ)}</text>')
            parts.append(f'<text x="{x + 78}" y="{yy + 17}" font-family="{FONT}" font-size="11" fill="#102A43">{escape(field)}</text>')
            if key:
                parts.append(f'<text x="{x + 218}" y="{yy + 17}" font-family="{FONT}" font-size="10" font-weight="700" fill="{accent}">{escape(key)}</text>')
            parts.append(f'<text x="{x + BOX_W - 8}" y="{yy + 17}" text-anchor="end" font-family="{FONT}" font-size="9.5" fill="#829AB1">{escape(comment)}</text>')
        parts.append("</g>")
    parts.append(
        '<g transform="translate(80,2268)"><rect width="980" height="34" rx="8" fill="#F8FAFC" stroke="#D9E2EC"/>'
        f'<circle cx="18" cy="17" r="6" fill="#7851A9"/><text x="32" y="21" font-family="{FONT}" font-size="11" fill="#52606D">导入审计</text>'
        f'<circle cx="120" cy="17" r="6" fill="#167E6D"/><text x="134" y="21" font-family="{FONT}" font-size="11" fill="#52606D">主数据</text>'
        f'<circle cx="210" cy="17" r="6" fill="#3B67B1"/><text x="224" y="21" font-family="{FONT}" font-size="11" fill="#52606D">订单履约</text>'
        f'<circle cx="320" cy="17" r="6" fill="#B16A13"/><text x="334" y="21" font-family="{FONT}" font-size="11" fill="#52606D">活动</text>'
        f'<circle cx="400" cy="17" r="6" fill="#B4235A"/><text x="414" y="21" font-family="{FONT}" font-size="11" fill="#52606D">优惠券</text>'
        f'<circle cx="500" cy="17" r="6" fill="#147D4A"/><text x="514" y="21" font-family="{FONT}" font-size="11" fill="#52606D">核算结果</text>'
        f'<line x1="640" y1="17" x2="680" y2="17" stroke="#9FB3C8" stroke-width="1.6"/><text x="688" y="21" font-family="{FONT}" font-size="11" fill="#52606D">外键</text>'
        f'<line x1="760" y1="17" x2="800" y2="17" stroke="#B4235A" stroke-width="1.6" stroke-dasharray="6 4"/><text x="808" y="21" font-family="{FONT}" font-size="11" fill="#52606D">编号文本关联（无 FK）</text>'
        "</g></svg>"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    return OUT


def render_png(svg_path: Path | None = None) -> Path:
    """Rasterize the SVG so chat clients that skip SVG can still show the ER."""
    import cairosvg

    svg_path = svg_path or OUT
    cairosvg.svg2png(
        url=str(svg_path),
        write_to=str(OUT_PNG),
        output_width=W * 2,
        output_height=H * 2,
    )
    return OUT_PNG


if __name__ == "__main__":
    svg = render()
    png = render_png(svg)
    print(svg)
    print(png)
