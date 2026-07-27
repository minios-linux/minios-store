/**
 * MiniOS Store - Type Definitions
 *
 * Data types for recipes, categories, cart, WebSocket messages,
 * and installation configuration.
 */

// ============================================
// Recipe / Application Types
// ============================================

/** Compression type for squashfs modules */
export type CompressionType = 'zstd' | 'xz' | 'gzip' | 'lzo' | 'lz4';

/** Installation method */
export type InstallMethod = 'apt' | 'script' | 'deb';

/** Installation mode: module (build .sb) or system (direct install) */
export type InstallMode = 'module' | 'system';

/** Module packaging mode: single module for all recipes, or separate module per recipe */
export type PackagingMode = 'single' | 'separate';

/** Module level for live system. 'auto' means all bundles, no prefix. */
export type ModuleLevel = 'auto' | '01' | '02' | '03' | '04' | '05' | '06' | '07' | '08' | '09';

/** A distribution entry with per-distribution architecture list */
export interface DistributionEntry {
  /** Distribution codename (e.g. "bookworm", "trixie") */
  name: string;
  /** Supported architectures for this distribution. If omitted/empty = all architectures. */
  architectures?: string[];
}

/** Distribution filter */
export interface DistributionFilter {
  /** Include only these distribution+architecture combos */
  include?: DistributionEntry[];
  /** Exclude these distribution+architecture combos */
  exclude?: DistributionEntry[];
}

/** A single recipe (application) that can be installed */
export interface Recipe {
  /** Unique recipe identifier (e.g. "firefox", "vlc") */
  id: string;
  /** Display name */
  name: string;
  /** Short description (1-2 sentences) */
  description: string;
  /** Category ID this recipe belongs to */
  categoryId: string;
  /** Icon name from lucide-react icon map, or path to icon image */
  icon: string;
  /** Installation method */
  method: InstallMethod;
  /** Module level for live filesystem (default "05") */
  level: ModuleLevel;
  /** Compression type (default "zstd") */
  compression: CompressionType;

  // Package-based installation (method: "apt")
  /** APT packages to install */
  packages?: string[];

  // Script-based installation (method: "script")
  /** Installation script content (bash) */
  script?: string;

  // Deb-based installation (method: "deb")
  /** URL to .deb package */
  debUrl?: string;

  /** Distribution compatibility filter */
  distributions?: DistributionFilter;
  /** App icon image path (e.g. "/icons/firefox.png") */
  appIcon?: string;
  /** Developer / publisher name */
  developer?: string;
  /** Project homepage URL */
  homepage?: string;
  /** Screenshot image paths (relative to /screenshots/) */
  screenshots?: string[];
  /** Long description / notes */
  longDescription?: string;
  /** Tags for search */
  tags?: string[];
  /** Whether this recipe is enabled (default true) */
  enabled?: boolean;
  /** Sort order within category */
  order?: number;
}

// ============================================
// Category Types
// ============================================

/** A category grouping recipes */
export interface Category {
  /** Unique category ID */
  id: string;
  /** Translation key for display name (e.g. "category.internet") */
  nameKey: string;
  /** Fallback display name (English) */
  name: string;
  /** Icon name from lucide-react */
  icon: string;
  /** Sort order */
  order: number;
  /** Whether this category is visible */
  enabled?: boolean;
}

// ============================================
// Cart Types
// ============================================

/** An item in the installation cart */
export interface CartItem {
  /** Recipe ID */
  recipeId: string;
}

/** Cart state persisted to localStorage */
export interface CartState {
  items: CartItem[];
  /** Last modification timestamp */
  updatedAt: number;
}

// ============================================
// WebSocket Message Types
// ============================================

/** Connection status */
export type ConnectionStatus = 'connected' | 'disconnected' | 'connecting';

/** Messages sent from client to server */
export type ClientMessage =
  | { type: 'install'; recipes: InstallRecipe[]; mode: InstallMode; packaging?: PackagingMode; moduleName?: string }
  | { type: 'cancel' }
  | { type: 'get_status' }
  | { type: 'ping' }
  | { type: 'open_folder'; path: string; user?: string; display?: string };

/** A recipe prepared for installation */
export interface InstallRecipe {
  id: string;
  name: string;
  method: InstallMethod;
  level: ModuleLevel;
  compression: CompressionType;
  packages?: string[];
  script?: string;
  debUrl?: string;
}

/** System information received from backend */
export interface SystemInfo {
  codename: string | null;
  id: string | null;
  name: string | null;
  version_id: string | null;
  arch: string | null;
  is_native: boolean;
}

/** Messages sent from server to client */
export type ServerMessage =
  | { type: 'pong' }
  | { type: 'system_info'; codename: string | null; id: string | null; name: string | null; version_id: string | null; arch: string | null; is_native: boolean }
  | { type: 'install_status'; installing: boolean; current?: number; total?: number; recipeName?: string; step?: string; successful?: string[]; failed?: string[]; outputLines?: string[] }
  | { type: 'install_start'; total: number }
  | { type: 'install_progress'; recipeId: string; recipeName: string; step: string; progress: number; total: number; current: number }
  | { type: 'install_complete'; successful: string[]; failed: string[] }
  | { type: 'install_error'; recipeId?: string; error: string }
  | { type: 'log'; level: 'info' | 'warn' | 'error'; message: string }
  | { type: 'output'; text: string }
  | { type: 'module_location'; directory: string; isFallback: boolean; moduleName?: string };

// ============================================
// Admin Types
// ============================================

/** Default compression types */
export const COMPRESSION_TYPES: { value: CompressionType; label: string }[] = [
  { value: 'zstd', label: 'Zstandard (fast, recommended)' },
  { value: 'xz', label: 'XZ (smallest size)' },
  { value: 'gzip', label: 'Gzip (compatible)' },
  { value: 'lzo', label: 'LZO (fastest)' },
  { value: 'lz4', label: 'LZ4 (very fast)' },
];

// ============================================
// SEO Configuration
// ============================================

/** SEO configuration for the store */
export interface SEOConfig {
  // Primary meta tags
  title: string;           // <title> and og:title
  description: string;     // meta description and og:description
  keywords: string;        // meta keywords
  author: string;          // meta author
  canonicalUrl: string;    // canonical URL (e.g., "https://store.minios.dev")
  
  // Open Graph
  ogImage: string;         // og:image URL (1200x630 recommended)
  ogSiteName: string;      // og:site_name
  // Note: og:locale is auto-generated from available translations
  
  // Twitter
  twitterCard: 'summary' | 'summary_large_image';
  twitterImage?: string;   // twitter:image (defaults to ogImage)
  
  // Verification codes
  yandexVerification?: string;
  googleVerification?: string;
  
  // Analytics
  yandexMetrikaId?: string;
  googleAnalyticsId?: string;
  
  // JSON-LD structured data
  structuredData?: {
    softwareVersion?: string;
    ratingValue?: string;
    ratingCount?: string;
  };
  
  // Sitemap settings
  sitemap?: {
    includeExternalLinks: boolean;
    externalLinks?: string[];
  };
}

// ============================================
// Admin Types
// ============================================

/** Available icon names for icon picker */
export const AVAILABLE_ICONS = [
  'Package', 'PackageOpen', 'ShoppingCart', 'Store', 'Puzzle',
  'Gamepad2', 'Music', 'Video', 'Camera', 'Palette',
  'Wrench', 'Shield', 'Lock', 'BookOpen', 'Star',
  'Heart', 'Users', 'Zap', 'Rocket', 'Gauge',
  'Globe', 'Code', 'Terminal', 'Database', 'Cloud',
  'Cpu', 'HardDrive', 'Monitor', 'Wifi', 'FolderOpen',
  'Download', 'Mail', 'MessageCircle', 'FileText', 'Image',
] as const;
