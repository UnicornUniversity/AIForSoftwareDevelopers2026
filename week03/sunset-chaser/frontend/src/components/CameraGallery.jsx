import { CameraCard } from './CameraCard.jsx';
import { EmptyState } from './EmptyState.jsx';

/**
 * A titled grid of camera cards.
 *
 * The empty case is handled here rather than by the caller because "this section
 * has no cameras" is information, not an error - it is the expected result of a
 * terminator crossing open ocean, and it needs an explanation rather than
 * nothing.
 */
export function CameraGallery({
  title,
  description,
  cameras = [],
  emptyTitle,
  emptyDetail,
  hints = [],
}) {
  return (
    <section className="gallery">
      <header className="gallery-header">
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </header>

      {cameras.length === 0 ? (
        <EmptyState title={emptyTitle} detail={emptyDetail} hints={hints} />
      ) : (
        <div className="gallery-grid">
          {cameras.map((camera) => (
            <CameraCard key={camera.webcamId} camera={camera} />
          ))}
        </div>
      )}
    </section>
  );
}
