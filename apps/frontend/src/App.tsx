import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, lazy, Suspense } from 'react';
import { Loader2 } from 'lucide-react';
import seedAllDemoDataIfMissing from '@/lib/demoSeeder';
import { AppLayout } from "@/components/layout/AppLayout";
import { TermProvider } from "@/contexts/TermContext";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { AuthProvider } from "@/contexts/AuthContext";

// Route pages are code-split so the initial bundle stays small and each screen
// loads only what it needs — the app boots and navigates much faster.
const CloudFolders = lazy(() => import("./pages/CloudFolders"));
const Landing = lazy(() => import("./pages/Landing"));
const Signup = lazy(() => import("./pages/Signup"));
const Login = lazy(() => import("./pages/Login"));
const TranscriptTypesNeedsSetup = lazy(() => import("./pages/TranscriptTypesNeedsSetup"));
const TranscriptTypesInSetup = lazy(() => import("./pages/TranscriptTypesInSetup"));
const TranscriptTypesReady = lazy(() => import("./pages/TranscriptTypesReady"));
const AdmissionCriteria = lazy(() => import("./pages/AdmissionCriteria"));
const TranscriptCodes = lazy(() => import("./pages/TranscriptCodes"));
const ProgramCriteria = lazy(() => import("./pages/ProgramCriteria"));
const CourseMapping = lazy(() => import("./pages/CourseMapping"));
const TermRules = lazy(() => import("./pages/TermRules"));
const DetectorIncoming = lazy(() => import("./pages/DetectorIncoming"));
const DetectorExisting = lazy(() => import("./pages/DetectorExisting"));
const DetectorNewType = lazy(() => import("./pages/DetectorNewType"));
const DetectorUnknown = lazy(() => import("./pages/DetectorUnknown"));
const TranscriptClassify = lazy(() => import("./pages/TranscriptClassify"));
const TranscriptExtract = lazy(() => import("./pages/TranscriptExtract"));
const Home = lazy(() => import("./pages/Home"));
const TranscriptIntelligence = lazy(() => import("./pages/TranscriptIntelligence"));
const InstitutionSetup = lazy(() => import("./pages/InstitutionSetup"));
const AdmissionCenter = lazy(() => import("./pages/AdmissionCenter"));
const ReportsInsights = lazy(() => import("./pages/ReportsInsights"));
const TranscriptDetail = lazy(() => import("./pages/TranscriptDetail"));
const ExtractorCompleted = lazy(() => import("./pages/ExtractorCompleted"));
const ExtractorNeedsReview = lazy(() => import("./pages/ExtractorNeedsReview"));
const ExtractorNotProcessed = lazy(() => import("./pages/ExtractorNotProcessed"));
const DecisionsAdmitted = lazy(() => import("./pages/DecisionsAdmitted"));
const DecisionsDenied = lazy(() => import("./pages/DecisionsDenied"));
const DecisionsWaitlisted = lazy(() => import("./pages/DecisionsWaitlisted"));
const TrainerDashboard = lazy(() => import("./pages/TrainerDashboard"));
const TemplateManager = lazy(() => import("./pages/TemplateManager"));
const FieldMapping = lazy(() => import("./pages/FieldMapping"));
const AdmissionsDashboard = lazy(() => import("./pages/AdmissionsDashboard"));
const ApplicationList = lazy(() => import("./pages/ApplicationList"));
const ApplicationDetail = lazy(() => import("./pages/ApplicationDetail"));
const I20List = lazy(() => import("./pages/I20List"));
const DecisionTemplates = lazy(() => import("./pages/DecisionTemplates"));
const EnrollmentGoals = lazy(() => import("./pages/EnrollmentGoals"));
const AdmissionsYield = lazy(() => import("./pages/AdmissionsYield"));
const DesignSystemTest = lazy(() => import("./pages/DesignSystemTest"));
const NotFound = lazy(() => import("./pages/NotFound"));
const DriveOAuthCallback = lazy(() => import("./pages/DriveOAuthCallback"));
const MicrosoftCallback = lazy(() => import("./pages/MicrosoftCallback"));

const queryClient = new QueryClient();

function RouteFallback() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center text-sm text-muted-foreground">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      Loading…
    </div>
  );
}

const App = () => {
  useEffect(() => {
    try {
      seedAllDemoDataIfMissing();
    } catch (e) {
      // ignore in non-browser environments
    }
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
    <AuthProvider>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <ThemeProvider>
        <TermProvider>
          <Suspense fallback={<RouteFallback />}>
          <Routes>
            {/* Landing page and auth outside of the authenticated app shell */}
            <Route path="/" element={<Landing />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/login" element={<Login />} />
            <Route path="/drive/callback" element={<DriveOAuthCallback />} />
            <Route path="/sso/callback" element={<MicrosoftCallback />} />

            {/* Mount the existing app behind /app so the site can have a public landing */}
            <Route path="/app" element={<AppLayout />}>
              {/* Default Route - Redirects to Cloud Folders */}
              <Route index element={<Navigate to="/app/cloud-folders" replace />} />

              {/* Home — workflow tiles */}
              <Route path="home" element={<Home />} />

              {/* Transcript Intelligence Center — workflow dashboard */}
              <Route path="transcript-intelligence" element={<TranscriptIntelligence />} />
              <Route path="institution-setup" element={<InstitutionSetup />} />
              <Route path="admission-center" element={<AdmissionCenter />} />

              {/* Upload / Classify / Extract */}
              <Route path="cloud-folders" element={<CloudFolders />} />
              <Route path="classify" element={<TranscriptClassify />} />
              <Route path="extract" element={<TranscriptExtract />} />

            {/* Institutional Admission Criteria */}
            <Route path="admission-criteria" element={<AdmissionCriteria />} />
            <Route path="program-criteria" element={<ProgramCriteria />} />
            <Route path="course-mapping" element={<CourseMapping />} />
            <Route path="term-rules" element={<TermRules />} />
            <Route path="transcript-codes" element={<TranscriptCodes />} />

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
            <Route path="admissions/reports" element={<ReportsInsights />} />

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
            <Route path="decisions/admitted" element={<DecisionsAdmitted />} />
            <Route path="decisions/denied" element={<DecisionsDenied />} />
            <Route path="decisions/waitlisted" element={<DecisionsWaitlisted />} />

            {/* Design System Test */}
            <Route path="design-system-test" element={<DesignSystemTest />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
          </Suspense>
        </TermProvider>
        </ThemeProvider>
      </BrowserRouter>
    </TooltipProvider>
    </AuthProvider>
  </QueryClientProvider>
  );
};

export default App;
