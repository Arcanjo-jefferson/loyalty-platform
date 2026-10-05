import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Optimize all Auth entry points together before login; dependency discovery
  // must not trigger a development reload in the middle of a Cognito challenge.
  optimizeDeps: { include: ['aws-amplify', 'aws-amplify/auth', 'aws-amplify/auth/cognito', 'aws-amplify/utils'] },
})
