export interface SseFrame {
  id?: string;
  event: string;
  data: string;
}

export class SseParser {
  private buffer = '';
  private dataLines: string[] = [];
  private eventName = '';
  private lastId: string | undefined;

  push(chunk: string): SseFrame[] {
    this.buffer += chunk;
    const frames: SseFrame[] = [];
    let start = 0;
    for (let i = 0; i < this.buffer.length; i++) {
      const ch = this.buffer[i];
      if (ch !== '\n' && ch !== '\r') continue;
      // A lone trailing CR may be the first half of CRLF split across chunks.
      if (ch === '\r' && i === this.buffer.length - 1) break;
      const line = this.buffer.slice(start, i);
      if (ch === '\r' && this.buffer[i + 1] === '\n') i++;
      start = i + 1;
      const frame = this.processLine(line);
      if (frame) frames.push(frame);
    }
    this.buffer = this.buffer.slice(start);
    return frames;
  }

  private processLine(line: string): SseFrame | null {
    if (line === '') return this.dispatch();
    if (line.startsWith(':')) return null;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    switch (field) {
      case 'data':
        this.dataLines.push(value);
        break;
      case 'event':
        this.eventName = value;
        break;
      case 'id':
        if (!value.includes('\0')) this.lastId = value;
        break;
    }
    return null;
  }

  private dispatch(): SseFrame | null {
    if (this.dataLines.length === 0) {
      this.eventName = '';
      return null;
    }
    const frame: SseFrame = {
      event: this.eventName || 'message',
      data: this.dataLines.join('\n'),
      ...(this.lastId === undefined ? {} : { id: this.lastId }),
    };
    this.dataLines = [];
    this.eventName = '';
    return frame;
  }
}
