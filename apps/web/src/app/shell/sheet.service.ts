import type { DialogRef } from '@angular/cdk/dialog';
import { Dialog } from '@angular/cdk/dialog';
import { createGlobalPositionStrategy } from '@angular/cdk/overlay';
import type { ComponentType } from '@angular/cdk/portal';
import { Injectable, Injector, inject } from '@angular/core';

export type SheetPlacement = 'bottom' | 'right' | 'left' | 'center';

@Injectable({ providedIn: 'root' })
export class SheetService {
  private readonly dialog = inject(Dialog);
  private readonly injector = inject(Injector);
  private current: DialogRef<unknown> | null = null;

  open<T, D = unknown>(
    component: ComponentType<T>,
    options: { placement: SheetPlacement; label: string; data?: D },
  ): DialogRef<unknown, T> {
    this.current?.close();
    const position = createGlobalPositionStrategy(this.injector);
    const panelClass = ['cd-sheet', `cd-sheet--${options.placement}`];
    switch (options.placement) {
      case 'bottom':
        position.bottom('0').centerHorizontally();
        break;
      case 'right':
        position.top('0').right('0');
        break;
      case 'left':
        position.top('0').left('0');
        break;
      case 'center':
        position.top('12vh').centerHorizontally();
        break;
    }
    const ref: DialogRef<unknown, T> = this.dialog.open<unknown, D, T>(component, {
      positionStrategy: position,
      panelClass,
      backdropClass: 'cd-sheet-backdrop',
      ariaLabel: options.label,
      autoFocus: 'first-tabbable',
      restoreFocus: true,
      closeOnNavigation: true,
      ...(options.data === undefined ? {} : { data: options.data }),
    });
    this.current = ref as DialogRef<unknown>;
    ref.closed.subscribe(() => {
      if (this.current === (ref as DialogRef<unknown>)) this.current = null;
    });
    return ref;
  }

  closeAll(): void {
    this.dialog.closeAll();
  }
}
