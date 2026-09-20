import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Xynn — Trading Command Center',
  description: 'Xynn Autonomous Trading Command Center',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Default tema = dark (PRD §78). Atribut data-theme dibaca token di
  // globals.css; bahasa UI = English (PRD §107).
  return (
    <html lang="en" data-theme="dark">
      <body className={inter.className}>{children}</body>
    </html>
  );
}
