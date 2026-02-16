import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect } from 'react';
import seedTranscriptTypesIfMissing, { seedTranscriptTypes } from '@/lib/transcriptTypesSeeder';
import seedAllDemoDataIfMissing from '@/lib/demoSeeder';
import { AppLayout } from "@/components/layout/AppLayout";
import { TermProvider } from "@/contexts/TermContext";
import { ThemeProvider } from "@/contexts/ThemeContext";
import CloudFolders from "./pages/CloudFolders";
import Landing from "./pages/Landing";
import Signup from "./pages/Signup";
import Login from "./pages/Login";
import TranscriptTypesNeedsSetup from "./pages/TranscriptTypesNeedsSetup";
import TranscriptTypesInSetup from "./pages/TranscriptTypesInSetup";
import TranscriptTypesReady from "./pages/TranscriptTypesReady";
import AdmissionCriteria from "./pages/AdmissionCriteria";
import ProgramCriteria from "./pages/ProgramCriteria";
import CourseMapping from "./pages/CourseMapping";
import DetectorIncoming from "./pages/DetectorIncoming";
import DetectorExisting from "./pages/DetectorExisting";
import DetectorNewType from "./pages/DetectorNewType";
import DetectorUnknown from "./pages/DetectorUnknown";
// transcript listing pages unused in root routes; keep individual detail route
import TranscriptDetail from "./pages/TranscriptDetail";
import ExtractorCompleted from "./pages/ExtractorCompleted";
import ExtractorNeedsReview from "./pages/ExtractorNeedsReview";
import ExtractorNotProcessed from "./pages/ExtractorNotProcessed";
import DecisionsPending from "./pages/DecisionsPending";
import DecisionsAdmitted from "./pages/DecisionsAdmitted";
import DecisionsDenied from "./pages/DecisionsDenied";
import DecisionsWaitlisted from "./pages/DecisionsWaitlisted";
import TrainerDashboard from "./pages/TrainerDashboard";
import TemplateManager from "./pages/TemplateManager";
import FieldMapping from "./pages/FieldMapping";
import AdmissionsDashboard from "./pages/AdmissionsDashboard";
import ApplicationList from "./pages/ApplicationList";
import ApplicationDetail from "./pages/ApplicationDetail";
import I20List from "./pages/I20List";
import DecisionTemplates from "./pages/DecisionTemplates";
import EnrollmentGoals from "./pages/EnrollmentGoals";
import AdmissionsYield from "./pages/AdmissionsYield";
import DesignSystemTest from "./pages/DesignSystemTest";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

const App = () => {
  useEffect(() => {
    try {
  // Force demo data: 10 items per status so each page shows 10 rows
  seedTranscriptTypes(true, 10);
  seedTranscriptTypesIfMissing();
  // Seed lightweight demo records used across pages when missing
  seedAllDemoDataIfMissing();
    } catch (e) {
      // ignore in non-browser environments
    }
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <ThemeProvider>
        <TermProvider>
          <Routes>
            {/* Landing page and auth outside of the authenticated app shell */}
            <Route path="/" element={<Landing />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/login" element={<Login />} />

            {/* Mount the existing app behind /app so the site can have a public landing */}
            <Route path="/app" element={<AppLayout />}>
              {/* Default Route - Redirects to Cloud Folders */}
              <Route index element={<Navigate to="/app/cloud-folders" replace />} />

              {/* Cloud Folders */}
              <Route path="cloud-folders" element={<CloudFolders />} />

            {/* Institutional Admission Criteria */}
            <Route path="admission-criteria" element={<AdmissionCriteria />} />
            <Route path="program-criteria" element={<ProgramCriteria />} />
            <Route path="course-mapping" element={<CourseMapping />} />

            {/* Transcript Extractor */}
            <Route path="extractor/completed" element={<ExtractorCompleted />} />
            <Route path="extractor/needs-review" element={<ExtractorNeedsReview />} />
            <Route path="extractor/not-processed" element={<ExtractorNotProcessed />} />
            {/* legacy listing routes removed from app; keep individual detail route */}
            <Route path="transcripts/:id" element={<TranscriptDetail />} />

            {/* Transcript Trainer */}
            <Route path="trainer/dashboard" element={<TrainerDashboard />} />
            <Route path="trainer/templates" element={<TemplateManager />} />
            <Route path="trainer/field-mapping" element={<FieldMapping />} />

            {/* Admissions */}
            <Route path="admissions/dashboard" element={<AdmissionsDashboard />} />
            <Route path="admissions/received" element={<ApplicationList />} />
            <Route path="admissions/eligible" element={<ApplicationList />} />
            <Route path="admissions/ineligible" element={<ApplicationList />} />
            <Route path="admissions/verification" element={<ApplicationList />} />
            <Route path="admissions/i20s" element={<I20List />} />
            <Route path="admissions/templates" element={<DecisionTemplates />} />
            <Route path="admissions/applications/:applicationId" element={<ApplicationDetail />} />

            {/* Goals */}
            <Route path="admissions/enrollment-goals" element={<EnrollmentGoals />} />
            <Route path="admissions/yield" element={<AdmissionsYield />} />

            {/* New Transcript Type - Read-only automated states */}
            <Route path="transcripts/new-types/needs-setup" element={<TranscriptTypesNeedsSetup />} />
            <Route path="transcripts/new-types/in-setup" element={<TranscriptTypesInSetup />} />
            <Route path="transcripts/new-types/ready" element={<TranscriptTypesReady />} />

            {/* Transcript Detector */}
            <Route path="detector/incoming" element={<DetectorIncoming />} />
            <Route path="detector/existing" element={<DetectorExisting />} />
            <Route path="detector/new-type" element={<DetectorNewType />} />
            <Route path="detector/unknown" element={<DetectorUnknown />} />

            {/* Admission Decision */}
            <Route path="decisions/pending" element={<DecisionsPending />} />
            <Route path="decisions/admitted" element={<DecisionsAdmitted />} />
            <Route path="decisions/denied" element={<DecisionsDenied />} />
            <Route path="decisions/waitlisted" element={<DecisionsWaitlisted />} />

            {/* Design System Test */}
            <Route path="design-system-test" element={<DesignSystemTest />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </TermProvider>
        </ThemeProvider>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
  );
};

export default App;

