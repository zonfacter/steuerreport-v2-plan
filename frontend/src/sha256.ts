import { sha256 } from "@noble/hashes/sha2.js";

export async function sha256Bytes(bytes: Uint8Array): Promise<Uint8Array> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle) return new Uint8Array(await subtle.digest("SHA-256", new Uint8Array(bytes)));
  return sha256(bytes);
}
