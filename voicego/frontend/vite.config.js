import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';

// HTTPS (self-signed) + host:true so the mic works in a SECURE CONTEXT when the
// app is opened from a phone / another device over the LAN (http + IP is blocked
// by the browser for getUserMedia / SpeechRecognition).
export default defineConfig({
  plugins: [react(), basicSsl()],
  server: {
    host: true,           // expose on the LAN (0.0.0.0)
    port: 5173,
    https: true,
    proxy: {
      // Browser talks HTTPS to Vite; Vite forwards to the HTTP backends
      // server-side, so there is no mixed-content issue.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/socket.io': {
        target: 'http://localhost:3001',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
