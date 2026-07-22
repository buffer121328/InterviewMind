import assert from 'node:assert/strict';
import test from 'node:test';

import { getAudioUrl } from './audioStorage.ts';

test('getAudioUrl keeps static paths relative when the API URL is /api', async () => {
    const previousApiUrl = process.env.NEXT_PUBLIC_API_URL;
    process.env.NEXT_PUBLIC_API_URL = '/api';

    try {
        assert.equal(await getAudioUrl('static/audio/foo.wav'), '/static/audio/foo.wav');
    } finally {
        if (previousApiUrl === undefined) {
            delete process.env.NEXT_PUBLIC_API_URL;
        } else {
            process.env.NEXT_PUBLIC_API_URL = previousApiUrl;
        }
    }
});

test('getAudioUrl preserves remote static resource bases', async () => {
    const previousApiUrl = process.env.NEXT_PUBLIC_API_URL;
    process.env.NEXT_PUBLIC_API_URL = 'https://api.example.test/';

    try {
        assert.equal(
            await getAudioUrl('static/audio/foo.wav'),
            'https://api.example.test/static/audio/foo.wav',
        );
    } finally {
        if (previousApiUrl === undefined) {
            delete process.env.NEXT_PUBLIC_API_URL;
        } else {
            process.env.NEXT_PUBLIC_API_URL = previousApiUrl;
        }
    }
});

test('getAudioUrl removes the API path from remote static resource bases', async () => {
    const previousApiUrl = process.env.NEXT_PUBLIC_API_URL;

    try {
        for (const apiUrl of [
            'https://interview.example.com/api',
            'https://interview.example.com/api/',
        ]) {
            process.env.NEXT_PUBLIC_API_URL = apiUrl;
            assert.equal(
                await getAudioUrl('static/audio/foo.wav'),
                'https://interview.example.com/static/audio/foo.wav',
            );
        }
    } finally {
        if (previousApiUrl === undefined) {
            delete process.env.NEXT_PUBLIC_API_URL;
        } else {
            process.env.NEXT_PUBLIC_API_URL = previousApiUrl;
        }
    }
});
