'use client';

// Theme system (dark/light) — Xynn Command Center.
//
// The theme is applied as a `data-theme` attribute on <html>, which the design
// tokens in globals.css key off. Choice is persisted to localStorage under
// `ea-theme`; on first visit we honour the OS preference. A blocking inline
// script in layout.tsx applies the saved theme before paint to avoid a flash.

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'ea-theme';

type ThemeContextValue = {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

/** Resolve the initial theme from localStorage, then OS preference. */
export function resolveInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark';
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    // ignore
  }
  try {
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
      return 'light';
    }
  } catch {
    // ignore
  }
  return 'dark';
}

/** Apply a theme to <html> and persist it. */
export function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // ignore
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>('dark');

  // Sync React state with whatever the blocking script already applied.
  useEffect(() => {
    const current = document.documentElement.getAttribute('data-theme');
    const initial: Theme = current === 'light' || current === 'dark' ? current : resolveInitialTheme();
    setThemeState(initial);
    applyTheme(initial);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    applyTheme(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState(prev => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      return next;
    });
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    // Safe fallback so a component used outside the provider never crashes.
    return {
      theme: 'dark',
      setTheme: applyTheme,
      toggleTheme: () => applyTheme(resolveInitialTheme() === 'dark' ? 'light' : 'dark'),
    };
  }
  return ctx;
}
