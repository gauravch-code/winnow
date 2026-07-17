import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        lane: {
          needs: '#f59e0b',
          info: '#3b82f6',
          hidden: '#6b7280',
        },
        winnow: {
          bg: '#0a0e17',
          panel: '#111827',
          accent: '#34d399',
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};
export default config;
