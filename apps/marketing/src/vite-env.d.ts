/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Where "Request a buyout" / "Talk to us" / "Start a conversation" should
   * point, e.g. a scheduling link (Cal.com, Calendly). When unset the CTAs
   * fall back to a mailto: for the Proq contact inbox (see Landing.tsx).
   */
  readonly VITE_DEMO_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
