import type { ApiError } from "../api/client";

interface StatusBannerProps {
  loading: boolean;
  error: ApiError | null;
  warnings: string[];
  summary: string | null;
  hint: string | null;
  onRetry: () => void;
}

/** Loading, result summary, warnings and errors. Uses live regions so changes are announced. */
export function StatusBanner({ loading, error, warnings, summary, hint, onRetry }: StatusBannerProps) {
  return (
    <div className="flex flex-col gap-2 px-3 pt-3">
      <p role="status" aria-live="polite" className="flex min-h-6 items-center gap-2 text-sm font-medium">
        {loading ? (
          <>
            <span
              aria-hidden="true"
              className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-emerald-800 border-t-transparent motion-reduce:animate-none"
            />
            Loading parks…
          </>
        ) : (
          (summary ?? "")
        )}
      </p>

      {hint && !loading && (
        <p className="rounded-md border-2 border-sky-800 bg-sky-50 px-3 py-2 text-sm">
          <span aria-hidden="true">ℹ </span>
          {hint}
        </p>
      )}

      {warnings.length > 0 && (
        <ul aria-label="Notices" className="flex flex-col gap-1">
          {warnings.map((w) => (
            <li key={w} className="rounded-md border-2 border-amber-700 bg-amber-50 px-3 py-2 text-sm">
              <span aria-hidden="true">⚠ </span>
              <span className="font-semibold">Notice: </span>
              {w}
            </li>
          ))}
        </ul>
      )}

      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-md border-2 border-red-800 bg-red-50 px-3 py-2 text-sm">
          <p>
            <span aria-hidden="true">✖ </span>
            <span className="font-semibold">Error: </span>
            {error.message}
            {error.requestId && (
              <span className="mt-1 block text-xs text-slate-700">
                Reference ID: <code className="select-all">{error.requestId}</code>
              </span>
            )}
          </p>
          {error.status !== 404 && error.status !== 422 && (
            <button
              type="button"
              onClick={onRetry}
              className="focus-ring rounded-md border-2 border-red-800 bg-white px-3 py-1 font-semibold hover:bg-red-100"
            >
              Try again
            </button>
          )}
        </div>
      )}
    </div>
  );
}
