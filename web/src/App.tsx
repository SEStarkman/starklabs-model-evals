import {
  ArrowDown,
  ArrowUp,
  Ban,
  CheckCircle2,
  Database,
  FileText,
  GitCompare,
  Play,
  RefreshCw,
  Save,
  Search,
  Server,
  ShieldCheck,
  Upload,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { Api, ExecutionEvidence, ModelConnection, Result, Run, Suite, SuiteTest } from './api';
import { apiClient, tokenFromFragment } from './api';
import { publicPack } from './publicPack';
import './styles.css';

type AppProps = {
  api?: Api;
  initialToken?: string;
};

type ActiveTab = 'compare' | 'models' | 'suites' | 'runs';

const navItems = [
  { id: 'compare', label: 'Compare', icon: GitCompare },
  { id: 'models', label: 'Models', icon: Server },
  { id: 'suites', label: 'Suites', icon: FileText },
  { id: 'runs', label: 'Runs', icon: Database },
] as const;

const providerOptions = ['fake', 'openai-compatible', 'openai', 'anthropic', 'gemini'];
const expectedTypes = ['text', 'json', 'html', 'code'];

export default function App({ api, initialToken }: AppProps) {
  const [token] = useState(initialToken ?? tokenFromFragment());
  const client = useMemo(() => api ?? apiClient(token), [api, token]);
  const [active, setActive] = useState<ActiveTab>('compare');
  const [models, setModels] = useState<ModelConnection[]>([]);
  const [suites, setSuites] = useState<Suite[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [results, setResults] = useState<Result[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [selectedSuiteId, setSelectedSuiteId] = useState<number | null>(null);
  const [selectedModelIds, setSelectedModelIds] = useState<number[]>([]);
  const [blind, setBlind] = useState(false);
  const [status, setStatus] = useState('Ready');
  const [error, setError] = useState('');
  const [connectionStatus, setConnectionStatus] = useState('Not tested');
  const [ratings, setRatings] = useState<Record<number, { winner: number | null; rating: number; notes: string }>>({});
  const [executions, setExecutions] = useState<Record<number, ExecutionEvidence>>({});
  const [modelForm, setModelForm] = useState({
    name: 'Fake OK',
    provider: 'fake',
    endpoint: '',
    modelId: 'fake-ok',
    credential: '',
  });
  const [discovery, setDiscovery] = useState({ runtime: 'ollama', endpoint: 'http://127.0.0.1:11434', status: 'Not checked' });
  const [suiteForm, setSuiteForm] = useState({
    stableId: 'local-suite',
    name: 'Local Suite',
    version: '0.1.0',
    title: 'New test',
    prompt: 'Answer as plain text.',
    referenceText: '',
    fileName: '',
    fileContent: '',
    expectedOutput: '',
    expectedType: 'text',
    privateRubric: '',
    executable: false,
  });

  const refresh = useCallback(async () => {
    try {
      await client.health();
      const [modelPayload, suitePayload, runPayload] = await Promise.all([
        client.listModels(),
        client.listSuites(),
        client.listRuns(),
      ]);
      setModels(modelPayload.models);
      setSuites(suitePayload.suites);
      setRuns(runPayload.runs);
      setSelectedSuiteId((current) => current ?? suitePayload.suites[0]?.id ?? null);
      setSelectedModelIds((current) =>
        current.length > 0 ? current : modelPayload.models.map((model) => model.id),
      );
      const runId = selectedRunId ?? runPayload.runs[0]?.id ?? null;
      setSelectedRunId(runId);
      const loadedResults = runId ? (await client.results(runId)).results : [];
      setResults(loadedResults);
      setRatings((current) => ({
        ...Object.fromEntries(
          loadedResults
            .filter((result) => result.rating)
            .map((result) => [
              result.id,
              {
                winner: result.rating?.winner_model_id ?? null,
                rating: result.rating?.rating ?? 5,
                notes: result.rating?.notes ?? '',
              },
            ]),
        ),
        ...current,
      }));
      const executionHistory = await Promise.all(
        loadedResults.map(async (result) => [
          result.id,
          (await client.resultExecutions(result.id)).executions[0],
        ] as const),
      );
      setExecutions(Object.fromEntries(executionHistory.filter((entry) => entry[1])));
      setStatus('Connected to local backend');
      setError('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unknown error');
    }
  }, [api, client, selectedRunId, token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedRunId) return undefined;
    const run = runs.find((item) => item.id === selectedRunId);
    if (!run || !['queued', 'running', 'canceling'].includes(run.status)) return undefined;
    const timer = window.setInterval(() => {
      void refresh();
    }, 500);
    return () => window.clearInterval(timer);
  }, [refresh, runs, selectedRunId]);

  async function connectModel() {
    try {
      const created = await client.createModel({
        name: modelForm.name,
        provider: modelForm.provider,
        endpoint: modelForm.endpoint || undefined,
        model_id: modelForm.modelId,
        credential_label: modelForm.provider,
        credential_value: modelForm.credential || undefined,
      });
      setSelectedModelIds((ids) => [...new Set([...ids, created.id])]);
      setModelForm((current) => ({ ...current, credential: '' }));
      await refresh();
      setActive('models');
      setConnectionStatus(`${created.name} saved`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Failed to connect model');
    }
  }

  async function testSelectedModel() {
    const modelId = selectedModelIds[0] ?? models[0]?.id;
    if (!modelId) return;
    try {
      const result = await client.testModel(modelId);
      setConnectionStatus(JSON.stringify(result));
    } catch (caught) {
      setConnectionStatus(caught instanceof Error ? caught.message : 'Connection test failed');
    }
  }

  async function discoverRuntime() {
    try {
      const result = await client.discover(discovery.runtime, discovery.endpoint);
      setDiscovery((current) => ({ ...current, status: JSON.stringify(result) }));
    } catch (caught) {
      setDiscovery((current) => ({
        ...current,
        status: caught instanceof Error ? caught.message : 'Discovery failed',
      }));
    }
  }

  async function importPublicPack() {
    try {
      const suite = await client.importPack(publicPack);
      setSelectedSuiteId(suite.id);
      await refresh();
      setActive('suites');
      setStatus('Public pack imported');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Failed to import suite');
    }
  }

  async function createSuite() {
    const referenceFiles = suiteForm.fileName
      ? [{ name: suiteForm.fileName, media_type: 'text/plain', content: suiteForm.fileContent }]
      : [];
    const test: SuiteTest = {
      stable_id: slug(suiteForm.title),
      title: suiteForm.title,
      prompt: suiteForm.prompt,
      reference_text: suiteForm.referenceText || null,
      reference_files: referenceFiles,
      expected_output: suiteForm.expectedOutput || null,
      expected_output_type: suiteForm.expectedType,
      private_rubric: suiteForm.privateRubric || null,
      execution_settings: {},
      executable: suiteForm.executable,
    };
    try {
      const suite = await client.createSuite({
        stable_id: suiteForm.stableId,
        name: suiteForm.name,
        version: suiteForm.version,
        tests: [test],
      });
      setSelectedSuiteId(suite.id);
      await refresh();
      setActive('suites');
      setStatus(`${suite.name} created`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Failed to create suite');
    }
  }

  async function runMatrix() {
    const suiteId = selectedSuiteId ?? suites[0]?.id;
    const modelIds = selectedModelIds.length > 0 ? selectedModelIds : models.map((model) => model.id);
    if (!suiteId || modelIds.length === 0) {
      setError('Select a suite and at least one model');
      return;
    }
    try {
      const run = await client.startRun(suiteId, modelIds);
      setSelectedRunId(run.id);
      setRuns([run, ...runs.filter((existing) => existing.id !== run.id)]);
      setResults([]);
      setActive('runs');
      setStatus(`Run ${run.id} started`);
      setError('');
      window.setTimeout(() => void refresh(), 250);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Run failed');
    }
  }

  async function cancelRun() {
    if (!selectedRunId) return;
    const run = await client.cancelRun(selectedRunId);
    setRuns((items) => [run, ...items.filter((item) => item.id !== run.id)]);
    setStatus(`Run ${run.id} ${run.status}`);
  }

  async function waitRun() {
    if (!selectedRunId) return;
    const run = await client.waitRun(selectedRunId);
    setRuns((items) => [run, ...items.filter((item) => item.id !== run.id)]);
    setResults((await client.results(run.id)).results);
    setActive('compare');
  }

  async function saveResultRating(result: Result) {
    const rating = ratings[result.id] ?? { winner: result.model_id, rating: 5, notes: '' };
    await client.saveRating(result.id, rating.winner, rating.rating, rating.notes);
    setStatus(`Saved rating for result ${result.id}`);
  }

  async function executeResult(result: Result) {
    try {
      const evidence = await client.executeResult(result.id);
      setExecutions((current) => ({ ...current, [result.id]: evidence }));
      setStatus(`Recorded isolated execution for result ${result.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Artifact execution failed');
    }
  }

  const activeRun = runs.find((run) => run.id === selectedRunId);
  const grouped = results.reduce<Record<string, Result[]>>((accumulator, result) => {
    accumulator[result.test_title] = [...(accumulator[result.test_title] ?? []), result];
    return accumulator;
  }, {});

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <ShieldCheck aria-hidden="true" />
          <span>Starklabs Evals</span>
        </div>
        <nav aria-label="Primary navigation">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} type="button" className={active === item.id ? 'nav active' : 'nav'} onClick={() => setActive(item.id)}>
                <Icon aria-hidden="true" size={18} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="workspace" aria-live="polite">
        <header className="topbar">
          <div>
            <h1>Local Model Evaluation</h1>
            <p>{status}</p>
          </div>
          <div className="actions">
            <button type="button" onClick={() => void refresh()}><RefreshCw size={16} />Refresh</button>
            <button type="button" onClick={() => void importPublicPack()}><Upload size={16} />Import pack</button>
            <button type="button" onClick={() => void runMatrix()}><Play size={16} />Run</button>
            <button type="button" onClick={() => void cancelRun()} disabled={!activeRun || activeRun.status !== 'running'}><Ban size={16} />Cancel</button>
          </div>
        </header>

        {error && <div className="error" role="alert">{error}</div>}

        {active === 'models' && (
          <section className="pane split">
            <form className="panel form-grid" onSubmit={(event) => { event.preventDefault(); void connectModel(); }}>
              <h2>Model Connection</h2>
              <Field label="Provider">
                <select value={modelForm.provider} onChange={(event) => setModelForm({ ...modelForm, provider: event.target.value })}>
                  {providerOptions.map((provider) => <option key={provider}>{provider}</option>)}
                </select>
              </Field>
              <Field label="Name">
                <input value={modelForm.name} onChange={(event) => setModelForm({ ...modelForm, name: event.target.value })} />
              </Field>
              <Field label="Endpoint">
                <input value={modelForm.endpoint} placeholder="https://api.example.test/v1" onChange={(event) => setModelForm({ ...modelForm, endpoint: event.target.value })} />
              </Field>
              <Field label="Model ID">
                <input value={modelForm.modelId} onChange={(event) => setModelForm({ ...modelForm, modelId: event.target.value })} />
              </Field>
              <Field label="Credential">
                <input type="password" value={modelForm.credential} onChange={(event) => setModelForm({ ...modelForm, credential: event.target.value })} />
              </Field>
              <div className="button-row">
                <button type="submit"><Save size={16} />Save</button>
                <button type="button" onClick={() => void testSelectedModel()}><CheckCircle2 size={16} />Test</button>
              </div>
              <pre>{connectionStatus}</pre>
            </form>

            <section className="panel form-grid">
              <h2>Local Discovery</h2>
              <Field label="Runtime">
                <select value={discovery.runtime} onChange={(event) => setDiscovery({ ...discovery, runtime: event.target.value })}>
                  {['ollama', 'lmstudio', 'llamacpp', 'vllm'].map((runtime) => <option key={runtime}>{runtime}</option>)}
                </select>
              </Field>
              <Field label="Endpoint">
                <input value={discovery.endpoint} onChange={(event) => setDiscovery({ ...discovery, endpoint: event.target.value })} />
              </Field>
              <button type="button" onClick={() => void discoverRuntime()}><Search size={16} />Discover</button>
              <pre>{discovery.status}</pre>
            </section>

            <ModelTable models={models} selected={selectedModelIds} onToggle={setSelectedModelIds} />
          </section>
        )}

        {active === 'suites' && (
          <section className="pane split">
            <form className="panel form-grid wide" onSubmit={(event) => { event.preventDefault(); void createSuite(); }}>
              <h2>Suite Editor</h2>
              <Field label="Suite name"><input value={suiteForm.name} onChange={(event) => setSuiteForm({ ...suiteForm, name: event.target.value })} /></Field>
              <Field label="Stable ID"><input value={suiteForm.stableId} onChange={(event) => setSuiteForm({ ...suiteForm, stableId: event.target.value })} /></Field>
              <Field label="Prompt"><textarea value={suiteForm.prompt} onChange={(event) => setSuiteForm({ ...suiteForm, prompt: event.target.value })} /></Field>
              <Field label="Reference"><textarea value={suiteForm.referenceText} onChange={(event) => setSuiteForm({ ...suiteForm, referenceText: event.target.value })} /></Field>
              <Field label="File name"><input value={suiteForm.fileName} onChange={(event) => setSuiteForm({ ...suiteForm, fileName: event.target.value })} /></Field>
              <Field label="File content"><textarea value={suiteForm.fileContent} onChange={(event) => setSuiteForm({ ...suiteForm, fileContent: event.target.value })} /></Field>
              <Field label="Expected"><textarea value={suiteForm.expectedOutput} onChange={(event) => setSuiteForm({ ...suiteForm, expectedOutput: event.target.value })} /></Field>
              <Field label="Expected type">
                <select value={suiteForm.expectedType} onChange={(event) => setSuiteForm({ ...suiteForm, expectedType: event.target.value })}>
                  {expectedTypes.map((type) => <option key={type}>{type}</option>)}
                </select>
              </Field>
              <Field label="Private rubric"><textarea value={suiteForm.privateRubric} onChange={(event) => setSuiteForm({ ...suiteForm, privateRubric: event.target.value })} /></Field>
              <label className="toggle"><input type="checkbox" checked={suiteForm.executable} onChange={(event) => setSuiteForm({ ...suiteForm, executable: event.target.checked })} />Executable</label>
              <button type="submit"><Save size={16} />Create suite</button>
            </form>
            <SuiteList suites={suites} selectedSuiteId={selectedSuiteId} setSelectedSuiteId={setSelectedSuiteId} />
          </section>
        )}

        {active === 'runs' && (
          <section className="pane">
            <div className="panel run-control">
              <Field label="Suite">
                <select value={selectedSuiteId ?? ''} onChange={(event) => setSelectedSuiteId(Number(event.target.value))}>
                  {suites.map((suite) => <option key={suite.id} value={suite.id}>{suite.name}</option>)}
                </select>
              </Field>
              <button type="button" onClick={() => void runMatrix()}><Play size={16} />Start</button>
              <button type="button" onClick={() => void waitRun()} disabled={!selectedRunId}><CheckCircle2 size={16} />Wait</button>
              <button type="button" onClick={() => void cancelRun()} disabled={!activeRun || activeRun.status !== 'running'}><Ban size={16} />Cancel</button>
            </div>
            <RunTable runs={runs} selectedRunId={selectedRunId} setSelectedRunId={setSelectedRunId} />
          </section>
        )}

        {active === 'compare' && (
          <section className="pane">
            <label className="toggle">
              <input type="checkbox" aria-label="Blind review" checked={blind} onChange={(event) => setBlind(event.target.checked)} />
              Blind review
            </label>
            {activeRun && <Progress run={activeRun} />}
            {Object.entries(grouped).map(([title, items]) => (
              <article className="comparison" key={title}>
                <h2>{title}</h2>
                {items[0]?.source_prompt && <pre className="source">{items[0].source_prompt}</pre>}
                <div className="result-grid">
                  {items.map((result, index) => (
                    <ResultPanel
                      key={result.id}
                      result={result}
                      label={blind ? `Model ${index + 1}` : result.model_name}
                      rating={ratings[result.id] ?? { winner: result.model_id, rating: 5, notes: '' }}
                      execution={executions[result.id]}
                      onRatingChange={(rating) => setRatings({ ...ratings, [result.id]: rating })}
                      onExecute={() => void executeResult(result)}
                      onSave={() => void saveResultRating(result)}
                    />
                  ))}
                </div>
              </article>
            ))}
            {results.length === 0 && <EmptyState text="Start or select a run to inspect stored outputs." />}
          </section>
        )}
      </section>
    </main>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>;
}

function ModelTable({ models, selected, onToggle }: { models: ModelConnection[]; selected: number[]; onToggle(ids: number[]): void }) {
  if (models.length === 0) return <EmptyState text="No model connections yet." />;
  return (
    <section className="panel table-wrap wide">
      <table>
        <thead><tr><th>Select</th><th>Name</th><th>Provider</th><th>Endpoint</th><th>Model</th><th>Credential</th></tr></thead>
        <tbody>
          {models.map((model) => (
            <tr key={model.id}>
              <td><input type="checkbox" checked={selected.includes(model.id)} onChange={(event) => onToggle(event.target.checked ? [...selected, model.id] : selected.filter((id) => id !== model.id))} /></td>
              <td>{model.name}</td><td>{model.provider}</td><td>{model.endpoint ?? 'local/fake'}</td><td>{model.model_id}</td><td>{model.credential_present ? 'present' : 'none'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function SuiteList({ suites, selectedSuiteId, setSelectedSuiteId }: { suites: Suite[]; selectedSuiteId: number | null; setSelectedSuiteId(id: number): void }) {
  if (suites.length === 0) return <EmptyState text="Import or create a suite to begin." />;
  return (
    <section className="panel table-wrap wide">
      {suites.map((suite) => (
        <article key={suite.id} className={suite.id === selectedSuiteId ? 'suite selected' : 'suite'}>
          <div className="suite-head">
            <button type="button" onClick={() => setSelectedSuiteId(suite.id)}>{suite.name}</button>
            <span>{suite.version}</span>
          </div>
          <table>
            <thead><tr><th>Order</th><th>Test</th><th>Type</th><th>Controls</th></tr></thead>
            <tbody>
              {suite.tests.map((test, index) => (
                <tr key={test.id ?? test.stable_id ?? test.title}>
                  <td>{index + 1}</td>
                  <td>{test.title}</td>
                  <td>{test.expected_output_type ?? 'text'}</td>
                  <td className="icon-row"><button type="button" aria-label="Move up"><ArrowUp size={14} /></button><button type="button" aria-label="Move down"><ArrowDown size={14} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
      ))}
    </section>
  );
}

function RunTable({ runs, selectedRunId, setSelectedRunId }: { runs: Run[]; selectedRunId: number | null; setSelectedRunId(id: number): void }) {
  if (runs.length === 0) return <EmptyState text="No runs yet." />;
  return (
    <section className="table-wrap panel">
      <table>
        <thead><tr><th>Run</th><th>Status</th><th>Progress</th><th>Fresh requests</th></tr></thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className={run.id === selectedRunId ? 'selected-row' : ''} onClick={() => setSelectedRunId(run.id)}>
              <td>#{run.id}</td><td>{run.status}</td><td>{run.completed_requests}/{run.total_requests}</td><td>{run.fresh_requests}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Progress({ run }: { run: Run }) {
  const total = Math.max(run.total_requests, 1);
  return (
    <div className="progress" aria-label={`Run progress ${run.completed_requests} of ${run.total_requests}`}>
      <span style={{ width: `${(run.completed_requests / total) * 100}%` }} />
    </div>
  );
}

function ResultPanel({
  result,
  label,
  rating,
  execution,
  onRatingChange,
  onExecute,
  onSave,
}: {
  result: Result;
  label: string;
  rating: { winner: number | null; rating: number; notes: string };
  execution?: ExecutionEvidence;
  onRatingChange(value: { winner: number | null; rating: number; notes: string }): void;
  onExecute(): void;
  onSave(): void;
}) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const hasHtmlPreview = looksLikeHtml(result.raw_output);
  return (
    <div className="result">
      <h3>{label}</h3>
      <dl>
        <dt>Status</dt><dd className={result.status}>{result.status}</dd>
        <dt>Model ID</dt><dd>{result.provider_model_id}</dd>
        <dt>Timing</dt><dd>{result.timing_ms} ms</dd>
        <dt>Requests</dt><dd>{result.request_count}</dd>
      </dl>
      <h4>Raw Output</h4>
      <pre>{result.raw_output ?? result.error?.message ?? 'No output'}</pre>
      {result.error && <pre>{JSON.stringify(result.error, null, 2)}</pre>}
      <h4>Settings</h4>
      <pre>{JSON.stringify(result.settings, null, 2)}</pre>
      {result.artifacts && result.artifacts.length > 0 && (
        <>
          <h4>Artifacts</h4>
          <div className="artifact-list">{result.artifacts.map((artifact) => <span className="artifact" key={artifact.id}>{artifact.name}</span>)}</div>
        </>
      )}
      {hasHtmlPreview && (
        <button type="button" onClick={() => setPreviewOpen((open) => !open)}>
          {previewOpen ? 'Close isolated preview' : 'Open isolated preview'}
        </button>
      )}
      {hasHtmlPreview && previewOpen && (
        <iframe title={`HTML preview ${result.id}`} sandbox="" srcDoc={safeHtmlSrcDoc(result.raw_output ?? '')} />
      )}
      {result.executable && result.expected_output_type === 'code' && (
        <button type="button" onClick={onExecute}><Play size={16} />Run isolated Python</button>
      )}
      {execution && <pre className="execution-evidence">{JSON.stringify(execution, null, 2)}</pre>}
      <div className="rating">
        <Field label="Winner">
          <select value={rating.winner ?? ''} onChange={(event) => onRatingChange({ ...rating, winner: event.target.value ? Number(event.target.value) : null })}>
            <option value="">No winner</option>
            <option value={result.model_id}>{result.model_name}</option>
          </select>
        </Field>
        <Field label="Rating">
          <input type="number" min="1" max="5" value={rating.rating} onChange={(event) => onRatingChange({ ...rating, rating: Number(event.target.value) })} />
        </Field>
        <Field label="Notes">
          <textarea value={rating.notes} onChange={(event) => onRatingChange({ ...rating, notes: event.target.value })} />
        </Field>
        <button type="button" onClick={onSave}><Save size={16} />Save</button>
      </div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="empty">{text}</p>;
}

function looksLikeHtml(value?: string | null) {
  return Boolean(value && /<\/?[a-z][\s\S]*>/i.test(value));
}

function safeHtmlSrcDoc(value: string) {
  const csp = [
    "default-src 'none'",
    "script-src 'unsafe-inline'",
    "style-src 'unsafe-inline'",
    "img-src data: blob:",
    "connect-src 'none'",
    "form-action 'none'",
    "navigate-to 'none'",
    "base-uri 'none'",
  ].join('; ');
  return `<meta http-equiv="Content-Security-Policy" content="${escapeAttribute(csp)}">${value}`;
}

function escapeAttribute(value: string) {
  return value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
}

function slug(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64) || 'test';
}
