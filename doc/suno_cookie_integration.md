# Lyric Studio - Suno Cookie Integration

## 1. What is Lyric Studio?

Lyric Studio is a 2-step music creation app:

```
Step 1: Claude AI writes song lyrics (text)
Step 2: Suno AI turns those lyrics into actual music (audio .mp3)
```

The full flow:

```
You (pick genre + theme)
  -> Claude AI (writes lyrics, title, style tags)
    -> Suno Cookie (proves you're logged in)
      -> Suno API (takes lyrics, generates .mp3 audio)
        -> You (download & listen to your song)
```

---

## 2. Where is the Code?

### Core files for music generation (Step 2)

| File | Role |
|------|------|
| `lyric_studio/core/suno_client.py` | **Main file** - HTTP client that talks to Suno API |
| `lyric_studio/core/suno_auth.py` | Opens browser, lets you log in, grabs cookies |
| `lyric_studio/suno_automation/suno_login.py` | Automated Google SSO login |
| `lyric_studio/suno_automation/google_auth.py` | Handles Google email/password/2FA steps |

### Key methods in `suno_client.py`

| Method | What it does |
|--------|-------------|
| `generate()` | Sends lyrics + style tags + title to Suno API, gets back 2 clip objects |
| `poll_until_done()` | Checks every 5 seconds if the song is ready (max 5 min timeout) |
| `download_mp3()` | Downloads finished audio from Suno CDN to a local `.mp3` file |
| `wait_and_download()` | Combines poll + download - this is what `main.py` calls |

---

## 3. Why Does It Need Suno Cookies?

Suno (suno.com) does not have a public API. To use its internal API, you need to be logged in. The app uses your **browser cookies** as proof that you are a real, logged-in user.

| Action | Needs Cookie? |
|--------|:---:|
| Generate music from lyrics | Yes |
| Check remaining credits | Yes |
| Poll if song is ready | Yes |
| Download finished .mp3 | No (public CDN) |

---

## 4. What Are Cookies?

Cookies are small `key=value` notes that a website asks your browser to remember. Every time you visit that website again, your browser sends those notes back automatically.

```
Your Browser                          suno.com Server
    |                                       |
    |-- GET suno.com/create --------------->|
    |   Cookie: __client=abc123;            |
    |           __cf_bm=xyz789              |
    |                                       |
    |<-- 200 OK (you're logged in!) --------|
```

Without cookies, every page load is like visiting for the first time.

---

## 5. Which Cookies Are Needed?

Only cookies from **3 domains** are kept (defined in `suno_auth.py`):

```python
SUNO_COOKIE_DOMAINS = {"suno.com", ".suno.com", "clerk.suno.com"}
```

Everything else (Google, Discord, tracking) is thrown away. Keeping them would cause HTTP 431 errors (header too large).

### The VIP Cookie: `__client`

This is the **only cookie that truly matters**. The app checks for it to confirm a successful login:

```python
has_client = any(c.name == "__client" and c.value for c in all_cookies)
if has_client:
    logged_in = True
```

If `__client` is missing after extraction, the app raises an error.

### Other cookies (supporting cast)

| Cookie | Purpose |
|--------|---------|
| `__client` | **The main one** - Clerk session state |
| `__cf_bm` | Cloudflare bot management (anti-bot) |
| `__client_uat` | Clerk "updated at" timestamp |
| `_cfuvid` | Cloudflare visitor ID |
| `__clerk_*` | Clerk internal state cookies |

---

## 6. What is `__client`?

**Clerk** is an auth-as-a-service provider (like Auth0 or Firebase Auth). Suno uses Clerk to handle all user login. When you log in to suno.com, Clerk sets the `__client` cookie.

### What is inside `__client`?

A long encoded string containing your Clerk client state:

- Your user identity (who you are)
- Session ID (your current login session)
- Session status (active/expired)
- Which sign-in method you used
- Timestamp info

---

## 7. How the App Uses the Cookie (The Chain)

```
__client cookie
    |
    v
Step 1: GET auth.suno.com/v1/client
        Send __client cookie -> Clerk returns session list
        -> Extract "last_active_session_id"
    |
    v
Step 2: POST auth.suno.com/v1/client/sessions/{session_id}/tokens
        Send __client cookie -> Clerk returns a JWT
    |
    v
Step 3: Use JWT as "Authorization: Bearer {jwt}"
        for ALL Suno API calls (generate, poll, billing)
    |
    v
Step 4: JWT expires in 60s, so refresh every 30s
        by repeating Step 2 (which needs __client again)
```

### In plain terms

| Step | What happens | Analogy |
|------|-------------|---------|
| `__client` cookie | Proves you logged in | Your **membership card** |
| Session ID | Identifies your current visit | The **seat number** assigned to you |
| JWT token | Short-lived access pass | A **wristband** that expires every 60 seconds |
| Refresh loop | Gets new wristband using membership card | Going back to the **front desk** every 30s |

### Why not just use the JWT directly?

JWTs expire in 60 seconds. The `__client` cookie is longer-lived (hours or days). The app stores the cookie and generates fresh JWTs from it on demand.

```
Cookie lifespan:    ================================  (hours/days)
JWT lifespan:       ==                                (60 seconds)
                    ==                                (refreshed)
                    ==                                (refreshed)
```

---

## 8. How the Cookie is Obtained

Two methods are available:

### Method A: Manual Browser Login (`suno_auth.py`)

1. App opens a stealth browser to `suno.com/sign-in`
2. You log in manually (Google, Discord, email - any method)
3. App polls browser cookies every 2 seconds looking for `__client`
4. Once found, navigates to `/create` to initialize the Clerk session
5. Extracts all suno.com domain cookies
6. Returns serialized cookie string: `name1=value1; name2=value2; ...`

### Method B: Automated Google SSO (`suno_automation/`)

1. App launches a stealth browser
2. Automatically logs into `accounts.google.com` (email, password, 2FA)
3. Navigates to `suno.com/sign-in`
4. Clicks "Continue with Google"
5. Waits for OAuth redirect chain to complete
6. Navigates to `/create` for Clerk initialization
7. Extracts cookies the same way as Method A

### Cookie storage

Once captured, the cookie string is saved to `~/.lyric_studio/settings.json` so you don't have to log in every time.

---

## 9. Architecture Overview

```
+-------------------------------------------------------------+
|                     LYRIC STUDIO GUI                         |
|  (Flet Desktop App - main.py)                               |
+----------+------------------------------+-------------------+
           |                              |
    +------v----------+         +---------v-------------+
    |   LYRIC GEN     |         |  SUNO INTEGRATION     |
    |  (Claude AI)    |         |  (music generation)   |
    +------+----------+         +---------+-------------+
           |                              |
    +------v----------+         +---------v--------------+
    | core/engine.py  |         | core/suno_client.py    |
    | - generate_     |         | - Cookie -> Session    |
    |   lyrics()      |         | - Session -> JWT       |
    | - parse_songs() |         | - generate()           |
    | - save_songs()  |         | - poll_until_done()    |
    +-----------------+         | - download_mp3()       |
                                +---------+--------------+
                                          |
                                +---------v--------------+
                                | SUNO AUTHENTICATION    |
                                | core/suno_auth.py      |
                                | (manual browser login) |
                                |                        |
                                | suno_automation/       |
                                | (Google SSO login)     |
                                +------------------------+
```
