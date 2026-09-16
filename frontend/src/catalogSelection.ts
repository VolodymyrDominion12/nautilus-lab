const STORAGE_KEY = 'nautilus.selectedCatalog';

export function getSelectedCatalogPath(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setSelectedCatalogPath(path: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, path);
  } catch {
    // ignore storage failures in restricted browsers
  }
}

export function clearSelectedCatalogPath(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
