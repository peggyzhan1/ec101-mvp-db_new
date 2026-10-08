# EC101 数据底座

本仓库包含 EC101 促销费用数据底座、MVP SQLite 数据库和费用运营平台。

多分支合并后的全景梳理见 [`docs/EC101项目现状梳理.md`](docs/EC101项目现状梳理.md)（主链路、数据库、功能、文档导航与下一步）。

## 本地真实数据联调

API 与运行说明见 [`api/README.md`](api/README.md)。最小启动流程：

```bash
python3 api/server.py
cd ec101-fee-platform-v1
NEXT_PUBLIC_EC101_API_URL=http://127.0.0.1:8787 npm run dev
```

当前 API 默认使用新库 `mvp/ec101_standard.db`。费用平台上传 `standard.xlsx` 时，`POST /api/imports` 调用 `import_snapshot`，把 CORE 事实写入该库，并立刻用 `actual_result_calculator.calculate_actual_results` 写出 RESULT。同一经销商、平台、覆盖区间再次导入时，只把这一份标成非当前；另一家的当前数据保留。费用页的当前模式会读出每一个当前批次的最新核算。

`mvp/scripts/ingest_*.py`、`result_service.py` 和 `promotion_calculator.py` 是早期样例或理论核算，费用平台不走这些脚本。历史样例库 `mvp/ec101_mvp.db` 不会被自动迁移或覆盖。新库的表和字段见 [`mvp/EC101_标准库数据字典.md`](mvp/EC101_标准库数据字典.md)。快马、舟谱怎么把源文件变成这些字段，见 [`mvp/快马数据转换与字段映射.md`](mvp/快马数据转换与字段映射.md) 和 [`mvp/舟谱数据转换与字段映射.md`](mvp/舟谱数据转换与字段映射.md)。入库后的实际发生核算见 [`mvp/实际发生核算逻辑.md`](mvp/实际发生核算逻辑.md)。

## Windows 转换工具

业务人员可运行 `desktop_converter/app.py`（打包后为 `EC101StandardConverter.exe`），选择快马或舟谱源文件，生成 `standard.xlsx`、`sources.zip` 和转换报告，再在费用平台“数据接入”页上传。Windows 构建脚本为 `desktop_converter/build_windows.ps1`。
