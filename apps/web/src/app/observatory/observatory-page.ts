import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import {
  ActivatedRoute,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet,
} from '@angular/router';
import { map } from 'rxjs';
import { ChatService } from '../core/chat/chat.service';
import { CommandService } from '../core/commands/commands';
import { GatewayService } from '../core/gateway/gateway.service';
import { answerText } from '../core/state/conversation.model';
import { ConversationsStore } from '../core/state/conversations.store';
import { TelemetryStore } from '../core/telemetry/telemetry.store';
import { LayoutService } from '../shell/layout.service';
import { TerminalPage } from '../terminal/terminal-page';
import { ObservatoryDataService } from './data/observatory-data.service';
import { ObservatoryUi } from './observatory-ui.service';

const SCENES = [
  { path: 'tower', label: 'Tower', title: 'Architecture Tower' },
  { path: 'field', label: 'Fine-tune', title: 'Fine-tune Field' },
  { path: 'galaxy', label: 'Galaxy', title: 'Embedding Galaxy' },
  { path: 'lab', label: 'Lab HUD', title: 'Lab HUD' },
  { path: 'spark', label: 'Spark Lab', title: 'Spark Lab' },
];

@Component({
  selector: 'cd-observatory-page',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, FormsModule, TerminalPage],
  templateUrl: './observatory-page.html',
  styleUrl: './observatory-page.css',
})
export class ObservatoryPage {
  protected readonly layout = inject(LayoutService);
  protected readonly data = inject(ObservatoryDataService);
  protected readonly ui = inject(ObservatoryUi);
  protected readonly telemetry = inject(TelemetryStore);
  protected readonly gateway = inject(GatewayService);
  protected readonly chat = inject(ChatService);
  private readonly commands = inject(CommandService);
  private readonly store = inject(ConversationsStore);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly scenes = SCENES;
  protected readonly prompt = signal('');
  protected readonly split = computed(() => this.layout.isWide());

  private readonly query = toSignal(this.route.queryParamMap.pipe(map((q) => q.get('model'))), {
    initialValue: null,
  });

  protected readonly selectedModel = computed(
    () => this.data.requestedModel() ?? this.data.proModel()?.id ?? '',
  );

  protected readonly proChoices = computed(() =>
    this.data.choices().filter((c) => c.group === 'Candela Pro'),
  );
  protected readonly sparkChoices = computed(() =>
    this.data.choices().filter((c) => c.group === 'Candela Spark'),
  );

  protected readonly liveLine = computed(() => {
    this.telemetry.count();
    const turns = this.store.active()?.turns ?? [];
    const last = turns.at(-1);
    if (last?.kind !== 'assistant') return '';
    const text = answerText(last).replace(/\s+/g, ' ').trim();
    if (text) return text.length > 120 ? `…${text.slice(-119)}` : text;
    if (last.status === 'queued') return `queued · position ${last.queue?.position ?? '?'}`;
    if (last.status === 'pending' || last.status === 'streaming') return 'thinking…';
    return '';
  });

  constructor() {
    effect(() => this.data.requestedModel.set(this.query()));

    const visible = () =>
      this.telemetry.observatoryVisible.set(document.visibilityState === 'visible');
    visible();
    document.addEventListener('visibilitychange', visible);
    inject(DestroyRef).onDestroy(() => {
      document.removeEventListener('visibilitychange', visible);
      this.telemetry.observatoryVisible.set(false);
    });
  }

  protected selectModel(id: string): void {
    void this.router.navigate([], {
      relativeTo: this.route.firstChild ?? this.route,
      queryParams: { model: id || null, step: null },
      queryParamsHandling: 'merge',
    });
  }

  protected send(input: HTMLInputElement): void {
    const text = this.prompt().trim();
    if (!text || this.chat.busy()) return;
    this.prompt.set('');
    input.value = '';
    if (!this.commands.execute(text)) void this.chat.send(text);
  }
}
