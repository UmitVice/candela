import type { ApplicationConfig } from '@angular/core';
import {
  inject,
  isDevMode,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
  provideZonelessChangeDetection,
} from '@angular/core';
import { provideRouter, withComponentInputBinding, withInMemoryScrolling } from '@angular/router';
import { provideServiceWorker } from '@angular/service-worker';
import { routes } from './app.routes';
import type { RuntimeConfig } from './core/config/runtime-config';
import { RUNTIME_CONFIG } from './core/config/runtime-config';
import { GatewayService } from './core/gateway/gateway.service';

export function createAppConfig(config: RuntimeConfig): ApplicationConfig {
  return {
    providers: [
      provideBrowserGlobalErrorListeners(),
      provideZonelessChangeDetection(),
      { provide: RUNTIME_CONFIG, useValue: config },
      provideRouter(routes, withComponentInputBinding(), withInMemoryScrolling()),
      provideServiceWorker('ngsw-worker.js', {
        enabled: !isDevMode(),
        registrationStrategy: 'registerWhenStable:30000',
      }),
      provideAppInitializer(() => {
        void inject(GatewayService).connect();
      }),
    ],
  };
}
