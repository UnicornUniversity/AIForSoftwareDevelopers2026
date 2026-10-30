/**
 * Tools offered to the model, and the dispatcher that runs them.
 *
 * The model's output is untrusted, so a call is checked in layers: the tool
 * name must exist in this registry, `arguments` arrives as a JSON *string* and
 * is parsed defensively, every key and value is validated, and only then does
 * the handler see it. A rejected call comes back as `{ error }` and is fed to
 * the model as the tool result, so it can correct itself on the next round
 * instead of failing the whole request.
 */
import { SUPPORTED_UNITS, getTemperature } from './weather.js';

/** The tool definitions, in the shape chat-completions expects. */
export const TOOLS = [
  {
    type: 'function',
    function: {
      name: 'get_temperature',
      description:
        'Get the current temperature and sky conditions for a city, by name. ' +
        'Use it whenever the user asks how warm or cold it is somewhere. ' +
        'The data is a stub: invented but stable, not a live forecast.',
      parameters: {
        type: 'object',
        properties: {
          city: {
            type: 'string',
            description: 'City name, for example "Paris" or "New York".',
          },
          unit: {
            type: 'string',
            enum: SUPPORTED_UNITS,
            description: 'Temperature unit. Defaults to celsius.',
          },
        },
        required: ['city'],
        additionalProperties: false,
      },
    },
  },
];

const handlers = new Map([
  [
    'get_temperature',
    {
      allowed: new Set(['city', 'unit']),
      run: ({ city, unit = 'celsius' }) => getTemperature(city, unit),
    },
  ],
]);

/** Names a caller may dispatch to, for error messages. */
export const toolNames = [...handlers.keys()];

function parseArguments(raw) {
  if (raw === undefined || raw === null || raw === '') return {};
  if (typeof raw === 'object') return raw; // some providers pre-parse
  if (typeof raw !== 'string') throw new Error('Tool arguments must be a JSON string.');

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('Tool arguments are not valid JSON.');
  }

  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Tool arguments must be a JSON object.');
  }
  return parsed;
}

/**
 * Run one tool call requested by the model.
 *
 * @param {unknown} name           Tool name as the model wrote it.
 * @param {unknown} rawArguments   JSON string, or an already-parsed object.
 * @returns {{
 *   ok: boolean,
 *   name: unknown,
 *   arguments?: object,
 *   result?: object,
 *   error?: string
 * }}
 *   Never throws: the reason travels back to the model as a tool result.
 */
export function runTool(name, rawArguments) {
  const tool = handlers.get(name);
  if (tool === undefined) {
    return {
      ok: false,
      name,
      error: `Unknown tool "${String(name)}". Available: ${toolNames.join(', ')}.`,
    };
  }

  try {
    const args = parseArguments(rawArguments);

    const unexpected = Object.keys(args).filter((key) => !tool.allowed.has(key));
    if (unexpected.length > 0) {
      throw new Error(`Unexpected argument(s): ${unexpected.join(', ')}.`);
    }

    return { ok: true, name, arguments: args, result: tool.run(args) };
  } catch (err) {
    return { ok: false, name, error: err.message };
  }
}
