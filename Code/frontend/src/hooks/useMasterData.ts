import { useQuery } from '@tanstack/react-query';
import {
  fetchZones,
  fetchPlants,
  fetchDepotsForPlant,
  fetchDestinationsForDepot,
  fetchTonnageOptions,
} from '@/api/masterData';

export function useZones() {
  return useQuery({
    queryKey: ['zones'],
    queryFn: fetchZones,
    staleTime: 0,
    refetchOnMount: true,
  });
}

export function usePlants(zoneId?: string) {
  return useQuery({
    queryKey: ['plants', zoneId],
    queryFn: () => fetchPlants(zoneId),
    enabled: !!zoneId,
    staleTime: 0,
    refetchOnMount: true,
  });
}

export function useDepotsForPlant(plantId?: string) {
  return useQuery({
    queryKey: ['plant-depots', plantId],
    queryFn: () => {
      if (!plantId) throw new Error('plantId is required');
      return fetchDepotsForPlant(plantId);
    },
    enabled: !!plantId,
    staleTime: 0,
    refetchOnMount: false,
  });
}

export function useDestinationsForDepot(depotCode?: string) {
  return useQuery({
    queryKey: ['depot-destinations', depotCode],
    queryFn: () => fetchDestinationsForDepot(depotCode!),
    enabled: !!depotCode,
    staleTime: 0,
    refetchOnMount: false,
  });
}

export function useTonnageOptions() {
  return useQuery({
    queryKey: ['tonnage-options'],
    queryFn: fetchTonnageOptions,
    staleTime: 0,
    refetchOnMount: true,
  });
}
