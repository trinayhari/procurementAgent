// Kept separate from vite.config.ts on purpose: this app pins vite 5 while
// vitest 4 bundles its own newer vite, and sharing one defineConfig trips
// plugin type conflicts between the two copies. If you change vite.config.ts
// (aliases, plugins), mirror anything test-relevant here.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'happy-dom',
  },
})
