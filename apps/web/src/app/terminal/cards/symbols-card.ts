import { Component, inject, input } from '@angular/core';
import type { SymbolMatch } from '../../core/api/types';
import { ShellStateService } from '../../shell/shell-state.service';

@Component({
  selector: 'cd-symbols-card',
  template: `
    @if (results().length) {
      <div class="chips" role="list" aria-label="Matching symbols">
        @for (r of results(); track r.symbol) {
          <span role="listitem">
            <button
              type="button"
              class="chip-btn"
              [attr.aria-label]="'Select ' + r.symbol + ', ' + r.name + ', ' + r.exchange"
              (click)="select(r)"
            >
              {{ r.symbol }}<span class="chip-name">{{ r.name }} · {{ r.exchange }}</span>
            </button>
          </span>
        }
      </div>
      <div class="note">Select a symbol to focus it and prefill /analyze.</div>
    } @else {
      <div class="muted">No matching US-listed symbols.</div>
    }
  `,
  styleUrl: './cards.css',
})
export class SymbolsCard {
  private readonly shell = inject(ShellStateService);
  readonly results = input.required<SymbolMatch[]>();

  protected select(match: SymbolMatch): void {
    this.shell.pinnedSymbol.set(match.symbol);
    this.shell.insert(`/analyze ${match.symbol}`);
  }
}
