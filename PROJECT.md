# EC101 数据底座与费用运营平台

## Purpose

将经销商平台导出的订单、活动、客户、商品和履约事实沉淀到 EC101 SQLite MVP，并通过费用运营平台查询和核验促销费用。

## Current capabilities

- `mvp/ec101_mvp.db` 是历史样例库；新导入库默认为 `mvp/ec101_standard.db`，由 `mvp/import_service.py` 按标准数据契约初始化。
- `api/server.py` 提供业务查询、标准 Excel 导入、批次详情和校验问题 API。
- `ec101-fee-platform-v1` 的“业务数据”工作区通过 API 查询、筛选、查看详情和导出 CSV；“费用与促销 TPM”读取 RESULT 层的活动、权益、异常和结算候选。
- 活动和优惠券是独立域，只通过订单间接汇合；活动优惠与券优惠在 RESULT 分别核算后汇总。
- 新 DDL 不再创建 `raw_*`、`std_*`、`tpm_*` 表；原始文件只作为 sources.zip 归档，数据库保存路径、哈希和大小。

## How to run

```bash
python3 api/server.py
cd ec101-fee-platform-v1
NEXT_PUBLIC_EC101_API_URL=http://127.0.0.1:8787 npm run dev
```

Windows 使用 `py api/server.py` 和 PowerShell 环境变量写法，详见 `api/README.md`。

## Main flow

平台原始文件 → 平台转换器 → 固定标准 Excel → 导入/校验 → 业务事实与核算 → API → 费用运营平台。

## Important files

- `mvp/ec101_mvp.db`：本地真实数据源；不要由前端直接读取。
- `api/server.py`：查询与标准数据导入服务；后续线上化主要替换数据库连接、认证和部署配置。
- `ec101-fee-platform-v1/app/page.tsx`：费用运营台界面和 API 联调逻辑。
- `mvp/ddl/ec101_mvp_sqlite.sql`：数据库结构的权威定义。
- `mvp/scripts/migrate_coupon_core.py`：优惠券 CORE 结构迁移、券配置导入和本地数据库备份。
- `docs/diagrams/ec101-mvp-core-er.svg`：CORE 层 ER 图，供业务和开发理解实体、字段与关系。
- `scripts/build_core_er_svg.py`：ER 图生成脚本；DDL 关系变化后重新运行即可生成新版图。
- `mvp/standard_schema.py`：已审核的标准 Excel 工作表和字段契约；转换器与导入器共同使用。
- `mvp/standard_workbook.py`：固定模板的 Excel 读写和基础行校验。
- `mvp/import_service.py`：标准 Excel 校验与入库；不写 RESULT。
- `mvp/calculation_engine.py`：按核销明细核算并写 RESULT；不读 Excel、不判断平台。
- `converters/common.py`、`converters/kuaima.py`、`converters/zhoupu.py`：将平台源文件转换为固定标准 Excel；不写数据库。
- `desktop_converter/app.py`：Tkinter Windows 桌面入口；`desktop_converter/build_windows.ps1`：PyInstaller 打包脚本。

## Current limits and next step

当前 API 仍为本地 SQLite，未配置认证、权限和线上统一数据库。异常确认、负责人、P0/P1、支付和 ERP 上账尚未实现；页面仅展示 RESULT 的原始“警告/提示”。生产多人使用前需迁移到受管数据库并加入认证、权限和审计。

后续如需更新实体关系图，应以 `mvp/ddl/ec101_standard_sqlite.sql` 为准，并用 `python3 scripts/build_standard_er_svg.py` 重新生成 `docs/diagrams/ec101-standard-er.svg` 和 `docs/diagrams/ec101-standard-er.png`。字段对照见 `docs/标准数据到标准库对照.md`。快马如何从源文件转到标准表、导入后如何核算，见 `docs/快马转换与核算逻辑.md`。对照旧项目后的后续步骤见 `docs/后续实施计划.md`。活动费用核验报告模版（待评审）见 `docs/活动费用核验报告模版说明.md` 和 `docs/templates/活动费用核验报告模版.xlsx`。
