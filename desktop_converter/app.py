"""Tkinter desktop entry point for business users."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from converters.common import ConversionRequest

ROLE_KEYS = {
    "客户": "customer",
    "商品": "product",
    "订单": "order_detail",
    "活动": "activity_execution",
    "优惠券": "coupon_redemption",
    "履约": "fulfillment",
}


def build_conversion_request(platform: str, dealer_name: str, source_paths: dict[str, list[Path]], output_dir: Path, activity_inputs=None, coupon_inputs=None) -> ConversionRequest:
    if platform not in {"快马", "舟谱"}:
        raise ValueError("请选择平台（快马或舟谱）")
    if not dealer_name.strip():
        raise ValueError("请输入经销商")
    if not any(source_paths.values()):
        raise ValueError("请选择至少一个源文件")
    normalized = {}
    for role, paths in source_paths.items():
        normalized.setdefault(ROLE_KEYS.get(role, role), []).extend(paths)
    return ConversionRequest(platform, dealer_name.strip(), normalized, activity_inputs or [], coupon_inputs or [], output_dir)


class DesktopApp:
    def __init__(self, root: tk.Tk | None = None):
        self.root = root or tk.Tk()
        self.root.title("EC101 标准数据转换工具")
        self.root.geometry("760x520")
        self.platform = tk.StringVar(value="快马")
        self.dealer = tk.StringVar()
        self.output = tk.StringVar()
        self.activity_config = tk.StringVar()
        self.coupon_config = tk.StringVar()
        self.files: dict[str, list[Path]] = {"客户": [], "商品": [], "订单": [], "活动": [], "优惠券": [], "履约": []}
        self._build()

    def _build(self):
        frame = ttk.Frame(self.root, padding=18); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="EC101 标准数据转换工具", font=("Microsoft YaHei", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="选择平台和源文件，生成可上传的 standard.xlsx 与 sources.zip").pack(anchor="w", pady=(4, 16))
        top = ttk.Frame(frame); top.pack(fill="x")
        ttk.Label(top, text="平台").pack(side="left"); ttk.Combobox(top, textvariable=self.platform, values=("快马", "舟谱"), state="readonly", width=12).pack(side="left", padx=(8, 24))
        ttk.Label(top, text="经销商").pack(side="left"); ttk.Entry(top, textvariable=self.dealer, width=28).pack(side="left", padx=8)
        file_frame = ttk.LabelFrame(frame, text="源文件"); file_frame.pack(fill="both", expand=True, pady=16)
        for role in self.files:
            row = ttk.Frame(file_frame); row.pack(fill="x", pady=3)
            ttk.Label(row, text=role, width=10).pack(side="left")
            label = ttk.Label(row, text="未选择", width=68); label.pack(side="left", padx=8)
            ttk.Button(row, text="选择", command=lambda r=role, l=label: self._choose(r, l)).pack(side="left")
        out = ttk.Frame(frame); out.pack(fill="x", pady=(0, 12)); ttk.Label(out, text="输出目录").pack(side="left"); ttk.Entry(out, textvariable=self.output).pack(side="left", fill="x", expand=True, padx=8); ttk.Button(out, text="选择", command=self._choose_output).pack(side="left")
        config = ttk.Frame(frame); config.pack(fill="x", pady=(0, 8))
        ttk.Label(config, text="活动配置 JSON").pack(side="left"); ttk.Entry(config, textvariable=self.activity_config, width=25).pack(side="left", padx=6); ttk.Button(config, text="选择", command=lambda: self._choose_json(self.activity_config)).pack(side="left")
        ttk.Label(config, text="优惠券配置 JSON").pack(side="left", padx=(18, 0)); ttk.Entry(config, textvariable=self.coupon_config, width=25).pack(side="left", padx=6); ttk.Button(config, text="选择", command=lambda: self._choose_json(self.coupon_config)).pack(side="left")
        self.status = ttk.Label(frame, text="就绪"); self.status.pack(anchor="w")
        ttk.Button(frame, text="开始转换", command=self.convert).pack(anchor="e", pady=(12, 0))

    def _choose(self, role, label):
        paths = filedialog.askopenfilenames(title=f"选择{role}源文件", filetypes=(("Excel/CSV", "*.xlsx *.xls *.csv"), ("所有文件", "*.*")))
        if paths:
            self.files[role] = [Path(path) for path in paths]; label.configure(text="; ".join(path.name for path in self.files[role]))

    def _choose_output(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path: self.output.set(path)

    def _choose_json(self, variable):
        path = filedialog.askopenfilename(title="选择 JSON 配置", filetypes=(("JSON", "*.json"), ("所有文件", "*.*")))
        if path: variable.set(path)

    def convert(self):
        try:
            activity_inputs = self._read_json(self.activity_config.get(), "活动配置")
            coupon_inputs = self._read_json(self.coupon_config.get(), "优惠券配置")
            request = build_conversion_request(self.platform.get(), self.dealer.get(), self.files, Path(self.output.get() or Path.cwd() / "ec101-standard-output"), activity_inputs, coupon_inputs)
            converter = __import__("converters.kuaima" if request.platform == "快马" else "converters.zhoupu", fromlist=["convert_kuaima", "convert_zhoupu"])
            result = (converter.convert_kuaima if request.platform == "快马" else converter.convert_zhoupu)(request)
            self.status.configure(text=f"转换完成：{result.workbook_path}")
            messagebox.showinfo("转换完成", f"标准 Excel：{result.workbook_path}\n归档：{result.sources_zip_path}\n报告：{result.report_path}")
        except Exception as exc:
            self.status.configure(text="转换失败")
            messagebox.showerror("转换失败", str(exc))

    @staticmethod
    def _read_json(path, label):
        if not path:
            return []
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"{label} JSON 必须是数组")
        return value

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    DesktopApp().run()
