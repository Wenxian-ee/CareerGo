import type {
  AuthTokenResponse,
  HealthResponse,
  JobReasoningApiResponse,
  JobRecord,
  JobsBrowseResponse,
  RecommendationsResponse,
  UserProfilePayload,
} from './types';
import { formatHttpError } from '@/utils/inputGuards';

/** Thrown on non-2xx API responses; `message` is user-facing. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(formatHttpError(status, detail));
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export function formatUnknownError(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message || 'Something went wrong.';
  return 'Something went wrong.';
}

const TOKEN_KEY = 'careergo_token';

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

function baseUrl(): string {
  const env = import.meta.env.VITE_API_BASE_URL;
  if (env && String(env).trim() !== '') {
    return String(env).replace(/\/$/, '');
  }
  return '';
}

function authHeaders(): HeadersInit {
  const t = getStoredToken();
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

async function request<T>(
  path: string,
  init?: RequestInit & { query?: Record<string, string | number | undefined>; auth?: boolean },
): Promise<T> {
  const { query, auth = true, ...rest } = init ?? {};
  const u = new URL(path.startsWith('http') ? path : `${baseUrl()}${path}`, window.location.origin);
  if (query) {
    Object.entries(query).forEach(([k, v]) => {
      if (v !== undefined && v !== '') u.searchParams.set(k, String(v));
    });
  }
  const headers = auth ? { ...authHeaders(), ...(rest.headers as Record<string, string>) } : { 'Content-Type': 'application/json', ...(rest.headers as Record<string, string>) };
  let res: Response;
  try {
    res = await fetch(u.toString(), { ...rest, headers });
  } catch (e) {
    if (e instanceof TypeError) {
      throw new Error(
        'Cannot reach the API. Start the backend (e.g. cd api && uvicorn app:app --host 0.0.0.0 --port 8000). With Vite dev, /api is proxied to that port.',
      );
    }
    throw e;
  }
  if (res.status === 401 && auth) {
    setStoredToken(null);
    window.dispatchEvent(new Event('careergo-auth'));
  }
  if (!res.ok) {
    let detail = '';
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === 'string') detail = j.detail;
      else if (j.detail != null) detail = JSON.stringify(j.detail);
    } catch {
      detail = await res.text();
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>('/api/health', { auth: false }),

  register: (body: { user_id: string; name: string; email?: string; phone?: string; password: string }) =>
    request<AuthTokenResponse>('/api/auth/register', { method: 'POST', body: JSON.stringify(body), auth: false }),

  login: (body: { user_id: string; password: string }) =>
    request<AuthTokenResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify(body), auth: false }),

  me: () => request<{ user_id: string; name: string; email?: string }>('/api/auth/me'),

  getProfile: () => request<UserProfilePayload>('/api/users/me/profile'),

  putProfile: (body: UserProfilePayload) =>
    request<UserProfilePayload>('/api/users/me/profile', { method: 'PUT', body: JSON.stringify(body) }),

  getRecommendations: () => request<RecommendationsResponse>('/api/users/me/recommendations'),

  /**
   * Compute and persist ranked recommendations.
   * `include_reasoning=false` (default) skips bulk LLM enrichment for speed;
   * per-job AI analysis is available on demand via `getLearningInsights`.
   */
  postRecommendations: (top_k?: number, include_reasoning = false) => {
    const k =
      top_k != null ? Math.min(10, Math.max(1, Math.floor(Number(top_k)))) : undefined;
    return request<RecommendationsResponse>('/api/users/me/recommendations', {
      method: 'POST',
      query: {
        ...(k != null ? { top_k: k } : {}),
        include_reasoning: include_reasoning ? 'true' : 'false',
      },
    });
  },

  /** Public job catalog */
  listJobs: (query?: {
    page?: number;
    page_size?: number;
    keywords?: string;
    job_type?: string;
    location?: string;
    category?: string;
    source?: string;
  }) => {
    const q = query
      ? {
          ...query,
          page: query.page != null ? Math.min(10_000, Math.max(1, Math.floor(Number(query.page)))) : undefined,
          page_size:
            query.page_size != null
              ? Math.min(100, Math.max(1, Math.floor(Number(query.page_size))))
              : undefined,
        }
      : undefined;
    return request<JobsBrowseResponse>('/api/jobs', {
      auth: false,
      query: q as Record<string, string | number | undefined>,
    });
  },

  jobsFilterMeta: () =>
    request<{
      sources: string[];
      job_types: string[];
      locations: string[];
      categories: string[];
    }>('/api/jobs/meta/filters', { auth: false }),

  getJob: (jobId: string) => request<JobRecord>(`/api/jobs/${encodeURIComponent(jobId)}`, { auth: false }),

  checkJobUrl: (jobId: string) =>
    request<{ reachable: boolean; reason: string | null; status_code: number | null; url?: string }>(
      `/api/jobs/${encodeURIComponent(jobId)}/check-url`,
      { auth: false },
    ),

  getJobSkillGraph: (jobId: string, fallbackRelated = false) =>
    request<{
      nodes: Array<{
        id: string;
        label: string;
        group: string;
        job_id?: string;
        job_url?: string;
        normalized_skill_name?: string;
      }>;
      links: Array<{ source: string; target: string; weight?: number }>;
      center_job_id?: string;
      empty_reason?: string;
      error?: string;
    }>(`/api/jobs/${encodeURIComponent(jobId)}/skill-graph`, {
      auth: false,
      query: { fallback_related: fallbackRelated ? 'true' : 'false' },
    }),

  postJobReasoning: (jobId: string) =>
    request<JobReasoningApiResponse>(`/api/users/me/jobs/${encodeURIComponent(jobId)}/reasoning`, {
      method: 'POST',
    }),

  getLearningInsights: (jobId: string) =>
    request<JobReasoningApiResponse>(`/api/users/me/jobs/${encodeURIComponent(jobId)}/learning-insights`),
};
