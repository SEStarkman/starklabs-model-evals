export type ModelConnection = {
  id: number;
  name: string;
  provider: string;
  endpoint?: string | null;
  model_id: string;
  credential_present: boolean;
};

export type ReferenceFile = {
  name: string;
  media_type?: string;
  content: string;
};

export type SuiteTest = {
  id?: number;
  stable_id?: string;
  title: string;
  prompt: string;
  expected_output?: string | null;
  reference_text?: string | null;
  reference_files?: ReferenceFile[];
  expected_output_type?: string;
  private_rubric?: string | null;
  execution_settings?: Record<string, unknown>;
  executable?: boolean;
};

export type Suite = {
  id: number;
  name: string;
  stable_id?: string;
  version?: string;
  tests: SuiteTest[];
};

export type Run = {
  id: number;
  suite_id?: number;
  status: string;
  fresh_requests: number;
  completed_requests: number;
  total_requests: number;
};

export type Artifact = {
  id: number;
  name: string;
  media_type: string;
};

export type Result = {
  id: number;
  test_id: number;
  test_title: string;
  test_stable_id?: string;
  source_prompt?: string;
  source_reference_text?: string | null;
  expected_output_type?: string;
  executable?: boolean;
  model_id: number;
  model_name: string;
  provider_model_id: string;
  status: string;
  raw_output?: string | null;
  error?: { code: string; message: string } | null;
  settings: Record<string, unknown>;
  timing_ms: number;
  request_count: number;
  artifacts?: Artifact[];
  rating?: { winner_model_id: number | null; rating: number; notes: string } | null;
};

export type ExecutionEvidence = {
  id: number;
  command_category: string;
  status: string;
  exit_code: number | null;
  timed_out: number;
  stdout: string;
  stderr: string;
  capability_gap?: string | null;
};

export type ModelCreatePayload = {
  name: string;
  provider: string;
  endpoint?: string;
  model_id: string;
  credential_label?: string;
  credential_value?: string;
};

export type SuiteCreatePayload = {
  stable_id: string;
  name: string;
  version: string;
  tests: SuiteTest[];
};

export type Api = {
  health(): Promise<Record<string, unknown>>;
  listModels(): Promise<{ models: ModelConnection[] }>;
  createModel(payload?: ModelCreatePayload): Promise<ModelConnection>;
  testModel(modelId: number): Promise<Record<string, unknown>>;
  discover(runtime: string, endpoint: string): Promise<Record<string, unknown>>;
  importPack(pack: unknown): Promise<Suite>;
  createSuite(payload: SuiteCreatePayload): Promise<Suite>;
  listSuites(): Promise<{ suites: Suite[] }>;
  startRun(suiteId: number, modelIds: number[], settings?: Record<string, unknown>): Promise<Run>;
  listRuns(): Promise<{ runs: Run[] }>;
  getRun(runId: number): Promise<Run>;
  waitRun(runId: number): Promise<Run>;
  cancelRun(runId: number): Promise<Run>;
  results(runId: number): Promise<{ results: Result[] }>;
  executeResult(resultId: number): Promise<ExecutionEvidence>;
  resultExecutions(resultId: number): Promise<{ executions: ExecutionEvidence[] }>;
  saveRating(
    resultId: number,
    modelId: number | null,
    rating: number,
    notes: string,
  ): Promise<Record<string, unknown>>;
};

export function apiClient(initialToken: string): Api {
  let launchBearer = initialToken;
  let sessionExchange: Promise<void> | null = null;

  async function ensureSession(): Promise<void> {
    if (!launchBearer) return;
    if (!sessionExchange) {
      const authorization = 'Bearer ' + launchBearer;
      sessionExchange = fetch('/api/session', {
        credentials: 'same-origin',
        headers: { Authorization: authorization },
      }).then(async (response) => {
        if (!response.ok) throw new Error(`Session exchange failed: ${response.status}`);
        launchBearer = '';
      });
    }
    await sessionExchange;
  }

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    await ensureSession();
    const response = await fetch(path, {
      ...init,
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(`API ${response.status}: ${body.slice(0, 300)}`);
    }
    return response.json() as Promise<T>;
  }

  return {
    health: () => request('/api/health'),
    listModels: () => request('/api/models'),
    createModel: (payload) =>
      request('/api/models', {
        method: 'POST',
        body: JSON.stringify(payload ?? { name: 'Fake OK', provider: 'fake', model_id: 'fake-ok' }),
      }),
    testModel: (modelId) => request(`/api/models/${modelId}/test`, { method: 'POST' }),
    discover: (runtime, endpoint) =>
      request(
        `/api/models/discover?runtime=${encodeURIComponent(runtime)}&endpoint=${encodeURIComponent(endpoint)}`,
      ),
    importPack: (pack) =>
      request('/api/import-pack', {
        method: 'POST',
        body: JSON.stringify(pack),
      }),
    createSuite: (payload) =>
      request('/api/suites', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    listSuites: () => request('/api/suites'),
    startRun: (suiteId, modelIds, settings = { temperature: 0 }) =>
      request('/api/runs', {
        method: 'POST',
        body: JSON.stringify({ suite_id: suiteId, model_ids: modelIds, settings }),
      }),
    listRuns: () => request('/api/runs'),
    getRun: (runId) => request(`/api/runs/${runId}`),
    waitRun: (runId) => request(`/api/runs/${runId}/wait`, { method: 'POST' }),
    cancelRun: (runId) => request(`/api/runs/${runId}/cancel`, { method: 'POST' }),
    results: (runId) => request(`/api/runs/${runId}/results`),
    executeResult: (resultId) =>
      request(`/api/results/${resultId}/execute`, {
        method: 'POST',
        body: JSON.stringify({ category: 'python-single-file' }),
      }),
    resultExecutions: (resultId) => request(`/api/results/${resultId}/executions`),
    saveRating: (resultId, modelId, rating, notes) =>
      request(`/api/results/${resultId}/rating`, {
        method: 'POST',
        body: JSON.stringify({ winner_model_id: modelId, rating, notes }),
      }),
  };
}

let launchToken = '';

export function tokenFromFragment(): string {
  if (launchToken) return launchToken;
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  const token = params.get('token') ?? '';
  if (token) {
    launchToken = token;
    const historyState =
      window.history.state && typeof window.history.state === 'object'
        ? { ...window.history.state }
        : null;
    if (historyState) delete historyState.starklabsSessionToken;
    window.history.replaceState(
      historyState,
      '',
      window.location.pathname + window.location.search,
    );
  }
  return token;
}
