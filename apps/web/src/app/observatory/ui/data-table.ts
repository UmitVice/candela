import { Component, input } from '@angular/core';

export interface Column {
  key: string;
  label: string;
  numeric?: boolean;
}

export type Row = Record<string, string | number | null | undefined>;

@Component({
  selector: 'cd-data-table',
  template: `
    <figure class="table-wrap">
      <figcaption class="mono">{{ caption() }}</figcaption>
      <div class="scroll" tabindex="0" [attr.aria-label]="caption() + ' table'">
        <table>
          <thead>
            <tr>
              @for (c of columns(); track c.key) {
                <th scope="col" [class.num]="c.numeric">{{ c.label }}</th>
              }
            </tr>
          </thead>
          <tbody>
            @for (r of rows(); track $index) {
              <tr>
                @for (c of columns(); track c.key; let first = $first) {
                  @if (first) {
                    <th scope="row" [class.num]="c.numeric">{{ r[c.key] ?? '—' }}</th>
                  } @else {
                    <td [class.num]="c.numeric">{{ r[c.key] ?? '—' }}</td>
                  }
                }
              </tr>
            } @empty {
              <tr>
                <td [attr.colspan]="columns().length" class="empty">No rows yet.</td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </figure>
  `,
  styles: `
    .table-wrap {
      margin: 0 0 20px;
    }
    figcaption {
      margin-bottom: 6px;
      color: var(--fg-1);
      font-size: 11.5px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .scroll {
      max-height: 420px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
    }
    .scroll:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-family: var(--font-mono);
      font-size: 12px;
    }
    th,
    td {
      padding: 5px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
      color: var(--fg-0);
      font-weight: 400;
    }
    thead th {
      position: sticky;
      top: 0;
      background: var(--bg-2);
      color: var(--fg-1);
      font-weight: 500;
    }
    tbody th {
      color: var(--fg-1);
    }
    .num {
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    .empty {
      color: var(--fg-2);
    }
  `,
})
export class DataTable {
  readonly caption = input.required<string>();
  readonly columns = input.required<Column[]>();
  readonly rows = input.required<Row[]>();
}
