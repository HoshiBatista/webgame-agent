import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, process.cwd(), 'P2P_');
  const preview = new URL(env.P2P_PREVIEW_ORIGIN || 'http://127.0.0.1:8001').origin;
  if (!/^https?:/.test(preview)) throw new Error('Preview origin must use HTTP(S)');
  return {
  plugins: [react()],
  server: {
    headers: { 'Content-Security-Policy': `frame-src ${preview}; object-src 'none'; base-uri 'self'; frame-ancestors 'none'` },
    proxy: { '/api': { target: env.P2P_API_ORIGIN || 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: { sourcemap: false, assetsDir: 'assets', emptyOutDir: true },
};
});
