import { useMemo, useState } from 'react';

import { preview, queryTerms, splitHighlight } from '../lib/highlight.js';

function ChunkCard({ chunk, terms, maxScore }) {
  const [open, setOpen] = useState(false);
  const visible = open ? chunk.text : preview(chunk.text);
  const segments = splitHighlight(visible, terms);
  const share = maxScore > 0 ? Math.max(5, (chunk.score / maxScore) * 100) : 0;

  return (
    <li className="chunk">
      <div className="chunk__head">
        <span className="chunk__rank" aria-label={`Passage ${chunk.rank}`}>
          {chunk.rank}
        </span>
        <div className="chunk__where">
          <span className="chunk__volume">Volume {chunk.volume}</span>
          <h3 title={chunk.chapter || 'Untitled chapter'}>
            {chunk.chapter || 'Untitled chapter'}
          </h3>
        </div>
        <span className="chunk__score" title="Cosine similarity to the question">
          {chunk.score.toFixed(2)}
        </span>
      </div>

      <div className="chunk__bar" aria-hidden="true">
        <span style={{ width: `${share}%` }} />
      </div>

      <p className="chunk__text">
        {segments.map((segment, index) =>
          segment.match ? (
            <mark key={index}>{segment.text}</mark>
          ) : (
            <span key={index}>{segment.text}</span>
          ),
        )}
      </p>

      {chunk.text.length > 360 && (
        <button
          type="button"
          className="chunk__toggle"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
        >
          {open ? 'Show less' : 'Show full passage'}
        </button>
      )}
    </li>
  );
}

export function ChunkList({ chunks, question }) {
  const terms = useMemo(() => queryTerms(question), [question]);

  if (chunks.length === 0) {
    return (
      <p className="empty">
        Retrieved passages appear here, ranked by similarity to your question.
        Each one is a chunk of roughly 1,500 characters from the six volumes.
      </p>
    );
  }

  const maxScore = chunks[0].score;

  return (
    <ol className="chunks">
      {chunks.map((chunk) => (
        <ChunkCard
          key={`${chunk.id}-${chunk.rank}`}
          chunk={chunk}
          terms={terms}
          maxScore={maxScore}
        />
      ))}
    </ol>
  );
}
