/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Where "Request a buyout" / "Talk to us" / "Start a conversation" should
   * point — a scheduling link (Cal.com, Calendly) or a `mailto:`. When unset
   * the CTAs render as inert buttons rather than a guessed address.
   */
  readonly VITE_DEMO_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
