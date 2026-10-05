"""Command-line entry point for local platform conversion."""

import argparse
import json
from pathlib import Path

from .common import ConversionRequest


def parse_source_arg(raw: str) -> tuple[str, Path]:
    role, separator, path = raw.partition("=")
    if not separator or not role or not path:
        raise ValueError("源文件参数必须使用 role=path 格式")
    return role, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="EC101 标准数据转换工具")
    parser.add_argument("--platform", choices=("kuaima", "zhoupu"), required=True)
    parser.add_argument("--dealer", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source", action="append", required=True, help="role=path，可重复")
    parser.add_argument("--activity-json", type=Path)
    parser.add_argument("--coupon-json", type=Path)
    args = parser.parse_args()
    sources: dict[str, list[Path]] = {}
    for raw in args.source:
        role, path = parse_source_arg(raw)
        sources.setdefault(role, []).append(path)
    read_json = lambda path: json.loads(path.read_text(encoding="utf-8")) if path else []
    request = ConversionRequest(
        platform="快马" if args.platform == "kuaima" else "舟谱",
        dealer_name=args.dealer,
        source_paths=sources,
        activity_inputs=read_json(args.activity_json),
        coupon_inputs=read_json(args.coupon_json),
        output_dir=Path(args.output),
    )
    if args.platform == "kuaima":
        from .kuaima import convert_kuaima
        result = convert_kuaima(request)
    else:
        from .zhoupu import convert_zhoupu
        result = convert_zhoupu(request)
    print(result.workbook_path)


if __name__ == "__main__":
    main()
