import { format } from 'date-fns';
import { useMemo } from 'react';
import { useTrucks } from '@/hooks/useTrucks';
import { useFleetDaily } from '@/hooks/useFleetAdmin';
import { useLiveBids } from '@/hooks/useLiveBids';
import { getActiveBidJobId } from '@/api/liveBids';
import { fleetDailyToTruckDetail } from '@/utils/fleetAdminMappers';
import { DEPOT_MASTER_LIST } from '@/constants/depots';
import { useDataStore } from '@/store/dataStore';

export interface FleetAvailabilityCounts {
  totalTrucks: number;
  availableTrucks: number;
  activeTrucks: number;
  nonActiveTrucks: number;
  inTripTrucks: number;
  biddingTrucks: number;
}

function liveBidDepotKey(depotName: string, quantity: number): string {
  const depot = DEPOT_MASTER_LIST.find(
    (d) => d.name.toUpperCase() === depotName.toUpperCase(),
  );
  const depotId = depot?.id ?? depotName;
  return `${depotId}-${quantity}T`;
}

/**
 * Fleet availability counts from Fleet Admin daily API (single source of truth).
 */
export function useFleetAvailability(): FleetAvailabilityCounts {
  const today = format(new Date(), 'yyyy-MM-dd');
  const { data: fleetDailyData } = useFleetDaily(today);
  const { data: trucksData } = useTrucks();
  const jobId = getActiveBidJobId();
  const { data: liveData } = useLiveBids(jobId);
  const { biddingContext } = useDataStore();

  const truckDetails = (fleetDailyData?.items ?? []).map(fleetDailyToTruckDetail);
  const totalTrucks = trucksData?.total ?? truckDetails.length;

  const biddingKeys = useMemo(() => {
    const keys = new Set<string>();
    (liveData?.items ?? [])
      .filter((b) => b.user_control !== 'stopped' && b.status !== 'completed' && b.status !== 'stopped')
      .forEach((b) => keys.add(liveBidDepotKey(b.depot, b.quantity)));

    if (biddingContext.started && biddingContext.specifications.length > 0) {
      biddingContext.specifications.forEach((spec) => {
        spec.tonnages.forEach((tonnage) => {
          keys.add(`${spec.depot_id}-${tonnage}T`);
        });
      });
    }
    return keys;
  }, [liveData?.items, biddingContext]);

  let availableCount = 0;
  let biddingCount = 0;

  truckDetails.forEach((truck) => {
    if (truck.status === 'Available') {
      const truckKey = `${truck.currentDepot}-${truck.tonnage}`;
      if (biddingKeys.has(truckKey)) {
        biddingCount++;
      } else {
        availableCount++;
      }
    }
  });

  const inTripTrucks = truckDetails.filter((t) => t.status === 'In Trip').length;
  const activeTrucks = availableCount + inTripTrucks + biddingCount;
  const nonActiveTrucks = truckDetails.filter((t) => t.status === 'Non-Active').length;

  return {
    totalTrucks,
    availableTrucks: availableCount,
    activeTrucks,
    nonActiveTrucks,
    inTripTrucks,
    biddingTrucks: biddingCount,
  };
}
