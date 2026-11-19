import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

const ERROR_MESSAGES: Record<string, string> = {
  domain_not_allowed: "Only @csulb.edu accounts are allowed.",
  token_exchange_failed: "Authentication failed. Please try again.",
  graph_failed: "Could not load your profile from Microsoft. Please try again.",
  invalid_state: "Session expired. Please sign in again.",
  sso_not_configured: "SSO is not configured. Contact your administrator.",
  access_denied: "Access was denied. Please try again.",
  no_access_token: "No access token received. Please try again.",
};

export default function MicrosoftCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { login } = useAuth();
  const [status, setStatus] = useState<"loading" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState("");
  const didRun = useRef(false);

  useEffect(() => {
    if (didRun.current) return;
    didRun.current = true;

    const token = searchParams.get("token");
    const error = searchParams.get("error");

    if (error) {
      const msg = ERROR_MESSAGES[error] ?? "Authentication failed. Please try again.";
      setErrorMsg(msg);
      setStatus("error");
      setTimeout(() => navigate("/login", { replace: true }), 3500);
      return;
    }

    if (!token) {
      setErrorMsg("No token received from Microsoft. Please try again.");
      setStatus("error");
      setTimeout(() => navigate("/login", { replace: true }), 3500);
      return;
    }

    const finish = async () => {
      try {
        await login(token);
        navigate("/app/cloud-folders", { replace: true });
      } catch {
        setErrorMsg("Failed to complete sign-in. Please try again.");
        setStatus("error");
        setTimeout(() => navigate("/login", { replace: true }), 3500);
      }
    };

    void finish();
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="rounded-2xl bg-white shadow-sm border border-slate-100 px-10 py-8 text-center max-w-sm w-full">
        {status === "loading" ? (
          <>
            <div className="mx-auto mb-5 h-9 w-9 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
            <p className="text-sm font-semibold text-slate-800">Completing sign-in…</p>
            <p className="mt-1 text-xs text-slate-500">Setting up your workspace</p>
          </>
        ) : (
          <>
            <div className="mx-auto mb-4 flex h-9 w-9 items-center justify-center rounded-full bg-red-100 text-red-600 text-lg font-bold">!</div>
            <p className="text-sm font-semibold text-red-700">{errorMsg}</p>
            <p className="mt-2 text-xs text-slate-500">Redirecting to sign-in…</p>
          </>
        )}
      </div>
    </div>
  );
}
