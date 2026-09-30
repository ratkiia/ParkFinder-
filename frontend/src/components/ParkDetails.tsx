import { useEffect, useRef, useState, type ReactNode } from "react";

import type { Park } from "../api/types";
import { formatAcreage, formatAmenity, formatSource } from "../utils/format";

interface ParkDetailsProps {
  park: Park;
  onBack: () => void;
}

function NotAvailable({ what }: { what: string }) {
  return <span className="italic text-slate-600">{`${what} not available`}</span>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-bold uppercase tracking-wide text-slate-600">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function ParkImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return <p className="rounded bg-slate-100 p-3 text-sm italic text-slate-600">Image could not be loaded.</p>;
  }
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className="aspect-video w-full rounded-md bg-slate-100 object-cover"
    />
  );
}

/** Shows every field we have for a park; missing information is labelled, never guessed. */
export function ParkDetails({ park, onBack }: ParkDetailsProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus(); // move focus to the new content for keyboard and screen-reader users
  }, [park.id]);

  return (
    <article aria-labelledby={`park-${park.id}-title`} className="flex flex-col gap-4 p-4">
      <button
        type="button"
        onClick={onBack}
        className="focus-ring self-start rounded-md border-2 border-slate-400 bg-white px-3 py-1 text-sm font-semibold hover:bg-slate-100"
      >
        <span aria-hidden="true">← </span>Back to results
      </button>

      <h2 id={`park-${park.id}-title`} ref={headingRef} tabIndex={-1} className="focus-ring text-2xl font-bold">
        {park.name}
      </h2>

      {park.images.length > 0 ? (
        <div className="flex flex-col gap-2">
          {park.images.map((src, i) => (
            <ParkImage key={src} src={src} alt={`Photo ${i + 1} of ${park.name}`} />
          ))}
        </div>
      ) : (
        <p className="rounded bg-slate-100 p-3 text-sm italic text-slate-600">No images available.</p>
      )}

      <dl className="flex flex-col gap-3">
        <Field label="Address">{park.location.address ?? <NotAvailable what="Address" />}</Field>
        <Field label="Description">
          {park.description ? <p className="whitespace-pre-line">{park.description}</p> : <NotAvailable what="Description" />}
        </Field>
        <Field label="Hours">{park.hours ?? <NotAvailable what="Hours" />}</Field>
        <Field label="Amenities">
          {park.amenities.length > 0 ? (
            <ul className="flex flex-wrap gap-2">
              {park.amenities.map((a) => (
                <li key={a} className="rounded-full border border-emerald-800 px-2 py-0.5 text-sm">
                  {formatAmenity(a)}
                </li>
              ))}
            </ul>
          ) : (
            <NotAvailable what="Amenity information" />
          )}
        </Field>
        {park.acreage !== null && <Field label="Size">{formatAcreage(park.acreage)}</Field>}
        {park.rating !== null && <Field label="Rating">{`${park.rating.toFixed(1)} out of 5`}</Field>}
        {park.website && (
          <Field label="Website">
            <a
              href={park.website}
              target="_blank"
              rel="noopener noreferrer"
              className="focus-ring break-all text-emerald-900 underline"
            >
              {park.website}
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          </Field>
        )}
        <Field label="Coordinates">{`${park.location.lat.toFixed(5)}, ${park.location.lng.toFixed(5)}`}</Field>
        <Field label="Data source">{formatSource(park.source)}</Field>
      </dl>
    </article>
  );
}
