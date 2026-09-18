import path from 'path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const projectRoot = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig(({ mode }) => {
    return {
      server: {
        port: 8888,
        strictPort: true,
        host: '127.0.0.1',
        watch: {
          ignored: [
            '**/.venv-qlib/**',
            '**/data/**',
            '**/logs/**',
            '**/dist/**',
            '**/__pycache__/**',
          ],
        },
        proxy: {
          '/api': {
            target: 'http://localhost:8880',
            changeOrigin: true,
          },
        },
      },
      plugins: [react()],
      resolve: {
        alias: {
          '@': path.resolve(projectRoot),
        }
      }
    };
});
