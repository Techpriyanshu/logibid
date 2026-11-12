import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import Login from "./pages/Login";
import Home from "./pages/dashboard/Home";
import ControlPanel from "./pages/dashboard/ControlPanel";
import LiveBiddingStatus from "./pages/dashboard/LiveBiddingStatus";
import VendorLiveBidding from "./pages/dashboard/VendorLiveBidding";
import SuccessfulBids from "./pages/dashboard/SuccessfulBids";
import ExcludedCompanies from "./pages/dashboard/ExcludedCompanies";
import TruckMaster from "./pages/dashboard/TruckMaster";
import Reports from "./pages/dashboard/Reports";
import Notifications from "./pages/dashboard/Notifications";
import NotFound from "./pages/NotFound";
import AdminLogin from "./pages/admin/AdminLogin";
import AdminDashboard from "./pages/admin/AdminDashboard";
import AdminLiveBidding from "./pages/admin/AdminLiveBidding";
import { PwaManager } from "@/components/pwa/PwaManager";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
    },
  },
});

const App = () => {
  // Dev-only cache clear utility
  if (import.meta.env.DEV && window.location.pathname === '/debug') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <button
          onClick={() => queryClient.clear()}
          className="px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:opacity-90"
        >
          Clear React Query Cache
        </button>
      </div>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <PwaManager />
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="/login" element={<Login />} />
            <Route path="/debug" element={null} />
            
            {/* Admin Routes */}
            <Route path="/admin/login" element={<AdminLogin />} />
            <Route path="/admin/dashboard" element={<AdminDashboard />} />
            <Route path="/admin/live-bidding" element={<AdminLiveBidding />} />
            
            {/* Dashboard Routes (Fleet & Vendor) */}
            <Route path="/dashboard" element={<DashboardLayout />}>
              <Route index element={<Navigate to="/dashboard/home" replace />} />
              <Route path="home" element={<Home />} />
              <Route path="control-panel" element={<ControlPanel />} />
              <Route path="live-status" element={<LiveBiddingStatus />} />
              <Route path="vendor-live-status" element={<VendorLiveBidding />} />
              <Route path="successful-bids" element={<SuccessfulBids />} />
              <Route path="excluded-companies" element={<ExcludedCompanies />} />
              <Route path="truck-master" element={<TruckMaster />} />
              <Route path="reports" element={<Reports />} />
              <Route path="notifications" element={<Notifications />} />
            </Route>

            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
};

export default App;
