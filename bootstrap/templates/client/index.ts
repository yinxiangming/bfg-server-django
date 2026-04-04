import type { Extension } from '@/extensions/registry'

/**
 * Minimal plugin scaffold for __APP_SLUG__. Extend adminNav, sections, and services.
 */
const extension: Extension = {
  id: '__APP_SLUG__',
  name: '__APP_TITLE__',
  priority: 100,
  enabled: true,
}

export default extension
