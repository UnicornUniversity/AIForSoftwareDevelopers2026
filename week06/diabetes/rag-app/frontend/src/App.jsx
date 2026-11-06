import { useCallback, useEffect, useRef, useState } from 'react';

import { REQUEST_TIMEOUT_MS, askQuestion, fetchHealth } from './api.js';
import { AnswerPanel } from './components/AnswerPanel.jsx';
import { ChunkList } from './components/ChunkList.jsx';
import { StatusPill } from './components/StatusPill.jsx';

const SUGGESTIONS = [
  'What HbA1c confirms diabetes?',
  'How is diabetic ketoacidosis managed?',
  'When is metformin contraindicated?',
  'How is prediabetes defined?',
];

/** Mirrors MAX_QUESTION_CHARS; the server is the authority and returns 400. */
const MAX_QUESTION_CHARS = 500;

const FALLBACK_DISCLAIMER = 'Educational reference only — not medical advice.';

export default function App() {
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState('idle'); // idle | loading | error
  const [error, setError] = useState(null);
  const [slow, setSlow] = useState(false);
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);

  const abortRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then(setHealth)
      .catch((err) => {
        if (err.name !== 'AbortError') setHealthError(err.message);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);

  // A slow model link is normal here (13-46 s has been measured), so after a
  // few seconds the waiting message says so instead of looking frozen.
  useEffect(() => {
    if (status !== 'loading') {
      setSlow(false);
      return undefined;
    }
    const timer = setTimeout(() => setSlow(true), 4000);
    return () => clearTimeout(timer);
  }, [status]);

  const runSearch = useCallback(async (text) => {
    const asked = text.trim();
    if (asked === '') {
      setError('Type a question first.');
      inputRef.current?.focus();
      return;
    }

    // Supersede any request still in flight, then start this one.
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const timer = setTimeout(
      () => controller.abort('timeout'),
      REQUEST_TIMEOUT_MS,
    );

    setStatus('loading');
    setError(null);
    setResult(null);

    try {
      const body = await askQuestion(asked, controller.signal);
      if (abortRef.current !== controller) return;
      setResult(body);
      setStatus('idle');
    } catch (err) {
      if (abortRef.current !== controller) return;

      if (controller.signal.aborted) {
        setError(
          `The request timed out after ${REQUEST_TIMEOUT_MS / 1000} seconds. ` +
            'The backend may still be waiting on the model; try again.',
        );
      } else if (err instanceof TypeError) {
        setError(
          'Could not reach the backend. Start it with `npm start` in ' +
            'week06/diabetes/rag-app/backend, then reload the page.',
        );
      } else {
        setError(err.message);
      }
      setStatus('error');
    } finally {
      clearTimeout(timer);
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, []);

  // `?q=...` makes a question shareable and lets the page be opened directly on
  // a result. It is a convenience, not a second way to ask: the form is still
  // the way a question is entered.
  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get('q');
    if (initial !== null && initial.trim() !== '') {
      setQuestion(initial);
      runSearch(initial);
    }
  }, [runSearch]);

  function handleSubmit(event) {
    event.preventDefault();
    runSearch(question);
  }

  function askSuggestion(suggestion) {
    setQuestion(suggestion);
    runSearch(suggestion);
  }

  const loading = status === 'loading';
  const disclaimer = health?.disclaimer ?? result?.disclaimer ?? FALLBACK_DISCLAIMER;

  return (
    <div className="app">
      <header className="masthead">
        <div className="masthead__inner">
          <p className="eyebrow">AI for Software Developers · Week 06</p>
          <h1 className="masthead__title">
            Ask the <span>Diabetes</span> KB
          </h1>
          <p className="masthead__lede">
            Questions answered from a twelve-document educational knowledge
            base — diagnostic thresholds, acute complications and medications,
            retrieved section by section.
          </p>
          <div className="masthead__status">
            <StatusPill health={health} error={healthError} />
            {health?.corpus && (
              <span className="masthead__stat">
                {health.corpus.chunks} sections ·{' '}
                {health.corpus.documents} documents
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="main">
        {healthError && (
          <p className="notice" role="status">
            The backend is not reachable at <code>/api</code>. Start it with{' '}
            <code>npm start</code> in <code>week06/diabetes/rag-app/backend</code>,
            then reload.
          </p>
        )}

        <form className="search" onSubmit={handleSubmit} role="search">
          <label className="search__label" htmlFor="question">
            Your question about diabetes
          </label>
          <div className="search__row">
            <input
              id="question"
              ref={inputRef}
              className="search__input"
              type="text"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="What HbA1c confirms diabetes?"
              autoComplete="off"
              maxLength={MAX_QUESTION_CHARS}
              disabled={loading}
            />
            <button className="search__button" type="submit" disabled={loading}>
              {loading ? (
                <>
                  <span className="spinner" aria-hidden="true" />
                  Searching…
                </>
              ) : (
                'Search'
              )}
            </button>
          </div>

          <div className="suggestions">
            <span className="suggestions__label">Try</span>
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                className="suggestions__chip"
                onClick={() => askSuggestion(suggestion)}
                disabled={loading}
              >
                {suggestion}
              </button>
            ))}
          </div>

          {error && (
            <p className="alert" role="alert">
              {error}
            </p>
          )}
        </form>

        <div className="results">
          <AnswerPanel
            result={result}
            loading={loading}
            slow={slow}
            disclaimer={disclaimer}
          />
          <section className="panel panel--chunks" aria-labelledby="chunks-title">
            <div className="panel__head">
              <h2 id="chunks-title">Related sections</h2>
              <span className="panel__meta">
                {result ? `${result.chunks.length} retrieved` : 'Top matches'}
              </span>
            </div>
            <ChunkList
              chunks={result?.chunks ?? []}
              question={result?.question ?? ''}
            />
          </section>
        </div>
      </main>

      <footer className="footer">
        <p className="footer__disclaimer">{disclaimer}</p>
        <p>
          Vector retrieval through ChromaDB over {health?.corpus?.chunks ?? 48}{' '}
          sections from <code>week06/diabetes</code>
          {health?.answer.hasLlmKey && health.answer.mode !== 'extractive'
            ? ` · answers synthesised by ${health.answer.model}`
            : ' · answers quoted from the retrieved text'}
          .
        </p>
        <p className="footer__fine">
          Answers can still be wrong; the sections beside each answer are the
          evidence to check them against. For personal health decisions, consult
          a qualified clinician.
        </p>
      </footer>
    </div>
  );
}
