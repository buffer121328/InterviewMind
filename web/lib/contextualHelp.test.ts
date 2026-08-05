import assert from 'node:assert/strict';
import test from 'node:test';

import { buildContextualHelpAttributes } from './contextualHelp.ts';

test('contextual help exposes a readable label and tooltip relationship', () => {
    assert.deepEqual(buildContextualHelpAttributes('凭据安全边界', 'credential-boundary'), {
        ariaLabel: '查看凭据安全边界',
        tooltipId: 'credential-boundary-tooltip',
    });
});
