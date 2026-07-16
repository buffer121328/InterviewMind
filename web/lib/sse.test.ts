import assert from 'node:assert/strict';
import test from 'node:test';

import { parseSseFrames } from './sse.ts';

test('parseSseFrames buffers partial frames', () => {
    const first = parseSseFrames('', 'data: {"a"');
    assert.deepEqual(first.frames, []);
    assert.equal(first.buffer, 'data: {"a"');

    const second = parseSseFrames(first.buffer, ':1}\n\n');
    assert.equal(second.buffer, '');
    assert.deepEqual(second.frames, [{ data: '{"a":1}', event: undefined, id: undefined }]);
});

test('parseSseFrames parses multiple frames from one chunk', () => {
    const parsed = parseSseFrames('', 'data: one\n\ndata: two\n\n');
    assert.equal(parsed.buffer, '');
    assert.deepEqual(parsed.frames.map(frame => frame.data), ['one', 'two']);
});

test('parseSseFrames joins multiline data fields', () => {
    const parsed = parseSseFrames('', 'data: line1\ndata: line2\n\n');
    assert.equal(parsed.frames[0].data, 'line1\nline2');
});

test('parseSseFrames keeps id and event fields and ignores comments', () => {
    const parsed = parseSseFrames('', ': keepalive\nid: 7\nevent: run.completed\ndata: {"ok":true}\n\n');
    assert.deepEqual(parsed.frames[0], {
        id: '7',
        event: 'run.completed',
        data: '{"ok":true}',
    });
});
