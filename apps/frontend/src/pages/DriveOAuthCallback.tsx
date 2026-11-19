import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { apiFetch } from "@/lib/utils";

export default function DriveOAuthCallback() {
  const navigate = useNavigate();
  const location = useLocation();
  const [status, setStatus] = useState("Finishing Google Drive connection...");

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      setStatus("Missing code or state");
      toast.error("Missing code or state");
      return;
    }
    const finish = async () => {
      try {
        await apiFetch(
          "/api/cloud-folder-locations/drive/oauth/callback?" +
            new URLSearchParams({ code, state }).toString()
        );
        toast.success("Google Drive connected");
        navigate("/app/cloud-folders");
      } catch (err: any) {
        toast.error(err?.message || "Failed to complete Drive connection");
        setStatus("Failed to complete Drive connection");
      }
    };
    void finish();
  }, [location.search, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="rounded-2xl bg-white shadow px-6 py-5 text-sm text-slate-700">
        {status}
      </div>
    </div>
  );
}
