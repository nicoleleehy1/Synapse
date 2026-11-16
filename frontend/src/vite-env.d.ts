/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute API origin for split deployments, e.g. https://synapse-api.fly.dev */
  readonly VITE_API_URL?: string
}
