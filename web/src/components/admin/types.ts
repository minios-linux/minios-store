/**
 * Interface for manager components to expose save/discard functionality
 */
export interface ManagerHandle {
  save: () => void;
  discard: () => void;
}

/**
 * State change callback for managers to notify parent of changes
 */
export interface StateChangeCallback {
  (state: { hasChanges: boolean; saving: boolean }): void;
}
