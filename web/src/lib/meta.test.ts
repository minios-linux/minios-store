import { describe, it, expect, beforeEach } from 'vitest';
import { updateMetaTags, resetMetaTags } from './meta';

function metaContent(attr: string, value: string): string | null {
  const el = document.querySelector(`meta[${attr}="${value}"]`);
  return el ? el.getAttribute('content') : null;
}

beforeEach(() => {
  document.head.innerHTML = '';
  document.title = '';
});

describe('updateMetaTags', () => {
  it('sets document title and og/twitter title', () => {
    updateMetaTags({ title: 'Hello World' });
    expect(document.title).toBe('Hello World');
    expect(metaContent('property', 'og:title')).toBe('Hello World');
    expect(metaContent('name', 'twitter:title')).toBe('Hello World');
  });

  it('sets description meta tags', () => {
    updateMetaTags({ description: 'A description' });
    expect(metaContent('name', 'description')).toBe('A description');
    expect(metaContent('property', 'og:description')).toBe('A description');
    expect(metaContent('name', 'twitter:description')).toBe('A description');
  });

  it('prefixes a relative image with the base url', () => {
    updateMetaTags({ image: '/assets/x.png' });
    expect(metaContent('property', 'og:image')).toBe(
      'https://store.minios.dev/assets/x.png',
    );
  });

  it('keeps an absolute image url unchanged', () => {
    updateMetaTags({ image: 'https://cdn.example/x.png' });
    expect(metaContent('property', 'og:image')).toBe('https://cdn.example/x.png');
  });

  it('creates a canonical link for the url', () => {
    updateMetaTags({ url: '/apps/vlc' });
    const link = document.querySelector('link[rel="canonical"]') as HTMLLinkElement;
    expect(link).toBeTruthy();
    expect(link.getAttribute('href')).toBe('https://store.minios.dev/apps/vlc');
  });

  it('adds article:tag meta tags for article type', () => {
    updateMetaTags({ type: 'article', tags: ['linux', 'store'] });
    const tags = Array.from(
      document.querySelectorAll('meta[property="article:tag"]'),
    ).map((m) => m.getAttribute('content'));
    expect(tags).toEqual(['linux', 'store']);
  });

  it('replaces article tags instead of accumulating them', () => {
    updateMetaTags({ type: 'article', tags: ['a'] });
    updateMetaTags({ type: 'article', tags: ['b', 'c'] });
    const tags = Array.from(
      document.querySelectorAll('meta[property="article:tag"]'),
    ).map((m) => m.getAttribute('content'));
    expect(tags).toEqual(['b', 'c']);
  });

  it('updates an existing tag instead of duplicating it', () => {
    updateMetaTags({ title: 'First' });
    updateMetaTags({ title: 'Second' });
    expect(document.querySelectorAll('meta[property="og:title"]').length).toBe(1);
    expect(metaContent('property', 'og:title')).toBe('Second');
  });
});

describe('resetMetaTags', () => {
  it('applies homepage defaults', () => {
    resetMetaTags();
    expect(document.title).toContain('MiniOS Store');
    expect(metaContent('name', 'description')).toBeTruthy();
    expect(metaContent('property', 'og:type')).toBe('website');
  });
});
