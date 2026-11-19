// CommonJS polyfill to add crypto.getRandomValues for Node 16 tooling
const crypto = require('crypto');

if (typeof crypto.getRandomValues !== 'function' && crypto.webcrypto?.getRandomValues) {
  crypto.getRandomValues = (...args) => crypto.webcrypto.getRandomValues(...args);
}

if (!global.crypto && crypto.webcrypto) {
  global.crypto = crypto.webcrypto;
} else if (global.crypto && typeof global.crypto.getRandomValues !== 'function' && crypto.webcrypto?.getRandomValues) {
  global.crypto.getRandomValues = crypto.webcrypto.getRandomValues.bind(crypto.webcrypto);
}

// Add structuredClone for Node 16 (Tailwind/Vite expect it)
try {
  const { structuredClone } = require('util');
  if (typeof global.structuredClone !== 'function' && typeof structuredClone === 'function') {
    global.structuredClone = structuredClone;
  }
} catch (_) {
  // ignore
}
