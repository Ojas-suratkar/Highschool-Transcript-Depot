import { Link } from "react-router-dom";
import Logo from '@/components/shared/Logo';
import {
  ArrowRight,
  UploadCloud,
  ScanText,
  Layers,
  Users,
  GitBranch,
  Download,
  CheckCircle2,
} from "lucide-react";

export default function Landing() {
  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,rgba(14,165,233,0.04),transparent)] text-slate-900">
      {/* Top subtle color accents */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(ellipse_at_top,rgba(14,165,233,0.04),transparent)]" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[320px] bg-[radial-gradient(ellipse_at_top_left,rgba(45,212,191,0.02),transparent)]" />

      {/* NAV */}
      <header className="sticky top-0 z-50 border-b border-slate-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-3">
            <Logo />
          </Link>

            

          <div className="flex items-center gap-8">
            <a href="#features" className="text-sm text-slate-700 hover:text-slate-900">Features</a>
            <Link to="/login" className="hidden rounded-xl px-3 py-2 text-sm text-slate-700 border border-slate-200 hover:bg-slate-50 md:inline-flex">Log in</Link>
            <Link to="/signup" className="hidden rounded-xl px-3 py-2 text-sm text-white bg-blue-600 hover:bg-blue-500 md:inline-flex">Sign up</Link>
          </div>
        </div>
      </header>

      {/* HERO */}
      <section className="relative">
        <div className="mx-auto grid max-w-6xl grid-cols-1 gap-10 px-4 py-16 md:grid-cols-2 md:py-24">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-100 bg-white px-3 py-1 text-xs text-slate-700">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              Hassle-Free Admissions Now !✌️
            </div>

            <h1 className="mt-5 text-4xl font-semibold leading-tight tracking-tight md:text-5xl text-slate-900">
              Turn transcripts into <span className="bg-gradient-to-r from-blue-500 to-cyan-400 bg-clip-text text-transparent">structured data</span> and <span className="bg-gradient-to-r from-cyan-400 to-emerald-400 bg-clip-text text-transparent">admission decisions</span>
            </h1>

            <p className="mt-4 max-w-xl text-base leading-relaxed text-slate-700">
              Highschool Transcript Depot automates transcript intake, extraction, and review so your admissions team spends less time fixing formats and more time making fair, documented decisions.
            </p>

            <div className="mt-7 flex flex-col gap-3 sm:flex-row">
              <Link to="/signup" className="inline-flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-500">Get started <ArrowRight size={16} /></Link>
            </div>

            <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
              {[
                { label: "Ingest", desc: "Manual upload + cloud folders" },
                { label: "Process", desc: "Human-in-the-loop for low-confidence cases" },
                { label: "Results", desc: "Admission Results and document templates" },
              ].map((x) => (
                <div
                  key={x.label}
                  className="rounded-2xl border border-slate-100 bg-white p-4"
                >
                  <div className="text-sm font-semibold">{x.label}</div>
                  <div className="mt-1 text-xs text-slate-500">{x.desc}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Right side: clean “pipeline” panel */}
          <div className="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold">Transcript Pipeline</div>
              <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-600">
              </div>
            </div>

            <div className="mt-5 space-y-3">
              <PipelineRow icon={<UploadCloud size={18} />} title="Ingestion" desc="Upload PDFs or sync from Drive/S3" tag="Input" />
              <PipelineRow icon={<ScanText size={18} />} title="Classification" desc="Classify transcripts by types" tag="Classify" />
              <PipelineRow icon={<Users size={18} />} title="Extraction" desc="Parse courses, grades, GPA → Structured Output" tag="Extract" />
              <PipelineRow icon={<CheckCircle2 size={18} />} title="Manual Review" desc="Flagged cases for human review" tag="Manual Review" />
              <PipelineRow icon={<Download size={18} />} title="Admission Decisions" desc="Admission Results and document templates" tag="Decision" />
            </div>

            <div className="mt-6 rounded-2xl border border-slate-100 bg-slate-50 p-4">
              <div className="text-xs text-slate-700">Key idea: Reduce manual effort in transcript processing.</div>
            </div>
          </div>
        </div>

        {/* Trust strip */}
        
      </section>


      {/* FEATURES */}
      <section id="features" className="mx-auto max-w-6xl px-4 py-16">
        <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div className="max-w-2xl">
            <h2 className="text-2xl font-semibold tracking-tight">Core Features</h2>
            <p className="mt-2 text-slate-600">
              Everything needed to ingest, classify, extract, process, and make admission decisions — with complete traceability.
            </p>
          </div>
        </div>

        <div className="mt-10 grid grid-cols-1 gap-4 md:grid-cols-3">
          <FeatureCard
            icon={<UploadCloud />}
            title="Cloud ingestion"
            body="Continuous intake from manual uploads and cloud folder links (Drive, S3) so transcripts flow into the system automatically."
            highlight="Connectors + uploads"
          />

          <FeatureCard
            icon={<GitBranch />}
            title="Classification by type"
            body="Automatically classify incoming transcripts by format/type so the right parsing template is applied."
            highlight="Type-aware classification"
          />

          <FeatureCard
            icon={<Layers />}
            title="Institution & program criteria"
            body="Define institutional and program-level admission criteria and map them to extracted transcript fields for decisioning."
            highlight="Configurable criteria"
          />

          <FeatureCard
            icon={<ScanText />}
            title="Extract data from transcripts"
            body="Parse students, course rows, grades, GPA and term structure into structured formats with confidence scores."
            highlight="Extraction"
          />

          <FeatureCard
            icon={<Users />}
            title="Auto-flagged & manual entry"
            body="Low-confidence or exception cases are auto-flagged for reviewers who can enter or correct data manually in the system."
            highlight="Human in the loop"
          />

          <FeatureCard
            icon={<Download />}
            title="Decisions & documents"
            body="Make admission decisions, generate and download decision documents (admit & decline letters, I-20's, other customized documents) for accepted or denied applicants."
            highlight="Decisions"
          />

          <FeatureCard
            icon={<CheckCircle2 />}
            title="Yields & goals"
            body="Track admission yields and enrollment goals with dashboards and reports to measure outcomes."
            highlight="Admissions Dashboards"/>
        </div>
      </section>

      

      {/* FOOTER */}
      <footer className="border-t border-white/10 py-10">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <Logo />
          </div>

          <div className="flex flex-wrap gap-4 text-sm text-slate-600">
            <Link to="/privacy" className="hover:text-slate-900">Privacy</Link>
            <Link to="/terms" className="hover:text-slate-900">Terms</Link>
            <a href="#top" className="hover:text-slate-900">Back to top</a>
          </div>
        </div>
      </footer>
    </div>
  );
}

/** components */

function PipelineRow({
  icon,
  title,
  desc,
  tag,
}: {
  icon: React.ReactNode;
  title: string;
  desc: string;
  tag: string;
}) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-slate-100 bg-white p-4">
      <div className="mt-0.5 grid h-9 w-9 place-items-center rounded-xl bg-slate-50 ring-1 ring-slate-100">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <div className="font-semibold text-slate-900">{title}</div>
          <div className="shrink-0 rounded-full border border-slate-100 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600">{tag}</div>
        </div>
        <div className="mt-1 text-sm text-slate-700">{desc}</div>
      </div>
    </div>
  );
}



function FeatureCard({
  icon,
  title,
  body,
  highlight,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  highlight: string;
}) {
  return (
    <div className="group rounded-3xl border border-slate-100 bg-white p-6 transition hover:border-slate-200 hover:bg-slate-50">
      <div className="flex items-center justify-between">
        <div className="grid h-11 w-11 place-items-center rounded-2xl bg-slate-50 ring-1 ring-slate-100">{icon}</div>
        <div className="rounded-full border border-slate-100 bg-slate-50 px-3 py-1 text-[11px] text-slate-600">{highlight}</div>
      </div>
      <div className="mt-4 text-base font-semibold text-slate-900">{title}</div>
      <div className="mt-1 text-sm leading-relaxed text-slate-700">{body}</div>
    </div>
  );
}

