import { openDB, IDBPDatabase } from 'idb'

/** 离线缓存数据库：扫码终端在弱网环境下将事件写入本地，恢复后批量回传。 */
const DB_NAME = 'xzc25_offline'
const STORE = 'pending_events'

let dbPromise: Promise<IDBPDatabase> | null = null

function getDb() {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, 1, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE)) {
          const store = db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true })
          store.createIndex('by_client', 'client_id')
          store.createIndex('by_time', 'occurred_at')
        }
      },
    })
  }
  return dbPromise
}

export interface PendingEvent {
  id?: number
  client_id: string
  event_type: string
  payload: Record<string, any>
  occurred_at: string
  sync_state: 'pending' | 'syncing' | 'done' | 'failed'
  last_error?: string
}

export async function putEvent(evt: Omit<PendingEvent, 'id'>): Promise<number> {
  const db = await getDb()
  return (await db.add(STORE, evt)) as number
}

export async function listPending(): Promise<PendingEvent[]> {
  const db = await getDb()
  return (await db.getAll(STORE)) as PendingEvent[]
}

export async function markEvent(id: number, state: PendingEvent['sync_state'], last_error?: string) {
  const db = await getDb()
  const evt: PendingEvent | undefined = await db.get(STORE, id)
  if (!evt) return
  evt.sync_state = state
  evt.last_error = last_error
  await db.put(STORE, evt)
}

export async function removeEvent(id: number) {
  const db = await getDb()
  await db.delete(STORE, id)
}

export async function pendingCount(): Promise<number> {
  const db = await getDb()
  return await db.count(STORE)
}

/** 在线状态监听：恢复网络时自动同步。 */
export function attachAutoSync(handler: () => Promise<void>) {
  const trigger = () => {
    if (navigator.onLine) {
      handler().catch(console.error)
    }
  }
  window.addEventListener('online', trigger)
  // 首次挂载也尝试一次
  setTimeout(trigger, 3000)
  return () => window.removeEventListener('online', trigger)
}
