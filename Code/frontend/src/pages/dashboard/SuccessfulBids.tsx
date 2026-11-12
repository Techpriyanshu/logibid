import { useState, useMemo } from 'react';
import { type VehicleBid, useDataStore } from '@/store/dataStore';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { CheckCircle, Clock, Trophy, Award, XCircle, TrendingDown, Eye, EyeOff, SlidersHorizontal } from 'lucide-react';
import { BidFilterBar } from '@/components/bidding/BidFilterBar';
import { useBidFilters } from '@/hooks/useBidFilters';
import { useSuccessfulBids } from '@/hooks/useSuccessfulBids';
import { useBidOutcomes } from '@/hooks/useBidOutcomes';
import { type SuccessfulBidRecord } from '@/api/successfulBids';
import { type BidOutcome } from '@/api/bidOutcomes';
import { DEPOT_MASTER_LIST } from '@/constants/depots';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

const DEFAULT_PLANT_ID = '1';
const DEFAULT_PLANT_NAME = 'Tanda Cement Plant';

function resolveDepotFromApiName(depotToken: string) {
  const upper = depotToken.trim().toUpperCase();
  return DEPOT_MASTER_LIST.find(
    (d) => d.name.toUpperCase() === upper || d.code === upper,
  );
}

function formatDepotDisplayName(depotToken: string): string {
  const matched = resolveDepotFromApiName(depotToken);
  if (matched) return matched.name;
  return depotToken
    .trim()
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function successfulBidToVehicleBid(record: SuccessfulBidRecord): VehicleBid {
  const depot = resolveDepotFromApiName(record.depot);
  return {
    id: String(record.id),
    plant_id: DEFAULT_PLANT_ID,
    plant_name: DEFAULT_PLANT_NAME,
    depot_id: depot?.id ?? '',
    depot_name: formatDepotDisplayName(record.depot),
    destination: record.destination?.trim() || undefined,
    tonnage: record.quantity,
    status: 'Closed',
    rank: record.rank,
    created_at: record.won_timestamp,
    time_remaining: 0,
  };
}

function outcomeToVehicleBid(record: BidOutcome): VehicleBid {
  const depot = resolveDepotFromApiName(record.depot);
  return {
    id: record.leg_id || record.outcome_id,
    plant_id: DEFAULT_PLANT_ID,
    plant_name: DEFAULT_PLANT_NAME,
    depot_id: depot?.id ?? '',
    depot_name: formatDepotDisplayName(record.depot),
    destination: record.destination?.trim() || undefined,
    tonnage: record.quantity,
    status: 'Closed',
    rank: record.rank,
    created_at: record.completed_at || record.created_at,
    time_remaining: 0,
  };
}

function formatDateTime(dateStr: string) {
  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return { date: dateStr, time: '' };
    return {
      date: date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }),
      time: date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }),
    };
  } catch {
    return { date: dateStr, time: '' };
  }
}

function getRankBadge(rank: number | null | undefined) {
  if (!rank || rank === 1) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-muted text-muted-foreground text-xs font-semibold">
        Rank &gt; 1
      </span>
    );
  }
  if (rank === 2) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30 text-xs font-bold">
        <TrendingDown className="h-3 w-3" />
        Rank 2
      </span>
    );
  }
  if (rank === 3) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-orange-500/15 text-orange-600 dark:text-orange-400 border border-orange-500/30 text-xs font-bold">
        <TrendingDown className="h-3 w-3" />
        Rank 3
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-destructive/15 text-destructive border border-destructive/30 text-xs font-bold">
      <TrendingDown className="h-3 w-3" />
      Rank {rank}
    </span>
  );
}

export default function SuccessfulBids() {
  const { data: winningData, isLoading: isWinningLoading, isError: isWinningError, error: winningError } = useSuccessfulBids();
  const { data: outcomesData, isLoading: isOutcomesLoading } = useBidOutcomes();
  const { vehicleBids: storeVehicleBids } = useDataStore();

  // Display options state for Failed Bids (Rank > 1)
  const [showFailedBids, setShowFailedBids] = useState(true);
  const [selectedRankFilter, setSelectedRankFilter] = useState<'all' | '2' | '3' | '4plus'>('all');

  // Convert Rank 1 winning bids
  const winningVehicleBids = useMemo(
    () => (winningData?.items ?? []).map(successfulBidToVehicleBid),
    [winningData?.items],
  );

  // Extract and deduplicate Rank > 1 failed bids from backend outcomes and store
  const allFailedVehicleBids = useMemo(() => {
    const failedMap = new Map<string, VehicleBid>();

    // 1. From live dataStore
    (storeVehicleBids ?? [])
      .filter((vb) => vb.rank !== null && vb.rank > 1)
      .forEach((vb) => failedMap.set(vb.id, vb));

    // 2. From historical outcomes API
    (outcomesData?.items ?? [])
      .filter((o) => (o.rank !== null && o.rank > 1) || (o.outcome_status === 'lost' && o.rank !== 1))
      .map(outcomeToVehicleBid)
      .forEach((vb) => failedMap.set(vb.id, vb));

    return Array.from(failedMap.values()).sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  }, [outcomesData?.items, storeVehicleBids]);

  // Combined pool for filter bar destinations & depots
  const allBidsForFiltering = useMemo(
    () => [...winningVehicleBids, ...allFailedVehicleBids],
    [winningVehicleBids, allFailedVehicleBids]
  );

  const {
    pendingFilters,
    appliedFilters,
    setPendingDepot,
    setPendingDestination,
    applyFilters,
    clearFilters,
    filterBids,
    availableDestinations,
    hasActiveFilters,
    canApplyFilters,
    isSearching,
  } = useBidFilters(allBidsForFiltering);

  // Filtered winning bids (Rank 1)
  const filteredWinningBids = filterBids(winningVehicleBids);

  // Filtered failed bids (Rank > 1) with depot/destination filters
  const filteredFailedBids = filterBids(allFailedVehicleBids);

  // Rank-specific filtered failed bids
  const displayedFailedBids = useMemo(() => {
    if (selectedRankFilter === 'all') return filteredFailedBids;
    if (selectedRankFilter === '2') return filteredFailedBids.filter((b) => b.rank === 2);
    if (selectedRankFilter === '3') return filteredFailedBids.filter((b) => b.rank === 3);
    if (selectedRankFilter === '4plus') return filteredFailedBids.filter((b) => b.rank && b.rank >= 4);
    return filteredFailedBids;
  }, [filteredFailedBids, selectedRankFilter]);

  const rank2Count = useMemo(() => filteredFailedBids.filter((b) => b.rank === 2).length, [filteredFailedBids]);
  const rank3Count = useMemo(() => filteredFailedBids.filter((b) => b.rank === 3).length, [filteredFailedBids]);
  const rank4PlusCount = useMemo(() => filteredFailedBids.filter((b) => b.rank && b.rank >= 4).length, [filteredFailedBids]);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header Section */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-success/20 rounded-lg">
            <Award className="h-6 w-6 text-success" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground">Bidding Results &amp; Archive</h1>
            <p className="text-sm text-muted-foreground">
              Winning bids (Rank 1) and competing outcomes (Rank &gt; 1)
            </p>
          </div>
        </div>

        {/* Display Option Switch for Failed Bids */}
        <div className="flex items-center gap-3 bg-card border border-border px-3.5 py-2 rounded-xl shadow-sm">
          <div className="flex items-center gap-2">
            {showFailedBids ? (
              <Eye className="h-4 w-4 text-primary" />
            ) : (
              <EyeOff className="h-4 w-4 text-muted-foreground" />
            )}
            <Label htmlFor="toggle-failed-bids" className="text-xs font-medium cursor-pointer select-none">
              Display Failed Bids (Rank &gt; 1)
            </Label>
          </div>
          <Switch
            id="toggle-failed-bids"
            checked={showFailedBids}
            onCheckedChange={setShowFailedBids}
          />
        </div>
      </div>

      {/* Filter Bar */}
      <BidFilterBar
        pendingFilters={pendingFilters}
        appliedFilters={appliedFilters}
        onDepotChange={setPendingDepot}
        onDestinationChange={setPendingDestination}
        onApplyFilters={applyFilters}
        onClearFilters={clearFilters}
        availableDestinations={availableDestinations}
        hasActiveFilters={hasActiveFilters}
        canApplyFilters={canApplyFilters}
        isSearching={isSearching}
      />

      {isWinningError && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-lg p-4 text-sm text-destructive">
          Failed to load successful bids: {String((winningError as Error)?.message || winningError)}
        </div>
      )}

      {/* Summary Cards */}
      <div className={cn(
        'grid gap-4',
        showFailedBids ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1'
      )}>
        {/* Winning Bids Summary Card */}
        <div className="bg-success/10 border border-success/30 rounded-xl p-4 transition-all">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-success/20 rounded-xl">
              <Trophy className="h-7 w-7 text-success" />
            </div>
            <div>
              <p className="text-2xl font-bold text-success">
                {isWinningLoading ? '…' : filteredWinningBids.length}
              </p>
              <p className="text-sm text-muted-foreground font-medium">
                {hasActiveFilters ? 'Filtered Winning Bids (Rank 1)' : 'Total Winning Bids (Rank 1 Wins)'}
              </p>
            </div>
          </div>
        </div>

        {/* Failed Bids Summary Card */}
        {showFailedBids && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-xl p-4 transition-all">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-destructive/20 rounded-xl">
                <TrendingDown className="h-7 w-7 text-destructive" />
              </div>
              <div>
                <p className="text-2xl font-bold text-destructive">
                  {isOutcomesLoading ? '…' : filteredFailedBids.length}
                </p>
                <p className="text-sm text-muted-foreground font-medium">
                  {hasActiveFilters ? 'Filtered Failed Bids (Rank > 1)' : 'Total Failed Bids (Rank > 1 Losses)'}
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* SECTION 1: Your Winning Bids (ONLY Rank 1 Bids) */}
      {isWinningLoading ? (
        <div className="bg-card rounded-xl border border-border p-12 text-center">
          <div className="flex flex-col items-center gap-4">
            <div className="p-4 bg-muted rounded-full">
              <Trophy className="h-8 w-8 text-muted-foreground animate-pulse" />
            </div>
            <p className="text-sm text-muted-foreground">Loading successful bids…</p>
          </div>
        </div>
      ) : filteredWinningBids.length > 0 ? (
        <div className="bg-card rounded-xl border border-border overflow-hidden">
          <div className="p-4 border-b border-border bg-muted/30 flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-foreground flex items-center gap-2">
                <Trophy className="h-4 w-4 text-warning" />
                Your Winning Bids
              </h2>
              <p className="text-xs text-muted-foreground mt-1">
                These are the bids you have WON - Permanent success archive
              </p>
            </div>
            <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-success/20 text-success border border-success/30">
              {filteredWinningBids.length} {filteredWinningBids.length === 1 ? 'Win' : 'Wins'}
            </span>
          </div>
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30">
                <TableHead>Vehicle</TableHead>
                <TableHead>Plant</TableHead>
                <TableHead>Depot</TableHead>
                <TableHead>Destination</TableHead>
                <TableHead>Tonnage</TableHead>
                <TableHead className="text-center">Status</TableHead>
                <TableHead className="text-center">Rank</TableHead>
                <TableHead className="text-center">Time</TableHead>
                <TableHead className="text-center">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredWinningBids.map((vb) => {
                const { date, time } = formatDateTime(vb.created_at);
                return (
                  <TableRow
                    key={vb.id}
                    className="hover:bg-muted/20 bg-success/5"
                  >
                    {/* Vehicle Column */}
                    <TableCell className="font-medium">
                      Vehicle – {vb.tonnage}T
                    </TableCell>

                    {/* Plant Column */}
                    <TableCell>{vb.plant_name}</TableCell>

                    {/* Depot Column */}
                    <TableCell>{vb.depot_name}</TableCell>

                    {/* Destination Column */}
                    <TableCell>{vb.destination || '—'}</TableCell>

                    {/* Tonnage Column */}
                    <TableCell>
                      <span className="px-2 py-1 bg-accent/50 text-accent-foreground rounded-md text-sm font-medium">
                        {vb.tonnage}T
                      </span>
                    </TableCell>

                    {/* Status Column - Successful Only */}
                    <TableCell className="text-center">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-success/20 text-success">
                        <CheckCircle className="h-3 w-3" />
                        Successful
                      </span>
                    </TableCell>

                    {/* Rank Column - Always 1 */}
                    <TableCell className="text-center">
                      <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-warning/20 text-warning font-bold">
                        <Trophy className="h-3 w-3" />1
                      </span>
                    </TableCell>

                    {/* Time Column - Completion Time */}
                    <TableCell className="text-center font-mono text-sm">
                      <div className="flex flex-col items-center">
                        <Clock className="h-3 w-3 inline mb-0.5 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">{date}</span>
                        <span className="text-xs">{time}</span>
                      </div>
                    </TableCell>

                    {/* Action Column - Read-only */}
                    <TableCell className="text-center">
                      <span className="inline-flex items-center px-3 py-1.5 rounded-md bg-muted text-muted-foreground text-xs font-medium">
                        Completed
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : (
        <div className="bg-card rounded-xl border border-border p-12 text-center">
          <div className="flex flex-col items-center gap-4">
            <div className="p-4 bg-muted rounded-full">
              <Trophy className="h-8 w-8 text-muted-foreground" />
            </div>
            <div>
              <h3 className="font-semibold text-foreground mb-2">
                {hasActiveFilters ? 'No Successful Bids Found' : 'No Successful Bids Yet'}
              </h3>
              <p className="text-sm text-muted-foreground max-w-md">
                {hasActiveFilters
                  ? 'No records found for selected criteria. Try adjusting your filters.'
                  : "You haven't won any bids yet. Successful bids (Rank 1 wins) will appear here permanently once you win them."}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* SECTION 2: Failed Bids (Rank > 1) - Placed after "Your Winning Bids" */}
      {showFailedBids && (
        <div className="bg-card rounded-xl border border-destructive/20 overflow-hidden shadow-sm">
          <div className="p-4 border-b border-border bg-destructive/5 flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 bg-destructive/10 text-destructive rounded-md">
                <XCircle className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="font-semibold text-foreground">Failed Bids</h2>
                  <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-destructive/15 text-destructive border border-destructive/20">
                    Rank &gt; 1
                  </span>
                  <span className="px-2 py-0.5 text-xs rounded-full bg-muted text-muted-foreground font-medium">
                    {displayedFailedBids.length} {displayedFailedBids.length === 1 ? 'bid' : 'bids'}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Bids where final rank was greater than 1 – Missed opportunities &amp; competing bids
                </p>
              </div>
            </div>

            {/* Display Option: Rank > 1 Quick Filter Pills */}
            <div className="flex items-center gap-1.5 bg-background/90 p-1 rounded-lg border border-border self-start md:self-auto overflow-x-auto max-w-full">
              <span className="text-xs text-muted-foreground px-2 font-medium flex items-center gap-1 whitespace-nowrap">
                <SlidersHorizontal className="h-3 w-3" />
                Rank:
              </span>
              <button
                type="button"
                onClick={() => setSelectedRankFilter('all')}
                className={cn(
                  'px-2.5 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap',
                  selectedRankFilter === 'all'
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                )}
              >
                All ({filteredFailedBids.length})
              </button>
              <button
                type="button"
                onClick={() => setSelectedRankFilter('2')}
                className={cn(
                  'px-2.5 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap',
                  selectedRankFilter === '2'
                    ? 'bg-amber-500 text-white shadow-sm'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                )}
              >
                Rank 2 ({rank2Count})
              </button>
              <button
                type="button"
                onClick={() => setSelectedRankFilter('3')}
                className={cn(
                  'px-2.5 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap',
                  selectedRankFilter === '3'
                    ? 'bg-orange-500 text-white shadow-sm'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                )}
              >
                Rank 3 ({rank3Count})
              </button>
              <button
                type="button"
                onClick={() => setSelectedRankFilter('4plus')}
                className={cn(
                  'px-2.5 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap',
                  selectedRankFilter === '4plus'
                    ? 'bg-destructive text-destructive-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                )}
              >
                Rank 4+ ({rank4PlusCount})
              </button>
            </div>
          </div>

          {isOutcomesLoading ? (
            <div className="p-12 text-center">
              <div className="flex flex-col items-center gap-4">
                <div className="p-4 bg-muted rounded-full">
                  <TrendingDown className="h-8 w-8 text-muted-foreground animate-pulse" />
                </div>
                <p className="text-sm text-muted-foreground">Loading failed bids…</p>
              </div>
            </div>
          ) : displayedFailedBids.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/30">
                  <TableHead>Vehicle</TableHead>
                  <TableHead>Plant</TableHead>
                  <TableHead>Depot</TableHead>
                  <TableHead>Destination</TableHead>
                  <TableHead>Tonnage</TableHead>
                  <TableHead className="text-center">Status</TableHead>
                  <TableHead className="text-center">Rank</TableHead>
                  <TableHead className="text-center">Time</TableHead>
                  <TableHead className="text-center">Outcome</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayedFailedBids.map((vb) => {
                  const { date, time } = formatDateTime(vb.created_at);
                  return (
                    <TableRow
                      key={vb.id}
                      className="hover:bg-muted/20 bg-destructive/5"
                    >
                      {/* Vehicle Column */}
                      <TableCell className="font-medium">
                        Vehicle – {vb.tonnage}T
                      </TableCell>

                      {/* Plant Column */}
                      <TableCell>{vb.plant_name}</TableCell>

                      {/* Depot Column */}
                      <TableCell>{vb.depot_name}</TableCell>

                      {/* Destination Column */}
                      <TableCell>{vb.destination || '—'}</TableCell>

                      {/* Tonnage Column */}
                      <TableCell>
                        <span className="px-2 py-1 bg-accent/50 text-accent-foreground rounded-md text-sm font-medium">
                          {vb.tonnage}T
                        </span>
                      </TableCell>

                      {/* Status Column - Failed */}
                      <TableCell className="text-center">
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-destructive/15 text-destructive border border-destructive/20">
                          <XCircle className="h-3 w-3" />
                          Failed
                        </span>
                      </TableCell>

                      {/* Rank Column - Color-coded by Rank */}
                      <TableCell className="text-center">
                        {getRankBadge(vb.rank)}
                      </TableCell>

                      {/* Time Column */}
                      <TableCell className="text-center font-mono text-sm">
                        <div className="flex flex-col items-center">
                          <Clock className="h-3 w-3 inline mb-0.5 text-muted-foreground" />
                          <span className="text-xs text-muted-foreground">{date}</span>
                          <span className="text-xs">{time}</span>
                        </div>
                      </TableCell>

                      {/* Outcome Column */}
                      <TableCell className="text-center">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-muted text-muted-foreground text-xs font-medium">
                          {vb.rank ? `Rank ${vb.rank} Loss` : 'Unsuccessful'}
                        </span>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <div className="p-12 text-center">
              <div className="flex flex-col items-center gap-3">
                <div className="p-3 bg-muted rounded-full">
                  <CheckCircle className="h-6 w-6 text-success/70" />
                </div>
                <div>
                  <h3 className="font-semibold text-foreground mb-1">
                    {hasActiveFilters || selectedRankFilter !== 'all'
                      ? 'No Failed Bids Found'
                      : 'No Failed Bids Recorded'}
                  </h3>
                  <p className="text-sm text-muted-foreground max-w-md">
                    {hasActiveFilters || selectedRankFilter !== 'all'
                      ? 'No failed bids match the selected filters. Try resetting the rank or depot filters.'
                      : 'No bids with Rank > 1 recorded yet. Any bids you lose or rank > 1 in will appear here.'}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
