"""Write the live ROI sales/fee workbook for review."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.server import query_fee_tpm_roi
from mvp.roi_workbook import build_roi_workbook

SNAPSHOT = ROOT / "docs" / "samples" / "kuaima-verified-standard" / "ec101_standard.db"
OUT = ROOT / "docs" / "samples" / "EC101-平台经销商活动-销量实付费用.xlsx"


def main() -> None:
    body, filename = build_roi_workbook(query_fee_tpm_roi(SNAPSHOT, {})["rows"])
    OUT.write_bytes(body)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(body)} bytes) as {filename}")


if __name__ == "__main__":
    main()
