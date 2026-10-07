import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Home from './page';

const gift = { activityId: 2, activityNo: '满赠优惠', activityName: '满赠优惠', dealer: '深圳市兴路强商贸有限公司', platform: '快马', promotionType: '满赠', benefitKind: 'gift', startTime: null, endTime: null, importBatchId: 2, calcBatchId: 2, calcDate: '2026-09-22', releaseCutoff: '2026-09-20 00:00:00', actualDiscountTotal: 0, settleAmount: null, participatingOrders: 98, releasedOrders: 98, releasedAmount: 0, pendingOrders: 0, pendingAmount: 0, warningCount: 0, tipCount: 0, status: '已核验' };
const manjian = { ...gift, activityId: 1, activityNo: '可口可乐满减', activityName: '可口可乐满减', promotionType: '满减', benefitKind: 'money', importBatchId: 1, calcBatchId: 1, actualDiscountTotal: 2040, settleAmount: 1995, participatingOrders: 136, releasedOrders: 133, releasedAmount: 1995, pendingOrders: 3, pendingAmount: 45, tipCount: 3, status: '可提交' };
const overview = { submittableAmount: 1995, couponBenefit: 200, releasedCouponBenefit: 200, participatingOrders: 234, releasedOrders: 231, giftReleasedOrders: 98, waitingCount: 0, handlingCount: 0, runs: [{ calcBatchId: 1, importBatchId: 1, dealer: '深圳市兴路强商贸有限公司', platform: '快马', coverageStart: '2026-08-31', coverageEnd: '2026-09-17', calcDate: '2026-09-22', releaseCutoff: '2026-09-20 00:00:00' }] };
const emptyOverview = { submittableAmount: 0, couponBenefit: 0, releasedCouponBenefit: 0, participatingOrders: 0, releasedOrders: 0, giftReleasedOrders: 0, waitingCount: 0, handlingCount: 0, runs: [] };
const importBatch = { import_batch_id: 1, dealer_name: '深圳市兴路强商贸有限公司', platform_name: '快马', coverage_start: '2026-08-31', coverage_end: '2026-09-17', imported_at: '2026-10-05T10:00:00', status: 'calculated', is_current: 1, calc_date: '2026-09-22', order_count: 1764, participating_orders: 136, released_orders: 133, activity_benefit: 2040, coupon_benefit: 200, released_activity_benefit: 1995, released_coupon_benefit: 200 };

const coupon = { couponConfigId: 1, configNo: 'KM-COUPON-AUTO-001', couponName: 'test1', couponType: '单品优惠', dealer: '深圳市兴路强商贸有限公司', platform: '快马', importBatchId: 1, calcBatchId: 1, calcDate: '2026-09-22', releaseCutoff: '2026-09-20 00:00:00', participatingOrders: 1, couponBenefit: 200, releasedCouponBenefit: 200, status: '可提交', benefitKind: 'coupon' };
const feeApi = (rows: unknown[], summary = overview, coupons: unknown[] = [], roi: unknown[] = []) => vi.fn((url: string) => {
  const path = String(url);
  const payload = path.includes('/api/fee-tpm/overview') ? summary
    : path.includes('/api/fee-tpm/coupons') ? { rows: coupons }
    : path.includes('/api/fee-tpm/roi') ? { rows: roi }
    : path.includes('/api/fee-tpm/activities') ? { rows }
    : path.includes('/api/fee-tpm/settlements') ? { rows: rows.filter((row) => (row as { status: string }).status === '可提交') }
    : path.includes('/api/imports') ? { rows: [importBatch] }
    : { rows: [] };
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('fee TPM workspace', () => {
  it('renders gift activities as order counts and money activities as released amounts', async () => {
    vi.stubGlobal('fetch', feeApi([manjian, gift]));
    render(<Home />);
    expect(await screen.findByText('¥ 1995.00')).toBeInTheDocument();
    expect(screen.getByText(/满赠可释放 98 单/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: '活动中心' })[0]);
    expect(await screen.findByText('98 单可释放')).toBeInTheDocument();
    expect(screen.getByText(/赠品按数量统计，不折算金额/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: '核销与对账' })[0]);
    expect(await screen.findByText(/1 个金额活动可释放，合计 ¥ 1995.00/)).toBeInTheDocument();
  });

  it('does not fall back to a snapshot when the API fails', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 500 })));
    render(<Home />);
    expect(await screen.findByText(/无法连接核算服务/)).toBeInTheDocument();
  });

  it('lists imported batches from the API instead of a static table', async () => {
    vi.stubGlobal('fetch', feeApi([]));
    render(<Home />);
    fireEvent.click(screen.getAllByRole('button', { name: '数据接入' })[0]);
    expect(await screen.findByText('2026-08-31 至 2026-09-17')).toBeInTheDocument();
    expect(screen.getByText('当前有效')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '查看结果' })).toBeInTheDocument();
  });

  it('queries business data from the standard schema and opens an order with its lines', async () => {
    const order = { id: 713, import_batch_id: 1, order_no: '1012420526026091000081', dealer: '深圳市兴路强商贸有限公司', platform: '快马', customer_no: 'WX-1', customer: '可口可乐客户测试', salesperson: '', order_time: '2026-09-10 16:18:49', order_status: '已完成', line_count: 2, paid_amount: 1704.8, discount_amount: 215, activities: '可口可乐满减', coupons: '202609091700313431' };
    const detail = { ...order, lines: [{ order_line_id: 1, product_no: 'P1', product_name: '可口可乐 330ml', spec: '330ml', unit: '箱', quantity: 10, unit_price: 50, pre_discount_amount: 500, discount_amount: 15, paid_amount: 485, activity_numbers: '可口可乐满减', coupon_numbers: '' }], activity_executions: [{ activity_no: '可口可乐满减', activity_name: '可口可乐满减', activity_type: '满减', product_amount: 1919.8, discount_amount: 15 }], coupon_redemptions: [{ coupon_no: '202609091700313431', status: '已使用', used_at: '2026-09-10 16:18:48', discount_amount: 200 }], release: { is_candidate: 1, reason: '已完成且达到T-2', activity_benefit: 15, coupon_benefit: 200, calc_date: '2026-09-22', release_cutoff: '2026-09-20 00:00:00' }, entitlement: { consistency: '一致', theoretical_activity_benefit: 15, theoretical_coupon_benefit: 200, formula_ref: 'activity_rule.reduce_amount' } };
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/api/business-data/orders/713')) return Promise.resolve({ ok: true, json: () => Promise.resolve(detail) });
      if (url.includes('/api/business-data/orders')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ rows: [order], total: 1, limit: 50, offset: 0 }) });
      return feeApi([])(url);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<Home />);
    fireEvent.click(screen.getAllByRole('button', { name: '业务数据' })[0]);
    expect(await screen.findByText('1012420526026091000081')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/business-data/orders?') && String(url).includes('limit=50'))).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '查看详情' }));
    expect(await screen.findByText('可口可乐 330ml')).toBeInTheDocument();
    expect(screen.getByText('已完成且达到T-2')).toBeInTheDocument();
    expect(screen.getByText('券优惠 ¥ 200.00')).toBeInTheDocument();
    expect(screen.getByText('一致性 一致')).toBeInTheDocument();
    expect(screen.getByText('理论活动 ¥ 15.00')).toBeInTheDocument();
  });

  it('shows confirmed ROI paid amount and hides gift ratio', async () => {
    const roi = [
      { kind: 'money', name: '可口可乐满减', dealer: '深圳市兴路强商贸有限公司', platform: '快马', periodStart: '2026-08-31 10:58:00', periodEnd: '2026-09-17 23:59:00', periodMissing: false, completedOrders: 133, cokeQtyBase: 24195, cokePaidAmount: 55021.83, feeAmount: 1995, roi: 27.58, calcBatchId: 1 },
      { kind: 'gift', name: '满赠优惠', dealer: '深圳市兴路强商贸有限公司', platform: '快马', periodStart: '2026-08-19 15:15:00', periodEnd: '2026-08-31 23:59:00', periodMissing: false, completedOrders: 98, cokeQtyBase: 10068, cokePaidAmount: 23112.68, feeAmount: 0, roi: null, calcBatchId: 2 },
      { kind: 'coupon', name: 'test1', dealer: '深圳市兴路强商贸有限公司', platform: '快马', periodStart: '2026-09-09 16:50:00', periodEnd: '2026-09-12 16:50:00', periodMissing: false, completedOrders: 1, cokeQtyBase: 960, cokePaidAmount: 1704.8, feeAmount: 200, roi: 8.52, calcBatchId: 1 },
    ];
    vi.stubGlobal('fetch', feeApi([manjian, gift], overview, [coupon], roi));
    render(<Home />);
    expect(await screen.findByText('券核销合计 ¥ 200.00')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'ROI 分析' })[0]);
    expect(await screen.findByText('27.58')).toBeInTheDocument();
    expect(screen.getByText('满赠只统计金额')).toBeInTheDocument();
    expect(screen.getByText('¥ 23112.68')).toBeInTheDocument();
    expect(screen.getByText('8.52')).toBeInTheDocument();
  });

  it('offers the verification report download for activities and coupons', async () => {
    vi.stubGlobal('fetch', feeApi([manjian, gift], overview, [coupon]));
    render(<Home />);
    expect(await screen.findByText('券核销合计 ¥ 200.00')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: '活动中心' })[0]);
    expect(await screen.findByText('test1')).toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: '下载核验报告' });
    expect(links.some((link) => link.getAttribute('href')?.includes('/api/fee-tpm/activities/1/verification-report?calc_batch_id=1'))).toBe(true);
    expect(links.some((link) => link.getAttribute('href')?.includes('/api/fee-tpm/coupons/1/verification-report?calc_batch_id=1'))).toBe(true);
  });

  it('shows standard workbook import controls in data intake', async () => {
    vi.stubGlobal('fetch', feeApi([], emptyOverview));
    render(<Home />);
    fireEvent.click(screen.getAllByRole('button', { name: '数据接入' })[0]);
    expect(await screen.findByText('上传标准数据')).toBeInTheDocument();
    expect(screen.getByLabelText('标准数据 Excel')).toBeInTheDocument();
    expect(screen.getByLabelText('核算日')).toBeInTheDocument();
  });

  it('sends the calc date with the upload and lists per-order release results', async () => {
    const calculation = { calculation_run_id: 1, calc_date: '2026-09-22', release_cutoff: '2026-09-20 00:00:00', activity_benefit: 30, coupon_benefit: 0, total_benefit: 30, released_activity_benefit: 15, released_coupon_benefit: 0, participating_orders: 2, released_orders: 1, status: 'calculated' };
    const releaseRows = [
      { order_id: 1, order_no: 'O-RELEASED', order_time: '2026-09-01 10:00:00', order_status: '已完成', customer_no: 'C1', customer_name: '客户一', salesperson: null, is_candidate: 1, reason: '已完成且达到T-2', activity_benefit: 15, coupon_benefit: 0, activities: '可口可乐满减', coupons: null },
      { order_id: 2, order_no: 'O-PENDING', order_time: '2026-09-14 10:00:00', order_status: '部分发货', customer_no: 'C1', customer_name: '客户一', salesperson: null, is_candidate: 0, reason: '订单状态=部分发货', activity_benefit: 15, coupon_benefit: 0, activities: '可口可乐满减', coupons: null },
    ];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return Promise.resolve({ ok: true, json: () => Promise.resolve({ import_batch_id: 7, calculation_run_id: 1, status: 'calculated', calculation }) });
      if (url.endsWith('/api/imports/7')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ import_batch_id: 7, calculation, activities: [{ activity_id: 1, activity_no: '可口可乐满减', activity_name: '可口可乐满减', activity_type: '满减', actual_discount_total: 30, participating_orders: 2, released_orders: 1, released_amount: 15, pending_orders: 1, pending_amount: 15 }] }) });
      if (url.includes('/api/imports/7/release')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ import_batch_id: 7, calculation, rows: releaseRows, total: 2, limit: 2000, offset: 0 }) });
      return feeApi([], emptyOverview)(url);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<Home />);
    fireEvent.click(screen.getAllByRole('button', { name: '数据接入' })[0]);
    await screen.findByText('上传标准数据');
    fireEvent.change(screen.getByLabelText('标准数据 Excel'), { target: { files: [new File(['x'], 'standard.xlsx')] } });
    fireEvent.change(screen.getByLabelText('核算日'), { target: { value: '2026-09-22' } });
    fireEvent.click(screen.getByRole('button', { name: '开始导入' }));
    expect(await screen.findByText('O-RELEASED')).toBeInTheDocument();
    expect(screen.getByText('O-PENDING')).toBeInTheDocument();
    expect(screen.getByText('订单状态=部分发货')).toBeInTheDocument();
    expect(screen.getByText(/核算日 2026-09-22/)).toBeInTheDocument();
    const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(postCall).toBeDefined();
    const postBody = postCall![1]!.body as FormData;
    expect(postBody.get('calc_date')).toBe('2026-09-22');
  });
});
