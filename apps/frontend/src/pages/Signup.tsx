import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Logo from '@/components/shared/Logo';
import { Mail, Lock, Eye, EyeOff, ArrowRight, ShieldCheck, UploadCloud, CheckCircle2, Users } from "lucide-react";

export default function Signup() {
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [institutionCity, setInstitutionCity] = useState("");
  const [institutionZip, setInstitutionZip] = useState("");
  const [institutionName, setInstitutionName] = useState("");
  const [role, setRole] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState("");
  const [showVerify, setShowVerify] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const navigate = useNavigate();

  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [otpValue, setOtpValue] = useState('');

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsSubmitting(true);
    if (!email || !firstName || !lastName || !password || !confirm) {
      setError("Please fill required fields");
      setIsSubmitting(false);
      return;
    }
    if (!email.includes("@")) {
      setError("Enter a valid email");
      setIsSubmitting(false);
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match');
      setIsSubmitting(false);
      return;
    }

    try {
      const res = await fetch('/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          phone,
          password,
          first_name: firstName,
          last_name: lastName,
          institution_name: institutionName,
          city: institutionCity,
          zip: institutionZip,
          role
        })
      });
      let data = null;
      try {
        data = await res.json();
      } catch (err) {
        data = null;
      }
      if (!res.ok) {
        const text = data?.detail || data?.message || (await res.text().catch(() => null)) || 'Failed to signup';
        setError(text);
        setIsSubmitting(false);
        return;
      }
      setChallengeId(data?.challenge_id || null);
      setShowVerify(true);
      // start a short resend cooldown (avoid spamming)
      setResendCooldown(60);
      const t = setInterval(() => {
        setResendCooldown((s: number) => {
          if (s <= 1) {
            clearInterval(t);
            return 0;
          }
          return s - 1;
        });
      }, 1000);
      setIsSubmitting(false);
    } catch (err: any) {
      setError(err?.message || 'Network error');
      setIsSubmitting(false);
    }
  };

  const verifyOtp = async () => {
  setError('');
  if (!challengeId || !otpValue) { setError('Enter OTP'); return; }
    setIsVerifying(true);
    try {
      const res = await fetch('/auth/verify-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ challenge_id: challengeId, otp: otpValue })
      });
      let data = null;
      try {
        data = await res.json();
      } catch (err) {
        data = null;
      }
      if (!res.ok) {
        const text = data?.detail || data?.message || (await res.text().catch(() => null)) || 'Verification failed';
        setError(text);
        setIsVerifying(false);
        return;
      }
      // store token (TODO: httpOnly cookie prefered)
      localStorage.setItem('th_access_token', data.access_token);
      // after verification redirect user to login page
      setIsVerifying(false);
      navigate('/login');
    } catch (err: any) {
      setError(err?.message || 'Network error');
      setIsVerifying(false);
    }
  };

  const resendOtp = async () => {
    // Re-use the signup endpoint to recreate a challenge and resend the OTP
    if (resendCooldown > 0) return setError(`Please wait ${resendCooldown}s before resending`);
  setError('');
    try {
      const res = await fetch('/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          phone,
          password,
          first_name: firstName,
          last_name: lastName,
          institution_name: institutionName,
          city: institutionCity,
          zip: institutionZip,
          role
        })
      });
      let data = null;
      try { data = await res.json(); } catch { data = null; }
      if (!res.ok) {
        const text = data?.detail || (await res.text().catch(() => null)) || 'Failed to resend OTP';
        return setError(text);
      }
      setChallengeId(data?.challenge_id || null);
      setError('OTP resent');
      setResendCooldown(60);
      const t2 = setInterval(() => {
        setResendCooldown((s: number) => {
          if (s <= 1) { clearInterval(t2); return 0; }
          return s - 1;
        });
      }, 1000);
    } catch (err: any) {
      setError(err?.message || 'Network error');
    }
  };

  return (
    <div className="min-h-screen h-screen flex items-center justify-center py-6 px-4 overflow-hidden relative bg-[radial-gradient(ellipse_at_top,rgba(14,165,233,0.06),rgba(247,250,252,0)_60%)] text-slate-900">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(ellipse_at_top,rgba(14,165,233,0.06),transparent)]" />
      <div className="pointer-events-none absolute inset-x-0 top-10 h-[320px] bg-[radial-gradient(ellipse_at_top_left,rgba(45,212,191,0.04),transparent)]" />

  <div className="container max-w-5xl grid grid-cols-1 md:grid-cols-2 gap-8 items-start w-full">
        <div className="hidden md:block">
          <Link to="/" className="inline-flex items-center gap-3">
            <Logo />
          </Link>

          <h1 className="mt-10 text-3xl font-semibold leading-tight">
            Create your account
          </h1>
          <p className="mt-4 max-w-md text-slate-600">
            Create an account and start using the workspace to manage your admissions workflows.
          </p>

          <div className="mt-8 space-y-3">
            <div className="flex items-start gap-3 rounded-2xl border border-slate-100 bg-white p-4">
              <div className="mt-0.5 text-slate-700"><ShieldCheck size={18} /></div>
              <div>
                <div className="text-sm font-semibold">Institution-ready</div>
                <div className="mt-1 text-sm text-slate-500">Role controls and audit examples are included in the demo.</div>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-2xl border border-slate-100 bg-white p-4">
              <div className="mt-0.5 text-slate-700"><UploadCloud size={18} /></div>
              <div>
                <div className="text-sm font-semibold">Cloud ingestion</div>
                <div className="mt-1 text-sm text-slate-500">Connect Drive or S3 folders and keep intake continuous.</div>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-2xl border border-slate-100 bg-white p-4">
              <div className="mt-0.5 text-slate-700"><CheckCircle2 size={18} /></div>
              <div>
                <div className="text-sm font-semibold">Automated extraction</div>
                <div className="mt-1 text-sm text-slate-500">Parse courses, grades and GPA with confidence scores.</div>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-2xl border border-slate-100 bg-white p-4">
              <div className="mt-0.5 text-slate-700"><Users size={18} /></div>
              <div>
                <div className="text-sm font-semibold">Manual review & correction</div>
                <div className="mt-1 text-sm text-slate-500">Flagged cases are surfaced for reviewers to correct and approve.</div>
              </div>
            </div>
          </div>
        </div>

        <div className="mx-auto w-full max-w-md max-h-[92vh] overflow-y-auto">
          <div className="rounded-3xl border border-slate-100 bg-white p-7 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold tracking-tight">Create account</h2>
                <p className="mt-1 text-sm text-slate-600">Sign up on the app to get started</p>
              </div>

              <Link to="/login" className="rounded-xl border border-slate-100 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">
                Back
              </Link>
            </div>

            {error && (
              <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <form onSubmit={submit} className="mt-6 space-y-4">
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <label className="text-sm text-slate-700">First name</label>
                  <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                    <input
                      value={firstName}
                      onChange={(e) => setFirstName(e.target.value)}
                      placeholder="Jane"
                      className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                      autoComplete="given-name"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-sm text-slate-700">Last name</label>
                  <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                    <input
                      value={lastName}
                      onChange={(e) => setLastName(e.target.value)}
                      placeholder="Doe"
                      className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                      autoComplete="family-name"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label className="text-sm text-slate-700">Email</label>
                <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                  <Mail size={18} className="text-slate-400" />
                  <input
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@university.edu"
                    className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                    autoComplete="email"
                  />
                </div>
              </div>

              <div>
                <label className="text-sm text-slate-700">Phone</label>
                <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                  <input
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="(555) 555-5555"
                    className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                    autoComplete="tel"
                  />
                </div>
              </div>

              <div>
                <label className="text-sm text-slate-700">Institution name</label>
                <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                  <input
                    value={institutionName}
                    onChange={(e) => setInstitutionName(e.target.value)}
                    placeholder="Institution name"
                    className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                    autoComplete="organization"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <label className="text-sm text-slate-700">City</label>
                  <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                    <input
                      value={institutionCity}
                      onChange={(e) => setInstitutionCity(e.target.value)}
                      placeholder="City"
                      className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                      autoComplete="address-level2"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-sm text-slate-700">ZIP / Postal code</label>
                  <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                    <input
                      value={institutionZip}
                      onChange={(e) => setInstitutionZip(e.target.value)}
                      placeholder="ZIP"
                      className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                      autoComplete="postal-code"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label className="text-sm text-slate-700">Role</label>
                <div className="mt-2">
                  <select value={role} onChange={(e) => setRole(e.target.value)} className="w-full rounded-2xl border border-slate-200 px-3 py-2.5 text-sm text-slate-800">
                    <option value="">Select a role</option>
                    <option>Admissions Officer</option>
                    <option>Evaluator / Reviewer</option>
                    <option>Enrollment Operations</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <label className="text-sm text-slate-700">Password</label>
                      <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                        <Lock size={18} className="text-slate-400" />
                        <input
                          type={showPassword ? 'text' : 'password'}
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          placeholder="Choose a secure password"
                          className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                          autoComplete="new-password"
                        />
                        <button type="button" aria-label={showPassword ? 'Hide password' : 'Show password'} onClick={() => setShowPassword((s) => !s)} className="text-slate-400 hover:text-slate-600">
                          {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                        </button>
                      </div>
                </div>

                <div>
                  <label className="text-sm text-slate-700">Confirm password</label>
                  <div className="mt-2 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
                    <Lock size={18} className="text-slate-400" />
                    <input
                      type={showConfirm ? 'text' : 'password'}
                      value={confirm}
                      onChange={(e) => setConfirm(e.target.value)}
                      placeholder="Repeat password"
                      className="w-full bg-transparent text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                      autoComplete="new-password"
                    />
                    <button type="button" aria-label={showConfirm ? 'Hide password' : 'Show password'} onClick={() => setShowConfirm((s) => !s)} className="text-slate-400 hover:text-slate-600">
                      {showConfirm ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                </div>
              </div>

              <button
                type="submit"
                disabled={isSubmitting || showVerify}
                className={`mt-2 inline-flex w-full items-center justify-center gap-2 rounded-2xl px-5 py-3 text-sm font-semibold text-white ${isSubmitting || showVerify ? 'bg-slate-300 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-500'}`}
              >
                {isSubmitting ? 'Sending...' : 'Create account'} <ArrowRight size={16} />
              </button>

              <div className="flex items-center justify-between pt-1 text-sm">
                <button type="button" className="text-slate-600 hover:text-slate-800" onClick={() => navigate("/login")}>Have an account?</button>
              </div>

              
            </form>

            {showVerify && (
              <div className="mt-4 rounded-2xl border border-slate-100 bg-white p-6">
                <h3 className="text-lg font-semibold">Verify your email</h3>
                <p className="mt-2 text-sm text-slate-700">We sent a verification code to <strong>{email}</strong>. Enter it below to finish creating your account.</p>

                <div className="mt-4 space-y-3">
                  <input
                    value={otpValue}
                    onChange={(e) => setOtpValue(e.target.value)}
                    placeholder="Enter 6-digit code"
                    className="w-full rounded-2xl border border-slate-200 px-3 py-2 text-sm"
                  />

                  <div className="flex gap-2">
                    <button onClick={verifyOtp} disabled={isVerifying} className={`rounded-xl px-4 py-2 text-white ${isVerifying ? 'bg-slate-300 cursor-not-allowed' : 'bg-blue-600'}`}>{isVerifying ? 'Verifying...' : 'Verify code'}</button>
                    <button onClick={resendOtp} disabled={resendCooldown > 0} className="rounded-xl border px-4 py-2">{resendCooldown > 0 ? `Resend (${resendCooldown}s)` : 'Resend code'}</button>
                    <button onClick={() => { setShowVerify(false); setOtpValue(''); }} className="rounded-xl border px-4 py-2">Cancel</button>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="mt-4 text-center text-xs text-slate-500">
            By creating an account you agree to the Terms and Privacy Policy.
          </div>
        </div>
      </div>
    </div>
  );
}
