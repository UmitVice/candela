import DOMPurify from 'dompurify';
import { Marked } from 'marked';

const marked = new Marked({
  gfm: true,
  breaks: false,
  async: false,
  renderer: {
    // Model output is untrusted: raw HTML is shown as text instead of being parsed.
    html({ text }) {
      return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
  },
});

let hooked = false;

function ensureHooks(): void {
  if (hooked) return;
  hooked = true;
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'A') {
      const href = node.getAttribute('href') ?? '';
      if (/^https?:\/\//i.test(href)) {
        node.setAttribute('target', '_blank');
        node.setAttribute('rel', 'noopener noreferrer nofollow');
      } else if (!href.startsWith('#')) {
        node.removeAttribute('href');
      }
    }
  });
}

const PURIFY_CONFIG = {
  ALLOWED_TAGS: [
    'p',
    'br',
    'hr',
    'strong',
    'em',
    'del',
    'code',
    'pre',
    'blockquote',
    'ul',
    'ol',
    'li',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'table',
    'thead',
    'tbody',
    'tr',
    'th',
    'td',
    'a',
    'div',
    'span',
    'input',
  ],
  ALLOWED_ATTR: ['href', 'title', 'align', 'class', 'type', 'checked', 'disabled', 'start'],
  ALLOW_DATA_ATTR: false,
};

export function renderMarkdown(source: string): string {
  ensureHooks();
  const html = marked.parse(source) as string;
  const wrapped = html
    .replace(/<table>/g, '<div class="md-table"><table>')
    .replace(/<\/table>/g, '</table></div>');
  return DOMPurify.sanitize(wrapped, PURIFY_CONFIG);
}
