import { Injectable } from '@angular/core';
import type { DBSchema, IDBPDatabase } from 'idb';
import { openDB } from 'idb';
import type { Conversation } from './conversation.model';

interface CandelaDb extends DBSchema {
  conversations: { key: string; value: Conversation; indexes: { updatedAt: string } };
}

@Injectable({ providedIn: 'root' })
export class ConversationRepository {
  private db: Promise<IDBPDatabase<CandelaDb> | null> | null = null;

  private open(): Promise<IDBPDatabase<CandelaDb> | null> {
    this.db ??= openDB<CandelaDb>('candela', 1, {
      upgrade(db) {
        const store = db.createObjectStore('conversations', { keyPath: 'id' });
        store.createIndex('updatedAt', 'updatedAt');
      },
    }).catch(() => null);
    return this.db;
  }

  async loadAll(): Promise<Conversation[]> {
    const db = await this.open();
    if (!db) return [];
    try {
      const all = await db.getAll('conversations');
      return all.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    } catch {
      return [];
    }
  }

  async save(conversation: Conversation): Promise<void> {
    const db = await this.open();
    await db?.put('conversations', conversation).catch(() => undefined);
  }

  async remove(id: string): Promise<void> {
    const db = await this.open();
    await db?.delete('conversations', id).catch(() => undefined);
  }
}
