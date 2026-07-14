import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Separate from vite.config.ts (which only needs to know about dev-server
// proxying and the production build) - test running is a distinct concern
// with its own settings (jsdom environment, setup file).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})
