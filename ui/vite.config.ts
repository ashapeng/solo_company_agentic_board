import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/members': 'http://127.0.0.1:8000',
      '/deliberate': 'http://127.0.0.1:8000',
      '/sessions': 'http://127.0.0.1:8000',
      '/delegated-tasks': 'http://127.0.0.1:8000',
      '/execution-agents': 'http://127.0.0.1:8000',
      '/execution-units': 'http://127.0.0.1:8000',
      '/evidence-packets': 'http://127.0.0.1:8000',
      '/harness': 'http://127.0.0.1:8000',
      '/sotb': 'http://127.0.0.1:8000',
      '/metrics': 'http://127.0.0.1:8000',
      '/role-gap': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom')) {
            return 'react';
          }
          if (id.includes('node_modules/recharts') || id.includes('node_modules/d3-')) {
            return 'charts';
          }
          if (id.includes('node_modules/motion')) {
            return 'motion';
          }
          if (id.includes('node_modules/lucide-react')) {
            return 'icons';
          }
        },
      },
    },
  },
});
