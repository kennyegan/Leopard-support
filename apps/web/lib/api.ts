export type Runtime = {
 provider: string; external_ai_enabled: boolean; ai_requests_remaining?: number | null; app_mode?: string;
 support_contact?: string; qualification_only?: boolean; status?: string; sections?: number;
};
export type Source = {id: string; title: string; href: string; corpus_version: string; score: number};
export type Ticket = {id: string; draft: string; edited: boolean};
export type Reply = {
 id: string; snapshot_id: string; action: 'ANSWER' | 'ASK' | 'HANDOFF'; text: string;
 steps: string[]; sources: Source[]; options: string[]; provider: string; ticket?: Ticket;
 user_message: Message;
 response_kind?: string; request_type?: string;
 progress?: {current: number; total: number; kind: string; prompt: string} | null;
 references?: {title: string; url: string; checked_at: string}[];
 state: {outcome: string; problem_id: string; details?: {system_or_app?: string; vendor?: string; os?: string}};
};
// `failed` marks a message the server never confirmed; it only exists in the browser.
export type Message = {id: string; role: string; text: string; response?: Reply; failed?: boolean};
export type History = {
 id: string; mode: string; messages: Message[]; ticket: Ticket | null;
 state: {pending_failure: boolean; outcome: string};
 feedback: {message_id: string; kind: string; value: string}[];
};

export type SavedSession = {id: string; title: string; updated_at: string; outcome: string | null};

let csrfToken = '';
// Supplies the signed-in user's ID token, or '' for guests.
let accountToken: () => Promise<string> = async () => '';
export function setAccountTokenProvider(provider: () => Promise<string>) { accountToken = provider; }
let storageKey = 'techspot.demo.session';
export const session = {
 get key() { return storageKey; },
 signIn(token: string, userId: string) { csrfToken = token; storageKey = `techspot.pilot.session.${userId}`; },
 get csrf() { return csrfToken; },
};

export class ApiError extends Error {
 constructor(message: string, readonly status: number) { super(message); }
}

function describe(status: number) {
 if (status === 401) return 'Your sign-in has expired. Refresh this page to sign in again.';
 if (status === 429) return 'Your request allowance is temporarily reached. Please wait before trying again.';
 if (status === 409) return 'This turn is running or its outcome is uncertain. Retry the same message later; start a new conversation if it remains uncertain.';
 if (status === 404) return 'That conversation is unavailable. Start a new chat.';
 return 'The support service is unavailable. Please try again.';
}

export async function api<T>(path: string, init?: RequestInit & {timeout?: number}): Promise<T> {
 const {timeout = 20000, ...rest} = init ?? {};
 let response: Response;
 try {
  const token = await accountToken();
  response = await fetch(path, {
   ...rest,
   headers: {
    'Content-Type': 'application/json',
    ...(csrfToken ? {'X-CSRF-Token': csrfToken} : {}),
    ...(token ? {'X-Account-Token': token} : {}),
    ...rest.headers,
   },
   signal: rest.signal ?? AbortSignal.timeout(timeout),
  });
 } catch (e) {
  if (e instanceof DOMException && e.name === 'AbortError' && rest.signal?.aborted) throw e;
  throw new ApiError(describe(0), 0);
 }
 if (!response.ok) throw new ApiError(describe(response.status), response.status);
 return response.json();
}

// Health answers 503 with a full body while the service is degraded; callers still want that body.
export async function readHealth(signal?: AbortSignal): Promise<Runtime> {
 const response = await fetch('/api/health', {signal: signal ?? AbortSignal.timeout(15000)});
 if (!response.ok && response.status !== 503) throw new ApiError(describe(response.status), response.status);
 return response.json();
}

export function canReportFix(r: Reply) {
 return r.response_kind !== 'check' && (!r.progress || r.progress.current === r.progress.total);
}

export function outcomeLabel(r: Reply) {
 if (r.response_kind === 'check') return 'Let’s check one thing';
 if (r.response_kind === 'service_error') return 'Assistant unavailable';
 if (r.response_kind === 'status') return r.state.outcome === 'resolved' ? 'Resolved' : 'Progress update';
 if (r.response_kind === 'explanation') return 'Let’s clarify';
 if (r.action === 'ASK') return 'A quick question';
 if (r.action === 'HANDOFF') return 'Let’s bring in a person';
 return r.request_type === 'install' ? 'Download and setup' : 'Guide-backed steps';
}

export const accountApi = {
 sessions: () => api<SavedSession[]>('/api/account/sessions'),
 claim: (id: string) => api<{claimed: boolean}>(`/api/sessions/${id}/claim`, {method: 'POST'}),
 remove: (id: string) => api<{deleted: boolean}>(`/api/sessions/${id}`, {method: 'DELETE'}),
};
