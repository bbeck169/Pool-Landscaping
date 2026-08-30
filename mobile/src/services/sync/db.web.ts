/**
 * db.web.ts — Web stub for the sync SQLite database.
 *
 * expo-sqlite's web worker imports a .wasm file that Metro can't
 * resolve. On web, the offline sync DB is not functional — all
 * operations return safe no-op values.
 */

const noop: any = {
  execAsync: async () => {},
  getFirstAsync: async () => null,
  getAllAsync: async () => [],
  runAsync: async () => ({ changes: 0, lastInsertRowId: 0 }),
};

export async function getSyncDb(): Promise<any> {
  return noop;
}

export async function getConfig(_key: string): Promise<string | null> {
  return null;
}

export async function setConfig(_key: string, _value: string): Promise<void> {}

export async function getSchemaVersion(): Promise<number> {
  return 0;
}

export function __resetForTests() {}
