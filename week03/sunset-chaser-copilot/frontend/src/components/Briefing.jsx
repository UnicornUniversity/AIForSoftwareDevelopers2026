/**
 * The written summary of what is happening on the terminator right now.
 *
 * The text is rendered as a text node, never with `dangerouslySetInnerHTML` or
 * `innerHTML`. It can come from DeepSeek, which has read camera titles supplied
 * by Windy, so it is untrusted text that happens to be well-formed.
 */
export function Briefing({ briefing }) {
  if (!briefing?.text) return null;

  const isModeled = briefing.source === 'deepseek';

  return (
    <section className="briefing">
      <div className="briefing-head">
        <span
          className={`badge ${isModeled ? 'badge-model' : 'badge-deterministic'}`}
          title={
            isModeled
              ? 'Written by DeepSeek from the ranked candidates.'
              : 'Composed locally from the same numbers, because the model was unavailable.'
          }
        >
          {isModeled ? 'DeepSeek' : 'Computed locally'}
        </span>
        {isModeled && briefing.model && <span className="briefing-model">{briefing.model}</span>}
      </div>
      <p className="briefing-text">{briefing.text}</p>
    </section>
  );
}
