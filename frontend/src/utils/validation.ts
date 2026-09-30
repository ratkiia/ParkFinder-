/** Client-side mirror of the backend's city rules (backend/app/api/routes.py). The server stays authoritative. */
const CITY_PATTERN = /^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ .,'-]*$/;

export function validateCity(raw: string): string | null {
  const value = raw.trim();
  if (!value) return "Enter a US city, for example “Austin, TX”.";
  if (value.length < 2) return "City name must be at least 2 characters.";
  if (value.length > 100) return "City name must be 100 characters or fewer.";
  if (!CITY_PATTERN.test(value)) return "Use letters, spaces, periods, commas, apostrophes or hyphens only.";
  return null;
}
