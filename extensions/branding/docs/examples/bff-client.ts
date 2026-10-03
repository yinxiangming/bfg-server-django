import 'server-only';

type PortalErrorBody = {
  code?: string;
  detail?: string;
  request_id?: string;
};

export class PortalApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly requestId: string,
  ) {
    super(`Portal API request failed: ${code}`);
  }
}

function requireServerEnvironment(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

type PortalFetchOptions = {
  method?: 'GET' | 'POST';
  body?: unknown;
  idempotencyKey?: string;
};

async function portalFetch<T>(path: string, options: PortalFetchOptions = {}): Promise<T> {
  if (!path.startsWith('/') || path.startsWith('//')) {
    throw new Error('Portal API path must be relative');
  }

  const baseUrl = requireServerEnvironment('BFG_API_URL').replace(/\/$/, '');
  const headers: Record<string, string> = {
    'X-Api-Key': requireServerEnvironment('BFG_PORTAL_API_KEY'),
    'X-Api-Secret': requireServerEnvironment('BFG_PORTAL_API_SECRET'),
    'X-Request-ID': crypto.randomUUID(),
  };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;

  const response = await fetch(`${baseUrl}${path}`, {
    method: options.method ?? 'GET',
    headers: {
      ...headers,
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    cache: 'no-store',
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as PortalErrorBody;
    throw new PortalApiError(
      response.status,
      body.code ?? 'portal_api_error',
      body.request_id ?? response.headers.get('X-Request-ID') ?? '',
    );
  }
  return (await response.json()) as T;
}

function contentPath(
  kind: 'pages' | 'posts' | 'menus',
  slug: string,
  language?: string,
) {
  const query = language ? `?language=${encodeURIComponent(language)}` : '';
  return `/api/v1/brand_portal/v1/cms/${kind}/${encodeURIComponent(slug)}/${query}`;
}

export function getPortalConfig<T>() {
  return portalFetch<T>('/api/v1/brand_portal/v1/config/');
}

export function getPortalPage<T>(slug: string, language?: string) {
  return portalFetch<T>(contentPath('pages', slug, language));
}

export function getPortalPost<T>(slug: string, language?: string) {
  return portalFetch<T>(contentPath('posts', slug, language));
}

export function getPortalMenu<T>(slug: string, language?: string) {
  return portalFetch<T>(contentPath('menus', slug, language));
}

export function registerPortalUser<T>(input: {
  email: string;
  password: string;
  password_confirm: string;
  first_name?: string;
  last_name?: string;
}) {
  return portalFetch<T>('/api/v1/brand_portal/v1/auth/register/', {
    method: 'POST',
    body: input,
  });
}

export function finalizePortalWorkspace<T>(
  input: {
    onboarding_token: string;
    workspace_name: string;
    admin_name?: string;
  },
  idempotencyKey: string,
) {
  return portalFetch<T>('/api/v1/brand_portal/v1/auth/finalize/', {
    method: 'POST',
    body: input,
    idempotencyKey,
  });
}
