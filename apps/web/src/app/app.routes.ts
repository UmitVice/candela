import type { Routes } from '@angular/router';
import { TerminalPage } from './terminal/terminal-page';

export const routes: Routes = [
  { path: '', component: TerminalPage, title: 'Candela Terminal' },
  {
    path: 'observatory',
    loadChildren: () =>
      import('./observatory/observatory.routes').then((m) => m.OBSERVATORY_ROUTES),
    title: 'Observatory · Candela',
  },
  { path: '**', redirectTo: '' },
];
