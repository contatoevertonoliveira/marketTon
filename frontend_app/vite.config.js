import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://localhost:8002',
      '/health': 'http://localhost:8002',
    },
  },
});
