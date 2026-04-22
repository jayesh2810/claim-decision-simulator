import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/sample-claims': 'http://127.0.0.1:8000',
      '/simulate/from-document': 'http://127.0.0.1:8000',
      '/simulate': 'http://127.0.0.1:8000',
    },
  },
});
