import { API_BASE } from '@/lib/apiClient';

export interface SuccessfulBidRecord {
  id: number;
  depot: string;
  destination: string | null;
  quantity: number;
  bid_amount: number;
  won_timestamp: string;
  rank: number;
}

export interface SuccessfulBidsResponse {
  items: SuccessfulBidRecord[];
  total: number;
}

export interface SuccessfulBidsQuery {
  month?: string;
  from?: string;
  to?: string;
  depot?: string;
}

export async function fetchSuccessfulBids(
  query?: SuccessfulBidsQuery,
): Promise<SuccessfulBidsResponse> {
  const params = new URLSearchParams();
  if (query?.month) params.set('month', query.month);
  if (query?.from) params.set('from', query.from);
  if (query?.to) params.set('to', query.to);
  if (query?.depot) params.set('depot', query.depot);
  const qs = params.toString();
  const url = `${API_BASE}/api/successful-bids${qs ? `?${qs}` : ''}`;
  const res = await fetch(url);
  const data = (await res.json()) as SuccessfulBidsResponse & { detail?: string };
  if (!res.ok) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return data;
}
