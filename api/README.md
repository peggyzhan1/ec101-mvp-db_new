# EC101 本地真实数据 API

这是一个只读本地 API，直接查询仓库内的 `mvp/ec101_mvp.db`。它不修改数据库，也不提供核算重跑、审批或结算写入。

## 环境要求

- Python 3.9+（macOS、Windows 均可）
- 不需要安装第三方 Python 包

## 启动

在仓库根目录执行：

```bash
python3 api/server.py
```

Windows PowerShell：

```powershell
py api/server.py
```

也可以从 `api/` 目录启动，程序会按脚本位置自动找到数据库：

```bash
cd api
python3 server.py
```

默认监听 `http://127.0.0.1:8787`。可用 `--port` 或 `--db` 覆盖端口和数据库路径。

## 检查服务

```text
GET /health
GET /api/business-data/orders?dealer=兴路强&limit=20
GET /api/business-data/orders/1
```

支持的业务对象：`orders`、`order-lines`、`activities`、`activity-details`、`customers`、`products`、`fulfillments`、`order-activities`。

列表接口支持 `q`、`dealer`、`platform`、`limit`、`offset`；`limit` 最大为 100，`offset` 最大为 10000。

## 标准数据导入与逐单释放清单

```text
POST /api/imports                       multipart: workbook(必填) sources(可选) calc_date(可选, YYYY-MM-DD, 默认今天)
GET  /api/imports                       导入批次列表
GET  /api/imports/{id}                  批次详情：calculation（本批核算汇总）+ activities（按活动的参与/可释放/待释放）
GET  /api/imports/{id}/issues           导入校验问题
GET  /api/imports/{id}/release          逐单释放清单；支持 candidate=1|0、q（订单号/客户）、limit（≤2000）、offset
```

核算口径：费用只按“标准活动核销明细”和“标准优惠券核销明细”汇总，订单行上的优惠金额只做展示；一张参与订单可释放的条件是订单状态为“已完成”且下单时间早于 `calc_date` 前两天的 00:00:00，其余订单在清单中带原因（订单状态、未达 T-2）。

```bash
curl -F workbook=@standard.xlsx -F sources=@sources.zip -F calc_date=2026-09-22 http://127.0.0.1:8787/api/imports
curl 'http://127.0.0.1:8787/api/imports/1/release?candidate=0'
```

## 费用与促销 TPM RESULT 接口

以下接口同样只读，直接展示 RESULT 层的计算结论，不在 API 或页面中重算促销门槛、T-2 或结算金额：

```text
GET /api/fee-tpm/overview
GET /api/fee-tpm/activities
GET /api/fee-tpm/activities/{activity_id}
GET /api/fee-tpm/issues
GET /api/fee-tpm/settlements
```

所有列表支持 `dealer`、`platform`、`limit`、`offset`（上限仍为 100）及可选的 `calc_batch_id`。省略 `calc_batch_id` 时为“当前”模式：每个活动读取其自身最新的费用结果批次；传入时为历史回放，所有记录固定来自该批次。不存在的批次返回 `404`，不会回退到最新数据。

例如：

```bash
curl 'http://127.0.0.1:8787/api/fee-tpm/activities?calc_batch_id=11'
```

响应中的 `tpm: null` 明确表示该活动不走 TPM；这不是预算为零。赠品的应赠/实赠始终以数量字段返回，未确认单价不会转换成金额或进入结算候选。`issues` 会保留无法唯一归属活动的批次级问题，其 `activityId` 为 `null`。

## 启动前端联调

另开一个终端：

```bash
cd ec101-fee-platform-v1
NEXT_PUBLIC_EC101_API_URL=http://127.0.0.1:8787 npm run dev
```

Windows PowerShell：

```powershell
cd ec101-fee-platform-v1
$env:NEXT_PUBLIC_EC101_API_URL = "http://127.0.0.1:8787"
npm run dev
```

前端 API 地址通过 `NEXT_PUBLIC_EC101_API_URL` 设置；未设置时默认使用 `http://127.0.0.1:8787`。

## 后续线上化

前端接口契约保持不变，只替换 API 服务端的数据库连接和部署地址。生产阶段再将 SQLite 迁移到统一 MySQL/PostgreSQL，并增加认证、权限和审计。
