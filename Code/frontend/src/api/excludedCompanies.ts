import { API_BASE } from '@/lib/apiClient';

export interface ExcludedCompanyRecord {
  id: number;
  depot_code: string;
  company_name: string;
  reason: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ExcludedCompaniesResponse {
  items: ExcludedCompanyRecord[];
  total: number;
}

export interface ExcludedCompanyCreatePayload {
  depot_code: string;
  company_name: string;
  reason?: string;
  is_active?: boolean;
}

export interface ExcludedCompanyUpdatePayload {
  depot_code?: string;
  company_name?: string;
  reason?: string;
  is_active?: boolean;
}

export interface MasterDepot {
  id: string;
  code: string;
  name: string;
}

export interface DepotsResponse {
  depots: MasterDepot[];
  total: number;
}

export async function fetchExcludedCompanies(params?: {
  depot_code?: string;
  search?: string;
  active_only?: boolean;
}): Promise<ExcludedCompaniesResponse> {
  const query = new URLSearchParams();
  if (params?.depot_code && params.depot_code !== 'ALL') {
    query.set('depot_code', params.depot_code);
  }
  if (params?.search && params.search.trim()) {
    query.set('search', params.search.trim());
  }
  if (params?.active_only) {
    query.set('active_only', 'true');
  }

  const qs = query.toString();
  const url = `${API_BASE}/api/excluded-companies${qs ? `?${qs}` : ''}`;
  const res = await fetch(url);
  if (!res.ok) {
    const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(errData.detail || `Failed to fetch excluded companies: ${res.status}`);
  }
  return res.json();
}

export async function createExcludedCompany(
  payload: ExcludedCompanyCreatePayload,
): Promise<{ success: boolean; item: ExcludedCompanyRecord }> {
  const res = await fetch(`${API_BASE}/api/excluded-companies`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(errData.detail || `Failed to create excluded company: ${res.status}`);
  }
  return res.json();
}

export async function updateExcludedCompany(
  id: number,
  payload: ExcludedCompanyUpdatePayload,
): Promise<{ success: boolean; item: ExcludedCompanyRecord }> {
  const res = await fetch(`${API_BASE}/api/excluded-companies/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(errData.detail || `Failed to update excluded company: ${res.status}`);
  }
  return res.json();
}

export async function deleteExcludedCompany(
  id: number,
): Promise<{ success: boolean; deleted_id: number }> {
  const res = await fetch(`${API_BASE}/api/excluded-companies/${id}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(errData.detail || `Failed to delete excluded company: ${res.status}`);
  }
  return res.json();
}

export async function fetchDepotsList(): Promise<DepotsResponse> {
  const res = await fetch(`${API_BASE}/api/depots`);
  if (!res.ok) {
    const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(errData.detail || `Failed to fetch depots: ${res.status}`);
  }
  return res.json();
}
