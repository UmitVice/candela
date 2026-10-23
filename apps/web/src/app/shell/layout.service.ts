import { BreakpointObserver } from '@angular/cdk/layout';
import { Injectable, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';

const DESKTOP = '(min-width: 1280px)';
const TABLET = '(min-width: 768px)';

@Injectable({ providedIn: 'root' })
export class LayoutService {
  private readonly observer = inject(BreakpointObserver);
  private readonly matches = toSignal(
    this.observer.observe([DESKTOP, TABLET]).pipe(map((state) => state.breakpoints)),
    {
      initialValue: {
        [DESKTOP]: window.matchMedia(DESKTOP).matches,
        [TABLET]: window.matchMedia(TABLET).matches,
      },
    },
  );

  readonly isDesktop = computed(() => !!this.matches()[DESKTOP]);
  readonly isTablet = computed(() => !this.isDesktop() && !!this.matches()[TABLET]);
  readonly isMobile = computed(() => !this.matches()[TABLET]);
  readonly reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
