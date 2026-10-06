# 快马验收用的转换后标准表

之前 e2e 验收（`tests/e2e/test_standard_pipeline.py`）把 `standard.xlsx` 写在临时目录，进程结束就删了，所以仓库里看不到转换结果。本目录用**同一套兴路强试点源文件、同一套转换器**重新导出，方便直接打开。

数据已经进过 `mvp/ec101_standard.db`（两批都是 `calculated`）。标准 Excel 是导入前的中间文件；库是导入后的落库结果。

重新生成：`python3 scripts/export_kuaima_verified_standard.py`

## 文件

| 文件 | 是什么 |
|---|---|
| `满减/standard.xlsx` | 满减批次完整标准工作簿（15 张固定表，可再导入） |
| `满减/standard_preview.xlsx` | 同上，大表只留前 20 行，方便打开看结构 |
| `满减/conversion_report.txt` | 转换器当次汇总 |
| `满赠/standard.xlsx` | 满赠批次完整标准工作簿 |
| `满赠/standard_preview.xlsx` | 满赠预览 |
| `满赠/conversion_report.txt` | 转换器当次汇总 |
| `ec101_standard库结构与当前数据.xlsx` | 当前 `ec101_standard.db` 的表、字段、行数、一条样例 |

## 满减 / 满赠各表行数

| 标准工作表 | 满减行数 | 满赠行数 | 落入数据库表 |
|---|---:|---:|---|
| 导入清单 | 1 | 1 | import_batch / dealer_platform |
| 标准客户 | 2292 | 2292 | customer |
| 标准商品 | 9175 | 9172 | product |
| 标准订单明细 | 36157 | 26254 | order_header + order_line |
| 标准活动 | 1 | 1 | activity |
| 标准活动规则 | 0 | 0 | activity_rule |
| 标准活动权益 | 0 | 0 | activity_benefit |
| 标准活动范围 | 0 | 0 | activity_scope |
| 标准活动核销明细 | 136 | 98 | activity_execution |
| 标准优惠券配置 | 0 | 0 | coupon_config |
| 标准优惠券发放规则 | 0 | 0 | coupon_issue_rule |
| 标准优惠券使用规则 | 0 | 0 | coupon_use_rule |
| 标准优惠券适用范围 | 0 | 0 | coupon_scope |
| 标准优惠券核销明细 | 1 | 0 | coupon_redemption |
| 标准履约 | 1764 | 1257 | fulfillment |

## 当前库里已经有的批次

| import_batch_id | 期间 | 状态 | 活动优惠合计 | 券优惠合计 | 可释放活动 | 可释放券 | 参与单 / 可释放单 |
|---|---|---|---:|---:|---:|---:|---|
| 1 | 2026-08-31 ~ 2026-09-17 | calculated | 2040 | 200 | 1995 | 200 | 136 / 133 |
| 2 | 2026-08-19 ~ 2026-08-31 | calculated | 0 | 0 | 0 | 0 | 98 / 98 |

## 当前 `ec101_standard.db` 有哪些表

库文件不进 git（`.gitignore`），但本机这次验收已经写入。下面是当前行数。

| 表 | 中文 | 当前行数 | 说明 |
|---|---|---:|---|
| `import_batch` | 导入批次 | 2 | 一次上传一份 standard.xlsx |
| `import_file` | 源文件归档记录 | 2 | sources.zip 元数据 |
| `import_validation_issue` | 导入校验问题 | 0 | 当前空 |
| `dealer_platform` | 经销商×平台 | 1 | 兴路强 × 快马 一条 |
| `customer` | 客户 | 4584 | 两个批次各导一次客户主数据，所以行数是 2292×2 |
| `product` | 商品 | 18347 | 同上，两个批次各自一份 |
| `order_header` | 订单头 | 3021 | 满减 1764 + 满赠 1257 |
| `order_line` | 订单行 | 62411 | 满减 36157 + 满赠 26254 |
| `fulfillment` | 履约 | 3021 | 快马目前用订单状态生成，一行对应一单 |
| `activity` | 活动主表 | 2 | 满减「可口可乐满减」+ 满赠「满赠优惠」 |
| `activity_rule` | 活动规则 | 0 | 快马自动转换不填 |
| `activity_benefit` | 活动权益 | 0 | 快马自动转换不填 |
| `activity_scope` | 活动范围 | 0 | 快马自动转换不填 |
| `activity_execution` | 活动核销 | 234 | 满减 136 + 满赠 98，费用从这里加 |
| `coupon_config` | 优惠券主表 | 0 | 快马自动转换不填 |
| `coupon_issue_rule` | 券发放规则 | 0 | 快马自动转换不填 |
| `coupon_use_rule` | 券使用规则 | 0 | 快马自动转换不填 |
| `coupon_scope` | 券适用范围 | 0 | 快马自动转换不填 |
| `coupon_redemption` | 券核销 | 1 | 满减批次 1 张已使用券 |
| `calculation_run` | 核算批次 | 2 | 每个导入批次一条 RESULT |
| `entitlement_check` | 权益核对 | 234 | 有核销的订单各一条 |
| `release_candidate` | 可释放候选 | 234 | T-2 + 已完成 判定 |
| `activity_fee_summary` | 活动费用汇总 | 2 | 每个活动一条 |
| `calculation_quality_issue` | 核算质量问题 | 3 | 满减 3 张未完成订单 |

库表完整字段见 `mvp/ddl/ec101_standard_sqlite.sql`，Excel 列怎么落到字段见 [`docs/标准数据到标准库对照.md`](../../标准数据到标准库对照.md)。
