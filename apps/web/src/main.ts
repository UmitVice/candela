import { bootstrapApplication } from '@angular/platform-browser';
import { App } from './app/app';
import { createAppConfig } from './app/app.config';
import { loadRuntimeConfig } from './app/core/config/runtime-config';
import { installTrustedTypesPolicy } from './app/core/config/trusted-types';

installTrustedTypesPolicy();

loadRuntimeConfig()
  .then((config) => bootstrapApplication(App, createAppConfig(config)))
  .catch((error: unknown) => console.error(error));
