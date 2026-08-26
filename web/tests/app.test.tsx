import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from '../src/App';

describe('App', () => {
  it('runs the fake first-run flow, reloads a rating, and escapes hostile output', async () => {
    const api = fakeApi();
    const view = render(<App api={api} initialToken="unit-token" />);

    await userEvent.click(screen.getByRole('button', { name: /models/i }));
    await userEvent.type(screen.getByLabelText('Credential'), 'credential-sentinel');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));
    expect(screen.getByLabelText('Credential')).toHaveValue('');
    await userEvent.click(screen.getByRole('button', { name: /import pack/i }));
    await userEvent.click(screen.getByRole('button', { name: /^run$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^wait$/i }));

    expect(await screen.findByRole('heading', { name: 'Fake OK' })).toBeInTheDocument();
    expect(screen.getByText(/raw-output.txt/)).toBeInTheDocument();
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(document.querySelector('img[src="x"]')).toBeNull();
    expect(screen.queryByTitle('HTML preview 1')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Open isolated preview' }));
    expect(screen.getByTitle('HTML preview 1')).toHaveAttribute('sandbox', '');
    expect(screen.getByTitle('HTML preview 1')).not.toHaveAttribute('sandbox', 'allow-scripts');

    await userEvent.click(screen.getByLabelText('Blind review'));
    await userEvent.clear(screen.getByLabelText('Rating'));
    await userEvent.type(screen.getByLabelText('Rating'), '4');
    await userEvent.type(screen.getByLabelText('Notes'), 'Persisted note');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(screen.getByText(/Saved/)).toBeInTheDocument());

    view.unmount();
    render(<App api={api} initialToken="unit-token" />);
    expect(await screen.findByDisplayValue('Persisted note')).toBeInTheDocument();
    expect(screen.getByLabelText('Rating')).toHaveValue(4);
  });
});

function fakeApi() {
  let modelCreated = false;
  let suiteCreated = false;
  let runCreated = false;
  let savedRating: { winner_model_id: number | null; rating: number; notes: string } | null = null;
  return {
    async health() {
      return { ok: true, version: 'test', bind_host: '127.0.0.1' };
    },
    async listModels() {
      return {
        models: modelCreated
          ? [{ id: 1, name: 'Fake OK', provider: 'fake', model_id: 'fake-ok', credential_present: false }]
          : [],
      };
    },
    async createModel() {
      modelCreated = true;
      return { id: 1, name: 'Fake OK', provider: 'fake', model_id: 'fake-ok', credential_present: false };
    },
    async testModel() {
      return { status: 'completed', raw_output: 'ok' };
    },
    async discover() {
      return { allowed: true, models: [] };
    },
    async importPack() {
      suiteCreated = true;
      return { id: 1, name: 'Public smoke', tests: [], version: '1.0.0' };
    },
    async createSuite() {
      suiteCreated = true;
      return { id: 1, name: 'Local Suite', tests: [], version: '0.1.0' };
    },
    async listSuites() {
      return {
        suites: suiteCreated
          ? [{ id: 1, name: 'Public smoke', version: '1.0.0', tests: [{ id: 1, title: 'Hostile', prompt: 'Hostile prompt' }] }]
          : [],
      };
    },
    async startRun() {
      runCreated = true;
      return { id: 1, status: 'running', fresh_requests: 0, completed_requests: 0, total_requests: 1 };
    },
    async listRuns() {
      return {
        runs: runCreated
          ? [{ id: 1, status: 'completed', fresh_requests: 1, completed_requests: 1, total_requests: 1 }]
          : [],
      };
    },
    async getRun() {
      return { id: 1, status: 'completed', fresh_requests: 1, completed_requests: 1, total_requests: 1 };
    },
    async waitRun() {
      return { id: 1, status: 'completed', fresh_requests: 1, completed_requests: 1, total_requests: 1 };
    },
    async cancelRun() {
      return { id: 1, status: 'canceled', fresh_requests: 1, completed_requests: 1, total_requests: 1 };
    },
    async results() {
      return {
        results: [{
          id: 1,
          test_id: 1,
          test_title: 'Hostile',
          test_stable_id: 'hostile',
          source_prompt: 'Hostile prompt',
          model_id: 1,
          model_name: 'Fake OK',
          provider_model_id: 'fake-ok',
          status: 'completed',
          raw_output: '<img src=x onerror=alert(1)>',
          error: null,
          settings: { temperature: 0 },
          timing_ms: 1,
          request_count: 1,
          artifacts: [{ id: 1, name: 'raw-output.txt', media_type: 'text/plain' }],
          rating: savedRating,
        }],
      };
    },
    async executeResult() {
      return {
        id: 1,
        command_category: 'python-single-file-container',
        status: 'unavailable',
        exit_code: null,
        timed_out: 0,
        stdout: '',
        stderr: '',
        capability_gap: 'Docker unavailable',
      };
    },
    async resultExecutions() {
      return { executions: [] };
    },
    async saveRating(
      _resultId: number,
      modelId: number | null,
      rating: number,
      notes: string,
    ) {
      savedRating = { winner_model_id: modelId, rating, notes };
      return { result_id: 1, ...savedRating };
    },
  };
}
