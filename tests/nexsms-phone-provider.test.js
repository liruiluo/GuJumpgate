const assert = require('node:assert/strict');
const test = require('node:test');

require('../phone-sms/providers/nexsms.js');

function createProvider(overrides = {}) {
  return globalThis.PhoneSmsNexSmsProvider.createProvider({
    fetchImpl: overrides.fetchImpl,
    sleepWithStop: overrides.sleepWithStop || (async () => {}),
    throwIfStopped: overrides.throwIfStopped || (() => {}),
    addLog: overrides.addLog || (async () => {}),
  });
}

test('NexSMS provider requests activation through unified module path', async () => {
  const requests = [];
  const provider = createProvider({
    fetchImpl: async (url, init = {}) => {
      requests.push({ url, init });
      if (String(url).includes('/api/getCountryByService')) {
        return {
          ok: true,
          text: async () => JSON.stringify({
            code: 0,
            data: {
              countryId: 1,
              countryName: 'Testland',
              minPrice: 0.2,
              medianPrice: 0.3,
              maxPrice: 0.4,
              priceMap: {
                '0.2': 4,
                '0.4': 1,
              },
            },
          }),
        };
      }
      if (String(url).includes('/api/order/purchase')) {
        assert.equal(init.method, 'POST');
        const body = JSON.parse(init.body);
        assert.equal(body.countryId, 1);
        assert.equal(body.serviceCode, 'ot');
        assert.equal(body.price, 0.2);
        return {
          ok: true,
          text: async () => JSON.stringify({
            code: 0,
            data: {
              phoneNumber: '17198279624',
              countryId: 1,
              countryName: 'Testland',
              serviceCode: 'ot',
            },
          }),
        };
      }
      throw new Error(`unexpected url: ${url}`);
    },
  });

  const activation = await provider.requestActivation({
    nexSmsApiKey: 'demo-key',
    nexSmsCountryOrder: [1],
    nexSmsServiceCode: 'ot',
  });

  assert.equal(activation.provider, 'nexsms');
  assert.equal(activation.activationId, '17198279624');
  assert.equal(activation.phoneNumber, '17198279624');
  assert.equal(activation.countryId, 1);
  assert.equal(activation.countryLabel, 'Testland');
  assert.equal(requests.length, 2);
});

test('NexSMS provider polls latest sms message for code', async () => {
  const provider = createProvider({
    fetchImpl: async (url) => {
      assert.match(String(url), /\/api\/sms\/messages/);
      return {
        ok: true,
        text: async () => JSON.stringify({
          code: 0,
          data: {
            text: 'Your OpenAI verification code is 654321',
          },
        }),
      };
    },
  });

  const code = await provider.pollActivationCode({
    nexSmsApiKey: 'demo-key',
  }, {
    activationId: '17198279624',
    phoneNumber: '17198279624',
    provider: 'nexsms',
  }, {
    timeoutMs: 100,
    intervalMs: 1,
    maxRounds: 1,
  });

  assert.equal(code, '654321');
});
