import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./styles/index.css";

// Token injection via URL removed. Authentication must use the app's
// /auth/request-otp and /auth/verify-otp flows so all users are validated.

createRoot(document.getElementById("root")!).render(<App />);