# 标准数据导入与 Windows 转换工具实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (native execution) or superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 用固定标准 Excel 替换现有 RAW/STANDARD/CORE/RESULT 四层导入链路，并交付可供业务人员使用的 Windows 转换工具和费用平台导入闭环。

**Architecture:** 快马、舟谱适配器复用当前 `std_mapping.py` 的 EC101 标准字段语义，在本地生成固定标准 Excel 与 `sources.zip`。Python API 对标准 Excel 做原子校验和导入，SQLite 保存导入审计、业务事实和核算输出；React 页面提供上传、错误报告、版本与核算状态。Windows 工具首期使用 Tkinter + PyInstaller，避免业务人员安装 Python。

**Tech Stack:** Python 3、SQLite、现有 Python HTTP API、React/TypeScript/Vite、Tkinter、PyInstaller、pytest、Vitest。

**Spec:** `docs/superpowers/specs/2026-10-05-standard-import-desktop-converter-design.md`

## Global Constraints

- 标准 Excel 固定完整工作表；空表也必须有表头。
- 标准字段必须使用已审核的中文字段名；编号、单号、券号按文本处理。
- 活动域与优惠券域不建立直接关联；两者只通过订单事实间接汇合。
- 标准订单明细的活动编号、优惠券编号仅用于展示；核算分别读取活动核销明细和优惠券核销明细。
- 优惠券配置使用独立的配置主表、发放规则、使用规则、适用范围和核销明细。
- 首期不引入 TPM、标准销售明细或动态扩展属性表。
- 导入按经销商+平台+覆盖期间执行全量快照；失败整包不写入，成功后自动核算。
- 原始平台文件和标准 Excel 归档在受控文件目录；数据库不保存 RAW 逐行表。
- 保留 SQLite、Python API 和现有 React 费用平台；不迁移旧数据库数据或主键。

## Review Focus

- Excel 中 18 位以上编号和券号被读取为字符串而非浮点/科学计数法：`test_standard_workbook_preserves_identifiers`。
- 舟谱没有下游订单或快马没有 XD 时仍能导入，`下游订单编号`允许为空：`test_fulfillment_allows_missing_downstream_order`。
- 同一订单同时存在活动核销和优惠券核销时，两个优惠分别计算后求和：`test_result_sums_independent_order_benefits`。
- 同一范围重导只切换一个当前版本且失败重导不影响旧版本：`test_snapshot_replacement_is_atomic`。
- 缺少活动/优惠券配置或跨表孤儿行时整包阻断并返回行级错误：`test_import_rejects_orphan_and_missing_configuration`。

---

### Task 1: 建立固定标准数据契约与工作簿读写器

**Files:**
- Create: `mvp/standard_schema.py`
- Create: `mvp/standard_workbook.py`
- Create: `mvp/tests/test_standard_schema.py`
- Create: `mvp/tests/test_standard_workbook.py`
- Modify: `PROJECT.md`

**Interfaces:**
- `STANDARD_SHEETS: tuple[str, ...]`：固定工作表顺序。
- `SHEET_COLUMNS: dict[str, tuple[str, ...]]`：每张表的精确中文列名。
- `validate_rows(sheet: str, rows: list[dict[str, str]]) -> list[Issue]`：只校验字段结构、类型和本表必填项。
- `write_standard_workbook(path: Path, tables: Mapping[str, Sequence[Mapping[str, object]]], manifest: Mapping[str, object]) -> None`。
- `read_standard_workbook(path: Path) -> StandardWorkbook`。

- [ ] **Step 1: Write failing schema tests**
  - 固定检查 `导入清单`、`标准客户`、`标准商品`、`标准订单明细`、活动四表、`标准活动核销明细`、优惠券配置四表、`标准优惠券核销明细`、`标准履约` 共 15 张表。
  - 将已审核字段名逐列写入断言；订单明细包含活动编号、优惠券编号、下游订单编号、单价、退货数量。
- [ ] **Step 2: Run `pytest mvp/tests/test_standard_schema.py -v` and verify it fails**
- [ ] **Step 3: Implement schema constants and row validation**
  - 用中文列名作为公开契约；金额、数量、日期和编号校验集中在本文件。
- [ ] **Step 4: Write failing workbook round-trip tests**
  - 空表保留表头；18 位编号和券号读回后与原字符串完全一致。
- [ ] **Step 5: Implement workbook reader/writer**
  - 使用现有依赖读取/写入 xlsx；禁止自动数字化编号；写出固定工作表顺序。
- [ ] **Step 6: Run schema and workbook tests; commit**

### Task 2: 把快马/舟谱适配器改造成标准 Excel 转换器

**Files:**
- Create: `converters/common.py`
- Create: `converters/kuaima.py`
- Create: `converters/zhoupu.py`
- Create: `converters/cli.py`
- Create: `converters/tests/test_kuaima_converter.py`
- Create: `converters/tests/test_zhoupu_converter.py`
- Modify: `mvp/scripts/std_mapping.py`
- Modify: `PROJECT.md`

**Interfaces:**
- `convert_kuaima(request: ConversionRequest) -> ConversionResult`。
- `convert_zhoupu(request: ConversionRequest) -> ConversionResult`。
- `ConversionRequest(platform, dealer_name, source_paths, activity_inputs, coupon_inputs, output_dir)`。
- `ConversionResult(workbook_path, sources_zip_path, report_path, counts)`。
- `build_sources_archive(source_paths: Sequence[Path], destination: Path) -> str`：返回 SHA-256。

- [ ] **Step 1: Add fixture-based failing tests from existing 快马 samples**
  - 客户、商品、订单明细、满减/满赠活动核销、优惠券核销、履约字段映射到已审核中文字段。
  - 活动配置和优惠券配置使用工具录入对象，不从截图猜测。
- [ ] **Step 2: Add failing 舟谱 tests**
  - 覆盖表头在第 4 行、SXD/XD 双文件、没有商品编号时保留商品条码、支付时间不误映射成支付方式。
- [ ] **Step 3: Extract shared source parsing and identifier/date/amount normalization into `converters/common.py`**
- [ ] **Step 4: Implement `convert_kuaima`**
  - 将现有 `ingest_manjian.py`、`ingest_manzeng.py`、`ingest_coupon.py` 的读取和匹配逻辑改为输出标准表，不写 SQLite。
- [ ] **Step 5: Implement `convert_zhoupu`**
  - 将当前 `std_field_mapping` 的舟谱映射迁移为版本化配置；平台特例仅留在适配器。
- [ ] **Step 6: Implement CLI**
  - `python -m converters.cli --platform kuaima|zhoupu --dealer ... --output ...`；错误只生成报告，不生成可上传的半成品。
- [ ] **Step 7: Run both converter test suites and compare counts with current real-sample reports; commit**

### Task 3: 重建 SQLite 结构与原子标准导入服务

**Files:**
- Create: `mvp/ddl/ec101_standard_sqlite.sql`
- Create: `mvp/import_service.py`
- Create: `mvp/tests/test_import_service.py`
- Modify: `api/server.py`
- Modify: `api/tests/test_server.py`
- Modify: `PROJECT.md`

**Interfaces:**
- `create_database(db_path: Path) -> None`。
- `validate_import(workbook: StandardWorkbook, db: Connection) -> list[Issue]`。
- `import_snapshot(db: Connection, workbook: StandardWorkbook, archive: ArchiveMetadata) -> ImportResult`。
- `run_calculation(db: Connection, import_batch_id: int) -> CalculationResult`。
- 业务事实表名固定为 `dealer_platform`、`customer`、`product`、`order_header`、`order_line`、`activity`、`activity_rule`、`activity_benefit`、`activity_scope`、`activity_execution`、`fulfillment`、`coupon_config`、`coupon_issue_rule`、`coupon_use_rule`、`coupon_scope`、`coupon_redemption`。
- 核算表名固定为 `calculation_run`、`entitlement_check`、`release_candidate`、`activity_fee_summary`、`calculation_quality_issue`；审计表名固定为 `import_batch`、`import_file`、`import_validation_issue`。
- `activity_execution` 仅引用 `activity`；`coupon_redemption` 仅引用 `coupon_config`/订单业务编号；活动域和优惠券域没有外键。
- `POST /imports`：multipart 标准 Excel + `sources.zip`。
- `GET /imports`、`GET /imports/{id}`、`GET /imports/{id}/issues`。

- [ ] **Step 1: Write failing DDL/import tests**
  - 活动配置四表与优惠券配置四表无直接外键。
  - 优惠券核销明细只通过订单号关联订单。
  - 标准履约的下游订单编号可空。
- [ ] **Step 2: Implement new DDL**
  - 导入审计、业务事实、核算输出使用新命名；不创建 `raw_*`、`std_*` 或 `tpm_*` 表。
  - 活动和优惠券配置分开；订单活动核销和券核销分开。
- [ ] **Step 3: Implement structural and cross-table validation**
  - 检查固定表、必填键、重复键、客户/商品/订单孤儿行、活动/优惠券配置缺失、日期金额格式。
- [ ] **Step 4: Implement atomic snapshot import**
  - 先写临时版本；全部成功后在事务中停用旧当前版本、激活新版本、保存归档路径和哈希；异常回滚。
- [ ] **Step 5: Implement independent activity/coupon calculation aggregation**
  - 活动优惠与券优惠分别计算；订单总优惠只在 RESULT 汇总层相加。
- [ ] **Step 6: Add API handlers and JSON error contract**
- [ ] **Step 7: Run API/import tests and `PRAGMA foreign_key_check`; commit**

### Task 4: 增加费用平台导入工作区

**Files:**
- Modify: `ec101-fee-platform-v1/app/page.tsx`
- Modify: `ec101-fee-platform-v1/app/fee-tpm.test.tsx`
- Create: `ec101-fee-platform-v1/app/imports.test.tsx`

**Interfaces:**
- `POST /imports` 的 FormData 客户端封装。
- `GET /imports`、详情、错误报告下载的 API 客户端函数。

- [ ] **Step 1: Write failing UI tests**
  - 显示上传标准 Excel 和 `sources.zip`；显示校验中、阻断错误、成功导入、核算中、核算完成状态。
  - 失败时可以下载错误报告；成功时显示经销商、平台、期间、版本和当前标记。
- [ ] **Step 2: Implement导入工作区**
  - 保持现有业务数据和 TPM 页面查询行为；不在浏览器解析平台原始文件或计算费用。
- [ ] **Step 3: Run Vitest and existing UI tests; commit**

### Task 5: 交付 Windows 桌面转换工具

**Files:**
- Create: `desktop_converter/app.py`
- Create: `desktop_converter/views.py`
- Create: `desktop_converter/requirements.txt`
- Create: `desktop_converter/build_windows.ps1`
- Create: `desktop_converter/tests/test_desktop_request.py`
- Modify: `README.md`

**Interfaces:**
- `DesktopApp.run() -> None`。
- GUI 将文件选择结果组装为 `ConversionRequest`，调用 Task 2 的转换器，不复制转换逻辑。

- [ ] **Step 1: Write failing request-building tests**
  - 平台、经销商、源文件、活动配置、优惠券配置缺失时给出可操作错误。
- [ ] **Step 2: Implement Tkinter workflow**
  - 平台选择、源文件选择、活动/券配置录入、预览、转换报告和输出目录打开。
- [ ] **Step 3: Add PyInstaller build script**
  - 生成可在 Windows 双击运行的目录或单文件程序；不要求安装 Python。
- [ ] **Step 4: Run desktop tests and a Windows packaging smoke check; commit**

### Task 6: 真实样本端到端验证与文档收口

**Files:**
- Create: `tests/e2e/test_standard_pipeline.py`
- Modify: `PROJECT.md`
- Modify: `README.md`
- Modify: `api/README.md`

- [ ] **Step 1: Add failing end-to-end tests**
  - 快马、舟谱：源文件 → 标准 Excel → 导入 → 自动核算。
  - 同一订单同时有活动核销和券核销时验证独立计算和最终汇总。
- [ ] **Step 2: Run full Python and frontend test suites; fix only task-scoped failures**
- [ ] **Step 3: Verify archive hashes, current-version replacement, rollback and foreign keys**
- [ ] **Step 4: Update run instructions and current capabilities in project docs**
- [ ] **Step 5: Commit final verification and produce implementation handoff**

## Execution Order

按 Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 执行。每个任务先写失败测试，再实现最小代码，最后运行该任务测试并提交；Task 3 的 API 契约冻结后才能接 Task 4，Task 2 的转换器接口冻结后才能接 Task 5。
