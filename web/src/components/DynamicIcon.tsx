import React from 'react';
import { iconMap, FallbackIcon } from '@/lib/icon-map';

interface DynamicIconProps {
  name: string;
  className?: string;
  size?: number;
}

/**
 * Dynamic icon component that renders Lucide icons by name.
 * Uses a curated icon map instead of importing all icons,
 * enabling proper tree-shaking (~500KB bundle savings).
 */
export const DynamicIcon: React.FC<DynamicIconProps> = ({ name, className, size }) => {
  const IconComponent = iconMap[name];
  if (!IconComponent) {
    return <FallbackIcon className={className} size={size} />;
  }
  return <IconComponent className={className} size={size} />;
};

export default DynamicIcon;
