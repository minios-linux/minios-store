import { useState, useRef } from 'react';
import { ChevronDown, Search, Ban } from 'lucide-react';
import { DynamicIcon } from '@/components/DynamicIcon';
import { AVAILABLE_ICONS } from '@/lib/types';
import { useTranslation } from '@/contexts/LanguageContext';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';

interface IconPickerProps {
  value: string;
  onChange: (icon: string) => void;
  className?: string;
  allowEmpty?: boolean;
}

export function IconPicker({ value, onChange, className = '', allowEmpty = true }: IconPickerProps) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filteredIcons = AVAILABLE_ICONS.filter(icon =>
    icon.toLowerCase().includes(search.toLowerCase())
  );

  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    const list = listRef.current;
    if (!list) return;
    list.scrollTop += e.deltaY;
    e.stopPropagation();
  };

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn('searchable-select-trigger', className)}
        >
          <span className="searchable-select-value">
            {value ? (
              <>
                <DynamicIcon name={value} size={16} />
                <span>{value}</span>
              </>
            ) : (
              <span className="searchable-select-placeholder">
                {allowEmpty ? t('No icon') : t('Select icon')}
              </span>
            )}
          </span>
          <ChevronDown size={16} className={cn('searchable-select-chevron', isOpen && 'open')} />
        </button>
      </PopoverTrigger>
      <PopoverContent 
        className="searchable-select-dropdown w-[280px] p-0"
        align="start"
        sideOffset={4}
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          setTimeout(() => searchInputRef.current?.focus(), 0);
        }}
      >
        <div className="searchable-select-search">
          <Search size={14} className="searchable-select-search-icon" />
          <input
            ref={searchInputRef}
            type="text"
            placeholder={t('Search icons...')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div 
          ref={listRef}
          className="searchable-select-list"
          onWheel={handleWheel}
        >
          {allowEmpty && !search && (
            <button
              type="button"
              className={cn('searchable-select-item', !value && 'active')}
              onClick={() => { 
                onChange(''); 
                setIsOpen(false); 
                setSearch(''); 
              }}
            >
              <Ban size={16} className="text-muted-foreground" />
              <span>{t('No icon')}</span>
            </button>
          )}
          {filteredIcons.length === 0 ? (
            <div className="searchable-select-empty">{t('No icons found')}</div>
          ) : (
            filteredIcons.map(icon => (
              <button
                key={icon}
                type="button"
                className={cn('searchable-select-item', value === icon && 'active')}
                onClick={() => { 
                  onChange(icon); 
                  setIsOpen(false); 
                  setSearch(''); 
                }}
              >
                <DynamicIcon name={icon} size={16} />
                <span>{icon}</span>
              </button>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
