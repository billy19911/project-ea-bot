import type { Metadata } from 'next';
import { Space_Grotesk, JetBrains_Mono } from 'next/font/google';
import { ThemeProvider } from '../lib/theme';
import './globals.css';

// Display/label face: Space Grotesk — a tighter, more technical grotesque than
// Inter; gives the command center a distinct instrument-panel character.
const display = Space_Grotesk({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-display',
  display: 'swap',
});

// Data face: JetBrains Mono — tabular figures for prices, PnL and ticket IDs.
const mono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Xynn — Trading Command Center',
  description: 'Xynn Autonomous Trading Command Center',
};

// Blocking script: apply the saved theme (or OS preference) before first paint
// so there is no flash of the wrong theme. Keep this tiny and dependency-free.
const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem('ea-theme');if(t!=='light'&&t!=='dark'){t=window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';}document.documentElement.setAttribute('data-theme',t);document.documentElement.style.colorScheme=t;}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Default theme = dark; user may switch to light. The attribute is set by the
  // inline script below before hydration; ThemeProvider syncs to it.
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className={`${display.variable} ${mono.variable}`}>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
