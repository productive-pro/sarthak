import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
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
            'marked',
            'remark-gfm',
            'remark-math',
            'rehype-highlight',
            'rehype-katex',
          ],

          // Syntax highlighting + math — loaded on demand
          'vendor-highlight': ['highlight.js'],
          'vendor-katex':     ['katex'],

          // Routing + state — small but separate from app code
          'vendor-infra': ['react-router-dom', 'zustand'],
        },
      },
    },
  },
})
