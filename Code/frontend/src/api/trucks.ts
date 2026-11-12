import { API_BASE } from '@/lib/apiClient';

export interface TruckDocumentRecord {
  id: string;
  truck_id: string;
  type: string;
  file_name: string;
  file_url: string;
  expiry_date: string | null;
  uploaded_at: string;
}

export interface TruckMasterRecord {
  id: string;
  truck_number: string;
  driver_name: string;
  tonnage: string;
  status: string;
  rotation_count: number;
  plant_id: string;
  plant_name: string;
  depot_id: string;
  depot_name: string;
  created_at: string;
  updated_at: string;
  documents: TruckDocumentRecord[];
}

export interface TrucksResponse {
  items: TruckMasterRecord[];
  total: number;
}

export interface TruckCreatePayload {
  truck_number: string;
  driver_name: string;
  tonnage?: string;
  status?: string;
  rotation_count?: number;
  plant_id?: string;
  plant_name?: string;
  depot_id?: string;
  depot_name?: string;
}

export interface TruckUpdatePayload {
  driver_name?: string;
  tonnage?: string;
  status?: string;
  rotation_count?: number;
  plant_id?: string;
  plant_name?: string;
  depot_id?: string;
  depot_name?: string;
}

export function truckDocumentFullUrl(fileUrl: string): string {
  if (fileUrl.startsWith('http://') || fileUrl.startsWith('https://')) {
    return fileUrl;
  }
  return `${API_BASE}${fileUrl.startsWith('/') ? fileUrl : `/${fileUrl}`}`;
}

async function parseError(res: Response): Promise<string> {
  const data = (await res.json().catch(() => ({}))) as { detail?: string };
  return data.detail || `HTTP ${res.status}`;
}

export async function fetchTrucks(): Promise<TrucksResponse> {
  const res = await fetch(`${API_BASE}/api/trucks`);
  const data = (await res.json()) as { trucks?: TruckMasterRecord[]; items?: TruckMasterRecord[]; total?: number; detail?: string };
  if (!res.ok) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  // Backend returns { trucks, total } — normalize to { items, total }
  const items = data.items ?? data.trucks ?? [];
  return { items, total: data.total ?? items.length };
}

export async function fetchTruck(truckId: string): Promise<TruckMasterRecord> {
  const res = await fetch(`${API_BASE}/api/trucks/${truckId}`);
  const data = (await res.json()) as TruckMasterRecord & { detail?: string };
  if (!res.ok) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return data;
}

export async function createTruck(payload: TruckCreatePayload): Promise<TruckMasterRecord> {
  const res = await fetch(`${API_BASE}/api/trucks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return (await res.json()) as TruckMasterRecord;
}

export async function updateTruck(
  truckId: string,
  payload: TruckUpdatePayload,
): Promise<TruckMasterRecord> {
  const res = await fetch(`${API_BASE}/api/trucks/${truckId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return (await res.json()) as TruckMasterRecord;
}

export async function deleteTruck(truckId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/trucks/${truckId}`, { method: 'DELETE' });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
}

export async function uploadTruckDocument(
  truckId: string,
  params: {
    docType: string;
    file: File;
    expiryDate?: string;
  },
): Promise<TruckDocumentRecord> {
  const form = new FormData();
  form.append('doc_type', params.docType);
  form.append('file', params.file);
  if (params.expiryDate) {
    form.append('expiry_date', params.expiryDate);
  }
  const res = await fetch(`${API_BASE}/api/trucks/${truckId}/documents`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return (await res.json()) as TruckDocumentRecord;
}
