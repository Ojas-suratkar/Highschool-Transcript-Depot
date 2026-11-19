import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";

import { listTerms, deleteTerm } from "@/lib/api/SemesterTerm";
import type { AcademicTerm } from "@/types/admissions";
import { useAuth } from "@/contexts/AuthContext";
import { emitTermDeleted } from "@/lib/notify";

interface TermContextValue {
  currentTerm: string;
  setCurrentTerm: (termId: string) => void;
  terms: AcademicTerm[];
  isLoading: boolean;
  addTerm: (term: AcademicTerm) => void;
  removeTerm: (termId: string) => Promise<void>;
  refreshTerms: () => Promise<void>;
}

const TermContext = createContext<TermContextValue | undefined>(undefined);

const TERM_ORDER: Record<string, number> = {
  spring: 0,
  summer: 1,
  fall: 2,
  winter: 3,
};

function normalizeTerm(term: any): AcademicTerm {
  const inferredTerm =
    typeof term.term === "string"
      ? term.term.toLowerCase()
      : String(term.term_name || "")
          .split(/\s+/)[0]
          ?.toLowerCase();

  const yearMatch =
    typeof term.year === "number"
      ? term.year
      : parseInt(
          (term.term_name || "").match(/\d{4}/)?.[0] ?? "",
          10,
        ) || 0;

  const termName =
    term.term_name && typeof term.term_name === "string"
      ? term.term_name.charAt(0).toUpperCase() + term.term_name.slice(1)
      : term.term_name;

  return {
    ...term,
    id: String(term.id),
    term: inferredTerm as AcademicTerm["term"],
    term_name: termName,
    year: yearMatch,
    isCurrent: Boolean(term.isCurrent ?? term.is_current),
  };
}

function sortTerms(terms: AcademicTerm[]): AcademicTerm[] {
  return [...terms].sort((a, b) => {
    if (a.year !== b.year) return b.year - a.year;

    const orderA =
      TERM_ORDER[a.term?.toLowerCase?.() ?? ""] ?? 99;
    const orderB =
      TERM_ORDER[b.term?.toLowerCase?.() ?? ""] ?? 99;

    if (orderA !== orderB) return orderA - orderB;

    return (a.term_name || "").localeCompare(b.term_name || "");
  });
}

const CACHED_TERMS_KEY = "cachedTerms";

function readCachedTerms(): AcademicTerm[] {
  try {
    const raw = localStorage.getItem(CACHED_TERMS_KEY);
    return raw ? (JSON.parse(raw) as AcademicTerm[]) : [];
  } catch {
    return [];
  }
}

export function TermProvider({ children }: { children: ReactNode }) {
  const { user, isLoading: authLoading } = useAuth();

  // Seed from localStorage so a hard refresh has the term list + selection
  // immediately (no waiting on listTerms before any page can fetch its data).
  const [terms, setTerms] = useState<AcademicTerm[]>(() =>
    readCachedTerms(),
  );

  const [currentTerm, setCurrentTermState] = useState(
    () => localStorage.getItem("currentTerm") || "",
  );

  const [isLoading, setIsLoading] = useState(
    () => readCachedTerms().length === 0,
  );

  useEffect(() => {
    if (authLoading) return;
    void refreshTerms();
  }, [authLoading, user?.institution_id, user?.institution?.id]);

  const refreshTerms = async (): Promise<void> => {
    const institutionId =
      user?.institution?.id ?? user?.institution_id;

    if (!institutionId) {
      setTerms([]);
      setCurrentTermState("");
      setIsLoading(false);
      localStorage.removeItem("currentTerm");
      localStorage.removeItem(CACHED_TERMS_KEY);
      return;
    }

    // Only show the loading state when we have nothing cached to render.
    if (terms.length === 0) {
      setIsLoading(true);
    }

    try {
      const data = await listTerms(institutionId);

      const unique = Array.from(
        new Map(data.map((term) => [term.id, term])).values(),
      );

      const normalized = unique.map(normalizeTerm);
      const ordered = sortTerms(normalized);

      setTerms(ordered);

      try {
        localStorage.setItem(
          CACHED_TERMS_KEY,
          JSON.stringify(ordered),
        );
      } catch {
        // Ignore cache write failures.
      }

      const savedTerm = localStorage.getItem("currentTerm");
      const savedExists = savedTerm
        ? ordered.some((term) => term.id === savedTerm)
        : false;

      if (savedExists && savedTerm) {
        setCurrentTermState(savedTerm);
      } else if (ordered.length > 0) {
        const active = ordered.find((term) => term.isCurrent);
        const initial = active ?? ordered[0];

        setCurrentTermState(initial.id);
        localStorage.setItem("currentTerm", initial.id);
      } else {
        setCurrentTermState("");
        localStorage.removeItem("currentTerm");
      }
    } catch (err) {
      console.error("Failed to load terms:", err);
      setTerms([]);
      setCurrentTermState("");
    } finally {
      setIsLoading(false);
    }
  };

  const setCurrentTerm = (termId: string) => {
    setCurrentTermState(termId);
    localStorage.setItem("currentTerm", termId);
  };

  const addTerm = (term: AcademicTerm) => {
    const normalized = normalizeTerm(term);

    setTerms((prev) => {
      const withoutDuplicate = prev.filter(
        (existing) => existing.id !== normalized.id,
      );
      const next = sortTerms([normalized, ...withoutDuplicate]);

      try {
        localStorage.setItem(CACHED_TERMS_KEY, JSON.stringify(next));
      } catch {
        // Ignore cache write failures.
      }

      return next;
    });

    // Creating a term immediately scopes the whole workspace to that term.
    setCurrentTerm(normalized.id);
  };

  const removeTerm = async (termId: string): Promise<void> => {
    const deleted = terms.find((term) => term.id === termId);

    await deleteTerm(termId);

    // Purge term-scoped state (notably the activity log, keyed by term name) so a
    // recreated term with the same name doesn't inherit old notifications.
    emitTermDeleted({ termId, termName: deleted?.term_name });

    const remaining = sortTerms(terms.filter((term) => term.id !== termId));
    setTerms(remaining);

    try {
      localStorage.setItem(
        CACHED_TERMS_KEY,
        JSON.stringify(remaining),
      );
    } catch {
      // Ignore cache write failures.
    }

    if (currentTerm === termId) {
      if (remaining.length > 0) {
        // Go to the newest remaining term.
        setCurrentTerm(remaining[0].id);
      } else {
        setCurrentTermState("");
        localStorage.removeItem("currentTerm");
      }
    }
  };

  return (
    <TermContext.Provider
      value={{
        currentTerm,
        setCurrentTerm,
        terms,
        isLoading,
        addTerm,
        removeTerm,
        refreshTerms,
      }}
    >
      {children}
    </TermContext.Provider>
  );
}

export function useTerm() {
  const context = useContext(TermContext);

  if (!context) {
    throw new Error("useTerm must be used within a TermProvider");
  }

  return context;
}
