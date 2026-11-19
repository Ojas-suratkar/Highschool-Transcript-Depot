import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';

// ================================
// Types
// ================================

export interface Institution {
  id: number;
  institution_name: string;
  city?: string | null;
  state?: string | null;
  zip_code?: string | null;
}

export interface User {
  id: string;  // UUID
  email: string;
  phone?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  role?: string | null;
  institution_id?: number | null;
  institution?: Institution | null;
  is_verified: boolean;
}

interface AuthContextType {
  user: User | null;
  institution: Institution | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  login: (token: string, userId?: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  updateUserLocal: (partial: Partial<User>) => void;
  updateProfile: (partial: Partial<User>) => Promise<void>;
  lastIssuedAtMs: number | null;
}

// ================================
// Context
// ================================

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Storage key for JWT token
const TOKEN_KEY = 'th_access_token';
const USER_KEY = 'th_user'; // cached profile so refresh renders instantly
const LAST_ACTIVITY_KEY = 'th_last_activity';
const SESSION_IDLE_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes of inactivity
const SESSION_CHECK_INTERVAL_MS = 30 * 1000; // check every 30s

// ================================
// Provider Component
// ================================

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tokenExpiry, setTokenExpiry] = useState<number | null>(null);
  const [lastIssuedAtMs, setLastIssuedAtMs] = useState<number | null>(null);

  const parseTokenMeta = useCallback((token: string): { expMs: number | null; iatMs: number | null } => {
    try {
      const payload = JSON.parse(atob(token.split('.')[1] || ''));
      const expMs = payload?.exp ? payload.exp * 1000 : null;
      const iatMs = payload?.iat ? payload.iat * 1000 : null;
      return { expMs, iatMs };
    } catch {
      return { expMs: null, iatMs: null };
    }
  }, []);

  // Fetch user profile from /api/auth/me
  const fetchUserProfile = useCallback(async (token: string): Promise<User | null> => {
    try {
      const response = await fetch('/api/auth/me', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        if (response.status === 401) {
          // Token is genuinely invalid/expired — clear and sign out.
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem(USER_KEY);
          return null;
        }
        // Transient failure (cold start, 5xx, network) — DON'T sign out.
        throw new Error('Failed to fetch user profile');
      }

      try {
        const userData: User = await response.json();
        try { localStorage.setItem(USER_KEY, JSON.stringify(userData)); } catch { /* ignore */ }
        return userData;
      } catch {
        return null;
      }
    } catch (err) {
      console.error('Error fetching user profile:', err);
      return null;
    }
  }, []);

  // Initialize auth state on mount — render instantly from the cached profile,
  // then validate the token in the background so a refresh never shows a long
  // buffer and a transient /auth/me failure never logs the user out.
  useEffect(() => {
    const initAuth = async () => {
      const token = localStorage.getItem(TOKEN_KEY);
      if (!token) { setIsLoading(false); return; }

      const meta = parseTokenMeta(token);
      // Already expired -> clear and bail (no network call needed).
      if (meta.expMs && meta.expMs < Date.now()) {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        setIsLoading(false);
        return;
      }
      setTokenExpiry(meta.expMs);
      setLastIssuedAtMs(meta.iatMs);

      const cachedRaw = localStorage.getItem(USER_KEY);
      if (cachedRaw) {
        // Optimistic: show the app immediately, validate in the background.
        try { setUser(JSON.parse(cachedRaw)); } catch { /* ignore */ }
        setIsLoading(false);
        const fresh = await fetchUserProfile(token);
        if (fresh) setUser(fresh);
        else if (!localStorage.getItem(TOKEN_KEY)) setUser(null); // 401 cleared it
        return;
      }

      // No cached profile -> must wait for it once.
      const userData = await fetchUserProfile(token);
      if (userData) setUser(userData);
      setIsLoading(false);
    };

    initAuth();
  }, [fetchUserProfile]);

  // Login - store token and fetch user profile
  const login = useCallback(async (token: string, _userId?: string) => {
    setIsLoading(true);
    setError(null);
    
    try {
      localStorage.setItem(TOKEN_KEY, token);
      // Also set a same-site cookie so browser requests without explicit
      // Authorization headers can still authenticate (for fetches that include credentials).
      try {
        document.cookie = `access_token=${token}; path=/; max-age=${60*60*24}; samesite=lax`;
      } catch (err) {
        // ignore in non-browser environments
      }
      const meta = parseTokenMeta(token);
      setTokenExpiry(meta.expMs);
      setLastIssuedAtMs(meta.iatMs);
      localStorage.setItem(LAST_ACTIVITY_KEY, Date.now().toString());
      
      const userData = await fetchUserProfile(token);
      if (userData) {
        setUser(userData);
      } else {
        throw new Error('Failed to fetch user profile after login');
      }
    } catch (err: any) {
      setError(err.message || 'Login failed');
      localStorage.removeItem(TOKEN_KEY);
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, [fetchUserProfile]);

  // Logout - clear token and user state
  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(LAST_ACTIVITY_KEY);
    setUser(null);
    setError(null);
    setTokenExpiry(null);
    setLastIssuedAtMs(null);
  }, []);

  // Refresh user profile
  const refreshUser = useCallback(async () => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setUser(null);
      return;
    }

    setIsLoading(true);
    const userData = await fetchUserProfile(token);
    if (userData) {
      setUser(userData);
    } else {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(LAST_ACTIVITY_KEY);
      setUser(null);
    }
    setIsLoading(false);
  }, [fetchUserProfile]);

  // Lightweight local update (UI only; no persistence)
  const updateUserLocal = useCallback((partial: Partial<User>) => {
    setUser((prev) => (prev ? { ...prev, ...partial } : prev));
  }, []);

  // Persist editable profile fields to the backend, then update state + cache
  // so the change survives a hard refresh.
  const updateProfile = useCallback(async (partial: Partial<User>) => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) throw new Error('Not authenticated');

    const response = await fetch('/api/auth/me', {
      method: 'PATCH',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        first_name: partial.first_name,
        last_name: partial.last_name,
        phone: partial.phone,
        role: partial.role,
      }),
    });

    if (!response.ok) {
      throw new Error('Failed to update profile');
    }

    const updated: User = await response.json();
    setUser(updated);
    try { localStorage.setItem(USER_KEY, JSON.stringify(updated)); } catch { /* ignore */ }
  }, []);

  // Session watchdog: idle timeout + token expiry; syncs across tabs
  useEffect(() => {
    const markActivity = () => {
      localStorage.setItem(LAST_ACTIVITY_KEY, Date.now().toString());
    };
    const storageListener = (e: StorageEvent) => {
      if (e.key === TOKEN_KEY && !e.newValue) {
        setUser(null);
        setTokenExpiry(null);
      }
    };
    ['click', 'keydown', 'mousemove', 'touchstart', 'scroll'].forEach((evt) =>
      window.addEventListener(evt, markActivity, { passive: true })
    );
    window.addEventListener('storage', storageListener);
    // seed activity if missing
    if (!localStorage.getItem(LAST_ACTIVITY_KEY)) {
      markActivity();
    }
    const interval = setInterval(() => {
      const token = localStorage.getItem(TOKEN_KEY);
      if (!token) return;
      const meta = parseTokenMeta(token);
      const expMs = tokenExpiry ?? meta.expMs;
      const lastActivity = parseInt(localStorage.getItem(LAST_ACTIVITY_KEY) || '0', 10);
      const now = Date.now();
      const idleTooLong = lastActivity > 0 && now - lastActivity > SESSION_IDLE_TIMEOUT_MS;
      const expired = expMs !== null && now > expMs;
      if (idleTooLong || expired) {
        logout();
      }
    }, SESSION_CHECK_INTERVAL_MS);
    return () => {
      ['click', 'keydown', 'mousemove', 'touchstart', 'scroll'].forEach((evt) =>
        window.removeEventListener(evt, markActivity)
      );
      window.removeEventListener('storage', storageListener);
      clearInterval(interval);
    };
  }, [logout, parseTokenMeta, tokenExpiry]);

  // Derived state
  const isAuthenticated = !!user;
  const institution = user?.institution || null;

  const value: AuthContextType = {
    user,
    institution,
    isAuthenticated,
    isLoading,
    error,
    login,
    logout,
    refreshUser,
    updateUserLocal,
    updateProfile,
    lastIssuedAtMs,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

// ================================
// Hook
// ================================

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

// ================================
// Utility Functions
// ================================

/**
 * Get the current JWT token from localStorage
 */
export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Check if user is authenticated (has valid token)
 */
export function hasAccessToken(): boolean {
  return !!localStorage.getItem(TOKEN_KEY);
}
