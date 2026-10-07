# 舟谱-羿柏标准表

数据来源：原库 `mvp/ec101_mvp.db` 的 dealer 羿柏 / platform 舟谱（`dealer_platform_id=2`）。

原库已经有配置、订单、核销和券台账。本目录只是把这些事实投影成标准工作表，再导入 `ec101_standard.db`，让 ROI 按同一套公式计算。没有的字段不编。

| 批次 | 原库 activity_id | 标准活动编号 | 核销来源 |
|---|---:|---|---|
| 返券 | 17 | 可口可乐产品288返15元券 | `order_activity` 45 单（使用侧 15 元/单） |
| 满赠 | 18 | 雪碧系列满100元送抱枕 | `order_activity` 142 单（赠品，优惠金额 0） |

生成：

```
python3 scripts/export_yibo_standard.py
python3 scripts/rebuild_standard_db.py
```

明确没有、因此留空或未写入的：

- 未桥接 `product_id` 的订单行没有商品编号，不编造编号，这些行不进入标准订单明细。
- 返券没有 `coupon_use_rule`，不把活动期间抄成券使用期间；ROI 按活动开始/结束算。
- 原库 `order_line` 没有实付列；实付 = 优惠前金额 − 优惠金额（入库时就是这样拆的）。
- 箱规原文（如 `1箱=24瓶`）原样写入「箱规」；解析出的每箱瓶/罐数写入「每箱基本单位数量」。
