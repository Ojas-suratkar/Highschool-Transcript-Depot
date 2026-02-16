import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./styles/index.css";

// Dev helper: allow injecting an access token via ?token=... in the URL.
// This is safe for local development and is ignored in production builds.
if (import.meta.env.DEV) {
	try {
		const url = new URL(window.location.href);
		const token = url.searchParams.get('token');
		if (token) {
			localStorage.setItem('th_access_token', token);
			// remove token from URL to avoid leaking it in browser history
			url.searchParams.delete('token');
			window.history.replaceState({}, document.title, url.toString());
		}
	} catch (e) {
		// ignore
	}
}

createRoot(document.getElementById("root")!).render(<App />);