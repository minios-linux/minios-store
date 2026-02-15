import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Save, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { updateMetaTags } from '@/lib/meta';
import type { SEOConfig } from '@/lib/types';

const DEFAULT_SEO: SEOConfig = {
  // Primary meta tags
  title: 'MiniOS Store - Linux Applications Repository',
  description: 'Official application repository for MiniOS. Browse and install software packages for your MiniOS Linux distribution.',
  keywords: 'MiniOS, Linux, applications, packages, repository, software store',
  author: 'MiniOS Team',
  canonicalUrl: 'https://store.minios.dev',
  
  // Open Graph
  ogImage: '/assets/svg/minios_store_icon.svg',
  ogSiteName: 'MiniOS Store',
  
  // Twitter
  twitterCard: 'summary_large_image',
  twitterImage: '',
  
  // Verification codes
  yandexVerification: '',
  googleVerification: '',
  
  // Analytics
  yandexMetrikaId: '',
  googleAnalyticsId: '',
  
  // JSON-LD structured data
  structuredData: {
    softwareVersion: '',
    ratingValue: '',
    ratingCount: '',
  },
  
  // Sitemap settings
  sitemap: {
    includeExternalLinks: false,
    externalLinks: [],
  },
};

export function SEOManager() {
  const [formData, setFormData] = useState<SEOConfig>(DEFAULT_SEO);
  const [isSaving, setIsSaving] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);

  // Load saved SEO settings
  useEffect(() => {
    const loadSettings = async () => {
      try {
        const res = await fetch('/api/seo/settings');
        if (res.ok) {
          const data = await res.json();
          setFormData({ ...DEFAULT_SEO, ...data });
        }
      } catch (error) {
        console.error('Failed to load SEO settings:', error);
      }
    };
    loadSettings();
  }, []);

  const updateField = (path: string, value: unknown) => {
    const keys = path.split('.');
    setFormData(prev => {
      const updated = { ...prev };
      let current: any = updated;
      
      for (let i = 0; i < keys.length - 1; i++) {
        const key = keys[i];
        if (!current[key]) {
          current[key] = {};
        }
        current[key] = { ...current[key] };
        current = current[key];
      }
      
      current[keys[keys.length - 1]] = value;
      return updated;
    });
    setHasChanges(true);
  };

  const renderField = (path: string, label: string, multiline = false) => {
    const keys = path.split('.');
    let value: any = formData;
    for (const key of keys) {
      value = value?.[key];
    }
    value = value || '';

    return (
      <div className="space-y-1.5">
        <Label>{label}</Label>
        {multiline ? (
          <Textarea
            value={value}
            onChange={(e) => updateField(path, e.target.value)}
            className="min-h-[80px]"
          />
        ) : (
          <Input
            value={value}
            onChange={(e) => updateField(path, e.target.value)}
          />
        )}
      </div>
    );
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const res = await fetch('/api/seo/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      if (res.ok) {
        toast.success('SEO settings saved successfully');
        setHasChanges(false);
        // Apply settings immediately
        updateMetaTags({
          title: formData.title,
          description: formData.description,
          image: formData.ogImage,
          url: formData.canonicalUrl,
          type: 'website',
        });
      } else {
        throw new Error('Failed to save settings');
      }
    } catch (error) {
      console.error('Save error:', error);
      toast.error('Failed to save SEO settings');
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    setFormData(DEFAULT_SEO);
    setHasChanges(true);
    toast.info('Settings reset to defaults');
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-fg-primary mb-2">SEO Settings</h2>
          <p className="text-fg-secondary text-sm">
            Configure meta tags for search engines and social media sharing
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleReset}
            disabled={isSaving}
          >
            <RefreshCw className="w-4 h-4 mr-2" />
            Reset
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={handleSave}
            disabled={!hasChanges || isSaving}
          >
            <Save className="w-4 h-4 mr-2" />
            {isSaving ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>

      {/* Primary Meta Tags */}
      <Card>
        <CardHeader>
          <CardTitle>Meta Tags</CardTitle>
          <CardDescription>Primary SEO meta tags for search engines</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {renderField('title', 'Title')}
          {renderField('description', 'Description', true)}
          {renderField('keywords', 'Keywords')}
          {renderField('author', 'Author')}
          {renderField('canonicalUrl', 'Canonical URL')}
        </CardContent>
      </Card>

      {/* Open Graph */}
      <Card>
        <CardHeader>
          <CardTitle>Open Graph</CardTitle>
          <CardDescription>Social media sharing preview (Facebook, LinkedIn, etc.)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {renderField('ogImage', 'OG Image URL')}
          <p className="text-xs text-muted-foreground">Recommended size: 1200×630px</p>
          {renderField('ogSiteName', 'Site Name')}
          <p className="text-xs text-muted-foreground">og:locale is auto-generated from available translations</p>
        </CardContent>
      </Card>

      {/* Twitter */}
      <Card>
        <CardHeader>
          <CardTitle>Twitter</CardTitle>
          <CardDescription>Twitter card settings</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Card Type</Label>
            <Select
              value={formData.twitterCard || 'summary_large_image'}
              onValueChange={(value) => updateField('twitterCard', value)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="summary">Summary</SelectItem>
                <SelectItem value="summary_large_image">Summary Large Image</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {renderField('twitterImage', 'Twitter Image URL (optional)')}
          <p className="text-xs text-muted-foreground">Falls back to OG Image if empty</p>
        </CardContent>
      </Card>

      {/* Verification & Analytics */}
      <Card>
        <CardHeader>
          <CardTitle>Verification & Analytics</CardTitle>
          <CardDescription>Search engine verification and analytics codes</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Yandex Verification</Label>
              <Input
                value={formData.yandexVerification || ''}
                onChange={(e) => updateField('yandexVerification', e.target.value)}
                placeholder="112ea334e65fa41b"
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Google Verification</Label>
              <Input
                value={formData.googleVerification || ''}
                onChange={(e) => updateField('googleVerification', e.target.value)}
                placeholder="..."
                className="font-mono text-xs"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Yandex Metrika ID</Label>
              <Input
                value={formData.yandexMetrikaId || ''}
                onChange={(e) => updateField('yandexMetrikaId', e.target.value)}
                placeholder="91951521"
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Google Analytics ID</Label>
              <Input
                value={formData.googleAnalyticsId || ''}
                onChange={(e) => updateField('googleAnalyticsId', e.target.value)}
                placeholder="G-XXXXXXXXXX"
                className="font-mono text-xs"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Structured Data */}
      <Card>
        <CardHeader>
          <CardTitle>Structured Data</CardTitle>
          <CardDescription>JSON-LD schema for rich search results</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <Label>Software Version</Label>
              <Input
                value={formData.structuredData?.softwareVersion || ''}
                onChange={(e) => updateField('structuredData.softwareVersion', e.target.value)}
                placeholder="4.0"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Rating Value</Label>
              <Input
                value={formData.structuredData?.ratingValue || ''}
                onChange={(e) => updateField('structuredData.ratingValue', e.target.value)}
                placeholder="4.8"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Rating Count</Label>
              <Input
                value={formData.structuredData?.ratingCount || ''}
                onChange={(e) => updateField('structuredData.ratingCount', e.target.value)}
                placeholder="150"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Sitemap Settings */}
      <Card>
        <CardHeader>
          <CardTitle>Sitemap</CardTitle>
          <CardDescription>External links to include in sitemap.xml</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>External Links</Label>
            <Textarea
              value={(formData.sitemap?.externalLinks || []).join('\n')}
              onChange={(e) => {
                const links = e.target.value.split('\n').filter(l => l.trim());
                setFormData({
                  ...formData,
                  sitemap: {
                    includeExternalLinks: true,
                    externalLinks: links
                  }
                });
                setHasChanges(true);
              }}
              placeholder="https://minios.dev/docs&#10;https://t.me/s/minios_news&#10;https://github.com/minios-linux/minios-store"
              className="font-mono text-xs h-32"
            />
            <p className="text-xs text-muted-foreground">One URL per line</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
