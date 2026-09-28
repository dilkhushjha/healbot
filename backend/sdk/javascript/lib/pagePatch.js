const HEALABLE_METHODS = new Set([
  'click',
  'dblclick',
  'fill',
  'clear',
  'press',
  'check',
  'uncheck',
  'selectOption',
  'hover',
  'focus',
  'textContent',
  'innerText',
  'inputValue',
  'getAttribute',
  'isVisible',
  'waitFor',
]);

function patchPage(page, client, testInfo = {}) {
  if (!page || page.__healbotPatched) return page;
  const originalLocator = page.locator.bind(page);

  page.locator = function healbotLocator(selector, ...args) {
    const locator = originalLocator(selector, ...args);
    return wrapLocator(locator, {
      page,
      client,
      selector: String(selector),
      originalLocator,
      testInfo,
    });
  };

  Object.defineProperty(page, '__healbotPatched', {
    value: true,
    enumerable: false,
    configurable: false,
  });

  page.healbot = client;
  return page;
}

function wrapLocator(locator, context) {
  return new Proxy(locator, {
    get(target, prop, receiver) {
      const value = Reflect.get(target, prop, receiver);
      if (typeof value !== 'function') {
        return value;
      }

      return (...args) => {
        const result = value.apply(target, args);
        if (looksLikeLocator(result)) {
          return wrapLocator(result, context);
        }
        if (!isPromise(result) || !HEALABLE_METHODS.has(String(prop))) {
          return result;
        }

        context.client.event({
          page: context.page,
          status: 'running',
          description: `${String(prop)}: ${context.selector}`,
          selector: context.selector,
        }).catch(() => {});

        return result
          .then((resolved) => {
            context.client.event({
              page: context.page,
              status: 'passed',
              description: `${String(prop)}: ${context.selector}`,
              selector: context.selector,
            }).catch(() => {});
            return resolved;
          })
          .catch(async (error) => {
            const healedSelector = await context.client.heal({
              page: context.page,
              selector: context.selector,
              intent: `${String(prop)} ${context.selector}`,
              testName: context.testInfo.title || '',
            });

            if (!healedSelector) {
              throw error;
            }

            const healedLocator = context.originalLocator(healedSelector);
            const healedMethod = healedLocator[prop];
            if (typeof healedMethod !== 'function') {
              throw error;
            }
            return healedMethod.apply(healedLocator, args);
          });
      };
    },
  });
}

function looksLikeLocator(value) {
  return Boolean(
    value &&
    typeof value === 'object' &&
    typeof value.waitFor === 'function' &&
    typeof value.locator === 'function'
  );
}

function isPromise(value) {
  return Boolean(value && typeof value.then === 'function');
}

module.exports = {
  patchPage,
  wrapLocator,
};
