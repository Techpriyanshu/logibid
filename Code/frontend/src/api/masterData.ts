import { API_BASE } from '@/lib/apiClient';

export interface Zone {
  id: string;
  code: string;
  name: string;
}

export interface Plant {
  id: string;
  code: string;
  name: string;
  zone_id: string;
  zone_name: string;
}

export interface DepotOption {
  id: string;
  code: string;
  name: string;
  sap_depot_id: string;
  quantity_only: boolean;
}

export interface TonnageOption {
  id: string;
  value: number;
  label: string;
}

export interface MasterDataSource {
  source?: 'database' | 'snapshot';
  snapshot_date?: string | null;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const fetchZones = () =>
  get<{ zones: Zone[]; total: number } & MasterDataSource>('/api/zones');

export const fetchPlants = (zoneId?: string) =>
  get<{ plants: Plant[]; total: number } & MasterDataSource>(
    zoneId ? `/api/plants?${new URLSearchParams({ zone_id: zoneId })}` : '/api/plants',
  );

export const fetchDepotsForPlant = (plantId: string) =>
  get<{ depots: DepotOption[]; total: number } & MasterDataSource>(
    `/api/plants/${encodeURIComponent(plantId)}/depots`,
  );

export const fetchDestinationsForDepot = (depotCode: string) =>
  get<{ destinations: string[]; total: number } & MasterDataSource>(
    `/api/depots/${encodeURIComponent(depotCode)}/destinations`,
  );

export const fetchTonnageOptions = () =>
  get<{ tonnage_options: TonnageOption[]; total: number } & MasterDataSource>(
    '/api/tonnage-options',
  );
