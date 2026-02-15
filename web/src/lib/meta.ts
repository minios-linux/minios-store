/**
 * Utility functions for updating meta tags dynamically in SPA
 */

export interface MetaTags {
  title?: string;
  description?: string;
  image?: string;
  url?: string;
  type?: 'website' | 'article';
  author?: string;
  publishedTime?: string;
  modifiedTime?: string;
  tags?: string[];
}

/**
 * Update document meta tags for SEO and social sharing
 * This is essential for SPA where meta tags need to be updated client-side
 */
export function updateMetaTags(tags: MetaTags): void {
  const baseUrl = 'https://store.minios.dev';
  
  // Update title
  if (tags.title) {
    document.title = tags.title;
    updateMetaTag('property', 'og:title', tags.title);
    updateMetaTag('name', 'twitter:title', tags.title);
  }
  
  // Update description
  if (tags.description) {
    updateMetaTag('name', 'description', tags.description);
    updateMetaTag('property', 'og:description', tags.description);
    updateMetaTag('name', 'twitter:description', tags.description);
  }
  
  // Update image
  if (tags.image) {
    const imageUrl = tags.image.startsWith('http') ? tags.image : `${baseUrl}${tags.image}`;
    updateMetaTag('property', 'og:image', imageUrl);
    updateMetaTag('name', 'twitter:image', imageUrl);
  }
  
  // Update URL
  if (tags.url) {
    const fullUrl = tags.url.startsWith('http') ? tags.url : `${baseUrl}${tags.url}`;
    updateMetaTag('property', 'og:url', fullUrl);
    updateMetaTag('name', 'twitter:url', fullUrl);
    updateLinkTag('canonical', fullUrl);
  }
  
  // Update type
  if (tags.type) {
    updateMetaTag('property', 'og:type', tags.type);
  }
  
  // Update article-specific tags
  if (tags.type === 'article') {
    if (tags.author) {
      updateMetaTag('property', 'article:author', tags.author);
    }
    if (tags.publishedTime) {
      updateMetaTag('property', 'article:published_time', tags.publishedTime);
    }
    if (tags.modifiedTime) {
      updateMetaTag('property', 'article:modified_time', tags.modifiedTime);
    }
    if (tags.tags && tags.tags.length > 0) {
      // Remove existing article:tag meta tags
      document.querySelectorAll('meta[property="article:tag"]').forEach(el => el.remove());
      
      // Add new tags
      tags.tags.forEach(tag => {
        const meta = document.createElement('meta');
        meta.setAttribute('property', 'article:tag');
        meta.setAttribute('content', tag);
        document.head.appendChild(meta);
      });
    }
  }
}

/**
 * Reset meta tags to default (homepage) values
 */
export function resetMetaTags(): void {
  updateMetaTags({
    title: 'MiniOS Store - Linux Applications Repository',
    description: 'Official application repository for MiniOS. Browse and install software packages for your MiniOS Linux distribution.',
    image: '/assets/svg/minios_store_icon.svg',
    url: '/',
    type: 'website',
  });
}

/**
 * Helper to update or create a meta tag
 */
function updateMetaTag(attr: 'name' | 'property', value: string, content: string): void {
  let meta = document.querySelector(`meta[${attr}="${value}"]`);
  
  if (!meta) {
    meta = document.createElement('meta');
    meta.setAttribute(attr, value);
    document.head.appendChild(meta);
  }
  
  meta.setAttribute('content', content);
}

/**
 * Helper to update or create a link tag
 */
function updateLinkTag(rel: string, href: string): void {
  let link = document.querySelector(`link[rel="${rel}"]`) as HTMLLinkElement;
  
  if (!link) {
    link = document.createElement('link');
    link.setAttribute('rel', rel);
    document.head.appendChild(link);
  }
  
  link.setAttribute('href', href);
}
