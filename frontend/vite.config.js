import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:4848',
        changeOrigin: true,
        // Keep /api prefix — backend expects /api/* routes
      },
    },
  },
  build: {
    // Silence the warning; we handle it with manualChunks below
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          // React core — tiny, loaded first
          'vendor-react': ['react', 'react-dom'],

          // CodeMirror editor (largest single dependency)
          'vendor-codemirror': [
            '@uiw/react-codemirror',
            '@codemirror/lang-markdown',
            '@codemirror/theme-one-dark',
          ],

          // Markdown rendering pipeline
          'vendor-markdown': [
            'react-markdown',
            'remark-gfm',
            'remark-math',
            'rehype-highlight',
            'rehype-katex',
          ],

          // Syntax highlighting + math — loaded on demand
          'vendor-highlight': ['highlight.js'],
          'vendor-katex':     ['katex'],

          // State management
          'vendor-infra': ['zustand'],
          // assistant-ui runtime primitives
          'vendor-assistant-ui': ['@assistant-ui/react', '@assistant-ui/react-markdown'],
        },
      },
    },
  },
})
