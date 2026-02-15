import { useState, useEffect, lazy, Suspense } from 'react';
import { ThemeProvider } from './contexts/ThemeContext';
import { LanguageProvider } from './contexts/LanguageContext';
import StorePage from './pages/StorePage';
import { AdminPanelSkeleton } from './components/admin/AdminPanelSkeleton';
import { Settings } from 'lucide-react';
import './index.css';

// Lazy-load admin panel
const AdminPanel = lazy(() => import('./components/admin/AdminPanel').then(m => ({ default: m.AdminPanel })));

// Check if running on localhost
function isDev(): boolean {
  const h = window.location.hostname;
  return h === 'localhost' || h === '127.0.0.1' || h === '::1';
}

function App() {
  const [isLocalhost] = useState(() => isDev());
  const [showAdmin, setShowAdmin] = useState(false);

  useEffect(() => {
    if ('scrollRestoration' in window.history) {
      window.history.scrollRestoration = 'manual';
    }
  }, []);

  return (
    <LanguageProvider>
      <ThemeProvider>
        {showAdmin ? (
          <Suspense fallback={<AdminPanelSkeleton />}>
            <AdminPanel onClose={() => setShowAdmin(false)} />
          </Suspense>
        ) : (
          <StorePage isDevMode={isLocalhost} />
        )}

        {/* Admin Toggle - only visible on localhost */}
        {isLocalhost && (
          <button
            className="admin-toggle-btn"
            onClick={() => setShowAdmin(!showAdmin)}
            title={showAdmin ? 'Back to store' : 'Admin Panel (localhost only)'}
          >
            <Settings size={24} />
          </button>
        )}
      </ThemeProvider>
    </LanguageProvider>
  );
}

export default App;
