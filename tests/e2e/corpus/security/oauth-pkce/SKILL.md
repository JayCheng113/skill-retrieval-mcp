---
name: oauth-pkce
description: Implement the OAuth 2.0 authorization code flow with PKCE for a client that cannot keep a secret.
category: security
tags: [oauth, pkce, authentication, mobile]
---

# Authorization code flow with PKCE

A native app or single-page app ships its source to the user, so it cannot hold a
client secret. PKCE replaces the secret with a value proven only at redemption.

Generate a high-entropy `code_verifier`, then send its SHA-256 hash as
`code_challenge` with `code_challenge_method=S256`. On redemption, present the
verifier itself. An attacker who intercepts the authorization code cannot exchange
it without the verifier, which never left the client.

The `plain` challenge method exists for constrained platforms and gives up the
entire protection, since challenge and verifier are then identical. Do not use it.

Validate the `state` parameter on return. PKCE protects the code exchange; `state`
is what protects against having a session fixated by a forged callback.
