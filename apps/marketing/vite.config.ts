import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // 5173 belongs to @proq/web; run both side by side without a port fight.
  server: { port: 5174 },
})
