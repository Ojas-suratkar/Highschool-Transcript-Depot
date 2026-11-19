import { SidebarTrigger } from '@/components/ui/sidebar';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useTerm } from '@/contexts/TermContext';
import { Plus, Bell, Calendar } from 'lucide-react';
import AddTermDialog from '@/components/shared/AddTermDialog';
import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { ProfileCard } from './ProfileCard';
import { useNotifications } from '@/contexts/NotificationsContext';
import { useUploadJobs } from '@/contexts/UploadJobsContext';
import { useExtractionJobs } from '@/contexts/ExtractionJobsContext';

const TITLE_OVERRIDES: Record<string, string> = {
  '/app/admissions/dashboard': 'Home',
  '/app/cloud-folders': 'Upload',
  '/app/extract': 'Extract',
  '/app/classify': 'Classify',
  '/app/transcript-intelligence': 'Transcript Intelligence Center',
  '/app/admission-criteria': 'University Admission Rules',
  '/app/program-criteria': 'Program Admission Rules',
  '/app/term-rules': 'Advanced Admission Rules',
  '/app/transcript-codes': 'Transcript Settings',
  '/app/course-mapping': 'Course Matching',
  '/app/admissions/templates': 'Decision Templates',
  '/app/admissions/reports': 'Reports & Insights',
  '/app/decisions/admitted': 'Admitted',
  '/app/decisions/denied': 'Denied',
  '/app/decisions/waitlisted': 'Waitlisted',
};

function titleForPath(pathname: string): string {
  if (TITLE_OVERRIDES[pathname]) return TITLE_OVERRIDES[pathname];
  const seg = pathname.split('/').filter(Boolean).pop() || 'workspace';
  return seg.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function AppHeader() {
  const { currentTerm, setCurrentTerm, terms } = useTerm();
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const { openPanel, seenIds, unreadCount, activityUnread } = useNotifications();
  const { jobs: uploadJobs } = useUploadJobs();
  const { jobs: extractionJobs } = useExtractionJobs();
  const location = useLocation();

  // iPhone-style dot: show while any job is active, there are unseen jobs, or
  // there are unread notifications in the feed.
  const hasActive =
    uploadJobs.some((j) => j.status === 'uploading') ||
    extractionJobs.some((j) => j.status === 'queued' || j.status === 'running');
  const hasUnseen =
    uploadJobs.some((j) => !seenIds.has(String(j.id))) ||
    extractionJobs.some((j) => !seenIds.has(String(j.id)));
  const showDot = hasActive || hasUnseen || unreadCount > 0 || activityUnread > 0;
  const totalUnread = unreadCount + activityUnread;
  const dotCount = totalUnread > 0 ? totalUnread : undefined;

  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  return (
    <header className="dpt-top">
      <SidebarTrigger className="dpt-iconbtn md:hidden" />

      <div className="hd">
        <h1>{titleForPath(location.pathname)}</h1>
        {termName && <span>{termName}</span>}
      </div>

      <div style={{ flex: 1 }} />

      {/* Term selector — scopes the whole workspace */}
      <label className="dpt-tsel" title="This term scopes the whole workspace">
        <Calendar className="h-3.5 w-3.5 text-[var(--ink-3)]" />
        <Select value={currentTerm} onValueChange={setCurrentTerm}>
          <SelectTrigger className="h-auto border-0 bg-transparent p-0 text-[13px] font-semibold shadow-none focus:ring-0 focus-visible:ring-0">
            <SelectValue placeholder="No terms" />
          </SelectTrigger>
          <SelectContent>
            {terms.map((term) => (
              <SelectItem key={term.id} value={term.id}>
                {term.term_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <button className="add" onClick={() => setIsDialogOpen(true)} title="Add a new term" aria-label="Add term">
          <Plus className="h-3.5 w-3.5" />
        </button>
      </label>
      <AddTermDialog open={isDialogOpen} onOpenChange={setIsDialogOpen} />

      <button className="dpt-iconbtn" onClick={openPanel} title="Notifications" aria-label="Open notifications">
        <Bell className="h-4 w-4" />
        {showDot && <span className="dpt-dot">{dotCount ?? ''}</span>}
      </button>

      <ProfileCard variant="header" />
    </header>
  );
}
