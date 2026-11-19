import { Navigate, Outlet } from 'react-router-dom';
import { useEffect } from 'react';
import { SidebarProvider, SidebarInset } from '@/components/ui/sidebar';
import { AppHeader } from './AppHeader';
import { AppSidebar } from './AppSidebar';
import { ExtractionJobDock } from './ExtractionJobDock';
import { ExtractionJobsProvider } from '@/contexts/ExtractionJobsContext';
import { UploadJobsProvider, useUploadJobs } from '@/contexts/UploadJobsContext';
import { UploadJobDock } from './UploadJobDock';
import { NotificationPanel } from './NotificationPanel';
import { useAuth } from '@/contexts/AuthContext';
import { NotificationsProvider, useNotifications } from '@/contexts/NotificationsContext';
import { Loader2 } from 'lucide-react';

/**
 * Warn before a reload/close drops an in-flight upload. Uploads run in the
 * browser (the file bytes live in this page), so a hard refresh genuinely loses
 * them — unlike extraction, which is a backend job that resumes from its stored
 * id. The native prompt gives the user a chance to not refresh mid-upload.
 */
function RefreshGuard() {
  const { jobs } = useUploadJobs();
  const hasActiveUpload = jobs.some((job) => job.status === 'uploading');
  useEffect(() => {
    if (!hasActiveUpload) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [hasActiveUpload]);
  return null;
}

/**
 * Bottom-left progress docks (upload + classification + extraction), stacked in
 * one container. Hidden while "muted"; the side panel still collects them.
 */
function NotificationDocks() {
  const { muted } = useNotifications();
  if (muted) return null;
  return (
    <div className="pointer-events-none fixed bottom-5 left-5 z-50 flex w-[380px] max-w-[calc(100vw-2rem)] flex-col gap-3">
      <UploadJobDock />
      <ExtractionJobDock />
    </div>
  );
}

export function AppLayout() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading your workspace...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <NotificationsProvider>
      <UploadJobsProvider>
        <ExtractionJobsProvider>
          <SidebarProvider>
            <AppSidebar />
            <SidebarInset className="dpt-bg">
              {/* Header is sticky so it stays visible while the page scrolls. */}
              <AppHeader />
              {/* One standardized content container for ALL pages: consistent
                  max-width + horizontal padding. Pages should NOT set their own
                  outer width/padding — just render their content here. */}
              <main className="dpt-bg flex-1">
                <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-4 px-5 py-5">
                  <Outlet />
                </div>
              </main>
            </SidebarInset>
            <NotificationDocks />
            <NotificationPanel />
            <RefreshGuard />
          </SidebarProvider>
        </ExtractionJobsProvider>
      </UploadJobsProvider>
    </NotificationsProvider>
  );
}
