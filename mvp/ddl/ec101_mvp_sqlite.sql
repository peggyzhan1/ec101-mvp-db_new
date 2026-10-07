-- EC101 MVP 薄物理模型 (SQLite)
-- 范围: 仅 MVP 接入所需表; 预留模块(经销商拿货/业务员/库存扩展/数据指标)不建表
-- 类型约定: 编号/单号=TEXT(字符串); 金额=NUMERIC(入库四舍五入2位, 生产MySQL映射DECIMAL(12,2));
--           日期时间=TEXT ISO 'YYYY-MM-DD HH:MM:SS'; 布尔=INTEGER 0/1
-- 连接时须执行: PRAGMA foreign_keys = ON;

PRAGMA foreign_keys = ON;

-- ========== RAW / 血缘 ==========
CREATE TABLE raw_import_batch (
  batch_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_code    TEXT NOT NULL UNIQUE,
  source_platform TEXT NOT NULL,
  dealer_name   TEXT NOT NULL,
  imported_at   TEXT NOT NULL,
  operator      TEXT
);

CREATE TABLE raw_file (
  file_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id      INTEGER NOT NULL REFERENCES raw_import_batch(batch_id),
  file_name     TEXT NOT NULL,
  module        TEXT NOT NULL,          -- 客户/商品/订单/销售/活动明细/优惠券/配置/TPM
  file_signature TEXT NOT NULL,         -- OOXML/BIFF/HTML/CSV/PNG
  read_method   TEXT NOT NULL,
  sheet_name    TEXT,
  header_row    INTEGER,
  data_rows     INTEGER,
  UNIQUE(batch_id, file_name, module)
);

-- ========== CORE ==========
CREATE TABLE dealer_platform (
  dealer_platform_id INTEGER PRIMARY KEY AUTOINCREMENT,
  dealer_name   TEXT NOT NULL,
  platform_name TEXT NOT NULL,
  swire_partner_code TEXT,              -- 太古侧合作伙伴编号(预留, 例0576259191)
  admission_status TEXT,
  UNIQUE(dealer_name, platform_name)
);

CREATE TABLE customer (
  customer_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  dealer_platform_id INTEGER NOT NULL REFERENCES dealer_platform(dealer_platform_id),
  platform_customer_no TEXT NOT NULL,
  customer_name TEXT NOT NULL,
  customer_type TEXT,
  customer_level TEXT,
  customer_tag  TEXT,
  customer_region TEXT,
  salesperson_name TEXT,
  created_at    TEXT,
  status        TEXT,
  swire_outlet_no TEXT,                 -- 来自跨系统映射
  UNIQUE(dealer_platform_id, platform_customer_no)
);

CREATE TABLE product (
  product_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  dealer_platform_id INTEGER NOT NULL REFERENCES dealer_platform(dealer_platform_id),
  platform_product_no TEXT NOT NULL,
  product_name  TEXT NOT NULL,
  brand         TEXT,
  category      TEXT,
  spec          TEXT,
  barcode       TEXT,
  base_unit     TEXT,
  box_conversion TEXT,
  swire_product_code TEXT,              -- 来自跨系统映射
  actual_stock  NUMERIC,
  occupied_stock NUMERIC,
  available_stock NUMERIC,
  shelf_status  TEXT,
  cost_avg_price NUMERIC,
  UNIQUE(dealer_platform_id, platform_product_no)
);

CREATE TABLE order_header (
  order_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  dealer_platform_id INTEGER NOT NULL REFERENCES dealer_platform(dealer_platform_id),
  order_no      TEXT NOT NULL,          -- 字符串
  order_time    TEXT NOT NULL,
  customer_id   INTEGER REFERENCES customer(customer_id),
  order_status  TEXT NOT NULL,
  pay_method    TEXT,
  pay_status    TEXT,
  order_source  TEXT,
  order_type    TEXT,
  downstream_order_no TEXT,             -- 舟谱: SXD 的下游 XD 履约单号 (= XD.单据); 兴路强无 XD 层故为 NULL
  batch_id      INTEGER REFERENCES raw_import_batch(batch_id),
  UNIQUE(dealer_platform_id, order_no)
);
CREATE INDEX idx_order_time        ON order_header(order_time);
CREATE INDEX idx_order_status_time ON order_header(order_status, order_time);

CREATE TABLE order_line (
  order_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id      INTEGER NOT NULL REFERENCES order_header(order_id),
  product_id    INTEGER REFERENCES product(product_id),
  order_qty     NUMERIC,
  order_unit    TEXT,
  base_qty      NUMERIC,
  base_unit     TEXT,
  pre_discount_amount NUMERIC,
  discount_amount NUMERIC,
  unit_price    NUMERIC,
  return_qty    NUMERIC,
  UNIQUE(order_id, product_id)
);
CREATE INDEX idx_orderline_order ON order_line(order_id);

CREATE TABLE tpm_application (
  tpm_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  tpm_code      TEXT NOT NULL UNIQUE,   -- DCN-...
  theme         TEXT,
  promo_type    TEXT,
  customer_scope TEXT,
  product_group TEXT,
  apply_amount  NUMERIC,                -- 预算(例30000)
  budget_reserve_no TEXT,
  target_volume_uc NUMERIC,
  target_revenue NUMERIC,
  target_customer_count INTEGER,
  sales_org     TEXT,
  marketing_org TEXT,
  bu            TEXT,
  applicant     TEXT,
  plan_owner    TEXT,
  fee_pay_dept  TEXT,                   -- 费用承担方来源
  invoice_title TEXT,                   -- 费用承担方来源
  plan_start    TEXT,
  plan_end      TEXT,
  release_start TEXT,
  release_end   TEXT,
  closing_date  TEXT,
  approval_status TEXT,
  wbs_id        TEXT,
  tp_indicator  TEXT
);

CREATE TABLE activity (
  activity_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  dealer_platform_id INTEGER NOT NULL REFERENCES dealer_platform(dealer_platform_id),
  tpm_id        INTEGER REFERENCES tpm_application(tpm_id),
  activity_name TEXT NOT NULL,
  activity_category TEXT,               -- 券类/非券类
  promo_method  TEXT,                   -- 阶梯/叠加
  promotion_type TEXT,                  -- 满一定金额立减/立赠
  product_scope_type TEXT,
  disabled_product_scope_type TEXT,
  purchase_limit_type TEXT,
  purchase_limit_value NUMERIC,
  customer_scope_type TEXT,
  disabled_customer_scope_type TEXT,
  use_device    TEXT,
  limit_recharge_gift TEXT,
  start_time    TEXT NOT NULL,
  end_time      TEXT NOT NULL,
  use_scene     TEXT,
  allow_stack   TEXT,
  allow_coupon  TEXT,
  min_sku_count NUMERIC,
  activity_status TEXT,
  rule_version  TEXT,
  activity_import_key TEXT
);
CREATE UNIQUE INDEX uq_activity_import_key
  ON activity(activity_import_key)
  WHERE activity_import_key IS NOT NULL;

CREATE TABLE activity_rule (
  rule_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id   INTEGER NOT NULL REFERENCES activity(activity_id),
  tier_no       INTEGER NOT NULL,
  threshold_type TEXT,
  threshold_value NUMERIC,
  reduce_amount NUMERIC,
  free_shipping INTEGER DEFAULT 0,
  UNIQUE(activity_id, tier_no)
);

CREATE TABLE activity_rule_benefit (
  benefit_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id       INTEGER NOT NULL REFERENCES activity_rule(rule_id),
  benefit_type  TEXT NOT NULL,          -- 立减/免邮/赠品/送券
  gift_product_no TEXT,
  gift_product_name TEXT,
  gift_qty      NUMERIC,
  coupon_id     TEXT,
  coupon_name   TEXT,
  coupon_qty    NUMERIC
);

CREATE TABLE activity_scope (
  scope_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id   INTEGER NOT NULL REFERENCES activity(activity_id),
  scope_category TEXT NOT NULL,         -- 商品/禁用商品/客户/禁用客户
  scope_dimension TEXT NOT NULL,        -- 品牌/商品/目录/标签/供货商/客户/等级/类型/区域
  scope_value   TEXT NOT NULL
);
CREATE INDEX idx_scope_activity ON activity_scope(activity_id);

CREATE TABLE order_activity (
  order_activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id      INTEGER NOT NULL REFERENCES order_header(order_id),
  activity_id   INTEGER NOT NULL REFERENCES activity(activity_id),
  rule_id       INTEGER REFERENCES activity_rule(rule_id),
  activity_product_amount NUMERIC,
  platform_actual_benefit NUMERIC,
  gift_qty_actual NUMERIC,              -- 赠品实际发放数(满赠类; 券/减类为NULL)
  policy_text   TEXT,
  exec_status   TEXT,
  evidence_ref  TEXT,
  UNIQUE(order_id, activity_id)
);
CREATE INDEX idx_oa_order   ON order_activity(order_id);
CREATE INDEX idx_oa_activity ON order_activity(activity_id);

CREATE TABLE fulfillment (
  fulfillment_id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id      INTEGER NOT NULL UNIQUE REFERENCES order_header(order_id),
  order_status  TEXT NOT NULL,
  completed_at  TEXT,
  t2_release_candidate INTEGER DEFAULT 0,
  return_qty    NUMERIC,
  special_reason TEXT
);

CREATE TABLE cross_mapping (
  mapping_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  mapping_object_type TEXT NOT NULL,    -- 客户/商品
  dealer_platform_id INTEGER NOT NULL REFERENCES dealer_platform(dealer_platform_id),
  ec101_key     TEXT NOT NULL,
  swire_key     TEXT,
  match_status  TEXT,
  hit_field     TEXT,
  fuzzy_score   NUMERIC,
  manual_corrected INTEGER DEFAULT 0,
  snapshot_version TEXT,
  UNIQUE(mapping_object_type, dealer_platform_id, ec101_key)
);

CREATE TABLE coupon_ledger (
  coupon_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  dealer_platform_id INTEGER NOT NULL REFERENCES dealer_platform(dealer_platform_id),
  activity_id   INTEGER REFERENCES activity(activity_id),
  coupon_no     TEXT NOT NULL,          -- 字符串
  coupon_name   TEXT,
  customer_id   INTEGER REFERENCES customer(customer_id),
  salesperson_name TEXT,
  receive_time  TEXT,
  use_period    TEXT,
  coupon_status TEXT,
  use_time      TEXT,
  use_order_no  TEXT,                   -- 字符串, 与 order_header.order_no 同类型
  discount_amount NUMERIC,
  fee_month     TEXT,
  UNIQUE(dealer_platform_id, coupon_no)
);
CREATE INDEX idx_coupon_useorder ON coupon_ledger(use_order_no);
CREATE INDEX idx_coupon_activity ON coupon_ledger(activity_id);

CREATE TABLE coupon_issue_rule (
  coupon_issue_rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id          INTEGER NOT NULL UNIQUE REFERENCES activity(activity_id),
  issue_mode           TEXT NOT NULL CHECK(issue_mode IN ('auto_grant', 'manual_claim', 'order_rebate')),
  issue_start_at       TEXT NOT NULL,
  issue_end_at         TEXT,
  auto_issue_at        TEXT,
  coupon_qty_per_grant NUMERIC NOT NULL,
  max_claim_per_customer NUMERIC,
  daily_claim_limit    NUMERIC,
  rule_status          TEXT NOT NULL
);

CREATE TABLE coupon_use_rule (
  coupon_use_rule_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id              INTEGER NOT NULL UNIQUE REFERENCES activity(activity_id),
  coupon_type              TEXT NOT NULL,
  validity_mode            TEXT NOT NULL CHECK(validity_mode IN ('fixed_period', 'days_after_receive')),
  use_start_at             TEXT,
  use_end_at               TEXT,
  valid_days_after_receive INTEGER,
  max_use_per_coupon       NUMERIC NOT NULL,
  rule_status              TEXT NOT NULL
);

-- ========== RESULT ==========
CREATE TABLE rule_catalog (
  rule_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_topic    TEXT NOT NULL,
  version       TEXT NOT NULL,
  effective_from TEXT,
  confirmed_by  TEXT,
  scope         TEXT,
  rule_text     TEXT,
  UNIQUE(rule_topic, version)
);

CREATE TABLE result_calc_batch (
  calc_batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
  calc_date     TEXT NOT NULL,
  rule_version  TEXT NOT NULL,
  input_batch_id INTEGER REFERENCES raw_import_batch(batch_id),
  operator      TEXT,
  created_at    TEXT
);

CREATE TABLE result_entitlement (
  entitlement_id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_activity_id INTEGER NOT NULL REFERENCES order_activity(order_activity_id),
  theoretical_benefit NUMERIC,
  platform_actual_benefit NUMERIC,
  gift_qty_entitled NUMERIC,            -- 应赠数(满赠类)
  gift_qty_actual   NUMERIC,            -- 实赠数(满赠类)
  consistency   TEXT,                   -- 一致/差异
  diff_amount   NUMERIC,
  formula_ref   TEXT,
  calc_batch_id INTEGER REFERENCES result_calc_batch(calc_batch_id),
  UNIQUE(order_activity_id, calc_batch_id)
);

CREATE TABLE result_release_candidate (
  candidate_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id      INTEGER NOT NULL REFERENCES order_header(order_id),
  calc_date     TEXT NOT NULL,
  is_candidate  INTEGER NOT NULL,
  reason        TEXT,
  calc_batch_id INTEGER REFERENCES result_calc_batch(calc_batch_id),
  UNIQUE(order_id, calc_batch_id)
);

CREATE TABLE result_fee (
  fee_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  tpm_id        INTEGER REFERENCES tpm_application(tpm_id),
  activity_id   INTEGER NOT NULL REFERENCES activity(activity_id),
  actual_discount_total NUMERIC,
  gift_cost_total NUMERIC,
  fee_bearer    TEXT,
  settle_target TEXT,
  budget_amount NUMERIC,
  budget_reserve_no TEXT,
  settle_amount NUMERIC,
  diff_amount   NUMERIC,
  settle_status TEXT,
  calc_batch_id INTEGER REFERENCES result_calc_batch(calc_batch_id),
  UNIQUE(tpm_id, activity_id, calc_batch_id)
);

CREATE TABLE result_quality_issue (
  issue_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no      TEXT,
  issue_type    TEXT,
  level         TEXT,
  reason        TEXT,
  evidence_ref  TEXT,
  calc_batch_id INTEGER REFERENCES result_calc_batch(calc_batch_id)
);

-- ========== STANDARD (轻量) ==========
CREATE TABLE std_field_mapping (
  mapping_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform      TEXT NOT NULL,
  module        TEXT NOT NULL,
  raw_field     TEXT NOT NULL,
  ec101_field   TEXT,
  confidence    TEXT,
  is_non_v1     INTEGER DEFAULT 0,
  gap_flag      TEXT,
  UNIQUE(platform, module, raw_field)
);

CREATE TABLE std_quality_check (
  check_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id      INTEGER REFERENCES raw_import_batch(batch_id),
  check_item    TEXT NOT NULL,
  result        TEXT NOT NULL,          -- 通过/条件通过/阻断
  level         TEXT,
  impact        TEXT
);
