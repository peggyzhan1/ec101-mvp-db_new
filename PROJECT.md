# EC101 数据底座与费用运营平台

## Purpose

将经销商平台导出的订单、活动、客户、商品和履约事实沉淀到 EC101 SQLite MVP，并通过费用运营平台查询和核验促销费用。

## Current capabilities

- `mvp/ec101_mvp.db` 已包含快马×兴路强、舟谱×羿柏的真实导入数据和核算结果。
- `api/server.py` 提供跨平台只读 HTTP API，直接查询 SQLite。
- `ec101-fee-platform-v1` 的“业务数据”工作区通过 API 查询、筛选、查看详情和导出 CSV；“费用与促销 TPM”读取 RESULT 层的活动、权益、异常和结算候选。
- 优惠券已纳入 CORE 活动模型：两张券规则表记录发放和使用配置，券台账可在有审计证据时关联券活动。
- 已根据 SQLite DDL 生成 CORE 层实体关系图，覆盖 16 张 CORE 表及其 PK/FK/UK 和主要关系。

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
- `api/server.py`：只读查询服务；后续线上化主要替换数据库连接和部署配置。
- `ec101-fee-platform-v1/app/page.tsx`：费用运营台界面和 API 联调逻辑。
- `mvp/ddl/ec101_mvp_sqlite.sql`：数据库结构的权威定义。
- `mvp/scripts/migrate_coupon_core.py`：优惠券 CORE 结构迁移、券配置导入和本地数据库备份。
- `docs/diagrams/ec101-mvp-core-er.svg`：CORE 层 ER 图，供业务和开发理解实体、字段与关系。
- `scripts/build_core_er_svg.py`：ER 图生成脚本；DDL 关系变化后重新运行即可生成新版图。
- `mvp/standard_schema.py`：已审核的标准 Excel 工作表和字段契约；转换器与导入器共同使用。
- `mvp/standard_workbook.py`：固定模板的 Excel 读写和基础行校验。

## Current limits and next step

当前 API 仍为本地 SQLite，标准导入 API 和 Windows 转换器尚在后续任务中，未配置认证、权限和线上统一数据库。异常确认、负责人、P0/P1、支付和 ERP 上账尚未实现；页面仅展示 RESULT 的原始“警告/提示”。生产多人使用前需迁移到受管数据库并加入认证、权限和审计。

CORE ER 图只展示 CORE 业务事实层；RAW、STANDARD、RESULT 层未展开。订单头中的 `batch_id` 对 RAW 层 `raw_import_batch` 的引用在图中作为外部引用字段保留。
