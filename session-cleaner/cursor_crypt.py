"""Decryption for Cursor's `EncryptedBlobStore` — the AES-256-GCM scheme
found by reading Cursor's own shipped, minified JS (both
`workbench.desktop.main.js` and `workbench.glass.main.js`, June 2026 build).
This module only implements the crypto primitive; cursor_backend.py owns
finding candidate keys and ciphertext in the SQLite store and wiring this in
as a fallback for `get_bubble_messages`.

WHERE THIS COMES FROM
----------------------
The class lives in Cursor's `packages/agent-kv/src/cached-blob-store.ts`
(confirmed via its own telemetry event names, `agent_kv.encrypted.get_blob`
/ `agent_kv.encrypted.set_blob`). Minified, its shape is:

    class EncryptedBlobStore {
      constructor(blobStore, encryptionKeyStr) {
        this.blobStore = blobStore;
        this.encryptionKeyStr = encryptionKeyStr;
      }
      static ALGORITHM = "AES-GCM";
      static IV_LENGTH = 12;

      async getEncryptionKey() {
        if (this.encryptionKey === undefined) {
          const bytes = new TextEncoder().encode(this.encryptionKeyStr);
          const hash = await crypto.subtle.digest("SHA-256", bytes);
          this.encryptionKey = await crypto.subtle.importKey(
            "raw", hash, {name: "AES-GCM", length: 256}, true, ["encrypt", "decrypt"]
          );
        }
        return this.encryptionKey;
      }

      async getBlob(e, t) {
        const raw = await this.blobStore.getBlob(e, t);
        const iv = raw.slice(0, EncryptedBlobStore.IV_LENGTH);
        const ciphertext = raw.slice(EncryptedBlobStore.IV_LENGTH);
        return crypto.subtle.decrypt({name: "AES-GCM", iv}, await this.getEncryptionKey(), ciphertext);
      }
    }

THE SCHEME, TRANSLATED
-----------------------
- Algorithm: AES-256-GCM (authenticated encryption — decrypting with the
  wrong key doesn't produce garbage plaintext, it raises, because GCM
  verifies a 16-byte authentication tag appended to the ciphertext).
- Key derivation: `key = SHA-256(UTF-8 bytes of encryptionKeyStr)`.
  `encryptionKeyStr` is not a passphrase — it's one of two random,
  per-conversation values Cursor generates once via `crypto.getRandomValues`
  and stores as a base64 string directly on the conversation's own record:
  `blobEncryptionKey` (primary) or `speculativeSummarizationEncryptionKey`
  (a sibling field from the same schema migration, tried too since we can't
  rule out it gating some blobs — see cursor_backend._composer_encryption_keys).
- Blob layout: `IV (12 bytes) || ciphertext+tag (rest)`. The IV is random
  per-encryption, generated with `crypto.getRandomValues`.
- Where ciphertext would live: content-addressed blobs in Cursor's global
  SQLite store (`cursorDiskKV`, key prefix `composer.content.`), keyed by a
  hash of the serialized payload — not by conversation or bubble ID, so
  there's no way to look up "the" blob for a given message; you have to try
  candidates and let GCM's tag tell you whether you found the right one.

WHAT IT'S ACTUALLY USED FOR (as of this investigation)
--------------------------------------------------------
Searched every construction site (`new <ClassName>(...)`) of this class in
both shipped bundles: there are none. The class is defined and exported, and
every conversation gets both keys generated unconditionally at creation
time, but nothing in either bundle ever calls it. Real chat message text
lives in plain, unencrypted `bubbleId:{composerId}:{uuid}` rows instead,
which is what `get_bubble_messages` reads first and normally the only thing
it needs. This module exists as a defensive, seamless fallback in case that
ever changes — not because message content is provably encrypted today.

WHY THIS ISN'T A SECURITY BOUNDARY WE'RE CROSSING
---------------------------------------------------
The key material (`blobEncryptionKey`) travels in plaintext in the very
same JSON record whose blobs it would decrypt — no OS keychain, no user
passphrase, no per-device secret. Anything that can already read Cursor's
SQLite database (which is the only precondition for this whole tool to work
at all) can already read the key. Decrypting this format isn't defeating a
security control; it's just parsing a format Cursor itself would parse the
same way, using data that's already sitting right next to it.
"""

import hashlib
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_AESGCM = True
except ImportError:
    HAS_AESGCM = False

ALGORITHM = "AES-GCM"
IV_LENGTH = 12


def derive_key(key_str: str) -> bytes:
    """Cursor's key derivation: SHA-256 of the UTF-8 bytes of the stored key
    string (itself just a random base64 value, not a passphrase)."""
    return hashlib.sha256(key_str.encode("utf-8")).digest()


def decrypt_blob(raw: bytes, key_str: str) -> Optional[bytes]:
    """Attempt to decrypt one candidate blob under one candidate key.

    Returns the plaintext bytes on success, or None if this key doesn't
    match, `raw` is too short to contain an IV, or the `cryptography`
    package isn't installed. Never raises — GCM's built-in authentication
    tag means a wrong key fails cleanly rather than yielding corrupted
    plaintext, so callers can safely try every key they have and treat "did
    this return non-None" as the correctness check.
    """
    if not HAS_AESGCM or len(raw) <= IV_LENGTH:
        return None
    key = derive_key(key_str)
    iv, ciphertext = raw[:IV_LENGTH], raw[IV_LENGTH:]
    try:
        return AESGCM(key).decrypt(iv, ciphertext, None)
    except Exception:
        return None
