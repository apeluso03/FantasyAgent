export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="card flex flex-col items-center gap-3 border-rose-200 py-10 text-center dark:border-rose-900">
      <p className="text-rose-700 dark:text-rose-300">{message}</p>
      <button className="btn-secondary" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
