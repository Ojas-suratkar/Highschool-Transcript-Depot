import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { getAcademicTerms } from '@/lib/admissionsApi';
import type { AcademicTerm } from '@/types/admissions';

interface TermContextValue {
  currentTerm: string;
  setCurrentTerm: (termId: string) => void;
  terms: AcademicTerm[];
  isLoading: boolean;
  addTerm: (term: AcademicTerm) => void;
}

const TermContext = createContext<TermContextValue | undefined>(undefined);

export function TermProvider({ children }: { children: ReactNode }) {
  const [currentTerm, setCurrentTerm] = useState<string>('');
  const [terms, setTerms] = useState<AcademicTerm[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const CUSTOM_KEY = 'custom_academic_terms_v1';

  useEffect(() => {
    // Load terms from API
    getAcademicTerms().then((data) => {
      // merge with any locally stored custom terms
      const rawCustom = localStorage.getItem(CUSTOM_KEY);
      const custom: AcademicTerm[] = rawCustom ? JSON.parse(rawCustom) : [];
      const merged = [...data, ...custom];
      setTerms(merged);
      
      // Set current term from API or localStorage
      const savedTerm = localStorage.getItem('currentTerm');
      if (savedTerm) {
        setCurrentTerm(savedTerm);
      } else {
        const current = data.find(t => t.isCurrent);
        if (current) {
          setCurrentTerm(current.id);
        }
      }
      
      setIsLoading(false);
    });
  }, []);

  const handleSetCurrentTerm = (termId: string) => {
    setCurrentTerm(termId);
    localStorage.setItem('currentTerm', termId);
  };

  const addTerm = (term: AcademicTerm) => {
    setTerms((prev) => {
      const next = [...prev, term];
      // persist only the custom terms (those with id starting with 'term-custom')
      const custom = next.filter((t) => t.id.startsWith('term-custom'));
      localStorage.setItem(CUSTOM_KEY, JSON.stringify(custom));
      return next;
    });
  };

  return (
    <TermContext.Provider
      value={{
        currentTerm,
        setCurrentTerm: handleSetCurrentTerm,
        terms,
        isLoading,
        addTerm,
      }}
    >
      {children}
    </TermContext.Provider>
  );
}

export function useTerm() {
  const context = useContext(TermContext);
  if (!context) {
    throw new Error('useTerm must be used within a TermProvider');
  }
  return context;
}

