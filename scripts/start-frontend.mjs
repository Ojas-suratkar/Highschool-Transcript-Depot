#!/usr/bin/env node
// Programmatically start Vite dev server with explicit root to avoid CLI parsing issues
import { createServer } from 'vite';

async function start() {
  const server = await createServer({
    root: './apps/frontend',
    server: {
      host: true,
      port: 5173,
      strictPort: false,
    },
  });

  await server.listen();
  const info = server.config.server;
  console.log(`Vite dev server started at http://localhost:${info.port}`);
}

start().catch((err) => {
  console.error('Failed to start Vite:', err);
  process.exit(1);
});
