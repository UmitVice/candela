import type { Routes } from '@angular/router';
import { TerminalPage } from './terminal/terminal-page';

export const routes: Routes = [
  { path: '', component: TerminalPage, title: 'Candela Terminal' },
  {
    path: 'observatory',
    loadComponent: () => import('./observatory/observatory-page').then((m) => m.ObservatoryPage),
    title: 'Observatory · Candela',
  },
  { path: '**', redirectTo: '' },
];
