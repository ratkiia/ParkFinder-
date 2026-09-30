import { useId, useState, type FormEvent } from "react";

import { validateCity } from "../utils/validation";

interface SearchBarProps {
  onSearch: (city: string) => void;
  busy?: boolean;
}

export function SearchBar({ onSearch, busy = false }: SearchBarProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();
  const errorId = useId();
  const hintId = useId();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = validateCity(value);
    setError(problem);
    if (!problem) onSearch(value.trim());
  }

  return (
    <form role="search" onSubmit={handleSubmit} noValidate className="flex w-full max-w-xl flex-col gap-1">
      <label htmlFor={inputId} className="text-sm font-semibold">
        US city
      </label>
      <div className="flex gap-2">
        <input
          id={inputId}
          type="search"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="e.g. Austin, TX"
          autoComplete="address-level2"
          maxLength={100}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${errorId} ${hintId}` : hintId}
          className="focus-ring min-w-0 flex-1 rounded-md border-2 border-slate-400 bg-white px-3 py-2 text-base aria-[invalid=true]:border-red-700"
        />
        <button
          type="submit"
          disabled={busy}
          className="focus-ring rounded-md bg-emerald-800 px-4 py-2 font-semibold text-white hover:bg-emerald-900 disabled:cursor-wait disabled:opacity-70"
        >
          {busy ? "Searching…" : "Find parks"}
        </button>
      </div>
      <p id={hintId} className="text-xs text-slate-600">
        Include the state for best results, e.g. “Portland, OR”.
      </p>
      {error && (
        <p id={errorId} role="alert" className="text-sm font-medium text-red-800">
          <span aria-hidden="true">⚠ </span>
          {error}
        </p>
      )}
    </form>
  );
}
