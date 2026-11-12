import type { LiveBid } from '@/api/liveBids';
import type { TruckDetail } from '@/store/adminStore';
import type { ActionRequest, VehicleBid } from '@/store/dataStore';
import type { FleetDailyEntry, FleetRequestRecord } from '@/api/fleetAdmin';
import { DEPOT_MASTER_LIST } from '@/constants/depots';

export function fleetDailyToTruckDetail(entry: FleetDailyEntry): TruckDetail {
  return {
    id: entry.id,
    truckNumber: entry.truck_number,
    driverName: entry.driver_name,
    tonnage: entry.tonnage,
    currentDepot: entry.current_depot,
    status: entry.status as TruckDetail['status'],
    previousDepot: entry.previous_depot ?? undefined,
    destination: entry.destination ?? undefined,
    availableSince: entry.available_since ?? undefined,
    contractType: entry.remarks ?? undefined,
  };
}

export function fleetRequestToActionRequest(req: FleetRequestRecord): ActionRequest {
  return {
    id: req.id,
    requestType: req.request_type,
    bidId: req.leg_id,
    vehicleId: req.leg_id,
    plantName: req.plant_name ?? '',
    depotName: req.depot_name ?? '',
    destination: req.destination ?? undefined,
    tonnage: req.tonnage ?? 0,
    requestedBy: req.requested_by,
    requestedAt: req.requested_at,
    status: req.status,
    remarks: req.remarks ?? undefined,
  };
}

export function pendingRequestByLegId(
  requests: FleetRequestRecord[],
): Map<string, FleetRequestRecord> {
  const map = new Map<string, FleetRequestRecord>();
  requests
    .filter((r) => r.status === 'Pending')
    .forEach((r) => map.set(r.leg_id, r));
  return map;
}

function isTerminalLiveBid(bid: LiveBid): boolean {
  return bid.status === 'won' || bid.status === 'completed' || bid.status === 'stopped';
}

export function liveBidToVehicleBid(
  bid: LiveBid,
  pendingRequest?: ActionRequest | null,
): VehicleBid {
  const depot = DEPOT_MASTER_LIST.find(
    (d) => d.name.toUpperCase() === bid.depot.toUpperCase(),
  );
  let status: VehicleBid['status'] = 'Live';
  if (isTerminalLiveBid(bid) || bid.user_control === 'stopped') {
    status = 'Closed';
  } else if (bid.user_control === 'paused' || bid.status === 'paused') {
    status = 'Paused';
  }
  return {
    id: bid.id,
    plant_id: 'tanda',
    plant_name: 'Tanda Cement Works',
    depot_id: depot?.id ?? '',
    depot_name: bid.depot,
    destination: bid.destination ?? undefined,
    tonnage: bid.quantity,
    status,
    rank: bid.current_rank,
    created_at: bid.updated_at,
    time_remaining: 0,
    pendingRequest: pendingRequest ?? null,
  };
}
