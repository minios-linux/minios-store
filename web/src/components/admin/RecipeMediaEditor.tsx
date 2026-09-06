import { useState } from 'react';
import { Download, Image as ImageIcon, Trash2, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { useTranslation } from '@/contexts/LanguageContext';
import type { RecipeMediaSource } from '@/lib/types';

interface RecipeMediaEditorProps {
  recipeId: string;
  iconSources?: RecipeMediaSource[] | null;
  screenshotSources?: RecipeMediaSource[] | null;
  iconPreview?: string;
  screenshotPreviews?: string[];
  onIconSourcesChange: (sources: RecipeMediaSource[] | null) => void;
  onScreenshotSourcesChange: (sources: RecipeMediaSource[] | null) => void;
}

interface MediaResponse {
  success?: boolean;
  source?: RecipeMediaSource;
  error?: string;
}
function readFileAsBase64(file: File): Promise<{ base64: string; preview: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.onload = () => {
      const preview = String(reader.result || '');
      const comma = preview.indexOf(',');
      resolve({ base64: comma >= 0 ? preview.slice(comma + 1) : preview, preview });
    };
    reader.readAsDataURL(file);
  });
}

function sourceLabel(source: RecipeMediaSource): string {
  return source.file || source.url || source.cached || '';
}

const RecipeMediaEditor: React.FC<RecipeMediaEditorProps> = ({
  recipeId,
  iconSources,
  screenshotSources,
  iconPreview,
  screenshotPreviews = [],
  onIconSourcesChange,
  onScreenshotSourcesChange,
}) => {
  const { t } = useTranslation();
  const [iconUrl, setIconUrl] = useState('');
  const [screenshotUrl, setScreenshotUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [localPreviews, setLocalPreviews] = useState<Record<string, string>>({});

  const storeMedia = async (
    kind: 'icon' | 'screenshot',
    slot: number,
    payload: { url?: string; dataBase64?: string },
  ): Promise<RecipeMediaSource | null> => {
    if (!recipeId.trim()) {
      toast.error(t('Recipe ID is required'));
      return null;
    }
    setBusy(true);
    try {
      const res = await fetch('/api/recipes/media', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipeId, kind, slot, ...payload }),
      });
      const data = await res.json().catch(() => ({})) as MediaResponse;
      if (!res.ok || !data.source) {
        toast.error(data.error || t('Failed to save media'));
        return null;
      }
      return data.source;
    } catch {
      toast.error(t('Failed to save media'));
      return null;
    } finally {
      setBusy(false);
    }
  };
  const screenshots = screenshotSources || [];
  const currentIcon = iconSources?.[0];

  const nextScreenshotSlot = (): number => {
    const used = new Set<number>();
    screenshots.forEach((source, index) => {
      const match = source.file?.match(/screenshot-(\d+)\./);
      used.add(match ? Number(match[1]) - 1 : index);
    });
    for (let slot = 0; slot < 3; slot += 1) {
      if (!used.has(slot)) return slot;
    }
    return -1;
  };

  const previewFor = (source: RecipeMediaSource | undefined, fallback?: string) => {
    if (!source) return fallback;
    if (source.file && localPreviews[source.file]) return localPreviews[source.file];
    if (source.url?.startsWith('http')) return source.url;
    return fallback;
  };

  const saveIconUrl = async () => {
    const url = iconUrl.trim();
    if (!url) return;
    const source = await storeMedia('icon', 0, { url });
    if (source) {
      onIconSourcesChange([source]);
      setIconUrl('');
    }
  };
  const saveIconFile = async (file?: File) => {
    if (!file) return;
    if (file.type !== 'image/png' && !file.name.toLowerCase().endsWith('.png')) {
      toast.error('PNG');
      return;
    }
    try {
      const { base64, preview } = await readFileAsBase64(file);
      const source = await storeMedia('icon', 0, { dataBase64: base64 });
      if (source) {
        if (source.file) setLocalPreviews(prev => ({ ...prev, [source.file!]: preview }));
        onIconSourcesChange([source]);
      }
    } catch {
      toast.error(t('Failed to save media'));
    }
  };

  const saveScreenshotUrl = async () => {
    const url = screenshotUrl.trim();
    if (!url || screenshots.length >= 3) return;
    const slot = nextScreenshotSlot();
    if (slot < 0) return;
    const source = await storeMedia('screenshot', slot, { url });
    if (source) {
      onScreenshotSourcesChange([...screenshots, source]);
      setScreenshotUrl('');
    }
  };
  const saveScreenshotFile = async (file?: File) => {
    if (!file || screenshots.length >= 3) return;
    const slot = nextScreenshotSlot();
    if (slot < 0) return;
    try {
      const { base64, preview } = await readFileAsBase64(file);
      const source = await storeMedia('screenshot', slot, { dataBase64: base64 });
      if (source) {
        if (source.file) setLocalPreviews(prev => ({ ...prev, [source.file!]: preview }));
        onScreenshotSourcesChange([...screenshots, source]);
      }
    } catch {
      toast.error(t('Failed to save media'));
    }
  };

  const removeScreenshot = (index: number) => {
    const next = screenshots.filter((_, i) => i !== index);
    onScreenshotSourcesChange(next.length > 0 ? next : null);
  };

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Label>{t('Icon')}</Label>
        <div className="flex items-start gap-3">
          <div className="h-20 w-20 shrink-0 overflow-hidden rounded-lg border bg-muted/20 flex items-center justify-center">
            {previewFor(currentIcon, iconPreview) ? (
              <img src={previewFor(currentIcon, iconPreview)} alt="" className="h-full w-full object-contain" />
            ) : (
              <ImageIcon className="h-8 w-8 opacity-30" />
            )}
          </div>
          <div className="min-w-0 flex-1 space-y-2">
            {currentIcon && (
              <div className="flex items-start gap-2">
                <span className="min-w-0 flex-1 break-all text-xs text-muted-foreground">
                  {sourceLabel(currentIcon)}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => onIconSourcesChange(null)}
                  title={t('Remove')}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            )}
            <div className="flex gap-2">
              <Input
                value={iconUrl}
                onChange={e => setIconUrl(e.target.value)}
                placeholder="https://…/icon.png"
                disabled={busy}
              />
              <Button type="button" variant="outline" onClick={saveIconUrl} disabled={busy || !iconUrl.trim()}>
                <Download className="h-4 w-4" />
                URL
              </Button>
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 text-sm font-medium hover:bg-accent disabled:pointer-events-none">
                <Upload className="h-4 w-4" />
                {t('Add')}
                <input
                  type="file"
                  accept="image/png,.png"
                  className="hidden"
                  disabled={busy}
                  onChange={e => {
                    void saveIconFile(e.target.files?.[0]);
                    e.currentTarget.value = '';
                  }}
                />
              </label>
            </div>
            <p className="text-xs text-muted-foreground">PNG</p>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <Label>{t('Screenshots')}</Label>
          <span className="text-xs text-muted-foreground">{screenshots.length}/3</span>
        </div>
        {screenshots.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-3">
            {screenshots.map((source, index) => {
              const preview = previewFor(source, screenshotPreviews[index]);
              return (
                <div key={`${sourceLabel(source)}-${index}`} className="min-w-0 rounded-lg border p-2">
                  <div className="mb-2 aspect-video overflow-hidden rounded-md bg-muted/20 flex items-center justify-center">
                    {preview ? (
                      <img src={preview} alt="" className="h-full w-full object-contain" />
                    ) : (
                      <ImageIcon className="h-8 w-8 opacity-30" />
                    )}
                  </div>
                  <div className="flex items-start gap-1">
                    <span className="min-w-0 flex-1 break-all text-[11px] text-muted-foreground">
                      {sourceLabel(source)}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => removeScreenshot(index)}
                      title={t('Remove')}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {screenshots.length < 3 && (
          <div className="flex gap-2">
            <Input
              value={screenshotUrl}
              onChange={e => setScreenshotUrl(e.target.value)}
              placeholder="https://…/screenshot.png"
              disabled={busy}
            />
            <Button
              type="button"
              variant="outline"
              onClick={saveScreenshotUrl}
              disabled={busy || !screenshotUrl.trim()}
            >
              <Download className="h-4 w-4" />
              URL
            </Button>
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 text-sm font-medium hover:bg-accent">
              <Upload className="h-4 w-4" />
              {t('Add')}
              <input
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp,.png,.jpg,.jpeg,.gif,.webp"
                className="hidden"
                disabled={busy}
                onChange={e => {
                  void saveScreenshotFile(e.target.files?.[0]);
                  e.currentTarget.value = '';
                }}
              />
            </label>
          </div>
        )}
      </div>
    </div>
  );
};

export default RecipeMediaEditor;
