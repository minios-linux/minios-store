/**
 * Skeleton loading state for AdminPanel
 * Shows placeholder structure while the actual admin panel loads
 */

export function AdminPanelSkeleton() {
  return (
    <div className="admin-panel">
      {/* Top Header Skeleton */}
      <header className="admin-top-header">
        <div className="admin-top-header-inner">
          <div className="admin-logo">
            <div className="skeleton-box" style={{ width: 28, height: 28, borderRadius: 6 }} />
          </div>

          {/* Section tabs skeleton */}
          <nav className="admin-top-nav">
            {[1, 2, 3].map(i => (
              <div key={i} className="admin-skeleton-tab">
                <div className="skeleton-box" style={{ width: 16, height: 16, borderRadius: 4 }} />
                <div className="skeleton-box" style={{ width: 50 + (i % 3) * 20, height: 14, borderRadius: 4 }} />
              </div>
            ))}
          </nav>

          <div className="admin-header-actions">
            <div className="skeleton-box" style={{ width: 36, height: 36, borderRadius: 8 }} />
            <div className="skeleton-box" style={{ width: 36, height: 36, borderRadius: 8 }} />
          </div>
        </div>
      </header>

      {/* Main content skeleton */}
      <main className="admin-main-content">
        <div className="container">
          <div className="admin-skeleton-content">
            {[1, 2, 3].map(i => (
              <div key={i} className="admin-skeleton-card">
                <div className="admin-skeleton-card-header">
                  <div className="skeleton-box" style={{ width: 120 + i * 30, height: 20, borderRadius: 4 }} />
                  <div className="skeleton-box" style={{ width: 180, height: 14, borderRadius: 4, opacity: 0.5 }} />
                </div>
                <div className="admin-skeleton-card-body">
                  {[1, 2, 3].map(j => (
                    <div key={j} className="admin-skeleton-field">
                      <div className="skeleton-box" style={{ width: 80, height: 14, borderRadius: 4 }} />
                      <div className="skeleton-box" style={{ width: '100%', height: 40, borderRadius: 6 }} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
