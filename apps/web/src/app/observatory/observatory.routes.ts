import type { Routes } from '@angular/router';
import { ObservatoryPage } from './observatory-page';

export const OBSERVATORY_ROUTES: Routes = [
  {
    path: '',
    component: ObservatoryPage,
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'tower' },
      {
        path: 'tower',
        loadComponent: () => import('./views/tower-view').then((m) => m.TowerView),
        title: 'Architecture Tower · Observatory · Candela',
      },
      {
        path: 'field',
        loadComponent: () => import('./views/field-view').then((m) => m.FieldView),
        title: 'Fine-tune Field · Observatory · Candela',
      },
      {
        path: 'galaxy',
        loadComponent: () => import('./views/galaxy-view').then((m) => m.GalaxyView),
        title: 'Embedding Galaxy · Observatory · Candela',
      },
      {
        path: 'lab',
        loadComponent: () => import('./views/lab-view').then((m) => m.LabView),
        title: 'Lab HUD · Observatory · Candela',
      },
      {
        path: 'spark',
        loadComponent: () => import('./views/spark-view').then((m) => m.SparkView),
        title: 'Spark Lab · Observatory · Candela',
      },
      { path: '**', redirectTo: 'tower' },
    ],
  },
];
