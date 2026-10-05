import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Home from './page';

const activity = { activityId: 2, activityName: '满赠优惠', dealer: '兴路强', platform: '快马', promotionType: '立赠', benefitKind: 'gift', ruleVersion: 'v1', calcBatchId: 2, calcDate: '2026-10-04', tpm: null, actualDiscountTotal: 0, settleAmount: null, budgetRemaining: null, giftQtyEntitled: 98, giftQtyActual: 98, releaseCandidates: 1, warningCount: 0, tipCount: 0, status: '已核验' };

afterEach(() => vi.unstubAllGlobals());

describe('fee TPM workspace', () => {
  it('renders a non-TPM gift as a quantity and never as currency', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve({ ok: true, json: () => Promise.resolve(url.includes('overview') ? { submittableAmount: 0, giftQtyActual: 98, waitingCount: 0, handlingCount: 0 } : url.includes('activities') ? { rows: [activity] } : { rows: [] }) })));
    render(<Home />);
    await screen.findByText('98 个');
    expect(screen.getByText(/不走 TPM/)).toBeInTheDocument();
    expect(screen.getByText(/预算和结算金额不会按零值展示/)).toBeInTheDocument();
  });

  it('does not fall back to a snapshot when the API fails', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 500 })));
    render(<Home />);
    expect(await screen.findByText('无法加载核算结果，未使用快照回退。')).toBeInTheDocument();
  });

  it('shows standard workbook import controls in data intake', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve({ ok: true, json: () => Promise.resolve(url.includes('overview') ? { submittableAmount: 0, giftQtyActual: 0, waitingCount: 0, handlingCount: 0 } : { rows: [] }) })));
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
      return Promise.resolve({ ok: true, json: () => Promise.resolve(url.includes('overview') ? { submittableAmount: 0, giftQtyActual: 0, waitingCount: 0, handlingCount: 0 } : { rows: [] }) });
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
