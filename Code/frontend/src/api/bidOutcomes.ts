import { API_BASE } from '@/lib/apiClient';

export type OutcomeStatus = 'won' | 'lost' | 'stopped' | 'paused' | 'failed';

export interface BidOutcome {
  outcome_id: string;
  leg_id: string;
  job_id: string;
  depot: string;
  destination: string | null;
  quantity: number;
  organization_name: string | null;
  bid_amount: number | null;
  rank: number | null;
  outcome_status: OutcomeStatus;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface BidOutcomesResponse {
  items: BidOutcome[];
  total: number;
}

export interface BidOutcomesJobResponse extends BidOutcomesResponse {
  job_id: string;
}

export interface BidOutcomesSummary {
  total: number;
  by_status: Partial<Record<OutcomeStatus, number>>;
  won: number;
  lost: number;
  stopped: number;
  paused: number;
  failed: number;
  win_rate: number | null;
}

export interface BidOutcomesQuery {
  job_id?: string;
  outcome_status?: OutcomeStatus;
  depot?: string;
  from_date?: string;
  to_date?: string;
  limit?: number;
}

export interface BidOutcomesSummaryQuery {
  depot?: string;
  from_date?: string;
  to_date?: string;
}

async function parseError(res: Response): Promise<string> {
  const data = (await res.json().catch(() => ({}))) as { detail?: string };
  return data.detail || `HTTP ${res.status}`;
}

export async function fetchBidOutcomes(
  query: BidOutcomesQuery = {},
): Promise<BidOutcomesResponse> {
  const params = new URLSearchParams();
  if (query.job_id) params.set('job_id', query.job_id);
  if (query.outcome_status) params.set('outcome_status', query.outcome_status);
  if (query.depot) params.set('depot', query.depot);
  if (query.from_date) params.set('from_date', query.from_date);
  if (query.to_date) params.set('to_date', query.to_date);
  if (query.limit != null) params.set('limit', String(query.limit));
  const qs = params.toString();
  const res = await fetch(`${API_BASE}/api/bid-outcomes${qs ? `?${qs}` : ''}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as BidOutcomesResponse;
}

export async function fetchBidOutcomesSummary(
  query: BidOutcomesSummaryQuery = {},
): Promise<BidOutcomesSummary> {
  const params = new URLSearchParams();
  if (query.depot) params.set('depot', query.depot);
  if (query.from_date) params.set('from_date', query.from_date);
  if (query.to_date) params.set('to_date', query.to_date);
  const qs = params.toString();
  const res = await fetch(`${API_BASE}/api/bid-outcomes/summary${qs ? `?${qs}` : ''}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as BidOutcomesSummary;
}

export async function fetchBidOutcomesByJob(
  jobId: string,
): Promise<BidOutcomesJobResponse> {
  const res = await fetch(`${API_BASE}/api/bid-outcomes/${encodeURIComponent(jobId)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as BidOutcomesJobResponse;
}
