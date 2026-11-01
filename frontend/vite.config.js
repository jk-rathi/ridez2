import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
const target = process.env.API_PROXY_TARGET || 'http://127.0.0.1:5000';
export default defineConfig({ plugins: [react()], server: { proxy: { '/api': {target,changeOrigin:false}, '/socket.io': {target,ws:true} } } });
