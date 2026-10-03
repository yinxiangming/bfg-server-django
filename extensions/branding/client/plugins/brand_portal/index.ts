import type { Extension } from '@/extensions/registry'

import BrandPortalConsolePanel from '@/plugins/brand_portal/components/BrandPortalConsolePanel'

const extension: Extension = {
  id: 'brand_portal',
  name: 'Brand Portal',
  priority: 80,
  enabled: true,
  consoleWorkspacePanels: [
    {
      id: 'brand-portal-profile',
      component: BrandPortalConsolePanel,
      priority: 100
    }
  ]
}

export default extension
