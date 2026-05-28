// phone-sms/providers/sms-verification-number.js - SMS Verification Number 接码平台适配层
(function attachSmsVerificationNumberProvider(root, factory) {
  root.PhoneSmsVerificationNumberProvider = factory(root);
})(typeof self !== 'undefined' ? self : globalThis, function createSmsVerificationNumberProviderModule(root) {
  const PROVIDER_ID = 'sms-verification-number';
  const DEFAULT_BASE_URL = 'https://sms-verification-number.com/stubs/handler_api';
  const DEFAULT_SERVICE_CODE = 'dr';
  const DEFAULT_SERVICE_LABEL = 'OpenAI';
  const DEFAULT_COUNTRY_ID = 33;
  const DEFAULT_COUNTRY_LABEL = 'Colombia';
  const DEFAULT_LANG = 'en';
  const DEFAULT_PRICES_ACTION = 'getPrices';

  function translateState(state = {}) {
    return {
      ...state,
      smsBowerApiKey: state.smsVerificationNumberApiKey ?? state.smsBowerApiKey ?? '',
      smsBowerBaseUrl: state.smsVerificationNumberBaseUrl ?? state.smsBowerBaseUrl ?? DEFAULT_BASE_URL,
      smsBowerServiceCode: state.smsVerificationNumberServiceCode ?? state.smsBowerServiceCode ?? DEFAULT_SERVICE_CODE,
      smsBowerCountryId: state.smsVerificationNumberCountryId ?? state.smsBowerCountryId ?? DEFAULT_COUNTRY_ID,
      smsBowerCountryLabel: state.smsVerificationNumberCountryLabel ?? state.smsBowerCountryLabel ?? DEFAULT_COUNTRY_LABEL,
      smsBowerCountryFallback: state.smsVerificationNumberCountryFallback ?? state.smsBowerCountryFallback ?? [],
      smsBowerMinPrice: state.smsVerificationNumberMinPrice ?? state.smsBowerMinPrice ?? '',
      smsBowerMaxPrice: state.smsVerificationNumberMaxPrice ?? state.smsBowerMaxPrice ?? '',
      smsBowerPreferredPrice: state.smsVerificationNumberPreferredPrice ?? state.smsBowerPreferredPrice ?? '',
      smsBowerLang: DEFAULT_LANG,
      smsBowerPricesAction: DEFAULT_PRICES_ACTION,
    };
  }

  function translateActivation(activation) {
    if (!activation || typeof activation !== 'object' || Array.isArray(activation)) {
      return activation;
    }
    return {
      ...activation,
      provider: PROVIDER_ID,
    };
  }

  function relabelText(value) {
    return String(value || '').replace(/SMSBower/g, 'SMS Verification Number');
  }

  function wrapError(error) {
    if (!error) {
      return error;
    }
    if (typeof error === 'string') {
      return relabelText(error);
    }
    const nextError = new Error(relabelText(error.message || String(error)));
    Object.keys(error).forEach((key) => {
      if (key === 'message') {
        return;
      }
      nextError[key] = error[key];
    });
    if (error.payload !== undefined) {
      nextError.payload = error.payload;
    }
    return nextError;
  }

  async function callWithState(baseProvider, methodName, state, ...args) {
    try {
      const result = await baseProvider[methodName](translateState(state), ...args);
      if (methodName === 'requestActivation') {
        return translateActivation(result);
      }
      if (typeof result === 'string') {
        return relabelText(result);
      }
      return result;
    } catch (error) {
      throw wrapError(error);
    }
  }

  function createProvider(deps = {}) {
    const baseFactory = root?.PhoneSmsBowerProvider?.createProvider;
    if (typeof baseFactory !== 'function') {
      throw new Error('SMS Verification Number 依赖 SMSBower provider，但对应模块未加载。');
    }
    const baseProvider = baseFactory(deps);
    return {
      id: PROVIDER_ID,
      label: 'SMS Verification Number',
      defaultCountryId: DEFAULT_COUNTRY_ID,
      defaultCountryLabel: DEFAULT_COUNTRY_LABEL,
      defaultProduct: DEFAULT_SERVICE_LABEL,
      defaultServiceCode: DEFAULT_SERVICE_CODE,
      normalizeCountryId: baseProvider.normalizeCountryId,
      normalizeCountryLabel: baseProvider.normalizeCountryLabel,
      normalizeCountryFallback: baseProvider.normalizeCountryFallback,
      normalizeMaxPrice: baseProvider.normalizeMaxPrice,
      normalizeServiceCode: baseProvider.normalizeServiceCode,
      resolveCountryCandidates: (state) => baseProvider.resolveCountryCandidates(translateState(state)),
      requestActivation: (state, options) => callWithState(baseProvider, 'requestActivation', state, options),
      finishActivation: (state, activation) => callWithState(baseProvider, 'finishActivation', state, activation),
      cancelActivation: (state, activation) => callWithState(baseProvider, 'cancelActivation', state, activation),
      banActivation: (state, activation) => callWithState(baseProvider, 'banActivation', state, activation),
      requestAdditionalSms: (state, activation) => callWithState(baseProvider, 'requestAdditionalSms', state, activation),
      pollActivationCode: (state, activation, options) => callWithState(baseProvider, 'pollActivationCode', state, activation, options),
      fetchBalance: (state) => callWithState(baseProvider, 'fetchBalance', state),
      fetchPrices: (state, countryConfig) => callWithState(baseProvider, 'fetchPrices', state, countryConfig),
      collectPriceEntries: baseProvider.collectPriceEntries,
      describePayload: (payload) => relabelText(baseProvider.describePayload(payload)),
    };
  }

  return {
    PROVIDER_ID,
    DEFAULT_BASE_URL,
    DEFAULT_COUNTRY_ID,
    DEFAULT_COUNTRY_LABEL,
    DEFAULT_LANG,
    DEFAULT_PRICES_ACTION,
    DEFAULT_SERVICE_CODE,
    DEFAULT_SERVICE_LABEL,
    createProvider,
  };
});
