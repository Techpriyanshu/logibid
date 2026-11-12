import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Building2,
  Plus,
  Search,
  Filter,
  Trash2,
  Edit2,
  ShieldCheck,
  ShieldAlert,
  MapPin,
  Ban,
  RotateCcw,
  CheckCircle2,
  XCircle,
} from 'lucide-react';
import {
  fetchExcludedCompanies,
  createExcludedCompany,
  updateExcludedCompany,
  deleteExcludedCompany,
  fetchDepotsList,
  type ExcludedCompanyRecord,
} from '@/api/excludedCompanies';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';

// Standard fallback depots if master list is loading
const FALLBACK_DEPOTS = [
  'AYODHYA',
  'BASTI',
  'DEORIA',
  'GONDA',
  'GORAKHPUR',
  'HARDOI',
  'LUCKNOW',
  'MAU',
  'SITAPUR',
];

export default function ExcludedCompanies() {
  const queryClient = useQueryClient();

  // Filters State
  const [selectedDepot, setSelectedDepot] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');

  // Dialogs State
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);

  // Form State for Add / Edit
  const [formData, setFormData] = useState({
    id: 0,
    depot_code: '',
    company_name: '',
    reason: '',
    is_active: true,
  });

  // Entry selected for Delete
  const [selectedForDelete, setSelectedForDelete] = useState<ExcludedCompanyRecord | null>(null);

  // 1. Fetch Depots List
  const { data: depotsData } = useQuery({
    queryKey: ['master-depots'],
    queryFn: fetchDepotsList,
    staleTime: 1000 * 60 * 10,
  });

  const availableDepots = useMemo(() => {
    if (depotsData?.depots && depotsData.depots.length > 0) {
      return depotsData.depots.map((d) => d.code.toUpperCase());
    }
    return FALLBACK_DEPOTS;
  }, [depotsData]);

  // 2. Fetch Excluded Companies
  const {
    data: companiesData,
    isLoading,
    isFetching,
  } = useQuery({
    queryKey: ['excluded-companies', selectedDepot, searchQuery, statusFilter],
    queryFn: () =>
      fetchExcludedCompanies({
        depot_code: selectedDepot === 'ALL' ? undefined : selectedDepot,
        search: searchQuery || undefined,
        active_only: statusFilter === 'ACTIVE',
      }),
  });

  const allItems = companiesData?.items ?? [];

  // Filter in-memory for inactive status if selected
  const filteredItems = useMemo(() => {
    let list = allItems;
    if (statusFilter === 'INACTIVE') {
      list = list.filter((i) => !i.is_active);
    }
    return list;
  }, [allItems, statusFilter]);

  // Statistics
  const stats = useMemo(() => {
    const total = allItems.length;
    const active = allItems.filter((i) => i.is_active).length;
    const inactive = total - active;
    const depotsCount = new Set(allItems.map((i) => i.depot_code)).size;
    return { total, active, inactive, depotsCount };
  }, [allItems]);

  // Mutations
  const createMutation = useMutation({
    mutationFn: createExcludedCompany,
    onSuccess: () => {
      toast.success('Excluded company added successfully');
      queryClient.invalidateQueries({ queryKey: ['excluded-companies'] });
      setIsAddOpen(false);
      resetForm();
    },
    onError: (err: any) => {
      toast.error(err.message || 'Failed to add excluded company');
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: any }) =>
      updateExcludedCompany(id, payload),
    onSuccess: () => {
      toast.success('Excluded company updated successfully');
      queryClient.invalidateQueries({ queryKey: ['excluded-companies'] });
      setIsEditOpen(false);
      resetForm();
    },
    onError: (err: any) => {
      toast.error(err.message || 'Failed to update excluded company');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteExcludedCompany(id),
    onSuccess: () => {
      toast.success('Excluded company removed successfully');
      queryClient.invalidateQueries({ queryKey: ['excluded-companies'] });
      setIsDeleteOpen(false);
      setSelectedForDelete(null);
    },
    onError: (err: any) => {
      toast.error(err.message || 'Failed to delete excluded company');
    },
  });

  // Handlers
  const resetForm = () => {
    setFormData({
      id: 0,
      depot_code: availableDepots[0] || 'AYODHYA',
      company_name: '',
      reason: '',
      is_active: true,
    });
  };

  const handleOpenAdd = () => {
    resetForm();
    if (selectedDepot !== 'ALL') {
      setFormData((prev) => ({ ...prev, depot_code: selectedDepot }));
    }
    setIsAddOpen(true);
  };

  const handleOpenEdit = (item: ExcludedCompanyRecord) => {
    setFormData({
      id: item.id,
      depot_code: item.depot_code,
      company_name: item.company_name,
      reason: item.reason || '',
      is_active: item.is_active,
    });
    setIsEditOpen(true);
  };

  const handleOpenDelete = (item: ExcludedCompanyRecord) => {
    setSelectedForDelete(item);
    setIsDeleteOpen(true);
  };

  const handleSaveAdd = () => {
    if (!formData.depot_code.trim()) {
      toast.error('Please select a depot');
      return;
    }
    if (!formData.company_name.trim()) {
      toast.error('Please enter a company name');
      return;
    }
    createMutation.mutate({
      depot_code: formData.depot_code,
      company_name: formData.company_name.trim(),
      reason: formData.reason.trim() || undefined,
      is_active: formData.is_active,
    });
  };

  const handleSaveEdit = () => {
    if (!formData.depot_code.trim()) {
      toast.error('Please select a depot');
      return;
    }
    if (!formData.company_name.trim()) {
      toast.error('Please enter a company name');
      return;
    }
    updateMutation.mutate({
      id: formData.id,
      payload: {
        depot_code: formData.depot_code,
        company_name: formData.company_name.trim(),
        reason: formData.reason.trim() || undefined,
        is_active: formData.is_active,
      },
    });
  };

  const handleConfirmDelete = () => {
    if (selectedForDelete) {
      deleteMutation.mutate(selectedForDelete.id);
    }
  };

  const handleResetFilters = () => {
    setSelectedDepot('ALL');
    setSearchQuery('');
    setStatusFilter('ALL');
  };

  return (
    <div className="space-y-6 pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground flex items-center gap-2.5">
            <ShieldAlert className="h-8 w-8 text-primary" />
            Excluded Companies
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Configure and manage depot-wise vendor company exclusions for automated live bidding.
          </p>
        </div>
        <Button onClick={handleOpenAdd} className="gap-2 shrink-0">
          <Plus className="h-4 w-4" />
          Add Excluded Company
        </Button>
      </div>

      {/* KPI Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="border-border/60 shadow-sm hover:shadow transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Exclusions
            </CardTitle>
            <Building2 className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.total}</div>
            <p className="text-xs text-muted-foreground mt-1">Configured company rules</p>
          </CardContent>
        </Card>

        <Card className="border-border/60 shadow-sm hover:shadow transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Depots Covered
            </CardTitle>
            <MapPin className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.depotsCount}</div>
            <p className="text-xs text-muted-foreground mt-1">Depots with active rules</p>
          </CardContent>
        </Card>

        <Card className="border-border/60 shadow-sm hover:shadow transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Active Filters
            </CardTitle>
            <ShieldCheck className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
              {stats.active}
            </div>
            <p className="text-xs text-muted-foreground mt-1">Actively skipped in live bidding</p>
          </CardContent>
        </Card>

        <Card className="border-border/60 shadow-sm hover:shadow transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Inactive Rules
            </CardTitle>
            <Ban className="h-4 w-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-muted-foreground">{stats.inactive}</div>
            <p className="text-xs text-muted-foreground mt-1">Temporarily disabled</p>
          </CardContent>
        </Card>
      </div>

      {/* Filters Toolbar */}
      <Card className="border-border/60 shadow-sm">
        <CardContent className="pt-5 pb-5">
          <div className="flex flex-col md:flex-row gap-4 items-stretch md:items-center justify-between">
            <div className="flex flex-1 flex-col sm:flex-row gap-3">
              {/* Depot Filter */}
              <div className="w-full sm:w-48">
                <Select value={selectedDepot} onValueChange={setSelectedDepot}>
                  <SelectTrigger>
                    <div className="flex items-center gap-2 truncate">
                      <MapPin className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      <SelectValue placeholder="All Depots" />
                    </div>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ALL">All Depots</SelectItem>
                    {availableDepots.map((depot) => (
                      <SelectItem key={depot} value={depot}>
                        {depot}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Status Filter */}
              <div className="w-full sm:w-36">
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                  <SelectTrigger>
                    <div className="flex items-center gap-2 truncate">
                      <Filter className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      <SelectValue placeholder="Status" />
                    </div>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ALL">All Status</SelectItem>
                    <SelectItem value="ACTIVE">Active Only</SelectItem>
                    <SelectItem value="INACTIVE">Inactive</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Search Bar */}
              <div className="relative flex-1 min-w-[200px]">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search company name or reason..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>
            </div>

            {/* Reset Filters */}
            {(selectedDepot !== 'ALL' || searchQuery || statusFilter !== 'ALL') && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleResetFilters}
                className="gap-1 text-muted-foreground hover:text-foreground self-start md:self-auto"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Main Table */}
      <Card className="border-border/60 shadow-sm overflow-hidden">
        <div className="relative">
          {isFetching && (
            <div className="absolute inset-x-0 top-0 h-1 bg-primary/20 overflow-hidden">
              <div className="w-full h-full bg-primary animate-pulse" />
            </div>
          )}
          <Table>
            <TableHeader className="bg-muted/50">
              <TableRow>
                <TableHead className="w-12 text-center">#</TableHead>
                <TableHead className="w-36">Depot</TableHead>
                <TableHead>Excluded Company Name</TableHead>
                <TableHead>Reason / Notes</TableHead>
                <TableHead className="w-28 text-center">Status</TableHead>
                <TableHead className="w-36">Updated At</TableHead>
                <TableHead className="w-24 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={7} className="h-36 text-center text-muted-foreground">
                    <div className="flex flex-col items-center justify-center gap-2">
                      <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                      <span>Loading excluded companies...</span>
                    </div>
                  </TableCell>
                </TableRow>
              ) : filteredItems.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="h-44 text-center">
                    <div className="flex flex-col items-center justify-center gap-2 text-muted-foreground">
                      <ShieldAlert className="h-10 w-10 text-muted-foreground/40" />
                      <p className="font-medium text-foreground text-base">
                        No excluded companies found
                      </p>
                      <p className="text-xs max-w-sm">
                        {searchQuery || selectedDepot !== 'ALL'
                          ? 'No results match your search or filter criteria. Try adjusting or resetting filters.'
                          : 'No companies are currently excluded. Click "Add Excluded Company" to create your first rule.'}
                      </p>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={handleOpenAdd}
                        className="mt-2 gap-1.5"
                      >
                        <Plus className="h-3.5 w-3.5" />
                        Add Company
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                filteredItems.map((item, index) => (
                  <TableRow key={item.id} className="hover:bg-muted/40 transition-colors">
                    <TableCell className="text-center text-xs font-mono text-muted-foreground">
                      {index + 1}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-semibold px-2 py-0.5 text-xs">
                        {item.depot_code}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <span className="font-medium uppercase tracking-wide text-foreground">
                        {item.company_name}
                      </span>
                    </TableCell>
                    <TableCell className="max-w-md">
                      {item.reason ? (
                        <span className="text-xs text-muted-foreground line-clamp-2">
                          {item.reason}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground/50 italic">
                          No remarks recorded
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-center">
                      {item.is_active ? (
                        <Badge
                          variant="secondary"
                          className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-0 gap-1 text-[11px]"
                        >
                          <CheckCircle2 className="h-3 w-3" />
                          Active
                        </Badge>
                      ) : (
                        <Badge
                          variant="secondary"
                          className="bg-muted text-muted-foreground border-0 gap-1 text-[11px]"
                        >
                          <XCircle className="h-3 w-3" />
                          Disabled
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                      {item.updated_at || item.created_at || '—'}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-foreground"
                          title="Edit Exclusion"
                          onClick={() => handleOpenEdit(item)}
                        >
                          <Edit2 className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-destructive"
                          title="Delete Exclusion"
                          onClick={() => handleOpenDelete(item)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </Card>

      {/* Add Dialog */}
      <Dialog open={isAddOpen} onOpenChange={setIsAddOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-primary" />
              Add Excluded Company
            </DialogTitle>
            <DialogDescription>
              Any company added here will be skipped automatically during live bidding for the
              selected depot.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Depot Selector */}
            <div className="space-y-1.5">
              <Label htmlFor="add-depot">Depot *</Label>
              <Select
                value={formData.depot_code}
                onValueChange={(val) => setFormData((p) => ({ ...p, depot_code: val }))}
              >
                <SelectTrigger id="add-depot">
                  <SelectValue placeholder="Select depot" />
                </SelectTrigger>
                <SelectContent>
                  {availableDepots.map((d) => (
                    <SelectItem key={d} value={d}>
                      {d}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Company Name */}
            <div className="space-y-1.5">
              <Label htmlFor="add-company">Company Name *</Label>
              <Input
                id="add-company"
                placeholder="e.g. ANJU TRADERS"
                value={formData.company_name}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, company_name: e.target.value.toUpperCase() }))
                }
              />
              <p className="text-[11px] text-muted-foreground">
                Matches the company name in the SAP live bidding table (case-insensitive).
              </p>
            </div>

            {/* Reason */}
            <div className="space-y-1.5">
              <Label htmlFor="add-reason">Reason / Remarks (Optional)</Label>
              <Textarea
                id="add-reason"
                rows={2}
                placeholder="e.g. Low freight margin, past performance issue, etc."
                value={formData.reason}
                onChange={(e) => setFormData((p) => ({ ...p, reason: e.target.value }))}
              />
            </div>

            {/* Active Toggle */}
            <div className="flex items-center justify-between pt-1">
              <div>
                <Label htmlFor="add-active" className="cursor-pointer">
                  Active Status
                </Label>
                <p className="text-xs text-muted-foreground">
                  When enabled, this rule immediately skips matching auction rows.
                </p>
              </div>
              <Switch
                id="add-active"
                checked={formData.is_active}
                onCheckedChange={(val) => setFormData((p) => ({ ...p, is_active: val }))}
              />
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setIsAddOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSaveAdd} disabled={createMutation.isPending}>
              {createMutation.isPending ? 'Adding...' : 'Add Exclusion'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit / Modify Dialog */}
      <Dialog open={isEditOpen} onOpenChange={setIsEditOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Edit2 className="h-5 w-5 text-primary" />
              Modify Excluded Company
            </DialogTitle>
            <DialogDescription>
              Update the depot, company name, reason, or active status.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Depot Selector */}
            <div className="space-y-1.5">
              <Label htmlFor="edit-depot">Depot *</Label>
              <Select
                value={formData.depot_code}
                onValueChange={(val) => setFormData((p) => ({ ...p, depot_code: val }))}
              >
                <SelectTrigger id="edit-depot">
                  <SelectValue placeholder="Select depot" />
                </SelectTrigger>
                <SelectContent>
                  {availableDepots.map((d) => (
                    <SelectItem key={d} value={d}>
                      {d}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Company Name */}
            <div className="space-y-1.5">
              <Label htmlFor="edit-company">Company Name *</Label>
              <Input
                id="edit-company"
                value={formData.company_name}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, company_name: e.target.value.toUpperCase() }))
                }
              />
            </div>

            {/* Reason */}
            <div className="space-y-1.5">
              <Label htmlFor="edit-reason">Reason / Remarks</Label>
              <Textarea
                id="edit-reason"
                rows={2}
                value={formData.reason}
                onChange={(e) => setFormData((p) => ({ ...p, reason: e.target.value }))}
              />
            </div>

            {/* Active Toggle */}
            <div className="flex items-center justify-between pt-1">
              <div>
                <Label htmlFor="edit-active" className="cursor-pointer">
                  Active Status
                </Label>
                <p className="text-xs text-muted-foreground">
                  Toggle off to temporarily disable without deleting.
                </p>
              </div>
              <Switch
                id="edit-active"
                checked={formData.is_active}
                onCheckedChange={(val) => setFormData((p) => ({ ...p, is_active: val }))}
              />
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setIsEditOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSaveEdit} disabled={updateMutation.isPending}>
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Alert Dialog */}
      <AlertDialog open={isDeleteOpen} onOpenChange={setIsDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2 text-destructive">
              <Trash2 className="h-5 w-5" />
              Remove Excluded Company?
            </AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <p>
                Are you sure you want to remove{' '}
                <strong className="text-foreground uppercase">
                  {selectedForDelete?.company_name}
                </strong>{' '}
                from <strong>{selectedForDelete?.depot_code}</strong> exclusions?
              </p>
              <p className="text-xs text-muted-foreground">
                Once removed, the live bidding automation will no longer filter out bids from this
                company for {selectedForDelete?.depot_code}.
              </p>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? 'Deleting...' : 'Delete Exclusion'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
