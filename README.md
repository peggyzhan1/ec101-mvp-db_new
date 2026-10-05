# EC101 数据底座

本仓库包含 EC101 促销费用数据底座、MVP SQLite 数据库和费用运营平台。

## 本地真实数据联调

API 与运行说明见 [`api/README.md`](api/README.md)。最小启动流程：

```bash
python3 api/server.py
cd ec101-fee-platform-v1
NEXT_PUBLIC_EC101_API_URL=http://127.0.0.1:8787 npm run dev
```

当前 API 默认使用新库 `mvp/ec101_standard.db`，支持上传标准 Excel（`POST /api/imports`），数据库仅保存标准业务事实、CORE/RESULT 核算结果与 sources.zip 归档元数据，不保存 RAW 逐行表。历史样例库 `mvp/ec101_mvp.db` 不会被自动迁移或覆盖。

## Windows 转换工具

业务人员可运行 `desktop_converter/app.py`（打包后为 `EC101StandardConverter.exe`），选择快马或舟谱源文件，生成 `standard.xlsx`、`sources.zip` 和转换报告，再在费用平台“数据接入”页上传。Windows 构建脚本为 `desktop_converter/build_windows.ps1`。
