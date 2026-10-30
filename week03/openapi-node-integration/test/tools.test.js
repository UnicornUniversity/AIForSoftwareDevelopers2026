import assert from 'node:assert/strict';
import { test } from 'node:test';

// tool-call.js reaches config.js through deepseek.js, which validates the key at
// import time. No network call is made: every loop test injects its own chat.
process.env.DEEPSEEK_API_KEY ??= 'test-key';

test('the stub returns the listed reading for a known city', async () => {
  const { getTemperature } = await import('../src/weather.js');

  const paris = getTemperature('Paris');

  assert.equal(paris.city, 'Paris');
  assert.equal(paris.country, 'France');
  assert.deepEqual(paris.temperature, { value: 14.5, unit: 'celsius' });
  assert.equal(paris.knownCity, true);
});

test('lookup ignores case, accents and surrounding whitespace', async () => {
  const { getTemperature } = await import('../src/weather.js');

  assert.equal(getTemperature('  REYKJAVÍK  ').city, 'Reykjavík');
  assert.equal(getTemperature('new    york').city, 'New York');
});

test('the requested unit is converted', async () => {
  const { getTemperature } = await import('../src/weather.js');

  assert.deepEqual(getTemperature('Paris', 'fahrenheit').temperature, {
    value: 58.1,
    unit: 'fahrenheit',
  });
});

test('an unlisted city gets a stable invented reading', async () => {
  const { getTemperature } = await import('../src/weather.js');

  const first = getTemperature('Atlantis');
  const again = getTemperature('atlantis');

  assert.equal(first.knownCity, false);
  assert.equal(first.country, 'Unknown');
  assert.deepEqual(first.temperature, again.temperature);
  assert.equal(first.conditions, again.conditions);
});

test('the stub rejects input it cannot answer', async () => {
  const { getTemperature } = await import('../src/weather.js');

  assert.throws(() => getTemperature(''), /city must not be empty/);
  assert.throws(() => getTemperature('   '), /city must not be empty/);
  assert.throws(() => getTemperature(42), /city must be a string/);
  assert.throws(() => getTemperature('Paris', 'kelvin'), /unit must be one of celsius, fahrenheit/);
});

test('runTool executes a valid call', async () => {
  const { runTool } = await import('../src/tools.js');

  const outcome = runTool('get_temperature', '{"city":"Paris","unit":"fahrenheit"}');

  assert.equal(outcome.ok, true);
  assert.deepEqual(outcome.arguments, { city: 'Paris', unit: 'fahrenheit' });
  assert.equal(outcome.result.temperature.value, 58.1);
});

test('runTool reports bad model output instead of throwing', async () => {
  const { runTool } = await import('../src/tools.js');

  assert.match(runTool('send_email', '{}').error, /Unknown tool "send_email"/);
  assert.match(runTool({ nested: true }, '{}').error, /Unknown tool/);
  assert.match(runTool('get_temperature', '{"city":').error, /not valid JSON/);
  assert.match(runTool('get_temperature', '["Paris"]').error, /must be a JSON object/);
  assert.match(
    runTool('get_temperature', '{"city":"Paris","admin":true}').error,
    /Unexpected argument\(s\): admin/,
  );
  assert.match(runTool('get_temperature', '{"city":null}').error, /city must be a string/);
  assert.match(runTool('get_temperature', '{"city":"Paris","unit":"kelvin"}').error, /unit must be/);
});

/** A chat stand-in that replays scripted replies and records what it was sent. */
function scriptedChat(replies) {
  const calls = [];

  async function chatFn(messages, options) {
    calls.push({ messages: messages.map((message) => ({ ...message })), options });
    const reply = replies.shift();
    if (reply === undefined) throw new Error('scripted chat ran out of replies');
    return reply;
  }

  return { chatFn, calls };
}

function weatherCall(id, city, extra = {}) {
  return {
    id,
    type: 'function',
    function: { name: 'get_temperature', arguments: JSON.stringify({ city, ...extra }) },
  };
}

function reply(overrides) {
  return {
    content: '',
    toolCalls: [],
    finishReason: 'tool_calls',
    model: 'deepseek-chat',
    usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
    elapsedMs: 100,
    ...overrides,
  };
}

test('askWithTools runs the requested tools and returns the final text', async () => {
  const { askWithTools } = await import('../src/tool-call.js');

  const { chatFn, calls } = scriptedChat([
    reply({ toolCalls: [weatherCall('call_1', 'Paris'), weatherCall('call_2', 'Reykjavík')] }),
    reply({
      content: 'Paris is 14.5 °C and Reykjavík is 2 °C, so Paris is warmer.',
      finishReason: 'stop',
      usage: { prompt_tokens: 40, completion_tokens: 20, total_tokens: 60 },
      elapsedMs: 150,
    }),
  ]);

  const result = await askWithTools('Compare Paris and Reykjavík.', { chatFn });

  assert.equal(result.answer, 'Paris is 14.5 °C and Reykjavík is 2 °C, so Paris is warmer.');
  assert.equal(result.rounds, 2);
  assert.equal(result.exhausted, false);
  assert.equal(result.toolCalls.length, 2);
  assert.equal(result.usage.total_tokens, 75);
  assert.equal(result.elapsedMs, 250);

  // The second request must carry the assistant's tool_calls and one `tool`
  // message per call id; the API rejects the history otherwise.
  assert.deepEqual(
    result.messages.map((message) => message.role),
    ['user', 'assistant', 'tool', 'tool', 'assistant'],
  );
  assert.deepEqual(
    result.messages.filter((message) => message.role === 'tool').map((message) => message.tool_call_id),
    ['call_1', 'call_2'],
  );
  assert.equal(result.messages[1].tool_calls.length, 2);
  assert.equal(JSON.parse(result.messages[2].content).city, 'Paris');
  assert.equal(JSON.parse(result.messages[3].content).city, 'Reykjavík');

  // The tool definitions were offered on every round.
  assert.equal(calls[0].options.tools[0].function.name, 'get_temperature');
  assert.equal(calls[1].options.tools[0].function.name, 'get_temperature');
});

test('a rejected tool call goes back to the model as an error result', async () => {
  const { askWithTools } = await import('../src/tool-call.js');

  const { chatFn } = scriptedChat([
    reply({
      toolCalls: [{ id: 'call_1', type: 'function', function: { name: 'get_temperature', arguments: '{oops' } }],
    }),
    reply({ content: 'I could not look that up.', finishReason: 'stop' }),
  ]);

  const result = await askWithTools('Temperature?', { chatFn });

  assert.equal(result.answer, 'I could not look that up.');
  assert.equal(result.toolCalls[0].error.includes('not valid JSON'), true);
  assert.equal(result.toolCalls[0].result, null);
  assert.match(JSON.parse(result.messages[2].content).error, /not valid JSON/);
});

test('the loop stops with exhausted:true when the model keeps calling tools', async () => {
  const { askWithTools } = await import('../src/tool-call.js');

  const { chatFn, calls } = scriptedChat([
    reply({ toolCalls: [weatherCall('call_1', 'Paris')] }),
    reply({ toolCalls: [weatherCall('call_2', 'Paris')] }),
    reply({ toolCalls: [weatherCall('call_3', 'Paris')] }),
  ]);

  const result = await askWithTools('Temperature?', { chatFn, maxRounds: 2 });

  assert.equal(result.exhausted, true);
  assert.equal(result.answer, '');
  assert.equal(result.rounds, 2);
  assert.equal(result.toolCalls.length, 2);
  assert.equal(calls.length, 2);
});

test('the earlier history is resent ahead of the new question', async () => {
  const { askWithTools } = await import('../src/tool-call.js');

  const { chatFn, calls } = scriptedChat([reply({ content: 'Paris.', finishReason: 'stop' })]);
  const history = [
    { role: 'user', content: 'Name a city.' },
    { role: 'assistant', content: 'Paris.' },
  ];

  await askWithTools('And its temperature?', { chatFn, history });

  assert.deepEqual(
    calls[0].messages.map((message) => message.content),
    ['Name a city.', 'Paris.', 'And its temperature?'],
  );
});

test('a blank question is refused before any request', async () => {
  const { askWithTools } = await import('../src/tool-call.js');

  await assert.rejects(askWithTools('   ', { chatFn: async () => assert.fail('must not call') }), {
    message: /question must be a non-empty string/,
  });
});
