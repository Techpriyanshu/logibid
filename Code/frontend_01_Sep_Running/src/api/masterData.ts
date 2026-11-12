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

async function get<T>(path: string): Promise<T> {
  console.log('[API] Fetching:', `${API_BASE}${path}`);
  const res = await fetch(`${API_BASE}${path}`);
  console.log('[API] Response:', res.status, res.url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export const fetchZones = () =>
  get<{ zones: Zone[]; total: number }>('/api/zones');

export const fetchPlants = (zoneId?: string) =>
  get<{ plants: Plant[]; total: number }>(
    zoneId ? `/api/plants?zone_id=${zoneId}` : '/api/plants',
  );

export const fetchDepotsForPlant = (plantId: string) =>
  get<{ depots: DepotOption[]; total: number }>(`/api/plants/${plantId}/depots`);

export const fetchDestinationsForDepot = (depotCode: string) =>
  get<{ destinations: string[]; total: number }>(`/api/depots/${depotCode}/destinations`);

export const fetchTonnageOptions = () =>
  get<{ tonnage_options: TonnageOption[]; total: number }>('/api/tonnage-options');
