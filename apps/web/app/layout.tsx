import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Winnow — demo',
  description: 'Local-first AI inbox triage. Demo mode: synthetic data.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
