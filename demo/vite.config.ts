import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: import.meta.dirname,
  base: '/winnow/',
  plugins: [react()],
  build: {
    outDir: '../docs',
    emptyOutDir: false,
  },
});
