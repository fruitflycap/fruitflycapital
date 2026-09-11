import { defineConfig } from 'vite'

export default defineConfig({
  base: './',
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
  build: {
    rollupOptions: {
      input: {
        main: 'index.html',
        portfolio: 'portfolio/index.html',
        about: 'about/index.html',
      },
      output: {
        manualChunks: {
          three: ['three'],
          postprocessing: ['postprocessing'],
        },
      },
    },
  },
})
