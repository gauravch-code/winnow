import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Winnow — local-first AI inbox triage',
  description:
    'A local-first Gmail triage agent. Small classifier on your machine handles 80%+ of routing; an LLM sees only the uncertain cases. Try the demo — synthetic data, real classifier, pre-recorded LLM.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
