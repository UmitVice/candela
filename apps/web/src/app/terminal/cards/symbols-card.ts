import { Component, input } from '@angular/core';
import type { SymbolMatch } from '../../core/api/types';

@Component({
  selector: 'cd-symbols-card',
  template: `
    @if (results().length) {
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Name</th>
              <th>Exchange</th>
            </tr>
          </thead>
          <tbody>
            @for (r of results(); track r.symbol) {
              <tr>
                <td>{{ r.symbol }}</td>
                <td style="text-align:left">{{ r.name }}</td>
                <td>{{ r.exchange }}</td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    } @else {
      <div class="muted">No matching US-listed symbols.</div>
    }
  `,
  styleUrl: './cards.css',
})
export class SymbolsCard {
  readonly results = input.required<SymbolMatch[]>();
}
