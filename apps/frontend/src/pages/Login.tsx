import { Link, useSearchParams } from "react-router-dom";
import Logo from '@/components/shared/Logo';
import { ShieldCheck, ArrowRight } from "lucide-react";

function MicrosoftIcon() {
  return (
    <svg viewBox="0 0 21 21" width="20" height="20" xmlns="http://www.w3.org/2000/svg">
      <path d="M0 0h10v10H0z" fill="#f25022" />
      <path d="M11 0h10v10H11z" fill="#7fba00" />
      <path d="M0 11h10v10H0z" fill="#00a4ef" />
      <path d="M11 11h10v10H11z" fill="#ffb900" />
    </svg>
  );
}

const ERROR_MESSAGES: Record<string, string> = {
  domain_not_allowed: "Only @csulb.edu email addresses are allowed. Please sign in with your CSULB account.",
  token_exchange_failed: "Authentication failed — Microsoft did not return a valid token. Please try again.",
  graph_failed: "Could not load your profile from Microsoft. Please try again.",
  invalid_state: "Session expired or the request was invalid. Please try again.",
  sso_not_configured: "Microsoft SSO is not configured. Contact your administrator.",
  access_denied: "Access was denied. Please accept the required permissions and try again.",
  no_access_token: "Authentication failed — no access token received. Please try again.",
};

export default function Login() {
  const [searchParams] = useSearchParams();
  const error = searchParams.get("error");

  return (
    <div className="min-h-screen h-screen flex items-center justify-center py-6 px-4 overflow-hidden relative bg-[radial-gradient(ellipse_at_top,rgba(14,165,233,0.06),rgba(247,250,252,0)_60%)] text-slate-900">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(ellipse_at_top,rgba(14,165,233,0.06),transparent)]" />
      <div className="pointer-events-none absolute inset-x-0 top-10 h-[320px] bg-[radial-gradient(ellipse_at_top_left,rgba(45,212,191,0.04),transparent)]" />

      <div className="relative mx-auto grid max-w-6xl grid-cols-1 items-start gap-10 px-4 py-6 md:grid-cols-2 md:py-10">

        {/* Left panel */}
        <div className="hidden md:block">
          <Link to="/" className="inline-flex items-center gap-3">
            <Logo />
          </Link>
          <h1 className="mt-6 text-4xl font-semibold leading-tight tracking-tight">
            Sign in to your{" "}
            <span className="bg-gradient-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent">
              admissions workspace
            </span>
          </h1>
          <p className="mt-4 max-w-md text-slate-800">
            Use your CSULB Microsoft account to securely access the review queue, templates, and cloud folder intake.
          </p>
          <div className="mt-8 grid grid-cols-1 gap-3">
            <div className="rounded-2xl border border-slate-100 bg-white p-4">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 text-slate-700"><ShieldCheck size={18} /></div>
                <div>
                  <div className="text-sm font-semibold">Microsoft Single Sign-On</div>
                  <div className="mt-1 text-sm text-slate-500">Secured by CSULB's Microsoft Entra ID with MFA via Microsoft Authenticator.</div>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-slate-100 bg-white p-4">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 text-slate-700"><ArrowRight size={18} /></div>
                <div>
                  <div className="text-sm font-semibold">CSULB accounts only</div>
                  <div className="mt-1 text-sm text-slate-500">Sign in with your <span className="font-mono">@csulb.edu</span> email address. New accounts are created automatically on first sign-in.</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right panel */}
        <div className="mx-auto w-full max-w-md">
          <div className="rounded-3xl border border-slate-100 bg-white p-7 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold tracking-tight">Sign in</h2>
                <p className="mt-1 text-sm text-slate-600">Use your CSULB Microsoft account to continue.</p>
              </div>
              <Link to="/" className="rounded-xl border border-slate-100 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">
                Back
              </Link>
            </div>

            {error && (
              <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {ERROR_MESSAGES[error] ?? "An unexpected error occurred. Please try again."}
              </div>
            )}

            <div className="mt-6">
              <a
                href="/api/auth/microsoft/login"
                className="flex w-full items-center justify-center gap-3 rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-800 shadow-sm hover:bg-slate-50 transition-colors"
              >
                <MicrosoftIcon />
                Sign in with Microsoft
              </a>
            </div>

            <div className="mt-4 rounded-2xl bg-slate-50 px-4 py-3 text-xs text-slate-500">
              You will be redirected to Microsoft's sign-in page. Use your{" "}
              <span className="font-mono font-medium text-slate-700">@csulb.edu</span> email.
              Your account is created automatically on first sign-in.
            </div>
          </div>

          <div className="mt-4 text-center text-xs text-slate-500">
            By signing in, you agree to the Terms and Privacy Policy.
          </div>
        </div>
      </div>
    </div>
  );
}
