// Current product rollout: MineM is the only connector exposed in the client.
// Keep this projection separate from the backend registry so hiding a connector
// never deletes its credentials, data, or implementation.
const VISIBLE_CONNECTOR_NAMES = new Set(["minem"]);

export function isConnectorVisible(name: string): boolean {
  return VISIBLE_CONNECTOR_NAMES.has(name);
}

export function visibleConnectors<T extends { name: string }>(rows: T[]): T[] {
  return rows.filter((row) => isConnectorVisible(row.name));
}
