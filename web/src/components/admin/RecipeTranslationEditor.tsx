import { useState, useEffect, useCallback, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { SearchableSelect } from '@/components/ui/searchable-select';
import { Badge } from '@/components/ui/badge';
import { Check, AlertTriangle, Sparkles, RefreshCw, Languages, Package, StopCircle, Trash2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { toast } from 'sonner';
import { useTranslation } from '@/contexts/LanguageContext';
import { loadParallelSettings, parallelLimit, type ParallelTranslationTask } from '@/utils/parallelTranslation';

type TranslationStatus = 'missing' | 'ok';

interface RecipeTranslation {
  id: string;
  name: string;
  enabled: boolean;
  translations: Record<string, TranslationStatus>;
}

interface LanguageMeta {
  code: string;
  name: string;
  flag: string;
}

interface RecipeTranslationEditorProps {
  onTranslateRecipe: (
    sourceContent: string,
    targetLang: string,
    onProgress?: (progress: string) => void
  ) => Promise<string>;
}

export function RecipeTranslationEditor({
  onTranslateRecipe
}: RecipeTranslationEditorProps) {
  const { t } = useTranslation();
  const [recipes, setRecipes] = useState<RecipeTranslation[]>([]);
  const [languages, setLanguages] = useState<LanguageMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedLang, setSelectedLang] = useState<string>('');
  const [translatingId, setTranslatingId] = useState<string | null>(null);
  const [translatingAll, setTranslatingAll] = useState(false);
  const [translationProgress, setTranslationProgress] = useState('');

  // Structured progress for progress bar
  type RecipeTranslationProgress = {
    completed: number;
    total: number;
    activeLanguages: Array<{ code: string; name: string }>;
  };
  const [structuredProgress, setStructuredProgress] = useState<RecipeTranslationProgress | null>(null);

  // Cancellation flag for stopping translations
  const cancelTranslationRef = useRef(false);

  // Load recipe translation status
  const loadTranslations = useCallback(async () => {
    try {
      const response = await fetch('/api/recipes/translations');
      if (!response.ok) throw new Error('Failed to fetch');
      const data = await response.json();
      setRecipes(data.recipes || []);
      setLanguages(data.languages || []);
      if (!selectedLang && data.languages?.length > 0) {
        setSelectedLang(data.languages[0].code);
      }
    } catch (error) {
      console.error('Failed to load recipe translations:', error);
      toast.error(t('Failed to load recipe translations'));
    } finally {
      setLoading(false);
    }
  }, [selectedLang, t]);

  useEffect(() => {
    loadTranslations();
  }, [loadTranslations]);

  // Translate a single recipe
  const handleTranslateRecipe = async (recipeId: string) => {
    if (!selectedLang) {
      toast.error(t('Please select a target language'));
      return;
    }

    setTranslatingId(recipeId);
    setTranslationProgress(t('Loading recipe...'));

    try {
      // Fetch the original recipe
      const recipeResponse = await fetch(`/api/recipes/${recipeId}`);
      if (!recipeResponse.ok) throw new Error('Failed to fetch recipe');
      const recipe = await recipeResponse.json();

      // Build content to translate (name, description, longDescription)
      const sourceContent = JSON.stringify({
        name: recipe.name,
        description: recipe.description,
        ...(recipe.longDescription ? { longDescription: recipe.longDescription } : {})
      }, null, 2);

      const targetLangName = languages.find(l => l.code === selectedLang)?.name || selectedLang;

      setTranslationProgress(t('Translating to {{lang}}...').replace('{{lang}}', targetLangName));

      // Use the parent's translation function
      const translatedContent = await onTranslateRecipe(
        sourceContent,
        targetLangName,
        setTranslationProgress
      );

      // Parse the translated JSON
      let translated: { name?: string; description?: string; longDescription?: string };
      try {
        let jsonStr = translatedContent.trim();
        console.log('[Recipe Translate] Raw AI response length:', jsonStr.length);
        console.log('[Recipe Translate] Raw AI response start:', jsonStr.substring(0, 300));
        console.log('[Recipe Translate] Raw AI response end:', jsonStr.substring(Math.max(0, jsonStr.length - 200)));

        // Only extract from markdown code blocks if response starts with one
        if (jsonStr.startsWith('```')) {
          const codeBlockMatch = jsonStr.match(/^```(?:json)?\s*([\s\S]*?)\s*```/);
          if (codeBlockMatch) {
            jsonStr = codeBlockMatch[1].trim();
            console.log('[Recipe Translate] Extracted from code block');
          }
        }

        try {
          translated = JSON.parse(jsonStr);
          console.log('[Recipe Translate] JSON parse succeeded');
        } catch (directParseError) {
          console.log('[Recipe Translate] Direct parse failed:', (directParseError as Error).message);
          
          const jsonMatch = jsonStr.match(/^\s*(\{[\s\S]*\})\s*$/);
          if (jsonMatch) {
            try {
              translated = JSON.parse(jsonMatch[1]);
              console.log('[Recipe Translate] Regex extraction succeeded');
            } catch (regexParseError) {
              console.error('[Recipe Translate] Regex parse failed:', (regexParseError as Error).message);
              throw regexParseError;
            }
          } else {
            if (jsonStr.startsWith('{') && !jsonStr.endsWith('}')) {
              console.error('[Recipe Translate] Response appears truncated');
              throw new Error('AI response appears truncated. Try increasing timeout.');
            }
            console.error('[Recipe Translate] No JSON pattern found in response');
            throw new Error('No JSON found in response');
          }
        }
      } catch (parseError) {
        console.error('Failed to parse translation:', parseError);
        console.error('Full response was:', translatedContent);
        toast.error(t('Failed to parse translation response'));
        return;
      }

      setTranslationProgress(t('Saving translation...'));

      // Save the translated recipe content
      const saveResponse = await fetch('/api/recipes/translations/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          recipeId,
          lang: selectedLang,
          translations: {
            name: translated.name || recipe.name,
            description: translated.description || recipe.description,
            ...(translated.longDescription ? { longDescription: translated.longDescription } : {})
          }
        })
      });

      if (!saveResponse.ok) throw new Error('Failed to save translation');

      toast.success(t('Recipe translated to {{lang}}').replace('{{lang}}', targetLangName));
      loadTranslations();
    } catch (error) {
      console.error('Translation error:', error);
      toast.error(t('Translation failed: {{error}}').replace('{{error}}', (error as Error).message));
    } finally {
      setTranslatingId(null);
      setTranslationProgress('');
    }
  };

  // Stop translation
  const handleStopTranslation = () => {
    cancelTranslationRef.current = true;
    toast.info(t('Stopping translation...'));
  };

  // Delete translations for current language
  const handleClearCurrentLanguage = async () => {
    if (!selectedLang) {
      toast.error(t('Please select a target language'));
      return;
    }

    if (!confirm(t('Clear all recipe translations for selected language?'))) {
      return;
    }

    try {
      const response = await fetch(`/api/recipes/translations/language/${selectedLang}`, {
        method: 'DELETE'
      });

      if (!response.ok) throw new Error('Failed to delete translations');

      toast.success(t('Translations cleared'));
      loadTranslations();
    } catch (error) {
      console.error('Failed to clear language:', error);
      toast.error(t('Failed to delete translations'));
    }
  };

  // Delete all translations for all languages
  const handleClearAllTranslations = async () => {
    if (!confirm(t('Clear all recipe translations for all languages?'))) {
      return;
    }

    try {
      const response = await fetch('/api/recipes/translations', {
        method: 'DELETE'
      });

      if (!response.ok) throw new Error('Failed to delete all translations');

      toast.success(t('All recipe translations cleared'));
      loadTranslations();
    } catch (error) {
      console.error('Failed to clear all translations:', error);
      toast.error(t('Failed to delete translations'));
    }
  };

  // Translate all missing recipes for selected language
  const handleTranslateAll = async () => {
    if (!selectedLang) {
      toast.error(t('Please select a target language'));
      return;
    }

    const missingRecipes = recipes.filter(r => r.translations[selectedLang] !== 'ok' && r.enabled !== false);
    if (missingRecipes.length === 0) {
      toast.info(t('All recipes are already translated'));
      return;
    }

    cancelTranslationRef.current = false;

    setTranslatingAll(true);
    const targetLangName = languages.find(l => l.code === selectedLang)?.name || selectedLang;
    let successCount = 0;
    let failCount = 0;

    const settings = loadParallelSettings();

    try {
      const tasks: ParallelTranslationTask<string>[] = missingRecipes.map(recipe => ({
        id: recipe.id,
        execute: async () => {
          // Fetch the original recipe
          const recipeResponse = await fetch(`/api/recipes/${recipe.id}`);
          if (!recipeResponse.ok) throw new Error('Failed to fetch recipe');
          const fullRecipe = await recipeResponse.json();

          // Build content to translate
          const sourceContent = JSON.stringify({
            name: fullRecipe.name,
            description: fullRecipe.description,
            ...(fullRecipe.longDescription ? { longDescription: fullRecipe.longDescription } : {})
          }, null, 2);

          // Translate
          const translatedContent = await onTranslateRecipe(sourceContent, targetLangName);

          // Parse
          let translated: { name?: string; description?: string; longDescription?: string };
          let jsonStr = translatedContent.trim();

          if (jsonStr.startsWith('```')) {
            const codeBlockMatch = jsonStr.match(/^```(?:json)?\s*([\s\S]*?)\s*```/);
            if (codeBlockMatch) {
              jsonStr = codeBlockMatch[1].trim();
            }
          }

          try {
            translated = JSON.parse(jsonStr);
          } catch {
            const jsonMatch = jsonStr.match(/^\s*(\{[\s\S]*\})\s*$/);
            if (jsonMatch) {
              translated = JSON.parse(jsonMatch[1]);
            } else {
              throw new Error('No JSON found');
            }
          }

          // Save
          await fetch('/api/recipes/translations/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              recipeId: recipe.id,
              lang: selectedLang,
              translations: {
                name: translated.name || fullRecipe.name,
                description: translated.description || fullRecipe.description,
                ...(translated.longDescription ? { longDescription: translated.longDescription } : {})
              }
            })
          });

          return recipe.id;
        }
      }));

      // Progress callback
      const onProgress = (completed: number) => {
        setTranslationProgress(
          `${targetLangName}: ${completed}/${tasks.length} ${t('recipes')} (${Math.round((completed / tasks.length) * 100)}%)`
        );
        setStructuredProgress({
          completed,
          total: tasks.length,
          activeLanguages: [{ code: selectedLang, name: targetLangName }]
        });
      };

      // Execute with parallelization
      const results = await parallelLimit(
        tasks,
        settings.mode === 'sequential' ? 1 : settings.maxConcurrent,
        onProgress,
        cancelTranslationRef,
        undefined,
        settings.requestDelay
      );

      successCount = results.filter(r => r.success).length;
      failCount = results.filter(r => !r.success).length;

    } catch (error) {
      console.error('[Recipe Translate] Fatal error:', error);
      toast.error(`Translation failed: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setTranslatingAll(false);
      setTranslationProgress('');
      setStructuredProgress(null);
      loadTranslations();

      if (failCount === 0 && successCount > 0) {
        toast.success(t('Translated {{count}} recipes').replace('{{count}}', String(successCount)));
      } else if (failCount > 0) {
        toast.warning(t('Translated {{success}}, failed {{fail}}')
          .replace('{{success}}', String(successCount))
          .replace('{{fail}}', String(failCount)));
      }
    }
  };

  // Translate all recipes to ALL languages
  const handleTranslateAllLanguages = async () => {
    const enabledRecipes = recipes.filter(r => r.enabled !== false);
    if (enabledRecipes.length === 0) {
      toast.info(t('No recipes to translate'));
      return;
    }

    cancelTranslationRef.current = false;

    setTranslatingAll(true);
    let totalSuccess = 0;
    let totalFail = 0;

    const settings = loadParallelSettings();

    try {
      // Build all tasks: for each language, for each missing recipe
      const allTasks: ParallelTranslationTask<{ lang: string; id: string }>[] = [];

      for (const lang of languages) {
        const missingForLang = enabledRecipes.filter(r => r.translations[lang.code] !== 'ok');

        for (const recipe of missingForLang) {
          allTasks.push({
            id: `${lang.code}-${recipe.id}`,
            execute: async () => {
              // Fetch original recipe
              const recipeResponse = await fetch(`/api/recipes/${recipe.id}`);
              if (!recipeResponse.ok) throw new Error('Failed to fetch recipe');
              const fullRecipe = await recipeResponse.json();

              // Build source content
              const sourceContent = JSON.stringify({
                name: fullRecipe.name,
                description: fullRecipe.description,
                ...(fullRecipe.longDescription ? { longDescription: fullRecipe.longDescription } : {})
              }, null, 2);

              // Translate
              const translatedContent = await onTranslateRecipe(sourceContent, lang.name);

              // Parse
              let translated: { name?: string; description?: string; longDescription?: string };
              let jsonStr = translatedContent.trim();

              if (jsonStr.startsWith('```')) {
                const codeBlockMatch = jsonStr.match(/^```(?:json)?\s*([\s\S]*?)\s*```/);
                if (codeBlockMatch) jsonStr = codeBlockMatch[1].trim();
              }

              try {
                translated = JSON.parse(jsonStr);
              } catch {
                const jsonMatch = jsonStr.match(/^\s*(\{[\s\S]*\})\s*$/);
                if (jsonMatch) {
                  translated = JSON.parse(jsonMatch[1]);
                } else {
                  throw new Error('No JSON found');
                }
              }

              // Save
              await fetch('/api/recipes/translations/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  recipeId: recipe.id,
                  lang: lang.code,
                  translations: {
                    name: translated.name || fullRecipe.name,
                    description: translated.description || fullRecipe.description,
                    ...(translated.longDescription ? { longDescription: translated.longDescription } : {})
                  }
                })
              });

              return { lang: lang.code, id: recipe.id };
            }
          });
        }
      }

      if (allTasks.length === 0) {
        toast.info(t('All recipes are already translated'));
        return;
      }

      // Progress callback
      const onProgress = (completed: number, active: Array<{ lang?: string }>) => {
        const activeLangs = active.map(a => a.lang?.toUpperCase()).filter(Boolean).join(', ');
        setTranslationProgress(
          `${completed}/${allTasks.length} ${t('recipes')} (${Math.round((completed / allTasks.length) * 100)}%)${activeLangs ? ` • ${activeLangs}` : ''}`
        );
        setStructuredProgress({
          completed,
          total: allTasks.length,
          activeLanguages: active
            .filter(a => a.lang)
            .map(a => {
              const langMeta = languages.find(l => l.code === a.lang);
              return { code: a.lang!, name: langMeta?.name || a.lang! };
            })
        });
      };

      // Execute with parallelization
      const results = await parallelLimit(
        allTasks,
        settings.mode === 'sequential' ? 1 : settings.maxConcurrent,
        onProgress,
        cancelTranslationRef,
        undefined,
        settings.requestDelay
      );

      totalSuccess = results.filter(r => r.success).length;
      totalFail = results.filter(r => !r.success).length;

    } catch (error) {
      console.error('[Recipe Translate All] Fatal error:', error);
      toast.error(`Translation failed: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setTranslatingAll(false);
      setTranslationProgress('');
      setStructuredProgress(null);
      loadTranslations();

      if (totalFail === 0 && totalSuccess > 0) {
        toast.success(t('Translated {{count}} recipes').replace('{{count}}', String(totalSuccess)));
      } else if (totalFail > 0) {
        toast.warning(t('Translated {{success}}, failed {{fail}}')
          .replace('{{success}}', String(totalSuccess))
          .replace('{{fail}}', String(totalFail)));
      }
    }
  };

  // Count translations for selected language
  const getStatusCounts = useCallback(() => {
    const enabled = recipes.filter(r => r.enabled !== false);
    let ok = 0, missing = 0;
    for (const r of enabled) {
      const status = r.translations[selectedLang];
      if (status === 'ok') ok++;
      else missing++;
    }
    return { ok, missing, total: enabled.length };
  }, [recipes, selectedLang]);

  const statusCounts = getStatusCounts();
  const totalEnabled = statusCounts.total;
  const translatedCount = statusCounts.ok;
  const missingCount = statusCounts.missing;

  // Calculate per-language stats for dropdown
  const getLanguageStats = useCallback((langCode: string) => {
    const enabled = recipes.filter(r => r.enabled !== false);
    let ok = 0;
    for (const r of enabled) {
      const status = r.translations[langCode];
      if (status === 'ok') ok++;
    }
    return { translated: ok, total: enabled.length };
  }, [recipes]);

  // Translation skeleton component
  const TranslationSkeleton = () => (
    <div className="admin-skeleton-content">
      <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
        <div className="skeleton-box" style={{ width: 256, height: 40, borderRadius: 6 }} />
        <div className="skeleton-box" style={{ width: 120, height: 40, borderRadius: 6 }} />
      </div>
      <div className="admin-skeleton-card">
        <div className="admin-skeleton-card-body">
          {[1, 2, 3, 4, 5].map(i => (
            <div key={i} style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
              <div className="skeleton-box" style={{ width: '40%', height: 20, borderRadius: 4 }} />
              <div className="skeleton-box" style={{ width: 80, height: 24, borderRadius: 12 }} />
              <div className="skeleton-box" style={{ width: 100, height: 32, borderRadius: 6 }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  if (recipes.length === 0 && !loading) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <Package className="w-12 h-12 mx-auto mb-4 opacity-50" />
        <p>{t('No recipes to translate')}</p>
        <p className="text-sm mt-2">{t('Create some recipes first in the Recipes section')}</p>
      </div>
    );
  }

  return (
    <AnimatePresence mode="wait">
      {loading ? (
        <motion.div
          key="skeleton"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <TranslationSkeleton />
        </motion.div>
      ) : (
        <motion.div
          key="content"
          className="space-y-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
      {/* Language selector and actions */}
      <div className="flex items-center gap-4 flex-wrap">
        <SearchableSelect
          value={selectedLang}
          onChange={setSelectedLang}
          options={languages.map(lang => {
            const stats = getLanguageStats(lang.code);
            const pct = stats.total > 0 ? Math.round((stats.translated / stats.total) * 100) : 0;
            return {
              value: lang.code,
              label: `${lang.flag} ${lang.name} (${pct}%)`,
            };
          })}
          placeholder={t('Select target language')}
          searchPlaceholder={t('Search languages...')}
          className="w-64"
        />

        <Button
          variant="outline"
          size="icon"
          onClick={loadTranslations}
          title={t('Refresh')}
        >
          <RefreshCw className="w-4 h-4" />
        </Button>

        <div className="ml-auto text-sm text-muted-foreground">
          {translatedCount}/{totalEnabled} {t('translated')}
          {missingCount > 0 && (
            <span className="text-yellow-500 ml-2">({missingCount} {t('missing')})</span>
          )}
        </div>
      </div>

      {/* Translate buttons */}
      <div className="flex items-center gap-4 flex-wrap">
        {selectedLang && missingCount > 0 && (
          <button
            type="button"
            onClick={handleTranslateAll}
            disabled={translatingAll || translatingId !== null}
            className="ai-translate-btn"
          >
            <Sparkles className="w-4 h-4" />
            {translatingAll
              ? translationProgress
              : `${t('Translate')} ${missingCount} ${t('missing recipes')}`}
          </button>
        )}

        <button
          type="button"
          onClick={handleTranslateAllLanguages}
          disabled={translatingAll || translatingId !== null}
          className="ai-translate-all-btn"
        >
          <Languages className="w-4 h-4" />
          {t('Translate All Languages')}
        </button>

        {translatingAll && (
          <Button
            variant="destructive"
            size="sm"
            onClick={handleStopTranslation}
            className="gap-2"
          >
            <StopCircle className="w-4 h-4" />
            {t('Stop')}
          </Button>
        )}

        <div className="flex gap-2 ml-auto">
          <Button
            variant="outline"
            size="sm"
            onClick={handleClearCurrentLanguage}
            disabled={!selectedLang || translatingAll || translatingId !== null}
            className="gap-2"
            title={t('Clear all recipe translations for selected language')}
          >
            <Trash2 className="w-4 h-4" />
            {t('Clear Language')}
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleClearAllTranslations}
            disabled={translatingAll || translatingId !== null}
            className="gap-2"
            title={t('Clear all recipe translations for all languages')}
          >
            <Trash2 className="w-4 h-4" />
            {t('Clear All Languages')}
          </Button>
        </div>
      </div>

      {/* Translation progress indicator */}
      {translatingAll && structuredProgress && (
        <div className="bg-muted/30 rounded-md border p-3">
          {/* Progress bar and stats */}
          <div className="flex items-center gap-3 mb-2">
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-muted-foreground">
                  {structuredProgress.completed}/{structuredProgress.total} {t('recipes')}
                </span>
                <span className="text-xs font-medium">
                  {structuredProgress.total > 0 
                    ? Math.round((structuredProgress.completed / structuredProgress.total) * 100) 
                    : 0}%
                </span>
              </div>
              <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
                <div 
                  className="bg-primary h-full transition-all duration-300 ease-out"
                  style={{ 
                    width: `${structuredProgress.total > 0 
                      ? (structuredProgress.completed / structuredProgress.total) * 100 
                      : 0}%` 
                  }}
                />
              </div>
            </div>
          </div>

          {/* Active languages */}
          {structuredProgress.activeLanguages.length > 0 && (
            <div className="text-xs text-muted-foreground">
              <span className="font-medium">{t('Active')}:</span> {structuredProgress.activeLanguages.map((lang, idx) => (
                <span key={idx} className="ml-1">
                  {lang.code.toUpperCase()}{idx < structuredProgress.activeLanguages.length - 1 ? ',' : ''}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Recipes list */}
      <div className="border rounded-lg overflow-hidden">
        <div className="max-h-[500px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0">
              <tr>
                <th className="text-left p-3 font-medium w-8"></th>
                <th className="text-left p-3 font-medium">{t('Recipe')}</th>
                <th className="text-left p-3 font-medium w-24">{t('Status')}</th>
                <th className="text-right p-3 font-medium w-32">{t('Actions')}</th>
              </tr>
            </thead>
            <tbody>
              {recipes.map(recipe => {
                const status = recipe.translations[selectedLang] || 'missing';
                const isTranslating = translatingId === recipe.id;

                return (
                  <tr key={recipe.id} className="border-t">
                    <td className="p-3">
                      {status === 'ok' ? (
                        <Check className="w-4 h-4 text-green-500" />
                      ) : (
                        <AlertTriangle className="w-4 h-4 text-yellow-500" />
                      )}
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{recipe.name}</span>
                        {recipe.enabled === false && (
                          <Badge variant="secondary" className="text-xs">
                            {t('Disabled')}
                          </Badge>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground font-mono">
                        {recipe.id}
                      </div>
                    </td>
                    <td className="p-3">
                      {status === 'ok' ? (
                        <Badge variant="default" className="text-xs">
                          {t('Translated')}
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-xs">
                          {t('Not translated')}
                        </Badge>
                      )}
                    </td>
                    <td className="p-3 text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleTranslateRecipe(recipe.id)}
                        disabled={isTranslating || translatingAll || !selectedLang}
                        className="gap-2"
                      >
                        {isTranslating ? (
                          <>
                            <RefreshCw className="w-3 h-3 animate-spin" />
                            {t('Translating...')}
                          </>
                        ) : (
                          <>
                            <Languages className="w-3 h-3" />
                            {status === 'ok' ? t('Re-translate') : t('Translate')}
                          </>
                        )}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="p-2 text-center text-xs text-muted-foreground bg-muted/30 border-t">
          {recipes.length} {t('recipes')} | {languages.length} {t('languages')}
        </div>
      </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
