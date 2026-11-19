// Ensure structuredClone exists in Node 16 (used by Tailwind/Vite)
// Safe no-op on newer Node where it already exists.
import v8 from 'v8'

if (typeof globalThis.structuredClone !== 'function') {
  globalThis.structuredClone = (value: any) => v8.deserialize(v8.serialize(value))
}
