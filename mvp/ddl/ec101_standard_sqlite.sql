PRAGMA foreign_keys = ON;

CREATE TABLE import_batch (
  import_batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_key TEXT NOT NULL UNIQUE,
  dealer_name TEXT NOT NULL,
  platform_name TEXT NOT NULL,
  coverage_start TEXT,
  coverage_end TEXT,
  template_version TEXT NOT NULL,
  converter_version TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  status TEXT NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE import_file (
  import_file_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batch(import_batch_id),
  file_role TEXT NOT NULL,
  file_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  file_size INTEGER NOT NULL
);
CREATE TABLE import_validation_issue (
  issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER REFERENCES import_batch(import_batch_id),
  code TEXT NOT NULL,
  sheet_name TEXT,
  row_number INTEGER,
  column_name TEXT,
  message TEXT NOT NULL
);

CREATE TABLE dealer_platform (
  dealer_platform_id INTEGER PRIMARY KEY AUTOINCREMENT,
  dealer_name TEXT NOT NULL,
  platform_name TEXT NOT NULL,
  UNIQUE(dealer_name, platform_name)
);
CREATE TABLE customer (
  customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batch(import_batch_id),
  dealer_platform_id INTEGER NOT NULL REFERENCES dealer_platform(dealer_platform_id),
  customer_no TEXT NOT NULL, customer_name TEXT NOT NULL, customer_type TEXT,
  customer_region TEXT, address TEXT, phone TEXT, added_at TEXT, salesperson TEXT,
  UNIQUE(import_batch_id, customer_no)
);
CREATE TABLE product (
  product_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batch(import_batch_id),
  dealer_platform_id INTEGER NOT NULL REFERENCES dealer_platform(dealer_platform_id),
  product_no TEXT NOT NULL, product_name TEXT NOT NULL, brand TEXT, category TEXT,
  barcode TEXT, spec TEXT, base_unit TEXT, box_conversion TEXT, base_qty_per_box NUMERIC,
  UNIQUE(import_batch_id, product_no)
);
CREATE TABLE order_header (
  order_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batch(import_batch_id),
  dealer_platform_id INTEGER NOT NULL REFERENCES dealer_platform(dealer_platform_id),
  order_no TEXT NOT NULL, order_time TEXT, customer_no TEXT NOT NULL, customer_name TEXT,
  salesperson TEXT, order_source TEXT, order_type TEXT, order_status TEXT NOT NULL,
  payment_method TEXT, downstream_order_no TEXT,
  UNIQUE(import_batch_id, order_no)
);
CREATE TABLE order_line (
  order_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES order_header(order_id),
  product_no TEXT NOT NULL, product_name TEXT, category TEXT, spec TEXT, barcode TEXT,
  unit TEXT, quantity NUMERIC, pre_discount_amount NUMERIC, activity_numbers TEXT,
  coupon_numbers TEXT, discount_amount NUMERIC, paid_amount NUMERIC, unit_price NUMERIC,
  return_qty NUMERIC
);

CREATE TABLE activity (
  activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batch(import_batch_id),
  activity_no TEXT NOT NULL, activity_name TEXT NOT NULL, activity_type TEXT NOT NULL,
  promo_method TEXT, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
  allow_activity_stack TEXT, allow_coupon_stack TEXT, activity_status TEXT NOT NULL,
  UNIQUE(import_batch_id, activity_no)
);
CREATE TABLE activity_rule (
  activity_rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER NOT NULL REFERENCES activity(activity_id),
  rule_no TEXT NOT NULL, threshold_type TEXT NOT NULL, threshold_value NUMERIC,
  reduce_amount NUMERIC, free_shipping INTEGER DEFAULT 0,
  UNIQUE(activity_id, rule_no)
);
CREATE TABLE activity_benefit (
  activity_benefit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER NOT NULL REFERENCES activity(activity_id),
  rule_no TEXT NOT NULL, benefit_no TEXT NOT NULL, benefit_type TEXT NOT NULL,
  gift_product_no TEXT, gift_product_name TEXT, gift_qty NUMERIC, gift_unit TEXT,
  UNIQUE(activity_id, rule_no, benefit_no)
);
CREATE TABLE activity_scope (
  activity_scope_id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER NOT NULL REFERENCES activity(activity_id),
  scope_no TEXT NOT NULL, scope_category TEXT NOT NULL, scope_dimension TEXT NOT NULL,
  scope_value TEXT NOT NULL
);
CREATE TABLE activity_execution (
  activity_execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER NOT NULL REFERENCES activity(activity_id),
  order_id INTEGER NOT NULL REFERENCES order_header(order_id),
  activity_name TEXT, customer_no TEXT, customer_name TEXT, salesperson TEXT,
  product_amount NUMERIC, discount_amount NUMERIC,
  UNIQUE(activity_id, order_id)
);
CREATE TABLE fulfillment (
  fulfillment_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batch(import_batch_id),
  order_no TEXT NOT NULL, downstream_order_no TEXT, fulfillment_status TEXT NOT NULL,
  outbound_at TEXT, completed_at TEXT, settlement_status TEXT, return_qty NUMERIC
);

CREATE TABLE coupon_config (
  coupon_config_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batch(import_batch_id),
  config_no TEXT NOT NULL, coupon_name TEXT NOT NULL, coupon_type TEXT, config_status TEXT NOT NULL,
  UNIQUE(import_batch_id, config_no)
);
CREATE TABLE coupon_issue_rule (
  coupon_issue_rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
  coupon_config_id INTEGER NOT NULL UNIQUE REFERENCES coupon_config(coupon_config_id),
  issue_mode TEXT NOT NULL, issue_start_at TEXT NOT NULL, issue_end_at TEXT,
  auto_issue_at TEXT, qty_per_issue NUMERIC NOT NULL, max_claim_per_customer NUMERIC,
  daily_claim_limit NUMERIC, rule_status TEXT NOT NULL
);
CREATE TABLE coupon_use_rule (
  coupon_use_rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
  coupon_config_id INTEGER NOT NULL UNIQUE REFERENCES coupon_config(coupon_config_id),
  coupon_type TEXT NOT NULL, validity_mode TEXT NOT NULL, use_start_at TEXT,
  use_end_at TEXT, valid_days_after_receive INTEGER, max_use_per_coupon NUMERIC NOT NULL,
  rule_status TEXT NOT NULL
);
CREATE TABLE coupon_scope (
  coupon_scope_id INTEGER PRIMARY KEY AUTOINCREMENT,
  coupon_config_id INTEGER NOT NULL REFERENCES coupon_config(coupon_config_id),
  scope_no TEXT NOT NULL, scope_category TEXT NOT NULL, scope_dimension TEXT NOT NULL,
  scope_value TEXT NOT NULL
);
CREATE TABLE coupon_redemption (
  coupon_redemption_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batch(import_batch_id),
  order_id INTEGER REFERENCES order_header(order_id),
  coupon_no TEXT NOT NULL, customer_no TEXT NOT NULL, customer_name TEXT,
  salesperson TEXT, receive_time TEXT, use_period TEXT, status TEXT NOT NULL,
  used_at TEXT, discount_amount NUMERIC
);

CREATE TABLE calculation_run (
  calculation_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batch(import_batch_id),
  calc_date TEXT,
  activity_benefit NUMERIC NOT NULL DEFAULT 0,
  coupon_benefit NUMERIC NOT NULL DEFAULT 0,
  total_benefit NUMERIC NOT NULL DEFAULT 0,
  status TEXT NOT NULL
);
CREATE TABLE entitlement_check (
  entitlement_check_id INTEGER PRIMARY KEY AUTOINCREMENT,
  calculation_run_id INTEGER NOT NULL REFERENCES calculation_run(calculation_run_id),
  order_id INTEGER REFERENCES order_header(order_id),
  activity_id INTEGER REFERENCES activity(activity_id),
  activity_benefit NUMERIC, coupon_benefit NUMERIC,
  total_benefit NUMERIC, gift_qty_entitled NUMERIC, gift_qty_actual NUMERIC, consistency TEXT
);
CREATE TABLE release_candidate (
  release_candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
  calculation_run_id INTEGER NOT NULL REFERENCES calculation_run(calculation_run_id),
  order_id INTEGER NOT NULL REFERENCES order_header(order_id), is_candidate INTEGER NOT NULL, reason TEXT
);
CREATE TABLE activity_fee_summary (
  activity_fee_summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
  calculation_run_id INTEGER NOT NULL REFERENCES calculation_run(calculation_run_id),
  activity_id INTEGER NOT NULL REFERENCES activity(activity_id), actual_discount_total NUMERIC NOT NULL DEFAULT 0,
  gift_cost_total NUMERIC NOT NULL DEFAULT 0, gift_qty_entitled NUMERIC, gift_qty_actual NUMERIC,
  releasable_discount_total NUMERIC, releasable_gift_qty NUMERIC, release_order_count INTEGER,
  settle_status TEXT
);
CREATE TABLE coupon_fee_summary (
  coupon_fee_summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
  calculation_run_id INTEGER NOT NULL REFERENCES calculation_run(calculation_run_id),
  coupon_config_id INTEGER REFERENCES coupon_config(coupon_config_id),
  used_count INTEGER NOT NULL DEFAULT 0,
  used_amount NUMERIC NOT NULL DEFAULT 0,
  linked_amount NUMERIC NOT NULL DEFAULT 0,
  releasable_count INTEGER NOT NULL DEFAULT 0,
  releasable_amount NUMERIC NOT NULL DEFAULT 0,
  unlinked_count INTEGER NOT NULL DEFAULT 0,
  unlinked_amount NUMERIC NOT NULL DEFAULT 0,
  settle_status TEXT
);
CREATE TABLE calculation_quality_issue (
  calculation_quality_issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
  calculation_run_id INTEGER NOT NULL REFERENCES calculation_run(calculation_run_id),
  order_no TEXT, issue_type TEXT NOT NULL, level TEXT NOT NULL, reason TEXT NOT NULL
);
