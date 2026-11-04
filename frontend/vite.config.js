import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({ mode }) => {
  // API_PROXY_TARGET may come from the shell or from frontend/.env.local (not exposed to the browser).
  const target = process.env.API_PROXY_TARGET || loadEnv(mode, process.cwd(), '').API_PROXY_TARGET || 'http://127.0.0.1:5000';
  return { plugins: [react()], server: { proxy: { '/api': {target,changeOrigin:false}, '/socket.io': {target,ws:true} } } };
});
