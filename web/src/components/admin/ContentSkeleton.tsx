/**
 * ContentSkeleton — loading placeholder for admin manager content areas.
 * Renders 3 skeleton cards matching the reference design from minios.dev.
 */

const ContentSkeleton = () => (
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
);

export default ContentSkeleton;
