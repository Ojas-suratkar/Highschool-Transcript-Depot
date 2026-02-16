import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Logo from '@/components/shared/Logo';
import { ArrowRight, Mail, AlertTriangle, ShieldCheck, CheckCircle2 } from "lucide-react";

export default function Login() {
  const [email, setEmail] = useState("");
  // password removed — OTP-only flow
  // Simplified: email-only OTP flow
  const [authPhase, setAuthPhase] = useState<'enter-credentials' | 'await-otp' | 'done'>('enter-credentials');
  const [otpSent, setOtpSent] = useState(false);
  const [otpValue, setOtpValue] = useState("");
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [password, setPassword] = useState("");
  const [fakeOtp, setFakeOtp] = useState<string | null>(null);
  const navigate = useNavigate();

  const canSubmit = useMemo(() => {
    if (authPhase === 'enter-credentials') return email.trim().length > 3 && password.trim().length > 0;
    if (authPhase === 'await-otp') return otpSent && otpValue.trim().length > 0;
    return false;
  }, [authPhase, email, password, otpSent, otpValue]);

  // loading states
  const [isRequestingOtp, setIsRequestingOtp] = useState(false);
  const [isVerifyingOtp, setIsVerifyingOtp] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (authPhase === 'enter-credentials') {
  // trigger request-otp only when the user presses the button
  await sendLoginOtp();
  return;
    }

    if (authPhase === 'await-otp') {
      if (!otpValue) return setError('Enter the OTP');
  setIsVerifyingOtp(true);
  try {
        const res = await fetch('/auth/verify-otp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ challenge_id: challengeId, otp: otpValue })
        });
        const data = await res.json();
        if (!res.ok) return setError(data.detail || 'Invalid code');
        localStorage.setItem('th_access_token', data.access_token);
        setAuthPhase('done');
        navigate('/app/cloud-folders');
      } catch (err: any) {
        setError(err?.message || 'Network error');
      } finally {
        setIsVerifyingOtp(false);
      }
    }
  };

  // request login OTP (email + password). Shared by auto-send and manual submit.
  const sendLoginOtp = async () => {
    setError('');
    if (!email || !email.includes('@')) return setError('Enter a valid email');
    if (!password) return setError('Enter your password');
    setIsRequestingOtp(true);
    try {
      const res = await fetch('/auth/request-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || 'Failed to request OTP');
        return;
      }
      setChallengeId(data.challenge_id);
      if (data.debug_otp) setFakeOtp(data.debug_otp);
      setOtpSent(true);
      setAuthPhase('await-otp');
    } catch (err: any) {
      setError(err?.message || 'Network error');
    } finally {
      setIsRequestingOtp(false);
    }
  };

  const sendOtp = async () => {
    setError('');
    // resend: call request-otp again
    try {
      const res = await fetch('/auth/request-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      const data = await res.json();
      if (!res.ok) return setError(data.detail || 'Failed to request OTP');
      setChallengeId(data.challenge_id);
      if (data.debug_otp) setFakeOtp(data.debug_otp);
      setOtpSent(true);
    } catch (err: any) {
      setError(err?.message || 'Network error');
    }
  };

  // Auto-send disabled: OTP will be sent only when user presses the Sign in button.

  return (
    <div className="min-h-screen h-screen flex items-center justify-center py-6 px-4 overflow-hidden relative bg-[radial-gradient(ellipse_at_top,rgba(14,165,233,0.06),rgba(247,250,252,0)_60%)] text-slate-900">
  <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(ellipse_at_top,rgba(14,165,233,0.06),transparent)]" />
      <div className="pointer-events-none absolute inset-x-0 top-10 h-[320px] bg-[radial-gradient(ellipse_at_top_left,rgba(45,212,191,0.04),transparent)]" />

  <div className="relative mx-auto grid max-w-6xl grid-cols-1 items-start gap-10 px-4 py-6 md:grid-cols-2 md:py-10">
        {/* left: message */}
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
            Use your account credentials to access the review queue, templates, and cloud folder intake.
          </p>

          <div className="mt-8 grid grid-cols-1 gap-3">
            <div className="rounded-2xl border border-slate-100 bg-white p-4">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 text-slate-700"><ShieldCheck size={18} /></div>
                <div>
                  <div className="text-sm font-semibold">Enterprise-ready access & security</div>
                  <div className="mt-1 text-sm text-slate-500">Role-based access supported & very secure.</div>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-slate-100 bg-white p-4">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 text-slate-700"><ArrowRight size={18} /></div>
                <div>
                  <div className="text-sm font-semibold">Define Course Criteria</div>
                  <div className="mt-1 text-sm text-slate-500">Set specific requirements for course eligibility and review.</div>
                </div>
              </div>
            </div>
          </div>
        </div>

  {/* right: form */}
        <div className="mx-auto w-full max-w-md">
          <div className="rounded-3xl border border-slate-100 bg-white p-7 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold tracking-tight">Sign in</h2>
    <p className="mt-1 text-sm text-slate-600">Use your account credentials to access the workspace.</p>
              </div>

              <Link to="/" className="rounded-xl border border-slate-100 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">
                Back
              </Link>
            </div>

            {error && (
              <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="mt-0.5" size={16} />
                  <div>{error}</div>
                </div>
              </div>
            )}

            <form onSubmit={submit} className="mt-4 space-y-4">

              <div>
                <label className="text-sm text-slate-700">Email</label>
                <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                  <Mail size={18} className="text-slate-400" />
                  <input
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder={'you@university.edu'}
                    className="w-full bg-transparent text-slate-800 placeholder:text-slate-400 focus:outline-none"
                    autoComplete={'email'}
                  />
                </div>
              </div>

              {/* password field follows */}

                <div>
                  <label className="text-sm text-slate-700">Password</label>
                  <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Your account password"
                      className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                      autoComplete="current-password"
                    />
                  </div>
                </div>

              {/* password-based login removed — OTP-only flow */}

              {/* OTP input appears after credentials are validated */}
              {authPhase === 'await-otp' && otpSent && (
                <div>
                  <label className="text-sm text-slate-700">One-time code</label>
                  <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                    <CheckCircle2 size={18} className="text-slate-400" />
                    <input
                      value={otpValue}
                      onChange={(e) => setOtpValue(e.target.value)}
                      placeholder="123456"
                      className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                      autoComplete="one-time-code"
                    />
                    <button type="button" onClick={sendOtp} className="rounded-md bg-blue-50 px-3 py-1 text-sm">Resend</button>
                  </div>

                  {/* QA-only visible OTP for testers: shows generated demo code and allows quick copy */}
                  {fakeOtp && (
                    <div className="mt-3 flex items-center gap-2 text-sm">
                      <div className="inline-flex items-center gap-2 rounded-md bg-slate-50 px-3 py-1 text-xs font-mono text-slate-800">
                        <span className="text-amber-600">QA OTP:</span>
                        <span className="font-semibold">{fakeOtp}</span>
                      </div>
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            await navigator.clipboard.writeText(fakeOtp);
                          } catch (err) {
                            // ignore clipboard errors in older browsers
                          }
                        }}
                        className="rounded-md border border-slate-200 px-3 py-1 text-xs bg-white"
                      >
                        Copy
                      </button>
                      <div className="text-xs text-slate-500">(visible for QA only)</div>
                    </div>
                  )}

                  <div className="mt-2 text-xs text-slate-600">OTP sent to your email. Enter the code to continue.</div>
                </div>
              )}

              <button
                type="submit"
                disabled={isRequestingOtp || isVerifyingOtp || !canSubmit}
                className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {authPhase === 'enter-credentials' && (
                  <>
                    {isRequestingOtp ? (
                      <span className="inline-flex items-center gap-2">
                        <span className="h-3 w-3 rounded-full bg-white/90 animate-pulse" />
                        Sending...
                      </span>
                    ) : (
                      <>Send OTP <ArrowRight size={16} /></>
                    )}
                  </>
                )}

                {authPhase === 'await-otp' && (
                  <>
                    {isVerifyingOtp ? (
                      <span className="inline-flex items-center gap-2">
                        <span className="h-3 w-3 rounded-full bg-white/90 animate-pulse" />
                        Verifying...
                      </span>
                    ) : (
                      <>Verify code <ArrowRight size={16} /></>
                    )}
                  </>
                )}
              </button>

              <div className="flex items-center justify-between pt-1 text-sm">
                <div className="text-slate-700">Don't have an account?</div>
                <button type="button" className="text-blue-600 font-semibold" onClick={() => navigate("/signup")}>Create account</button>
              </div>

              
            </form>
          </div>

          <div className="mt-4 text-center text-xs text-slate-500">By signing in, you agree to the Terms and Privacy Policy.</div>
        </div>
      </div>
    </div>
  );
}

// InfoRow removed — not used in this page
