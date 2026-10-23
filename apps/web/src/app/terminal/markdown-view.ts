import { Component, ViewEncapsulation, computed, inject, input } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { renderMarkdown } from '../core/markdown/markdown';

@Component({
  selector: 'cd-markdown',
  template: `<div class="md" [class.streaming]="streaming()" [innerHTML]="html()"></div>`,
  styleUrl: './markdown-view.css',
  // Rendered HTML is inserted via innerHTML and never receives emulated-encapsulation attributes.
  encapsulation: ViewEncapsulation.None,
})
export class MarkdownView {
  private readonly sanitizer = inject(DomSanitizer);
  readonly source = input.required<string>();
  readonly streaming = input(false);

  // DOMPurify is the trust boundary for model output; a second sanitizing pass would run on every streamed token.
  protected readonly html = computed(() =>
    this.sanitizer.bypassSecurityTrustHtml(renderMarkdown(this.source())),
  );
}
