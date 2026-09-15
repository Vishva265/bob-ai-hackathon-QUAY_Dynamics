import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  envDir:'..',
  plugins: [react()],
  build:{rollupOptions:{output:{manualChunks:{'charts':['recharts']}}}},
  server: { port: 5173, strictPort: true, proxy: Object.fromEntries(['/api','/docs','/openapi.json','/redoc'].map(path=>[path,{target:process.env.API_PROXY_TARGET||'http://127.0.0.1:8000',changeOrigin:true}])) },
});
