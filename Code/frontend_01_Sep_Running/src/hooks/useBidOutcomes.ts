import { useQuery } from '@tanstack/react-query';
import {
  fetchBidOutcomes,
  fetchBidOutcomesByJob,
  fetchBidOutcomesSummary,
  type BidOutcomesQuery,
  type BidOutcomesSummaryQuery,
} from '@/api/bidOutcomes';

export function useBidOutcomes(query: BidOutcomesQuery = {}) {
  return useQuery({
    queryKey: ['bid-outcomes', query],
    queryFn: () => fetchBidOutcomes(query),
  });
}

export function useBidOutcomesSummary(query: BidOutcomesSummaryQuery = {}) {
  return useQuery({
    queryKey: ['bid-outcomes-summary', query],
    queryFn: () => fetchBidOutcomesSummary(query),
  });
}

export function useBidOutcomesByJob(jobId?: string | null) {
  return useQuery({
    queryKey: ['bid-outcomes-job', jobId],
    queryFn: () => fetchBidOutcomesByJob(jobId!),
    enabled: Boolean(jobId),
  });
}
