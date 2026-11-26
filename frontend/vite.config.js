import { defineConfig } from 'vite'
import { coverageConfigDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // COPY_PUBLIC_DIR=0 leaves public/ out of dist: the deploy script uploads what the site needs from it (the wall
    // tiles) and never the 4 GB of source photos in public/pictures.
    copyPublicDir: process.env.COPY_PUBLIC_DIR !== '0',
  },
  server: {
    port: Number(process.env.PORT) || 5173,
    proxy: {
      '/api': process.env.API_URL || 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    clearMocks: true,
    setupFiles: './src/test/setup.js',
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{js,jsx}'],
      // main.jsx is the DOM bootstrap; there is no behavior to unit-test in it.
      exclude: [...coverageConfigDefaults.exclude, 'src/main.jsx'],
      thresholds: {
        lines: 95,
        functions: 95,
        branches: 95,
        statements: 95,
      },
    },
  },
})
