import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createFleetDailyEntry,
  createFleetRequest,
  deleteFleetDailyEntry,
  fetchFleetDaily,
  fetchFleetRequests,
  updateFleetDailyEntry,
  updateFleetRequest,
  type FleetDailyCreatePayload,
  type FleetDailyUpdatePayload,
  type FleetRequestCreatePayload,
  type FleetRequestUpdatePayload,
} from '@/api/fleetAdmin';

export function useFleetDaily(businessDate?: string) {
  return useQuery({
    queryKey: ['fleet-daily', businessDate ?? 'all'],
    queryFn: () => fetchFleetDaily(businessDate),
  });
}

export function useFleetRequests(status?: string) {
  return useQuery({
    queryKey: ['fleet-requests', status ?? 'all'],
    queryFn: () => fetchFleetRequests(status),
    refetchInterval: 3000,
  });
}

export function useFleetAdminActions() {
  const queryClient = useQueryClient();

  const invalidateDaily = () => {
    queryClient.invalidateQueries({ queryKey: ['fleet-daily'] });
  };

  const invalidateRequests = () => {
    queryClient.invalidateQueries({ queryKey: ['fleet-requests'] });
  };

  const createDaily = useMutation({
    mutationFn: (payload: FleetDailyCreatePayload) => createFleetDailyEntry(payload),
    onSuccess: invalidateDaily,
  });

  const updateDaily = useMutation({
    mutationFn: ({ entryId, payload }: { entryId: string; payload: FleetDailyUpdatePayload }) =>
      updateFleetDailyEntry(entryId, payload),
    onSuccess: invalidateDaily,
  });

  const removeDaily = useMutation({
    mutationFn: (entryId: string) => deleteFleetDailyEntry(entryId),
    onSuccess: invalidateDaily,
  });

  const createRequest = useMutation({
    mutationFn: (payload: FleetRequestCreatePayload) => createFleetRequest(payload),
    onSuccess: invalidateRequests,
  });

  const resolveRequest = useMutation({
    mutationFn: ({
      requestId,
      payload,
    }: {
      requestId: string;
      payload: FleetRequestUpdatePayload;
    }) => updateFleetRequest(requestId, payload),
    onSuccess: () => {
      invalidateRequests();
      queryClient.invalidateQueries({ queryKey: ['live-bids'] });
    },
  });

  return {
    createDaily,
    updateDaily,
    removeDaily,
    createRequest,
    resolveRequest,
  };
}
