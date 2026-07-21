import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Split the charting library into its own vendor chunk. Recharts (+ its
        // d3 dependencies) is the bulk of the bundle; isolating it keeps the app
        // chunk small and stops the single 500 kB+ chunk Vite warns about.
        manualChunks(id) {
          if (id.includes('node_modules/recharts') || id.includes('node_modules/d3')) {
            return 'charts'
          }
        },
      },
    },
  },
})
