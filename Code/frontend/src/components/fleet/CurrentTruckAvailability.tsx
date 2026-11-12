import { format } from 'date-fns';
import { useMemo } from 'react';
import { useFleetDaily } from '@/hooks/useFleetAdmin';
import { useLiveBids } from '@/hooks/useLiveBids';
import { getActiveBidJobId } from '@/api/liveBids';
import { fleetDailyToTruckDetail } from '@/utils/fleetAdminMappers';
import { DEPOT_MASTER_LIST } from '@/constants/depots';
import { useDataStore } from '@/store/dataStore';
import { getDepotDisplayName } from '@/constants/depots';
import { Truck, MapPin, Clock, User, Package } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

function liveBidDepotKey(depotName: string, quantity: number): string {
  const depot = DEPOT_MASTER_LIST.find(
    (d) => d.name.toUpperCase() === depotName.toUpperCase(),
  );
  const depotId = depot?.id ?? depotName;
  return `${depotId}-${quantity}T`;
}

export default function CurrentTruckAvailability() {
  const today = format(new Date(), 'yyyy-MM-dd');
  const { data: fleetDailyData, isLoading } = useFleetDaily(today);
  const jobId = getActiveBidJobId();
  const { data: liveData } = useLiveBids(jobId);
  const { biddingContext } = useDataStore();

  const truckDetails = (fleetDailyData?.items ?? []).map(fleetDailyToTruckDetail);

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

  const availableTrucks = truckDetails.filter((truck) => {
    if (truck.status !== 'Available') return false;
    const truckKey = `${truck.currentDepot}-${truck.tonnage}`;
    return !biddingKeys.has(truckKey);
  });

  const getDepotName = (depotId: string) => {
    return getDepotDisplayName(depotId) || depotId;
  };

  const formatLastUpdated = (timestamp?: string) => {
    if (!timestamp) return 'N/A';
    try {
      return format(new Date(timestamp), 'h:mm a');
    } catch {
      return 'N/A';
    }
  };

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="p-4 border-b border-border bg-muted/30 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary/10 rounded-lg">
            <Truck className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="font-semibold text-foreground">Current Truck Availability</h2>
            <p className="text-xs text-muted-foreground">
              Trucks ready for bidding • Data from Fleet Admin
            </p>
          </div>
        </div>
        <Badge variant="secondary" className="gap-1">
          <Truck className="h-3 w-3" />
          {availableTrucks.length} Available
        </Badge>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-muted-foreground text-sm">
          Loading fleet availability…
        </div>
      ) : availableTrucks.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 px-6">
          <div className="p-4 bg-muted rounded-full mb-4">
            <Truck className="h-10 w-10 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold text-foreground mb-2">No Trucks Available</h3>
          <p className="text-muted-foreground text-center max-w-sm text-sm">
            No trucks are currently available for bidding. Check back when Fleet Admin updates availability.
          </p>
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/20 hover:bg-muted/20">
              <TableHead className="font-semibold">Truck Number</TableHead>
              <TableHead className="font-semibold">Tonnage</TableHead>
              <TableHead className="font-semibold">Current Depot</TableHead>
              <TableHead className="font-semibold">Destination</TableHead>
              <TableHead className="font-semibold">Driver Name</TableHead>
              <TableHead className="font-semibold text-center">Last Updated</TableHead>
              <TableHead className="font-semibold text-center">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {availableTrucks.map((truck) => (
              <TableRow key={truck.id} className="hover:bg-muted/20">
                <TableCell className="font-medium font-mono">
                  {truck.truckNumber}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="font-semibold">
                    <Package className="h-3 w-3 mr-1" />
                    {truck.tonnage}
                  </Badge>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <MapPin className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm">{getDepotName(truck.currentDepot)}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <span className="text-sm text-muted-foreground">
                    {truck.destination || '—'}
                  </span>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <User className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm">{truck.driverName}</span>
                  </div>
                </TableCell>
                <TableCell className="text-center">
                  <div className="flex items-center justify-center gap-1 text-sm text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    {formatLastUpdated(truck.availableSince)}
                  </div>
                </TableCell>
                <TableCell className="text-center">
                  <Badge
                    variant="outline"
                    className="bg-success/20 text-success border-success/30"
                  >
                    Available
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
