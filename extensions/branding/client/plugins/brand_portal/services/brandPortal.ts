import { apiFetch, buildApiUrl } from '@/utils/api'

export interface BrandPortalProfile {
  configured: boolean
  public_id: string | null
  registration_enabled: boolean
  provisioning_extensions: string[]
  default_theme: string
  default_plan: string
  default_country: string
  default_currency: string
  default_language: string
  updated_at: string | null
}

export interface BrandPortalExtensionOption {
  key: string
  name: string
  name_zh: string
}

export interface BrandPortalDomain {
  hostname: string
  kind: string
  is_primary: boolean
  ssl_status: string
}

export interface BrandPortalProvisioningAudit {
  id: number
  status: string
  target_workspace: { uuid: string; name: string; slug: string } | null
  error_code: string
  created_at: string
  completed_at: string | null
}

export interface BrandPortalConsoleData {
  workspace: {
    id: number
    name: string
    is_active: boolean
    suspended: boolean
  }
  extension_active: boolean
  profile: BrandPortalProfile
  extension_options: BrandPortalExtensionOption[]
  verified_domains: BrandPortalDomain[]
  recent_provisionings: BrandPortalProvisioningAudit[]
}

export type BrandPortalProfileInput = Pick<
  BrandPortalProfile,
  | 'registration_enabled'
  | 'provisioning_extensions'
  | 'default_theme'
  | 'default_plan'
  | 'default_country'
  | 'default_currency'
  | 'default_language'
>

const endpoint = (workspaceId: number) =>
  buildApiUrl(`/brand_portal/v1/console/workspaces/${workspaceId}/`)

export const getBrandPortalConsole = (workspaceId: number) =>
  apiFetch<BrandPortalConsoleData>(endpoint(workspaceId))

export const updateBrandPortalProfile = (
  workspaceId: number,
  profile: BrandPortalProfileInput
) =>
  apiFetch<BrandPortalConsoleData>(endpoint(workspaceId), {
    method: 'PATCH',
    body: JSON.stringify(profile)
  })
