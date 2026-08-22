import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('all-Agent quick smoke client contract targets the server-owned endpoint', () => {
    const source = readFileSync(new URL('./api/evaluations.ts', import.meta.url), 'utf8');

    assert.match(source, /interface EvaluationAllQuickRunRequest[\s\S]*api_config/);
    assert.match(source, /allAgentsQuickRun:[\s\S]*'\/api\/evaluations\/quick-runs\/all'/);
    assert.match(source, /headers:\s*\{\s*'Idempotency-Key': idempotencyKey\s*\}/);
});
