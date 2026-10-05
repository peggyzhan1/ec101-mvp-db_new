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
  });
});
