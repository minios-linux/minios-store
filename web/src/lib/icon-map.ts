/**
 * Icon map for DynamicIcon component
 * 
 * Curated subset of lucide-react icons used in the store application.
 * Allows tree-shaking instead of importing entire library (~500KB savings).
 */

import {
  // Navigation & UI
  Menu,
  X,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Search,
  Settings,
  ExternalLink,
  GripVertical,
  Filter,
  Home,
  
  // Actions
  Download,
  Upload,
  Save,
  Copy,
  Trash2,
  Pencil,
  Plus,
  RefreshCw,
  Undo2,
  
  // Status & Feedback
  Check,
  AlertCircle,
  AlertTriangle,
  Loader2,
  
  // Theme & Display
  Sun,
  Moon,
  Languages,
  Globe,
  
  // Content & Media
  Image,
  FileText,
  Tag,
  
  // Technology & Hardware
  Cpu,
  HardDrive,
  Monitor,
  Wifi,
  
  // Development
  Code,
  Terminal,
  Database,
  Cloud,
  Github,
  
  // Store-specific
  Package,
  PackageOpen,
  ShoppingCart,
  Store,
  Puzzle,
  Gamepad2,
  Music,
  Video,
  Camera,
  Palette,
  Wrench,
  Shield,
  Lock,
  BookOpen,
  Star,
  Heart,
  Users,
  Zap,
  Rocket,
  Gauge,
  FolderOpen,
  ArrowLeft,
  ArrowRight,
  Sparkles,
  MessageCircle,
  Mail,
  FlaskConical,
  
  // Fallback
  HelpCircle,
} from 'lucide-react';

import type { LucideIcon } from 'lucide-react';

/**
 * Map of icon names to icon components.
 * Used by DynamicIcon for runtime icon rendering by name.
 */
export const iconMap: Record<string, LucideIcon> = {
  // Navigation & UI
  Menu,
  X,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Search,
  Settings,
  ExternalLink,
  GripVertical,
  Filter,
  Home,
  
  // Actions
  Download,
  Upload,
  Save,
  Copy,
  Trash2,
  Pencil,
  Plus,
  RefreshCw,
  Undo2,
  
  // Status & Feedback
  Check,
  AlertCircle,
  AlertTriangle,
  Loader2,
  
  // Theme & Display
  Sun,
  Moon,
  Languages,
  Globe,
  
  // Content & Media
  Image,
  FileText,
  Tag,
  
  // Technology & Hardware
  Cpu,
  HardDrive,
  Monitor,
  Wifi,
  
  // Development
  Code,
  Terminal,
  Database,
  Cloud,
  Github,
  
  // Store-specific
  Package,
  PackageOpen,
  ShoppingCart,
  Store,
  Puzzle,
  Gamepad2,
  Music,
  Video,
  Camera,
  Palette,
  Wrench,
  Shield,
  Lock,
  BookOpen,
  Star,
  Heart,
  Users,
  Zap,
  Rocket,
  Gauge,
  FolderOpen,
  ArrowLeft,
  ArrowRight,
  Sparkles,
  MessageCircle,
  Mail,
  FlaskConical,
  
  // Fallback
  HelpCircle,
};

// Re-export HelpCircle as fallback icon
export { HelpCircle as FallbackIcon };

// Type for valid icon names
export type IconName = keyof typeof iconMap;
