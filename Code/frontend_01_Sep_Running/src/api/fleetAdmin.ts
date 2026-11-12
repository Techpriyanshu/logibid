import { API_BASE } from '@/lib/apiClient';

export interface FleetDailyEntry {
  id: string;
  business_date: string;
  truck_id: string | null;
  truck_number: string;
  driver_name: string;
  tonnage: string;
  previous_depot: string | null;
  current_depot: string;
  destination: string | null;
  status: string;
  remarks: string | null;
  available_since: string | null;
  updated_at: string;
}

export interface FleetDailyResponse {
  items: FleetDailyEntry[];
  total: number;
}

export interface FleetDailyCreatePayload {
  business_date: string;
  truck_number: string;
  driver_name?: string;
  tonnage: string;
  previous_depot?: string;
  current_depot: string;
  destination?: string;
  status?: string;
  remarks?: string;
}

export interface FleetDailyUpdatePayload {
  driver_name?: string;
  tonnage?: string;
  previous_depot?: string;
  current_depot?: string;
  destination?: string;
  status?: string;
  remarks?: string;
}

export interface FleetRequestRecord {
  id: string;
  leg_id: string;
  job_id: string | null;
  truck_number: string | null;
  request_type: 'PAUSE' | 'CLOSE';
  status: 'Pending' | 'Approved' | 'Rejected';
  depot_name: string | null;
  destination: string | null;
  tonnage: number | null;
  plant_name: string | null;
  requested_by: string;
  requested_at: string;
  resolved_by: string | null;
  resolved_at: string | null;
  remarks: string | null;
  bidId?: string;
  vehicleId?: string;
  requestType?: 'PAUSE' | 'CLOSE';
  depotName?: string | null;
  requestedBy?: string;
  requestedAt?: string;
}

export interface FleetRequestsResponse {
  items: FleetRequestRecord[];
  total: number;
}

export interface FleetRequestCreatePayload {
  leg_id: string;
  request_type: 'PAUSE' | 'CLOSE';
  requested_by: string;
  job_id?: string;
  truck_number?: string;
  depot_name?: string;
  destination?: string;
  tonnage?: number;
  plant_name?: string;
  remarks?: string;
}

export interface FleetRequestUpdatePayload {
  status: 'Approved' | 'Rejected';
  resolved_by: string;
}

async function parseError(res: Response): Promise<string> {
  const data = (await res.json().catch(() => ({}))) as { detail?: string };
  return data.detail || `HTTP ${res.status}`;
}

export async function fetchFleetDaily(date?: string): Promise<FleetDailyResponse> {
  const params = new URLSearchParams();
  if (date) params.set('date', date);
  const qs = params.toString();
  const res = await fetch(`${API_BASE}/api/fleet-daily${qs ? `?${qs}` : ''}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as FleetDailyResponse;
}

export async function createFleetDailyEntry(
  payload: FleetDailyCreatePayload,
): Promise<FleetDailyEntry> {
  const res = await fetch(`${API_BASE}/api/fleet-daily`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as FleetDailyEntry;
}

export async function updateFleetDailyEntry(
  entryId: string,
  payload: FleetDailyUpdatePayload,
): Promise<FleetDailyEntry> {
  const res = await fetch(`${API_BASE}/api/fleet-daily/${entryId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as FleetDailyEntry;
}

export async function deleteFleetDailyEntry(entryId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/fleet-daily/${entryId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function fetchFleetRequests(
  status?: string,
): Promise<FleetRequestsResponse> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  const qs = params.toString();
  const res = await fetch(`${API_BASE}/api/fleet-requests${qs ? `?${qs}` : ''}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as FleetRequestsResponse;
}

export async function createFleetRequest(
  payload: FleetRequestCreatePayload,
): Promise<FleetRequestRecord> {
  const res = await fetch(`${API_BASE}/api/fleet-requests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as FleetRequestRecord;
}

export async function updateFleetRequest(
  requestId: string,
  payload: FleetRequestUpdatePayload,
): Promise<FleetRequestRecord> {
  const res = await fetch(`${API_BASE}/api/fleet-requests/${requestId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as FleetRequestRecord;
}

export async function deleteFleetRequest(requestId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/fleet-requests/${requestId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(await parseError(res));
}
