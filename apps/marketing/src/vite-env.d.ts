/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Where "Book a demo" / "Talk to the founders" should point — a scheduling
   * link (Cal.com, Calendly) or a `mailto:`. When unset the CTAs render as the
   * inert buttons the design specifies, rather than a guessed address.
   */
  readonly VITE_DEMO_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
