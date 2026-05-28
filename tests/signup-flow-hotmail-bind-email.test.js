const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function loadSignupFlowHelpersModule() {
  const filePath = path.join(__dirname, '..', 'background', 'signup-flow-helpers.js');
  const source = fs.readFileSync(filePath, 'utf8');
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
  };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  vm.runInNewContext(source, sandbox, { filename: filePath });
  return sandbox.MultiPageSignupFlowHelpers;
}

test('phone bind-email reuses current Hotmail account without marking it during email resolution', async () => {
  const module = loadSignupFlowHelpersModule();
  const ensureCalls = [];
  const persistedEmails = [];
  const state = {
    currentHotmailAccountId: 'hotmail-1',
    accountIdentifierType: 'phone',
    accountIdentifier: '+15550001111',
    signupPhoneNumber: '+15550001111',
    mailProvider: 'hotmail-api',
    email: '',
  };

  const helpers = module.createSignupFlowHelpers({
    ensureHotmailAccountForFlow: async (options = {}) => {
      ensureCalls.push(options);
      return {
        id: 'hotmail-1',
        email: 'base@outlook.com',
        registrationAliasEmail: 'base+fp1@outlook.com',
      };
    },
    isHotmailProvider: (candidate = {}) => candidate.mailProvider === 'hotmail-api',
    persistRegistrationEmailState: async (_state, email, options = {}) => {
      persistedEmails.push({ email, options });
    },
  });

  const email = await helpers.resolveSignupEmailForFlow(state, {
    preserveAccountIdentity: true,
  });

  assert.equal(email, 'base+fp1@outlook.com');
  assert.equal(ensureCalls.length, 1);
  assert.equal(ensureCalls[0].preferredAccountId, 'hotmail-1');
  assert.equal(ensureCalls[0].allowUsedCurrent, true);
  assert.equal(ensureCalls[0].markUsed, false);
  assert.equal(persistedEmails.length, 1);
  assert.equal(persistedEmails[0].email, 'base+fp1@outlook.com');
  assert.equal(persistedEmails[0].options.preserveAccountIdentity, true);
});
