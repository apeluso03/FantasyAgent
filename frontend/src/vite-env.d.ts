/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  /** "mock" builds a site with only the mock draft simulator (see src/lib/appMode.ts). */
  readonly VITE_APP_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
