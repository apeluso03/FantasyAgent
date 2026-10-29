import { Link } from "react-router-dom";

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="card flex flex-col items-center gap-3 py-10 text-center">
      <p className="text-neutral-600 dark:text-neutral-300">{message}</p>
      <Link to="/settings" className="btn-primary">
        Go to Settings to sync
      </Link>
    </div>
  );
}
