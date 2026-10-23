import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';
import { ChatService } from '../chat/chat.service';
import { GatewayService } from '../gateway/gateway.service';
import { RUNTIME_CONFIG } from '../config/runtime-config';
import type { SystemTurn } from '../state/conversation.model';
import { ConversationsStore } from '../state/conversations.store';
import { PreferencesStore } from '../state/preferences.store';
import { uuid } from '../util/ids';

export interface CommandSpec {
  name: string;
  usage: string;
  description: string;
  kind: 'analysis' | 'local';
  example: string;
}

export const COMMANDS: readonly CommandSpec[] = [
  {
    name: 'analyze',
    usage: '/analyze <SYM>',
    description: 'Full read: price action, technicals, forecast',
    kind: 'analysis',
    example: '/analyze NVDA',
  },
  {
    name: 'compare',
    usage: '/compare <SYM> <SYM>…',
    description: 'Side-by-side metrics for 2–3 tickers',
    kind: 'analysis',
    example: '/compare AAPL MSFT',
  },
  {
    name: 'chart',
    usage: '/chart <SYM> [range]',
    description: 'Price history over 1M, 3M, 6M, 1Y, 2Y or 5Y',
    kind: 'analysis',
    example: '/chart TSLA 1Y',
  },
  {
    name: 'fundamentals',
    usage: '/fundamentals <SYM>',
    description: 'Revenue, margins and growth from SEC filings',
    kind: 'analysis',
    example: '/fundamentals AAPL',
  },
  {
    name: 'forecast',
    usage: '/forecast <SYM>',
    description: 'P10 / P50 / P90 baseline bands to 12 months',
    kind: 'analysis',
    example: '/forecast AMD',
  },
  {
    name: 'watch',
    usage: '/watch <SYM>',
    description: 'Add a ticker to the watchlist',
    kind: 'local',
    example: '/watch META',
  },
  {
    name: 'unwatch',
    usage: '/unwatch <SYM>',
    description: 'Remove a ticker from the watchlist',
    kind: 'local',
    example: '/unwatch META',
  },
  {
    name: 'new',
    usage: '/new',
    description: 'Start a new session',
    kind: 'local',
    example: '/new',
  },
  {
    name: 'clear',
    usage: '/clear',
    description: 'Clear the current session',
    kind: 'local',
    example: '/clear',
  },
  {
    name: 'model',
    usage: '/model auto|pro|lite',
    description: 'Choose the inference tier',
    kind: 'local',
    example: '/model pro',
  },
  {
    name: 'reasoning',
    usage: '/reasoning on|off',
    description: 'Show or hide model thinking',
    kind: 'local',
    example: '/reasoning off',
  },
  {
    name: 'observatory',
    usage: '/observatory',
    description: 'Open the Observatory design view',
    kind: 'local',
    example: '/observatory',
  },
  {
    name: 'help',
    usage: '/help',
    description: 'List commands and shortcuts',
    kind: 'local',
    example: '/help',
  },
  {
    name: 'about',
    usage: '/about',
    description: 'About Candela',
    kind: 'local',
    example: '/about',
  },
];

const SYMBOL = /^\$?[A-Za-z][A-Za-z0-9.-]{0,9}$/;
const RANGES = ['1M', '3M', '6M', '1Y', '2Y', '5Y'];

export function matchCommands(input: string): CommandSpec[] {
  if (!input.startsWith('/') || /\s/.test(input)) return [];
  const query = input.slice(1).toLowerCase();
  return COMMANDS.filter((c) => c.name.startsWith(query));
}

@Injectable({ providedIn: 'root' })
export class CommandService {
  private readonly chat = inject(ChatService);
  private readonly store = inject(ConversationsStore);
  private readonly prefs = inject(PreferencesStore);
  private readonly gateway = inject(GatewayService);
  private readonly router = inject(Router);
  private readonly config = inject(RUNTIME_CONFIG);

  execute(raw: string): boolean {
    const input = raw.trim();
    if (!input.startsWith('/')) return false;
    const [head = '', ...rest] = input.slice(1).split(/\s+/);
    const name = head.toLowerCase();
    const args = rest.filter(Boolean);
    const symbols = args.map((a) => a.replace(/^\$/, '').toUpperCase());
    const invalid = args.find((a) => !SYMBOL.test(a));
    const command = `/${name}${args.length ? ` ${args.join(' ')}` : ''}`;

    switch (name) {
      case 'analyze':
        return this.needSymbols(
          command,
          symbols,
          1,
          invalid,
          ([s]) =>
            `Analyze ${s}: recent price action, technical indicators, the baseline forecast and the key risks.`,
        );
      case 'compare':
        if (symbols.length < 2)
          return this.warn('Usage: `/compare <SYM> <SYM>…` with at least two tickers.');
        return this.needSymbols(
          command,
          symbols.slice(0, 3),
          2,
          invalid,
          (list) =>
            `Compare ${list.slice(0, -1).join(', ')} and ${list.at(-1) ?? ''}: 1-year performance, volatility, drawdown and where each trades in its 52-week range.`,
        );
      case 'chart': {
        const range = (args[1] ?? '6M').toUpperCase();
        if (!RANGES.includes(range))
          return this.warn(`Unknown range \`${args[1] ?? ''}\`. Use one of ${RANGES.join(', ')}.`);
        return this.needSymbols(
          command,
          symbols.slice(0, 1),
          1,
          args[0] && !SYMBOL.test(args[0]) ? args[0] : undefined,
          ([s]) => `Show the ${s} price history over ${range} and summarize the trend.`,
        );
      }
      case 'fundamentals':
        return this.needSymbols(
          command,
          symbols,
          1,
          invalid,
          ([s]) =>
            `Summarize ${s} fundamentals from its latest filings: revenue, margins, earnings growth and cash flow.`,
        );
      case 'forecast':
        return this.needSymbols(
          command,
          symbols,
          1,
          invalid,
          ([s]) => `What does the 12-month forecast look like for ${s}?`,
        );
      case 'watch':
      case 'unwatch': {
        const [s] = symbols;
        if (!s || invalid) return this.warn(`Usage: \`/${name} <SYM>\`.`);
        const changed = name === 'watch' ? this.prefs.watch(s) : this.prefs.unwatch(s);
        return this.info(
          changed
            ? `${name === 'watch' ? 'Added' : 'Removed'} **${s}** ${name === 'watch' ? 'to' : 'from'} the watchlist.`
            : `**${s}** is ${name === 'watch' ? 'already' : 'not'} on the watchlist.`,
        );
      }
      case 'new':
        this.store.newConversation();
        return true;
      case 'clear': {
        const active = this.store.active();
        if (active && !this.chat.busy()) this.store.clear(active.id);
        return true;
      }
      case 'model': {
        const value = args[0]?.toLowerCase();
        if (value !== 'auto' && value !== 'pro' && value !== 'lite') {
          return this.info(`Model is **${this.prefs.model()}**. Usage: \`/model auto|pro|lite\`.`);
        }
        this.prefs.model.set(value);
        return this.info(
          value === 'auto'
            ? 'Model set to **auto**: pro when a GPU worker is online, otherwise lite.'
            : `Model set to **${value}**.`,
        );
      }
      case 'reasoning': {
        const value = args[0]?.toLowerCase();
        if (value !== 'on' && value !== 'off') {
          return this.info(
            `Reasoning is **${this.prefs.reasoning() ? 'on' : 'off'}**. Usage: \`/reasoning on|off\`.`,
          );
        }
        this.prefs.reasoning.set(value === 'on');
        return this.info(`Reasoning **${value}**.`);
      }
      case 'observatory':
        void this.router.navigate(['/observatory']);
        return true;
      case 'help':
        return this.system('help', this.helpText());
      case 'about':
        return this.system('about', this.aboutText());
      default:
        return this.warn(`Unknown command \`/${name}\`. Type \`/help\` for the list.`);
    }
  }

  private needSymbols(
    command: string,
    symbols: string[],
    min: number,
    invalid: string | undefined,
    prompt: (symbols: string[]) => string,
  ): boolean {
    if (invalid) return this.warn(`\`${invalid}\` is not a valid ticker.`);
    if (symbols.length < min) return this.warn(`Usage: \`${command.split(' ')[0] ?? ''} <SYM>\`.`);
    if (this.chat.busy()) return this.warn('Wait for the current answer or press Esc to stop it.');
    void this.chat.send(prompt(symbols), command);
    return true;
  }

  private system(variant: SystemTurn['variant'], content: string): boolean {
    const id = this.store.ensureActive();
    this.store.addTurn(id, {
      kind: 'system',
      id: uuid(),
      createdAt: new Date().toISOString(),
      variant,
      content,
    });
    return true;
  }

  private info(content: string): boolean {
    return this.system('info', content);
  }

  private warn(content: string): boolean {
    return this.system('warn', content);
  }

  private helpText(): string {
    const rows = COMMANDS.map((c) => `| \`${c.usage.replace(/\|/g, '\\|')}\` | ${c.description} |`);
    return [
      '**Commands**',
      '',
      '| Command | What it does |',
      '|---|---|',
      ...rows,
      '',
      '**Keys** · `Enter` send · `Shift+Enter` new line · `↑/↓` history · `Esc` stop · `⌘K / Ctrl+K` command palette · `/` commands',
    ].join('\n');
  }

  private aboutText(): string {
    const c = this.gateway.connection();
    return [
      `**Candela Terminal** ${this.config.release} — an open financial-analysis LLM fine-tuned locally on Apple Silicon with MLX, served by a Go gateway, used through this PWA.`,
      '',
      `- Connection: ${c.mode === 'replay' ? 'replay (recorded demo sessions)' : `live via ${c.transport.toUpperCase()}`}`,
      '- Every number comes from deterministic market tools; answers cite their data date.',
      '- Source: [github.com/UmitVice/candela](https://github.com/UmitVice/candela)',
      '',
      'Educational research tool. Not financial advice.',
    ].join('\n');
  }
}
