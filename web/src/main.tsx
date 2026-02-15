import { StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { initI18n } from './i18n'

// Loading component while translations load
const LoadingFallback = () => (
  <div style={{ 
    display: 'flex', 
    justifyContent: 'center', 
    alignItems: 'center', 
    height: '100vh',
    background: '#0f1115',
    color: '#fff'
  }}>
    <div className="loading-spinner" />
  </div>
)

// Initialize i18n with dynamic language discovery, then render app
initI18n().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Suspense fallback={<LoadingFallback />}>
        <App />
      </Suspense>
    </StrictMode>,
  )
})
