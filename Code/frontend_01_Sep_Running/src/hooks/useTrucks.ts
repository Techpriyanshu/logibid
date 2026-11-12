import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createTruck,
  deleteTruck,
  fetchTrucks,
  updateTruck,
  uploadTruckDocument,
  type TruckCreatePayload,
  type TruckUpdatePayload,
} from '@/api/trucks';

export function useTrucks() {
  return useQuery({
    queryKey: ['trucks'],
    queryFn: fetchTrucks,
  });
}

export function useTruckActions() {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['trucks'] });
  };

  const create = useMutation({
    mutationFn: (payload: TruckCreatePayload) => createTruck(payload),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: ({ truckId, payload }: { truckId: string; payload: TruckUpdatePayload }) =>
      updateTruck(truckId, payload),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (truckId: string) => deleteTruck(truckId),
    onSuccess: invalidate,
  });

  const uploadDocument = useMutation({
    mutationFn: ({
      truckId,
      docType,
      file,
      expiryDate,
    }: {
      truckId: string;
      docType: string;
      file: File;
      expiryDate?: string;
    }) => uploadTruckDocument(truckId, { docType, file, expiryDate }),
    onSuccess: invalidate,
  });

  return { create, update, remove, uploadDocument, invalidate };
}
