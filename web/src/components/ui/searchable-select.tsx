import { useState, useRef } from 'react';
import { ChevronDown, Search, Check } from 'lucide-react';
import { useTranslation } from '@/contexts/LanguageContext';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';

export interface SelectOption {
  value: string;
  label: string;
  description?: string;
}

interface SearchableSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  className?: string;
  showSearch?: boolean;
}

export function SearchableSelect({
  value,
  onChange,
  options,
  placeholder = 'Select...',
  searchPlaceholder = 'Search...',
  disabled = false,
  className = '',
  showSearch = true,
}: SearchableSelectProps) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Filter options by search
  const filteredOptions = options.filter(option =>
    option.label.toLowerCase().includes(search.toLowerCase()) ||
    option.value.toLowerCase().includes(search.toLowerCase())
  );

  // Get selected option label
  const selectedOption = options.find(opt => opt.value === value);

  // Handle wheel scroll manually (Radix can block wheel events)
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
          disabled={disabled}
          className={cn(
            'searchable-select-trigger',
            disabled && 'opacity-50 cursor-not-allowed',
            className
          )}
        >
          <span className="searchable-select-value">
            {selectedOption ? selectedOption.label : <span className="searchable-select-placeholder">{placeholder}</span>}
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
          if (showSearch) {
            setTimeout(() => searchInputRef.current?.focus(), 0);
          }
        }}
      >
        {showSearch && (
          <div className="searchable-select-search">
            <Search size={14} className="searchable-select-search-icon" />
            <input
              ref={searchInputRef}
              type="text"
              placeholder={t(searchPlaceholder)}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        )}
        <div 
          ref={listRef}
          className="searchable-select-list"
          onWheel={handleWheel}
        >
          {filteredOptions.length === 0 ? (
            <div className="searchable-select-empty">{t('No results found')}</div>
          ) : (
            filteredOptions.map(option => (
              <button
                key={option.value}
                type="button"
                className={cn('searchable-select-item', value === option.value && 'active')}
                onClick={() => { 
                  onChange(option.value); 
                  setIsOpen(false); 
                  setSearch(''); 
                }}
              >
                <span className="searchable-select-item-content">
                  <span>{option.label}</span>
                  {option.description && (
                    <span className="searchable-select-item-description">{option.description}</span>
                  )}
                </span>
                {value === option.value && <Check size={16} className="searchable-select-check" />}
              </button>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
