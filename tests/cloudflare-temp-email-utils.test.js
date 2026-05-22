const assert = require('node:assert/strict');
const test = require('node:test');

const cloudflareTempEmailUtils = require('../cloudflare-temp-email-utils.js');
const hotmailUtils = require('../hotmail-utils.js');

test('Cloudflare Temp Email normalizes HTML body fields for code matching', () => {
  const receivedAt = Math.floor(Date.UTC(2026, 4, 21, 0, 28, 9) / 1000);
  const messages = cloudflareTempEmailUtils.normalizeCloudflareTempEmailMailApiMessages({
    rows: [
      {
        id: 17,
        address: 'tmpv8ks2z13ni@example.com',
        from: 'ChatGPT <noreply@tm.openai.com>',
        subject: '你的 ChatGPT 临时验证码',
        created_at: receivedAt,
        html: '<main><p>输入此临时验证码以继续：</p><div>991207</div></main>',
      },
    ],
  });

  assert.equal(messages.length, 1);
  assert.equal(messages[0].bodyPreview.includes('<main>'), false);
  assert.equal(messages[0].bodyPreview.includes('991207'), true);
  assert.equal(messages[0].receivedDateTime, '2026-05-21T00:28:09.000Z');

  const matchResult = hotmailUtils.pickVerificationMessageWithTimeFallback(messages, {
    afterTimestamp: Date.UTC(2026, 4, 21, 0, 28, 0),
  });

  assert.equal(matchResult.match.code, '991207');
});

test('Cloudflare Temp Email reads nested content objects instead of stringifying metadata', () => {
  const messages = cloudflareTempEmailUtils.normalizeCloudflareTempEmailMailApiMessages([
    {
      id: 18,
      address: 'tmpv8ks2z13ni@example.com',
      sender: 'ChatGPT <noreply@tm.openai.com>',
      subject: '你的 ChatGPT 临时验证码',
      body: {
        html: '<section><strong>654321</strong></section>',
      },
      date: '2026-05-21T00:28:09.000Z',
    },
  ]);

  assert.equal(messages[0].bodyPreview.includes('[object Object]'), false);
  assert.equal(messages[0].bodyPreview.includes('654321'), true);
  assert.equal(hotmailUtils.extractVerificationCodeFromMessage(messages[0]), '654321');
});
