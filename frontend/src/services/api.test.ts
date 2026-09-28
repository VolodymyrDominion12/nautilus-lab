/**
 * How a failed request reads on screen: the FastAPI sentence, not the raw body.
 *
 * The Backtest Details modal showed `{"detail":"no live paper session '0d83e156-…'"}`
 * verbatim, which reads as a crash rather than as the API's answer.
 */
import { describe, expect, test } from 'vitest';

import { errorText } from './api';

describe('errorText', () => {
  test("a refusal shows FastAPI's detail sentence alone", () => {
    expect(errorText('{"detail":"no live paper session \'abc-123\'"}', 404)).toBe(
      "no live paper session 'abc-123'",
    );
  });

  test('a plain message field is read too', () => {
    expect(errorText('{"message":"Decision logging is disabled"}', 409)).toBe(
      'Decision logging is disabled',
    );
  });

  test('a validation list and a non-JSON body are kept as they came', () => {
    const validation = '{"detail":[{"loc":["body","bars"],"msg":"must be > 0"}]}';
    expect(errorText(validation, 422)).toBe(validation);
    expect(errorText('Bad Gateway', 502)).toBe('Bad Gateway');
  });

  test('an empty body still names the status', () => {
    expect(errorText('', 500)).toBe('Request failed (500)');
  });
});
