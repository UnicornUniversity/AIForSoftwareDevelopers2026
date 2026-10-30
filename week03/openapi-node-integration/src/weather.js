/**
 * Stub weather service for the tool-calling demo (`src/tool-call.js`).
 *
 * It stands in for a real HTTP API: the call is local and synchronous, but the
 * argument checks and the response shape are what a live service would give.
 * The numbers are invented — six cities are fixed so a demo reads the same
 * every time, and any other city derives from a hash of its name, so repeated
 * runs stay stable too. Nothing here claims to be a live reading.
 */

const CITIES = new Map([
  ['paris', { city: 'Paris', country: 'France', celsius: 14.5, conditions: 'Partly cloudy' }],
  ['reykjavik', { city: 'Reykjavík', country: 'Iceland', celsius: 2, conditions: 'Light snow' }],
  ['cairo', { city: 'Cairo', country: 'Egypt', celsius: 31, conditions: 'Clear' }],
  ['sydney', { city: 'Sydney', country: 'Australia', celsius: 22, conditions: 'Sunny' }],
  ['tokyo', { city: 'Tokyo', country: 'Japan', celsius: 18.5, conditions: 'Overcast' }],
  [
    'new york',
    { city: 'New York', country: 'United States', celsius: 11, conditions: 'Rain showers' },
  ],
]);

const CONDITIONS = ['Clear', 'Partly cloudy', 'Overcast', 'Light rain', 'Windy'];

/** The units the stub accepts, and that the tool schema offers the model. */
export const SUPPORTED_UNITS = ['celsius', 'fahrenheit'];

/** Case-, accent- and whitespace-insensitive lookup key. */
function normalize(city) {
  return city
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

function titleCase(text) {
  return text.replace(/\b\p{L}/gu, (letter) => letter.toUpperCase());
}

function hashName(name) {
  let hash = 0;
  for (const character of name) {
    hash = (hash * 31 + character.codePointAt(0)) >>> 0;
  }
  return hash;
}

/** An invented reading for a city that is not in the table: -12.0 .. 33.9 °C. */
function stubReading(key) {
  const hash = hashName(key);
  return {
    city: titleCase(key),
    country: 'Unknown',
    celsius: Math.round((-12 + (hash % 460) / 10) * 10) / 10,
    conditions: CONDITIONS[hash % CONDITIONS.length],
  };
}

function toFahrenheit(celsius) {
  return Math.round((celsius * (9 / 5) + 32) * 10) / 10;
}

/**
 * Return the stub temperature for a city by name.
 *
 * @param {string} city   City name; case and accents do not matter.
 * @param {'celsius'|'fahrenheit'} [unit]
 * @returns {{
 *   city: string,
 *   country: string,
 *   temperature: {value: number, unit: string},
 *   conditions: string,
 *   knownCity: boolean,
 *   source: string
 * }}
 */
export function getTemperature(city, unit = 'celsius') {
  if (typeof city !== 'string') throw new Error('city must be a string.');
  if (!SUPPORTED_UNITS.includes(unit)) {
    throw new Error(`unit must be one of ${SUPPORTED_UNITS.join(', ')}.`);
  }

  const key = normalize(city);
  if (key === '') throw new Error('city must not be empty.');
  if (key.length > 80) throw new Error('city must be 80 characters or fewer.');

  const entry = CITIES.get(key);
  const reading = entry ?? stubReading(key);

  return {
    city: reading.city,
    country: reading.country,
    temperature:
      unit === 'fahrenheit'
        ? { value: toFahrenheit(reading.celsius), unit }
        : { value: reading.celsius, unit },
    conditions: reading.conditions,
    knownCity: entry !== undefined,
    source: 'stub weather service (invented data, not a live reading)',
  };
}
