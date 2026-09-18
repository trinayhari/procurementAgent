/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BENCH_API_URL?: string
  /** "1" turns on the dev-only fixture adapter — see src/mock.ts. */
  readonly VITE_BENCH_MOCK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
