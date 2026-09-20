// Kept separate from vite.config.ts for the same reason as apps/web: vite 5
// is pinned here while vitest 4 bundles its own newer vite, and sharing one
// defineConfig trips plugin type conflicts between the two copies.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'happy-dom',
    setupFiles: ['./src/testSetup.ts'],
  },
})
