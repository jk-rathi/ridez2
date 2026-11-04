# Authentication sequence diagrams

[← Back to index](../README.md) · Details: [08 — Authentication and security](../08-authentication-and-security.md)

## Registration

```mermaid
sequenceDiagram
  autonumber
  actor U as User
  participant P as AuthPage (main.jsx)
  participant A as api.js
  participant R as routes.py
  participant S as services.register
  participant DB as users table
  U->>P: fill name, mobile, password, role tab
  P->>A: api('/auth/register', POST {name,mobile,password,role})
  A->>R: POST /api/v1/auth/register
  R->>R: before_request limit_auth (10/min per IP)
  R->>R: body() → must be JSON object
  R->>S: register(data)
  S->>S: validate name 1–100, password 10–128, role ∈ {rider,driver}
  S->>S: normalize(mobile) → E.164 via phonenumbers
  S->>DB: by_mobile(mobile) — 409 if exists
  S->>S: HMAC-SHA256(USER_CODE_SECRET, "role:mobile") → base32 → RID-/DRV- + 12..32 chars
  S->>DB: code_exists(candidate) loop
  S->>DB: INSERT users (status = pending for driver, active for rider)
  R-->>A: 201 {user}
  A-->>P: setCreated(user) → shows permanent account code
```

## Login

```mermaid
sequenceDiagram
  autonumber
  participant P as AuthPage
  participant AS as authSession.signIn
  participant R as routes.sign_in
  participant SS as session_service
  participant SV as services.login
  participant DB as DB
  P->>AS: signIn({mobile,password})
  AS->>AS: navigator.locks 'ridez-refresh-cookie'
  AS->>R: POST /auth/login + X-Session-Request:1
  R->>R: limit_auth (10/min/IP)
  R->>SS: check_origin(require_header=False)
  R->>SV: login(body)
  SV->>SV: normalize mobile (401 on failure)
  SV->>DB: by_mobile
  SV->>SV: check_password_hash(user hash OR dummy hash)
  SV-->>R: 401 'Mobile or password is incorrect' if unknown/wrong/disabled
  SV->>SS: issue(user)
  SS->>DB: INSERT auth_sessions (expires +30 d)
  SS->>DB: INSERT refresh_tokens (sha256 of random 48-byte token)
  SS-->>R: payload {access_token (JWT 15 min), expires_in, expires_at, user}, raw refresh token
  R->>R: cookie(): Set-Cookie ridez_refresh, HttpOnly, SameSite=Lax, Path=/api/v1/auth, Secure in prod
  R-->>AS: 200 JSON
  AS->>AS: generation++, publish(data) → listeners
  P->>P: navigate(/{role})
```

## Authenticated request (`@authenticated(role)`)

```mermaid
sequenceDiagram
  participant C as Client
  participant D as routes.authenticated
  participant SS as session_service.authenticate
  participant DB as DB
  C->>D: Authorization: Bearer <JWT>
  D->>D: header must start with 'Bearer ' else 401
  D->>SS: authenticate(token)
  SS->>SS: jwt.decode HS256, require sub,sid,iat,exp
  SS->>DB: users.get(sub)
  SS->>DB: auth_sessions.get(sid) — not revoked, not expired, same user
  SS-->>D: (user, claims) or 401 'Please sign in again'
  D->>D: role given and user.role != role → 403
  D->>D: g.user, g.auth_claims set → call view
```

## Silent refresh and single-use rotation

```mermaid
sequenceDiagram
  autonumber
  participant AP as AuthProvider (main.jsx)
  participant AS as authSession.refreshSession
  participant R as routes.refresh_session
  participant SS as session_service.refresh
  participant DB as DB
  AP->>AS: timer fires 60 s before expires_at (or api.js got 401)
  AS->>AS: dedupe with pendingRefresh, Web Lock across tabs
  AS->>R: POST /auth/refresh (cookie, X-Session-Request:1)
  R->>SS: check_origin() → header, Origin, Sec-Fetch-Site
  SS->>DB: refresh_tokens.get(sha256(cookie))
  SS->>DB: auth_sessions valid? user not disabled?
  alt invalid
    SS->>DB: revoke session if found
    R-->>AS: 401 + cookie cleared
    AS->>AS: publish(null) → user is signed out
  else valid
    SS->>DB: UPDATE refresh_tokens SET used_at=now WHERE hash=? AND used_at IS NULL
    alt rowcount != 1 (token replayed)
      SS->>DB: revoke session, stop driver requests
      R-->>AS: 401 'already used'
    else first use
      SS->>DB: INSERT new refresh token
      R-->>AS: 200 new access token + new cookie
    end
  end
```

## Logout and logout-all

```mermaid
sequenceDiagram
  participant W as Workspace / Account
  participant AS as authSession.signOut
  participant R as routes
  participant SS as session_service.logout
  participant RT as realtime.disconnect_invalid
  W->>AS: signOut(allDevices)
  alt allDevices
    AS->>R: POST /auth/refresh (get a fresh token)
    AS->>R: POST /auth/logout-all (Bearer)
    R->>SS: logout(user, all_devices=True) → UPDATE all sessions revoked_at
  else this device
    AS->>R: POST /auth/logout (cookie, optional Bearer)
    R->>SS: logout() → find session via cookie, else via Bearer sid → revoke
  end
  SS->>SS: stop_requests(user): driver → available=false, resume_available=false, PENDING invitations → CLOSED, notify
  SS->>RT: disconnect sockets whose session is no longer valid
  R-->>AS: 200 + Set-Cookie cleared
  AS->>AS: publish(null), BroadcastChannel 'ridez-auth' → other tabs sign out
```
