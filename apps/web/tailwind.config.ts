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
      },
    },
  },
  plugins: [],
};
export default config;
