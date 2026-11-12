import { useQuery } from '@tanstack/react-query';
import { fetchSuccessfulBids } from '@/api/successfulBids';

export function useSuccessfulBids() {
  return useQuery({
    queryKey: ['successful-bids'],
    queryFn: () => fetchSuccessfulBids(),
  });
}
