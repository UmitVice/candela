import type { Conversation, Segment } from './conversation.model';

function toolLine(segment: Extract<Segment, { type: 'tool' }>): string {
  const args = Object.values(segment.args).map(String).join(' · ');
  const result =
    segment.status === 'ok'
      ? `✓ ${segment.summary ?? ''}`
      : `✗ ${segment.error ?? segment.summary ?? 'failed'}`;
  return `> ⚙ \`${segment.name}\` ${args} — ${result}`;
}

export function conversationToMarkdown(conversation: Conversation): string {
  const lines: string[] = [
    `# ${conversation.title}`,
    '',
    `Exported from Candela Terminal on ${new Date().toISOString()}. Not financial advice.`,
    '',
  ];
  for (const turn of conversation.turns) {
    if (turn.kind === 'user') {
      lines.push(`## ❯ ${turn.content.split('\n')[0] ?? ''}`, '', `*${turn.createdAt}*`, '');
      if (turn.content.includes('\n')) lines.push(turn.content, '');
    } else if (turn.kind === 'assistant') {
      const model = turn.model
        ? `${turn.model.displayName} (${turn.model.version}, ${turn.model.tier})`
        : 'candela';
      lines.push(`### ${model}${turn.transport === 'replay' ? ' · replay' : ''}`, '');
      for (const segment of turn.segments) {
        if (segment.type === 'tool') lines.push(toolLine(segment), '');
        else if (segment.type === 'answer') lines.push(segment.text.trim(), '');
      }
      if (turn.error) lines.push(`> ✗ ${turn.error.code}: ${turn.error.message}`, '');
      if (turn.usage) {
        lines.push(
          `*${turn.usage.completionTokens} tok · ${turn.usage.tokensPerSecond} tok/s · TTFT ${(turn.usage.timeToFirstTokenMs / 1000).toFixed(1)} s*`,
          '',
        );
      }
    }
  }
  return lines.join('\n');
}

export function downloadMarkdown(conversation: Conversation): void {
  const blob = new Blob([conversationToMarkdown(conversation)], {
    type: 'text/markdown;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const slug =
    conversation.title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '') || 'session';
  a.href = url;
  a.download = `candela-${slug}.md`;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
