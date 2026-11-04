export function newRequestKey(prefix: string): string {
  return `${prefix}:${Date.now()}:${crypto.randomUUID()}`;
}
