import { mockBackend } from './mockBackend'

export const USE_MOCK_BACKEND = String(import.meta.env.VITE_USE_MOCK_BACKEND ?? 'true') !== 'false'

export const backendClient = mockBackend
