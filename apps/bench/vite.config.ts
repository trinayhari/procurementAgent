import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // 5173 is @proq/web, 5174 @proq/marketing; the bench owns 5185 (see
  // docs/eval-harness.md §5) and the API's CORS allowlist names that port, so
  // fall over rather than silently drifting to another one.
  server: { port: 5185, strictPort: true },
})
