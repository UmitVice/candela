interface TrustedTypePolicyFactoryLike {
  defaultPolicy: unknown;
  createPolicy(
    name: string,
    rules: { createScriptURL: (input: string) => string; createHTML: (input: string) => string },
  ): unknown;
}

const WORKER_SCRIPTS = /^\/(ngsw-worker|safety-worker)\.js$/;

// The CSP requires Trusted Types, and Angular registers the service worker with a plain string URL.
// This default policy admits only the same-origin worker scripts, plus the empty string for HTML
// sinks because the ECharts renderer clears its container with `innerHTML = ''` (ADR 0101).
// Every other script URL or markup string is rejected.
export function installTrustedTypesPolicy(): void {
  const factory = (window as unknown as { trustedTypes?: TrustedTypePolicyFactoryLike })
    .trustedTypes;
  if (!factory || factory.defaultPolicy) return;
  try {
    factory.createPolicy('default', {
      createScriptURL: (input: string) => {
        const url = new URL(input, window.location.href);
        if (url.origin === window.location.origin && WORKER_SCRIPTS.test(url.pathname))
          return input;
        throw new TypeError(`Blocked script URL: ${url.pathname}`);
      },
      createHTML: (input: string) => {
        if (input === '') return input;
        throw new TypeError('Blocked HTML string');
      },
    });
  } catch {
    /* a CSP without the default policy only costs offline support, never the app */
  }
}
