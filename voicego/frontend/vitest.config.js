// Vitest config, separate from vite.config.js on purpose: the app config loads
// basicSsl + react plugins for the dev server, which tests don't need. `vite build`
// never reads this file, so the Docker build is unaffected.
//
// Environment is plain `node` (no jsdom): each test file stubs only the browser
// globals it needs (vi.stubGlobal) and then imports the module dynamically.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    testTimeout: 15000,
  },
});
