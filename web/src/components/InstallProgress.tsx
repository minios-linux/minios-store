import { useEffect, useRef, useState } from 'react';
import { useTranslation } from '@/contexts/LanguageContext';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Progress } from '@/components/ui/progress';
import { Terminal, X, CheckCircle2, XCircle } from 'lucide-react';

export interface InstallProgressState {
  /** Whether installation is active (dialog open) */
  active: boolean;
  /** Current status */
  status: 'running' | 'complete' | 'error' | 'cancelled';
  /** Current recipe name being installed */
  recipeName: string;
  /** Current step (e.g. "install", "done") */
  step: string;
  /** Current recipe index (1-based) */
  current: number;
  /** Total recipes in batch */
  total: number;
  /** Scrolling terminal output lines */
  outputLines: string[];
  /** Successful recipe IDs */
  successful: string[];
  /** Failed recipe IDs */
  failed: string[];
}

export const INITIAL_PROGRESS_STATE: InstallProgressState = {
  active: false,
  status: 'running',
  recipeName: '',
  step: '',
  current: 0,
  total: 0,
  outputLines: [],
  successful: [],
  failed: [],
};

interface InstallProgressProps {
  state: InstallProgressState;
  open: boolean;
  onClose: () => void;
  onCancel: () => void;
}

const InstallProgress: React.FC<InstallProgressProps> = ({
  state,
  open,
  onClose,
  onCancel,
}) => {
  const { t } = useTranslation();
  const terminalRef = useRef<HTMLDivElement>(null);
  const [showOutput, setShowOutput] = useState(false);

  // Auto-scroll terminal to bottom when new lines arrive
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [state.outputLines.length]);

  const progressPercent = state.total > 0
    ? Math.round((state.current / state.total) * 100)
    : 0;

  const isFinished = state.status === 'complete' || state.status === 'error' || state.status === 'cancelled';

  const statusIcon = () => {
    switch (state.status) {
      case 'running':
        return (
          <div className="loading-dots" style={{ gap: '4px' }}>
            <span style={{ width: 6, height: 6 }}></span>
            <span style={{ width: 6, height: 6 }}></span>
            <span style={{ width: 6, height: 6 }}></span>
          </div>
        );
      case 'complete':
        return <CheckCircle2 size={20} style={{ color: 'var(--accent)' }} />;
      case 'error':
      case 'cancelled':
        return <XCircle size={20} style={{ color: 'hsl(var(--destructive))' }} />;
    }
  };

  const statusText = () => {
    // Special case: after page reload with no data
    if (state.status === 'running' && state.total === 1 && state.current === 0 && state.recipeName === '') {
      return t('Installation in progress...');
    }
    
    switch (state.status) {
      case 'running':
        return state.recipeName
          ? `${t('Installing')}: ${state.recipeName}`
          : t('Installing...');
      case 'complete':
        return t('Installation complete');
      case 'error':
        return t('Installation error');
      case 'cancelled':
        return t('Installation cancelled');
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent className="install-progress-modal">
        <DialogHeader>
          <DialogTitle className="sr-only">{t('Installation Progress')}</DialogTitle>
          <DialogDescription className="sr-only">{statusText()}</DialogDescription>
        </DialogHeader>

        {/* Status header */}
        <div className="install-progress-header">
          <div className="install-progress-status">
            {statusIcon()}
            <span className="install-progress-status-text">{statusText()}</span>
          </div>
          {state.total > 1 && state.current > 0 && (
            <span className="install-progress-counter">
              {state.current}/{state.total}
            </span>
          )}
        </div>

        {/* Progress bar - hide if no data after reload */}
        {!(state.total === 1 && state.current === 0 && state.recipeName === '' && state.status === 'running') && (
          <Progress
            value={isFinished ? 100 : progressPercent}
            className="install-progress-bar"
          />
        )}

        {/* Terminal output - collapsible */}
        <div 
          className="install-progress-terminal-header"
          onClick={() => setShowOutput(!showOutput)}
          style={{ cursor: 'pointer', userSelect: 'none' }}
        >
          <Terminal size={14} />
          <span>{t('Output')}</span>
          <span style={{ marginLeft: 'auto', fontSize: '12px', opacity: 0.6 }}>
            {showOutput ? '▼' : '▶'}
          </span>
        </div>
        {showOutput && (
          <div className="install-progress-terminal" ref={terminalRef}>
            {state.outputLines.map((line, i) => (
              <div key={i} className="install-progress-line">{line || '\u00A0'}</div>
            ))}
            {state.outputLines.length === 0 && state.total === 1 && state.current === 0 && state.status === 'running' && (
              <div className="install-progress-line install-progress-line-muted">
                {t('Installation in progress. Output details lost after page reload.')}
              </div>
            )}
            {state.outputLines.length === 0 && !(state.total === 1 && state.current === 0 && state.status === 'running') && (
              <div className="install-progress-line install-progress-line-muted">
                {t('Waiting for output...')}
              </div>
            )}
          </div>
        )}

        {/* Summary (shown when finished) */}
        {isFinished && (state.successful.length > 0 || state.failed.length > 0) && (
          <div className="install-progress-summary">
            {state.successful.length > 0 && (
              <span className="install-progress-summary-ok">
                {state.successful.length} {t('successful')}
              </span>
            )}
            {state.failed.length > 0 && (
              <span className="install-progress-summary-fail">
                {state.failed.length} {t('failed')}
              </span>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="install-progress-actions">
          {!isFinished ? (
            <button
              className="install-progress-cancel-btn"
              onClick={onCancel}
            >
              <X size={16} />
              {t('Cancel')}
            </button>
          ) : (
            <button
              className="install-progress-close-btn"
              onClick={onClose}
            >
              {t('Close')}
            </button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default InstallProgress;
