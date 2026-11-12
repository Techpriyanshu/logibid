import { API_BASE } from '@/lib/apiClient';

export interface LiveBid {
  id: string;
  job_id: string;
  depot: string;
  destination: string | null;
  quantity: number;
  organization_name: string | null;
  current_rank: number | null;
  status: string;
  won_timestamp: string | null;
  user_control: 'active' | 'paused' | 'stopped';
  updated_at: string;
}

export interface LiveBidsResponse {
  items: LiveBid[];
  total: number;
}

export const ACTIVE_BID_JOB_KEY = 'activeBidJobId';

export function getActiveBidJobId(): string | null {
  try {
    return sessionStorage.getItem(ACTIVE_BID_JOB_KEY);
  } catch {
    return null;
  }
}

export function setActiveBidJobId(jobId: string): void {
  try {
    sessionStorage.setItem(ACTIVE_BID_JOB_KEY, jobId);
  } catch {
    /* ignore */
  }
}

export async function debugLog(tag: string, data: Record<string, unknown>, level: 'info' | 'warn' | 'error' = 'info'): Promise<void> {
  console.log(`[${tag}]`, data);
  try {
    await fetch(`${API_BASE}/api/debug-log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level, tag, data }),
    });
  } catch { /* never block UI */ }
}

export async function fetchLiveBids(jobId?: string | null): Promise<LiveBidsResponse> {
  const params = new URLSearchParams();
  if (jobId) {
    params.set('job_id', jobId);
  }
  const qs = params.toString();
  const url = `${API_BASE}/api/live-bids${qs ? `?${qs}` : ''}`;
  console.log('[liveBids] fetchLiveBids url:', url);
  const res = await fetch(url);
  const data = (await res.json()) as LiveBidsResponse & { detail?: string };
  console.log('[liveBids] fetchLiveBids response status:', res.status, 'data:', data);
  if (!res.ok) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return data;
}

export async function pauseLiveBid(legId: string): Promise<void> {
  console.log('[liveBids] pauseLiveBid legId:', legId);
  const res = await fetch(`${API_BASE}/api/live-bids/${legId}/pause`, { method: 'POST' });
  console.log('[liveBids] pause response:', res.status);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`);
  }
}

export async function resumeLiveBid(legId: string): Promise<void> {
  console.log('[liveBids] resumeLiveBid legId:', legId);
  const res = await fetch(`${API_BASE}/api/live-bids/${legId}/resume`, { method: 'POST' });
  console.log('[liveBids] resume response:', res.status);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`);
  }
}

export async function stopLiveBid(legId: string): Promise<void> {
  console.log('[liveBids] stopLiveBid legId:', legId);
  const res = await fetch(`${API_BASE}/api/live-bids/${legId}/stop`, { method: 'POST' });
  console.log('[liveBids] stop response:', res.status);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`);
  }
}
