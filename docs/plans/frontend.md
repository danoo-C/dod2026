# Plan: frontend

How the frontend gets built. What it has to do is in
[../tech-spec.md](../tech-spec.md) (5.1–5.3, 4.5, 4.6), every message it sends
and gets is in [../backend.md](../backend.md) 9, and the look is the clickable
mockup [../preview.html](../preview.html). This plan only says in which order,
what each step produces, and how we know it is done.

## Goal

All three screens run against the backend with the simulated board
(`./dod sim`), in the mockup's look:

- `/` on a real phone: join the queue, wait, get a turn, pick presets, change
  parameters, draw on the 8x8, pick a song, lose the turn, queue up again
- `/internal/main` on a notebook-sized screen: the fake terminal on the left,
  the video or the big QR codes on the right, the info bar, the admin panel,
  and it plays the songs and sends their spectrum
- `/internal/logging`: the fake terminal alone, full screen

Visual polish, extra animations and the idle "attract" screen beyond the
mockup are phase 5 in tech-spec 9, not this plan.

## Starting point

- The backend is done up to step 6 and step 9 ([backend plan](backend.md)):
  sessions, the queue, presets with their parameters, the drawing, the
  previews, the fake logs, all over the WebSocket. Its message types are in
  `src/backend/schema/messages.json` (`./dod schema`).
- Music on the backend (its step 8) is not built yet: `welcome.songs` is
  empty and `/media/<id>.mp4` doesn't exist. Step 7 here needs it.
- The mockup has the layout, the colours (CSS variables on `:root`), the
  fonts, and the phone's four states (waiting, loading, your turn, time's up).
- Same rules as for the rest: everything runs in Docker (Node in a `node`
  container, never in WSL), one wrapper script (`./dod`).

Decisions this plan makes, to confirm or change:

1. **No state library.** One store, fed by the WebSocket, read with React's
   `useSyncExternalStore`. The server sends the whole state on every change
   (backend.md 6), so there is nothing to merge.
2. **Plain CSS** with the mockup's variables, one file per screen. No
   Tailwind, no CSS-in-JS.
3. **Fonts bundled** with the `@fontsource` packages (Unbounded, Manrope,
   JetBrains Mono, all OFL). The mockup loads them from Google Fonts; the app
   can't, it has to work without internet (tech-spec 5.1).
4. **Types generated** from `messages.json` into `src/frontend/src/api/messages.ts`,
   committed, with a check that fails when it is out of date (like the schema
   itself).
5. **Tests: Vitest + Testing Library**, in jsdom, for the logic and the
   components. No browser end-to-end suite (Playwright's image is ~2 GB);
   the real browsers are checked by hand, on a real Android phone and a real
   iPhone, with a checklist per step.
6. **The backend serves `src/frontend/dist`** from the mounted project. The
   self-contained image for the notebook (a Node stage in the Dockerfile, the
   source copied in instead of mounted) comes with the Windows launcher, not
   here.
7. **The Wi-Fi QR code needs the hotspot's name and password**, which the
   backend doesn't know yet: two new settings, `DOD_WIFI_SSID` and
   `DOD_WIFI_PASSWORD`, sent in the main screen's `welcome` only. Without
   them the main screen shows only the page's QR code.
8. **The phone's queue line shows positions, not ids.** The mockup shows the
   ids of the people around you (`#7f3a ty #b210`); the state only has how
   many wait (backend.md 6), and that is enough: dots for the others, "ty"
   for you.
9. **No brightness slider on the phone.** The mockup has `Jas`; the
   parameters come from the preset (`welcome.presets`), and the master
   brightness is a setting (`DOD_BRIGHTNESS`), not something visitors change.

## Needed from you along the way

| What | Needed by |
|---|---|
| what the 8x8 shows in manual mode (tech-spec 5.3) – the frontend draws whatever the preview says, so only the "Ikona presetu" button's label and hint wait for it | step 5 (not blocking) |
| backend step 8 (music), which needs the song list | step 7 |
| the hotspot's name and password, for the Wi-Fi QR code | step 6 (until then: only the page's QR code) |
| an Android phone and an iPhone for the hand checks | steps 5–8 |

## Scope

Not part of this plan: the backend (its own plan; the frontend only adds the
small things listed in steps 1 and 6), the Windows launcher and the
self-contained image, polish (tech-spec phase 5).

Layout, as in tech-spec 3:

```
src/frontend/
  package.json, package-lock.json, vite.config.ts, tsconfig.json, index.html
  src/
    main.tsx             the router: /, /internal/main, /internal/logging
    api/                 messages.ts (generated), socket.ts, store.ts, clock.ts
    screens/             Phone, Main, Logging
    apps/                Manual (presets, parameters, drawing), Music (songs, player, spectrum)
    components/          Preview, Terminal, LoadingScreen, Qr, Countdown, Badge, ...
    styles/              tokens.css (the mockup's variables), one file per screen
    assets/fonts/        via @fontsource
  tests/
```

---

### Step 1. Tooling

Files: `src/frontend/*` (the skeleton), `./dod`, `src/backend/dod/api/http.py`

- `src/frontend/` with React, React Router, TypeScript (`strict`) and Vite,
  every version pinned exactly, `package-lock.json` committed
- `./dod npm <args>`: any npm command in a `node:22-slim` container (pinned
  tag) in `src/frontend/`, as the calling user, with a named volume for
  npm's cache so `npm ci` doesn't download everything every time
- `./dod sim` and `./dod dev` (tech-spec 7.1): the backend and `vite --host`
  in two containers on a private Docker network, both reloading on save;
  Vite on port 5173 forwards `/api`, `/ws` (WebSocket) and `/media` to the
  backend. `sim` uses the simulated board, `dev` `/dev/ttyUSB0`. Ctrl-C stops
  both.
- `./dod frontend-build`: `npm run build` → `src/frontend/dist/` (not in git)
- the backend serves the build: the page routes answer with
  `dist/index.html`, `/assets/*` from `dist/assets/`; without a build, the
  placeholder page as now. `/` still sets the session cookie.
- `./dod schema` also writes `src/frontend/src/api/messages.ts` (with
  `json-schema-to-typescript`, in the node container)
- `./dod test frontend`: `tsc --noEmit`, Vitest, and the check that
  `messages.ts` matches `messages.json`; `./dod test` runs it as a third suite
- a hello page per route that shows its role and the backend's `/api/health`

Done when:

- [ ] `./dod sim`: `http://localhost:5173` opens from Windows, and from a phone
  on the same network at the PC's address; a change to a `.tsx` shows up
  without a reload – **partly checked**, see Built
- [x] after `./dod frontend-build`, `./dod backend` serves the app on port
  8000; `/internal/main` and `/internal/logging` too (React Router picks)
- [x] `./dod test` runs all three suites; renaming a field in
  `dod/api/messages.py` and running `./dod schema` makes `tsc` fail where
  the field is used
- [x] no request leaves the page for the internet (checked in the browser's
  network tab: fonts and everything else come from the backend) – checked in
  the build (no external URL in it); the browser's network tab once a
  browser looks at it

Built:

- `src/frontend/`: React 19.3, React Router 8.5, Vite 8.3, TypeScript 7.0
  (`strict`, plus `noUncheckedIndexedAccess`), Vitest 5 with jsdom and
  Testing Library. Every version exact, picked with `npm install
  --before=2026-10-21` (two weeks old at least), `package-lock.json`
  committed. Two type checks: `tsconfig.json` for the browser code and the
  tests, `tsconfig.node.json` for the Vite and Vitest configs (Node's types
  stay out of the browser code).
- `./dod npm`, `./dod sim`, `./dod dev`, `./dod frontend-build`, and
  `./dod test frontend` as the third suite (a path under `src/frontend`
  picks it; its arguments go to Vitest). Node is `node:22.23.4-slim`; npm's
  cache is the Docker volume `dod2026-npm`; `npm ci` runs by itself when
  `node_modules` is missing or older than the lock file. `sim` and `dev` run
  the backend in the background and Vite in front, on the network
  `dod2026-dev`; Ctrl-C stops both. The backend's port 8000 is published
  too, for `curl /api/status`. Neither container gets a terminal (`-t`): with
  one, Docker put the shared terminal into raw mode and the backend's lines
  came out as a staircase. Without a terminal Vite ignores SIGINT, so both
  run in the background and `./dod`'s trap stops them on Ctrl-C (or when
  either one ends). A second `./dod sim` while one runs refuses to start
  instead of stopping the first one's containers.
- `./dod schema` writes `messages.json` and then `src/api/messages.ts`
  (`scripts/types.mjs`, json-schema-to-typescript). Field titles and the
  bands' length are left out of the types (they would give aliases like
  `Type7` and a 32-element tuple); the backend checks the length.
  `npm test` fails when `messages.ts` is out of date.
- the backend: the page routes answer with `dist/index.html`
  (`Cache-Control: no-cache`), `/assets` from `dist/assets`; before a build
  the placeholder and 404s (Starlette's `StaticFiles` would answer with an
  error while the folder is missing). A build made while the backend runs is
  picked up. `create_app(frontend_dist=)` for the tests.
- the hello page per route: the screen's name, its role, and whether
  `/api/health` answers.
- checked by hand: the build on port 8000 (all three routes, the asset);
  through Vite on 5173: the page, `/api/health`, `/api/session` with its
  cookie, and a WebSocket upgrade that gets the backend's `welcome`; an
  edited `.tsx` is served changed at once. **Not checked yet:** a Windows
  browser and the reload-free update in it, and a phone. WSL runs in NAT
  mode, which forwards ports to Windows' `localhost` only: a phone needs
  `networkingMode=mirrored` in `%UserProfile%\.wslconfig` (then `wsl
  --shutdown`) or a `netsh interface portproxy` rule for 5173 (admin), and
  Windows Firewall allowing it.
- the frontend's suite: 7 tests, ~1 s (plus ~10 s for the two type checks
  and the container); backend 424 tests.
- `Error` in `messages.ts` is the backend's error message, and shadows the
  global `Error` where it is imported: import it as `import type { Error as
  ErrorMessage }`.

### Step 2. The connection (backend.md 9)

Files: `api/socket.ts`, `api/store.ts`, `api/clock.ts`

- the start of every page: `GET /api/session` (with `?key=` from the URL on
  the internal pages, and then the key removed from the address bar), then
  `WS /ws?role=…`
- the close codes, as in backend.md 9: `4401` → `/api/session` and connect
  again; `4403` → an error screen, no reconnect; `4001` → "Otvorené v inom
  okne" and a button to take over, no reconnect until it is pressed; `4400`
  → an error (a bug); `1009`, `1001` and anything else → reconnect with
  backoff (0.5 s doubling to 5 s, with jitter)
- reconnect at once when the page becomes visible again (a phone that was
  locked: iOS closes its WebSockets)
- the store: `welcome`, the latest `state`, `you`, `preview`, the log lines
  (the last 300), the connection's status, the last `error`; components read
  it with one hook, `useStand()`
- the clock: offset = server `now` − local time, from every `state`; times
  like `turn_ends_at` are shown against it (backend.md 6)
- sending: one typed function per message, `send({type: "set_preset", …})`,
  so a typo doesn't compile; nothing is queued while disconnected (a stale
  slider value is worse than none)
- `error` messages: `not_your_turn` and `no_player` become a short toast in
  Slovak; `rate_limited` is ignored (the slider already sends less, step 5)

Done when:

- [x] with a fake WebSocket in Vitest: each close code does what the table
  says; the backoff stays between 0.5 and 5 s; `4401` calls `/api/session`
  once, then connects
- [x] the clock offset is right with a phone clock 30 s off; a countdown
  shows the same seconds as the server
- [ ] by hand with `./dod sim`: stopping the backend shows "odpojené" and the
  page comes back by itself when it starts again; a second main screen shows
  "Otvorené v inom okne" on the first – **needs a browser**, see Built

Built:

- `api/socket.ts`: `StandSocket` – `/api/session` (the internal key once,
  then out of the address bar with `history.replaceState`), the WebSocket,
  the close codes as in the table. Statuses: `connecting`, `open` (after
  `welcome`), `offline`, `replaced`, `forbidden` (also a wrong key: 403 from
  `/api/session`), `broken`. Every retry starts with `/api/session`, so a
  restarted backend is fine; the first `4401` fetches it at once, a second
  one backs off. Backoff 0.5 → 1 → 2 → 4 → 5 s, ±20 %, clamped to 0.5–5 s,
  back to 0.5 s after a `welcome`. `visibilitychange` (and `online`) while
  waiting: try at once. `send()` returns false unless open, nothing is kept.
- `api/clock.ts`: `ServerClock` – the offset is the **largest of the last 10**
  `server now − local` samples: a message can only arrive late, never early,
  so a late one would make the offset too small; a clock set while the page
  runs is followed within 10 states. `secondsUntil()`, `formatSeconds()`.
- `api/store.ts`: `Store` (one immutable snapshot: status, welcome, state,
  you, preview, the last 300 log lines, a toast) and `Stand` (the socket
  feeding a store). Toasts: `not_your_turn`, `no_player` and also
  `unknown_song` (a song taken off the list while a phone shows it), 3 s;
  `rate_limited` ignored; `invalid` and `forbidden` go to the console (bugs).
- `api/useStand.tsx`: `<StandProvider role>`, `useStand(select)` (re-renders
  only when the selected part changes – previews come 10 times a second),
  `useStandActions()` (`send`, `takeOver`), `useServerClock()`.
- `components/Connection.tsx`: `ConnectionGate` – `replaced` (with
  "Prevziať"), `forbidden` and `broken` take the whole screen; `offline` is a
  strip on top and the screen stays. Plain styles until step 3.
- the hello page now shows the connection: status, session, mode, the queue,
  the turn's countdown on the server's clock, the clock offset, the number
  of log lines (internal pages); the phone's has "Postaviť sa do radu" /
  "Odísť z radu", to see a countdown run.
- fixed on the way: the type generator dropped every *field* called `title`
  (`MusicPart.title`, `SongInfo.title`) along with the schema titles it
  should drop; it now also fails when a model's field is missing from
  `messages.ts`.
- 53 frontend tests, ~1.3 s; two deliberate breaks (4001 treated as a lost
  connection, no backoff wait) each make the right tests fail.
- checked by hand: the build bundles, and `./dod sim` serves every new module.
  **Not checked yet** (needs a browser): the two checks above, and the
  phone's countdown against the server.

### Step 3. Shared components

Files: `components/Preview.tsx`, `Terminal.tsx`, `LoadingScreen.tsx`,
`Qr.tsx`, `Countdown.tsx`, `Badge.tsx`, `styles/tokens.css`

- `tokens.css`: the mockup's variables (colours, fonts, radius), dark only
- **Preview**: the strip as `preview.leds`, the 8x8 from `preview.matrix` (16
  hex characters, 8 rows, bit 7 = left) in the LEDs' red, dimmed by
  `brightness` (0–15) – the same picture the board shows. Small, large and
  phone sizes.
- **Terminal** (tech-spec 4.5): lines as `[14:02:17.481] tag  LEVEL text`, a
  colour per level (`DEBUG`, `INFO`, `OK`, `WARN`, as in the mockup) and per
  tag (a fixed hash into the five accent colours), at most 300 lines in the
  DOM, always scrolled to the bottom, a blinking cursor, the banner
  `DOD-2026 LIGHT ENGINE v4.2.0` when it opens. Text is rendered as text,
  never as HTML (board text ends up here).
- **LoadingScreen**: 2–4 s (random), the ring, the steps and the hex lines from
  the mockup; it sends `loading_started` when it starts, so the terminal
  bursts at the same time (backend.md 10)
- **Qr**: `qrcode.react`, for the page's address (`welcome.public_url`) and
  the Wi-Fi (`WIFI:S:<ssid>;T:WPA;P:<password>;;`)
- **Countdown**: mm:ss to a server time, with the clock from step 2
- **Badge**: the board's state (`state.hardware`) and the connection's, green
  / orange / red, with the error as its title

Done when:

- [ ] Vitest: the 8x8 decodes `183c7effff7e3c18` into the right pixels and
  dims with the brightness; the terminal keeps 300 lines after 1000, colours
  every level, and shows `<b>` as text; the loading screen ends within 2–4 s
  and sends `loading_started` once
- [ ] a dev-only page in Vite (`/components.html`, left out of the build)
  shows every component with fake data, for checking them by eye

### Step 4. The logging page (`/internal/logging`)

Files: `screens/Logging.tsx`

- the terminal full screen, nothing else; the role `logging`
- the badge in a corner, small, so a dead backend is noticed

Done when:

- [ ] by hand with `./dod sim`: it opens on a full screen of lines (the
  history), keeps scrolling at 3–8 lines a second, bursts when a phone's
  loading screen runs; a reload is full again at once
- [ ] without the key: an error screen, no lines
- [ ] runs an hour in Edge without the tab's memory growing (Task Manager)

### Step 5. The phone (`/`)

Files: `screens/Phone.tsx`, `apps/Manual/*`, `apps/Music/SongList.tsx`

What the phone shows comes from `you` and `state` alone, so a reload always
lands on the right screen:

| Condition | Screen |
|---|---|
| not in the queue (`you.position` is `null`), never had a turn | welcome: what this is, "Postaviť sa do radu" |
| waiting (`position` ≥ 1) | "Si 3. v poradí", about how long (the current turn's rest + a full turn for each one ahead), the queue line (dots, "ty"), the live preview, "Odísť z radu" |
| just got control (`in_control` turned true) | the loading screen, then the controls |
| in control | the timer to `you.turn_ends_at` (or "Kým niekto nepríde" when `turn_over` and nobody waits), tabs Ovládanie / Hudba |
| lost control (was `in_control`, isn't, not in the queue) | "Tvoj čas skončil", "Znova do radu" |

- **Ovládanie**: the presets from `welcome.presets` as big buttons; the
  current preset's parameters from its `ParamInfo`, one control per kind
  (`slider`, `color`, `choice`, `toggle`), labels in Slovak from the backend –
  so a new preset needs no frontend change (backend.md 7.2). The values shown
  are the state's, so two screens never disagree.
- a slider sends at most 10 values a second while dragged, and always the
  last one when released (the backend allows 20 a second, backend.md 9)
- **Kresli na 8×8**: an 8x8 grid, tap or drag to switch pixels, sent as
  `set_matrix` with `mode: "drawing"` (at most 10 a second, like a slider);
  "Vymazať"; "Ikona presetu" switches back to `mode: "icon"`
- **Hudba**: the songs from `welcome.songs`; greyed out when not downloaded
  (`ready`) or when no main screen plays (`player_connected` false);
  picking one sends `play_song` and shows the loading screen. Until backend
  step 8 the list is empty: "Zatiaľ žiadne skladby".
- the strip preview at the top of every screen, as in the mockup
- big tap targets (≥ 44 px), no zoom on double tap, works from 360 px wide

Done when:

- [ ] Vitest: a control for every parameter kind, built from the real
  `welcome` of `solid` and `rainbow`; the screen table above, with `you` and
  `state` messages as input; the slider sends ≤ 10 a second and the last
  value; a drawing round-trips through its 16 hex characters
- [ ] by hand, `./dod sim` and two real phones (Android, iPhone): join →
  wait (the other has control) → loading → control → preset, every
  parameter, a drawing on the board's 8x8 preview → "Tvoj čas skončil" when
  the time is up and the other waits → "Znova do radu"
- [ ] a reload, and 20 s with the phone locked, keep the place and the turn;
  30 s without input loses it and the phone says so
- [ ] the phone that isn't in control never shows controls, even after a
  reload in the middle of the other's turn

### Step 6. The main screen (`/internal/main`)

Files: `screens/Main.tsx`, `components/AdminPanel.tsx`; backend:
`dod/settings.py`, `dod/api/messages.py` (`Welcome.wifi`)

- the mockup's layout: the terminal on the left (`--term-w`, 25–33 %), the
  right part, and the info bar below it (what plays, the queue length, the
  small preview, both QR codes)
- the right part: while a song plays, the video (step 7); otherwise the big
  QR codes, "Naskenuj kód a ovládaj svetlá", the queue and the large preview
- **"Spustiť"** once at the start: one click, so the browser allows audio
  later (tech-spec 6.3, step 7); until then the main screen connects but
  doesn't count as the player
- **the admin panel**: opens with Ctrl+Alt+D, closes with Esc (Edge
  already uses Ctrl+Shift+A for its tab search; Ctrl+Alt+D is checked to be
  free in Edge's `--app` window); skip the
  current person, pause / resume the queue, stop the song, the terminal's
  width (kept in `localStorage`), the board's status in full. Visitors never
  see it: it isn't in the page until opened.
- **4001**: the overlay from step 2, with "Prevziať" to take over
- backend: `DOD_WIFI_SSID` and `DOD_WIFI_PASSWORD` (both or neither,
  checked at startup like the other settings), `welcome.wifi` for the main
  role only; `./dod schema` again

Done when:

- [ ] by hand on a 1920×1080 and a 1366×768 screen, full screen in Edge
  (`msedge --app=… --start-fullscreen`): nothing overflows, the terminal is
  readable from 2 m, the QR codes scan from 1.5 m with an Android phone and
  an iPhone
- [ ] each admin action does what it says (seen on a phone and in the state);
  Ctrl+Alt+D does nothing on `/`
- [ ] Vitest: the right part switches between video and QR codes with
  `state.mode`; the Wi-Fi QR code is left out without `welcome.wifi`
- [ ] backend tests: the two settings are checked together; `wifi` is only in
  the main screen's `welcome`

### Step 7. Music on the main screen (backend.md 6; tech-spec 5.2)

Needs: backend step 8 (`/media`, the player's song endings, `welcome.songs`).

Files: `apps/Music/Player.tsx`, `apps/Music/spectrum.ts`, `apps/Music/beat.ts`

- the player: when `state.music.song` changes, a `<video>` plays
  `/media/<id>.mp4` from the start; stops when it goes back to `null`
- `player` messages: the position once a second, and `ended: true` when the
  video ends or can't be played (the backend ends the song either way,
  backend.md 6, this only makes it quicker)
- the spectrum: Web Audio `AnalyserNode` on the video (`fftSize` 2048), its
  bins grouped into 32 bands spaced logarithmically from ~40 Hz to ~16 kHz,
  each 0–1 with a slow automatic gain, sent ~30 times a second with
  `requestAnimationFrame` (and not at all while the tab is hidden)
- the beat: the low bands' energy against its average over the last ~1 s,
  with a minimum gap of ~300 ms between beats
- only the main screen plays; `player_connected` in the state tells phones
  whether songs can be picked

Done when:

- [ ] Vitest: `spectrum.ts` turns a known bin array into the expected 32
  bands; `beat.ts` finds the beats in a synthetic 120 BPM kick and none in
  white noise
- [ ] by hand with `./dod sim`: a song picked on the phone → loading screens on
  the phone and the main screen, the terminal bursts → the video plays with
  sound → the preview follows the music → the song ends → back to the last
  preset
- [ ] ~30 spectrum messages a second (`/api/status` or the backend's log),
  none while the window is minimised
- [ ] closing the main screen mid-song: the song ends within 10 s, the phones
  grey the songs out; reopening it plays again

### Step 8. End to end

Files: `docs/plans/frontend.md` (checklist results)

- the whole Goal with `./dod sim` on the notebook-sized screen and two real
  phones, and once with `./dod dev` and the real board when it exists
  (phase 3)
- phones on the hotspot from tech-spec 6.4 when the notebook is available
  (phase 4); until then, a phone hotspot or the home Wi-Fi

Done when:

- [ ] every step's hand checklist passes again in one session, in this order:
  logging page, main screen, two phones, a song
- [ ] an hour with the main screen open and a phone joining every few minutes:
  no errors in the browser console, no reconnect loop, the tabs' memory
  stable
- [ ] the frontend's tests run in under 30 s
- [ ] tech-spec 5.1 and backend.md 9 are updated wherever the build showed
  the design had to change

---

## Order and dependencies

| Step | Needs |
|---|---|
| 1. Tooling | – |
| 2. Connection | 1 |
| 3. Components | 1; the terminal and the preview are checked against 2 |
| 4. Logging page | 2, 3 |
| 5. Phone | 2, 3; songs only with backend step 8 |
| 6. Main screen | 2, 3; the Wi-Fi QR code with the hotspot's name and password |
| 7. Music | 6, backend step 8 |
| 8. End to end | all |

- 4 is small and the first screen that shows the whole chain working, so it
  comes first after the components.
- 5 and 6 can be built in either order; 5 first, because the phone is what
  visitors use the most.
- 7 is the only step that waits for the backend; everything else runs
  against what the backend has today.
