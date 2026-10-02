'use client'

import { useEffect, useMemo, useState } from 'react'

import { useLocale, useTranslations } from 'next-intl'

import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CardHeader from '@mui/material/CardHeader'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import FormControl from '@mui/material/FormControl'
import FormControlLabel from '@mui/material/FormControlLabel'
import InputLabel from '@mui/material/InputLabel'
import MenuItem from '@mui/material/MenuItem'
import Select from '@mui/material/Select'
import Switch from '@mui/material/Switch'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import type { ConsoleWorkspacePanelProps } from '@/extensions/registry'
import { getApiErrorMessage } from '@/utils/apiErrors'
import {
  getBrandPortalConsole,
  updateBrandPortalProfile,
  type BrandPortalConsoleData,
  type BrandPortalProfileInput
} from '@/plugins/brand_portal/services/brandPortal'

const emptyProfile: BrandPortalProfileInput = {
  registration_enabled: false,
  provisioning_extensions: [],
  default_theme: '',
  default_plan: '',
  default_country: '',
  default_currency: '',
  default_language: ''
}

export default function BrandPortalConsolePanel({ workspaceId }: ConsoleWorkspacePanelProps) {
  const t = useTranslations('admin.brandPortal')
  const locale = useLocale()
  const [data, setData] = useState<BrandPortalConsoleData | null>(null)
  const [profile, setProfile] = useState<BrandPortalProfileInput>(emptyProfile)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const applyData = (next: BrandPortalConsoleData) => {
    setData(next)
    setProfile({
      registration_enabled: next.profile.registration_enabled,
      provisioning_extensions: next.profile.provisioning_extensions,
      default_theme: next.profile.default_theme,
      default_plan: next.profile.default_plan,
      default_country: next.profile.default_country,
      default_currency: next.profile.default_currency,
      default_language: next.profile.default_language
    })
  }

  const load = async () => {
    setLoading(true)
    setError(null)

    try {
      applyData(await getBrandPortalConsole(workspaceId))
    } catch (loadError) {
      setError(getApiErrorMessage(loadError) || t('errors.load'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // `load` deliberately refreshes whenever the selected workspace changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId])

  const blocked = Boolean(!data?.extension_active || !data.workspace.is_active || data.workspace.suspended)
  const extensionNames = useMemo(
    () =>
      new Map(
        (data?.extension_options ?? []).map(option => [
          option.key,
          locale.startsWith('zh') && option.name_zh ? option.name_zh : option.name
        ])
      ),
    [data?.extension_options, locale]
  )

  const save = async () => {
    setSaving(true)
    setSaved(false)
    setError(null)

    try {
      applyData(await updateBrandPortalProfile(workspaceId, profile))
      setSaved(true)
    } catch (saveError) {
      setError(getApiErrorMessage(saveError) || t('errors.save'))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <Card sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress size={28} aria-label={t('loading')} />
      </Card>
    )
  }

  if (!data) {
    return (
      <Alert
        severity='error'
        action={
          <Button color='inherit' size='small' onClick={() => void load()}>
            {t('retry')}
          </Button>
        }
      >
        {error || t('errors.load')}
      </Alert>
    )
  }

  return (
    <Card>
      <CardHeader title={t('title')} subheader={t('subtitle')} />
      <CardContent>
        {!data.extension_active && <Alert severity='info' sx={{ mb: 4 }}>{t('inactive')}</Alert>}
        {data.workspace.suspended && <Alert severity='warning' sx={{ mb: 4 }}>{t('suspended')}</Alert>}
        {!data.workspace.is_active && <Alert severity='warning' sx={{ mb: 4 }}>{t('workspaceInactive')}</Alert>}
        {error && <Alert severity='error' sx={{ mb: 4 }}>{error}</Alert>}
        {saved && <Alert severity='success' sx={{ mb: 4 }}>{t('saved')}</Alert>}

        <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' } }}>
          <FormControlLabel
            control={
              <Switch
                checked={profile.registration_enabled}
                disabled={blocked}
                onChange={event => setProfile(current => ({ ...current, registration_enabled: event.target.checked }))}
              />
            }
            label={t('fields.registrationEnabled')}
          />
          <FormControl sx={{ gridColumn: { md: 'span 2' } }}>
            <InputLabel id={`brand-portal-extensions-${workspaceId}`}>{t('fields.extensions')}</InputLabel>
            <Select
              multiple
              labelId={`brand-portal-extensions-${workspaceId}`}
              label={t('fields.extensions')}
              value={profile.provisioning_extensions}
              disabled={blocked}
              onChange={event =>
                setProfile(current => ({
                  ...current,
                  provisioning_extensions:
                    typeof event.target.value === 'string' ? event.target.value.split(',') : event.target.value
                }))
              }
              renderValue={keys => keys.map(key => extensionNames.get(key) ?? key).join(', ')}
            >
              {data.extension_options.map(option => (
                <MenuItem key={option.key} value={option.key}>
                  {extensionNames.get(option.key) ?? option.key}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {(['default_country', 'default_currency', 'default_language', 'default_theme', 'default_plan'] as const).map(field => (
            <TextField
              key={field}
              label={t(`fields.${field}`)}
              value={profile[field]}
              disabled={blocked}
              slotProps={{ htmlInput: { maxLength: field === 'default_language' ? 16 : 64 } }}
              onChange={event => setProfile(current => ({ ...current, [field]: event.target.value }))}
            />
          ))}
        </Box>

        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 3 }}>
          <Button variant='contained' disabled={blocked || saving} onClick={() => void save()}>
            {saving ? t('saving') : t('save')}
          </Button>
        </Box>

        <Typography variant='h6' sx={{ mt: 5, mb: 2 }}>{t('domains.title')}</Typography>
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          {data.verified_domains.length ? data.verified_domains.map(domain => (
            <Chip
              key={domain.hostname}
              label={domain.hostname}
              color={domain.is_primary ? 'primary' : 'default'}
              variant={domain.is_primary ? 'filled' : 'outlined'}
            />
          )) : <Typography color='text.secondary'>{t('domains.none')}</Typography>}
        </Box>

        <Typography variant='h6' sx={{ mt: 5, mb: 2 }}>{t('audit.title')}</Typography>
        {data.recent_provisionings.length ? (
          <Box sx={{ overflowX: 'auto' }}>
            <Table size='small'>
              <TableHead>
                <TableRow>
                  <TableCell>{t('audit.workspace')}</TableCell>
                  <TableCell>{t('audit.status')}</TableCell>
                  <TableCell>{t('audit.created')}</TableCell>
                  <TableCell>{t('audit.error')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.recent_provisionings.map(item => (
                  <TableRow key={item.id}>
                    <TableCell>{item.target_workspace?.name ?? '—'}</TableCell>
                    <TableCell><Chip size='small' label={item.status} /></TableCell>
                    <TableCell>{new Date(item.created_at).toLocaleString(locale)}</TableCell>
                    <TableCell>{item.error_code || '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        ) : <Typography color='text.secondary'>{t('audit.none')}</Typography>}
      </CardContent>
    </Card>
  )
}
