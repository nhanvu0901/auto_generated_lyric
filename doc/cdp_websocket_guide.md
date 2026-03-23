# Chrome DevTools Protocol (CDP) & nodriver Guide

## What is nodriver?

**nodriver** is a Python async library for automating Chrome. It's the successor to
`undetected-chromedriver` — instead of wrapping Selenium, it talks **directly** to
Chrome via CDP (Chrome DevTools Protocol) over WebSockets.

### nodriver vs Playwright vs Selenium

| | Selenium | Playwright | nodriver |
|---|---|---|---|
| How it talks to Chrome | WebDriver HTTP protocol → ChromeDriver binary → Chrome | CDP + custom protocol → bundled browser | **Raw CDP WebSocket → your existing Chrome** |
| Bot detection | Easily detected — sets `navigator.webdriver=true`, uses a separate ChromeDriver process | Medium — uses its own patched browsers, some fingerprints remain | **Hard to detect** — uses your real Chrome, patches automation fingerprints |
| Extra binaries needed | ChromeDriver (must match Chrome version) | Downloads its own Chromium/Firefox/WebKit | None — uses Chrome already on your machine |
| Async support | No (blocking) | Yes | Yes (native asyncio) |

### Why nodriver bypasses bot detection better

The key difference: **Playwright ships its own modified browsers**. Bot detection services
(Cloudflare, DataDome, Akamai) can fingerprint these modified browsers because they behave
slightly differently from real Chrome (different WebGL hashes, different `navigator` properties, etc.).

nodriver uses **your actual Chrome installation** — the same binary a human uses. It just
connects to it via CDP. From the website's perspective, it looks like a normal person browsing.

Additionally nodriver:
- Removes `navigator.webdriver = true` flag automatically
- Patches `window.chrome.runtime` to look normal
- Avoids the ChromeDriver process that Selenium exposes

### What is CDP?

**Chrome DevTools Protocol** — the same protocol Chrome DevTools (F12) uses internally.
It's a JSON-over-WebSocket API that lets you:
- Run JavaScript on a page
- Read/set cookies
- Intercept network requests
- Take screenshots
- Monitor DOM changes

When Chrome launches with `--remote-debugging-port=9222`, it exposes CDP endpoints
as WebSocket URLs. That's what nodriver (and Playwright) connect to.

### nodriver's Relationship to CDP

nodriver is essentially a **thin Python wrapper over CDP**:

| nodriver call | What it actually does (CDP) |
|---|---|
| `tab.evaluate(js)` | Sends `Runtime.evaluate` over tab WebSocket |
| `tab.find("Submit")` | Sends `Runtime.evaluate` with DOM query JS |
| `button.click()` | Sends `Input.dispatchMouseEvent` |
| `browser.get(url)` | Sends `Page.navigate` |
| `tab.send(cdp.network.enable())` | Sends `Network.enable` directly |

You can always drop down to raw CDP commands via `tab.send()` or `browser.connection.send()`
when nodriver's high-level API doesn't cover what you need.

### Key nodriver Objects

| Object | What it is | Key properties |
|---|---|---|
| `browser` | Chrome instance | `.tabs`, `.connection`, `.stop()` |
| `browser.connection` | Browser-level CDP WebSocket | `.websocket_url`, `.send()` |
| `tab` | Single page/tab | `.target.url`, `.send()`, `.evaluate()`, `.find()` |
| `tab.target` | Tab metadata (from Chrome's target list) | `.url`, `.title` — always available, no CDP call needed |

### Known nodriver Bugs

**Cookie parsing crash:** `browser.cookies.get_all()` crashes with `KeyError` because
Chrome returns a `sameParty` field that nodriver's `Cookie.from_json()` doesn't handle.
Workaround: extract cookies via raw CDP WebSocket (see Solutions section below).

---

## CDP Architecture

When you launch Chrome with remote debugging enabled, it exposes WebSocket endpoints:

```
Chrome Process (port 9222)
│
├── Browser-level endpoint
│   ws://127.0.0.1:9222/devtools/browser/<id>
│   - Connected to Chrome itself
│   - Survives all navigations, redirects, tab changes
│   - Can query cookies, targets, storage for the entire browser
│
├── Tab 1 endpoint
│   ws://127.0.0.1:9222/devtools/page/<id>
│   - Connected to a specific page
│   - Can run JS (evaluate), intercept network, read DOM
│   - Dies or goes deaf after cross-origin redirects
│
├── Tab 2 endpoint
│   ws://127.0.0.1:9222/devtools/page/<id>
└── ...
```

## The Cross-Origin Redirect Problem

### What happens during OAuth login

```
yoursite.com/login → accounts.google.com → yoursite.com/dashboard
```

1. Browser automation opens a WebSocket to `Tab 1` (your site)
2. User clicks "Login with Google" → tab navigates to `accounts.google.com`
3. Google redirects back to `yoursite.com/dashboard`

### What breaks

After these cross-origin redirects, the **tab-level WebSocket** can become "deaf":
- The socket is still technically **open** (not closed)
- `tab.closed` returns `False`
- But Chrome **stops routing responses** through it
- Any command you send (`evaluate()`, `getCookies()`, etc.) **hangs forever**
- No error, no timeout, no exception — just silence

### Why it's hard to debug

- No error is thrown
- The connection appears healthy
- It works fine with same-origin flows (email/password login)
- It only breaks with cross-origin OAuth (Google, Discord, etc.)

## Solutions

### 1. Passive observation (no CDP calls needed)

For detecting **where the user is**, you don't need a working tab connection.
Chrome maintains a **target list** that's always up to date:

```python
# Safe — reads from Chrome's target list, not via tab WebSocket
for tab in browser.tabs:
    url = tab.target.url  # always available
```

Use this for polling login state:

```python
while time.monotonic() < deadline:
    await asyncio.sleep(2)

    for tab in browser.tabs:
        host = urlparse(tab.target.url).hostname
        path = urlparse(tab.target.url).path

        if host == "yoursite.com" and "/login" not in path:
            # User is logged in!
            break
```

### 2. Browser-level CDP commands

For commands that don't need a specific page (cookies, storage):

```python
import websockets, json

# Get the browser-level WebSocket URL
ws_url = browser.connection.websocket_url
# e.g. ws://127.0.0.1:9222/devtools/browser/a1b2c3d4-...

# Open an independent WebSocket
async with websockets.connect(ws_url, max_size=2**24) as ws:
    # Send any browser-level CDP command
    await ws.send(json.dumps({
        "id": 1,
        "method": "Storage.getCookies",
        "params": {}
    }))

    raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
    result = json.loads(raw)
    cookies = result["result"]["cookies"]
```

### Why open a NEW WebSocket?

The browser automation library (nodriver, playwright, etc.) already has a WebSocket
to the browser. But its internal `_listener` loop **owns** `recv()` on that socket.
If you call `send()` on it, the listener might consume your response before you read it.

Opening a second WebSocket to the **same URL** avoids this conflict:

```
Chrome Browser Endpoint (ws://127.0.0.1:9222/devtools/browser/<id>)
│
├── Library's WebSocket    ← library's listener loop owns recv()
├── Your new WebSocket     ← you control send/recv cleanly
```

Chrome handles multiple WebSocket clients to the same endpoint — no conflicts.

### 3. Open a fresh tab (if you need tab-level commands)

If you need to run JS or interact with the DOM after OAuth:

```python
# Don't reuse the existing (deaf) tab
# Open a brand new tab instead
new_tab = await browser.get("https://yoursite.com/dashboard", new_tab=True)
await new_tab.evaluate("document.title")  # this works — fresh connection
```

## Quick Reference

| Need to...                  | Safe after OAuth? | Method                          |
|-----------------------------|-------------------|---------------------------------|
| Check what URL a tab is on  | Yes               | `tab.target.url`                |
| Get all browser cookies     | Yes               | New WebSocket → `Storage.getCookies` |
| Run JavaScript on a page    | No                | Open a `new_tab=True` instead   |
| Intercept network requests  | No                | Open a `new_tab=True` instead   |
| List all open tabs          | Yes               | `browser.tabs`                  |

## Common CDP Commands (Browser-Level)

These work on the browser-level WebSocket (survive all navigations):

```json
// Get all cookies
{"method": "Storage.getCookies", "params": {}}

// Set a cookie
{"method": "Network.setCookie", "params": {
    "name": "session", "value": "abc123",
    "domain": ".example.com", "path": "/"
}}

// Delete cookies
{"method": "Network.deleteCookies", "params": {
    "name": "session", "domain": ".example.com"
}}

// Get all open tabs/targets
{"method": "Target.getTargets", "params": {}}
```

## Key Takeaways

1. **Browser-level WebSocket** = connected to Chrome itself, always works
2. **Tab-level WebSocket** = connected to a page, can go deaf after cross-origin redirects
3. After OAuth flows, **never trust tab connections** — use browser-level or open new tabs
4. The socket being "open" does NOT mean it works — it can be open but deaf
5. Use `tab.target.url` (target list) instead of `tab.evaluate("location.href")` (CDP call) for URL checking