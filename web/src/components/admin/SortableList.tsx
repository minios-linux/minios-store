import React from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { DragEndEvent } from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
  rectSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';

interface SortableItemProps {
  id: string;
  children: React.ReactNode;
  className?: string;
  handleClassName?: string;
  disabled?: boolean;
}

export function SortableItem({ id, children, className = '', handleClassName = '', disabled = false }: SortableItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 1000 : 'auto',
  };

  return (
    <div ref={setNodeRef} style={style} className={`sortable-item ${className} ${isDragging ? 'is-dragging' : ''}`}>
      {!disabled && (
        <div className={`sortable-handle ${handleClassName}`} {...attributes} {...listeners}>
          <GripVertical className="w-4 h-4" />
        </div>
      )}
      {children}
    </div>
  );
}

interface SortableGridItemProps {
  id: string;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
}

export function SortableGridItem({ id, children, className = '', disabled = false }: SortableGridItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 1000 : 'auto',
  };

  return (
    <div ref={setNodeRef} style={style} className={`sortable-grid-item ${className} ${isDragging ? 'is-dragging' : ''}`}>
      <div 
        ref={setActivatorNodeRef}
        className="sortable-grid-handle" 
        {...attributes} 
        {...listeners}
      >
        <GripVertical className="w-3 h-3" />
      </div>
      {children}
    </div>
  );
}

interface SortableListProps<T> {
  items: T[];
  getItemId: (item: T) => string;
  onReorder: (items: T[]) => void;
  renderItem: (item: T, index: number) => React.ReactNode;
  className?: string;
  strategy?: 'vertical' | 'grid';
  disabled?: boolean;
}

export function SortableList<T>({ 
  items, 
  getItemId, 
  onReorder, 
  renderItem, 
  className = '',
  strategy = 'vertical',
  disabled = false
}: SortableListProps<T>) {
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;

    if (over && active.id !== over.id) {
      const oldIndex = items.findIndex(item => getItemId(item) === active.id);
      const newIndex = items.findIndex(item => getItemId(item) === over.id);
      onReorder(arrayMove(items, oldIndex, newIndex));
    }
  };

  const sortingStrategy = strategy === 'grid' ? rectSortingStrategy : verticalListSortingStrategy;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext
        items={items.map(getItemId)}
        strategy={sortingStrategy}
        disabled={disabled}
      >
        <div className={className}>
          {items.map((item, index) => renderItem(item, index))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
