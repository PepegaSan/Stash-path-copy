# Stash Path Copy

## About

**Stash Path Copy** bridges your **[Stash](https://github.com/stashapp/stash)** library and every other app on Windows that still wants you to **browse for files by hand**.

Search scenes through Stash’s database (title or path), then **copy the real path on disk** — folder, filename, or **full path** — mapped to your NAS or backup drive. Use that path when you **import, open, or link media** in DaVinci, editors, encoders, or any tool with a standard Windows **Open file** dialog.

**No more digging through nested folders** trying to remember where a clip lives.

### Quick workflow (with optional AutoHotkey)

1. Find the scene in Stash Path Copy → **Copy full path**.
2. In your other program, open **File → Open / Import** (file dialog appears).
3. Press your **hotkey** (default **F20**) — the full path is pasted into the file name field and confirmed.

The app can **generate** the same AutoHotkey v2 script from **Settings** (“Create AHK script…”), or use the ready-made [`examples/Pfadpaste.ahk`](examples/Pfadpaste.ahk). You need [AutoHotkey v2](https://www.autohotkey.com/) installed; run the `.ahk` once so it sits in the tray.

**Read-only:** queries Stash over GraphQL only — nothing is written back to Stash.

---

**Short description** (GitHub repo “About” field):

> Copy real file paths from your Stash library for import in other apps. Optional AutoHotkey helper pastes the full path into Windows open dialogs — no more manual folder hunting.

---

## Features

- Search scenes (title / path), load by ID or Stash URL from clipboard
- Right-click a result: **Open in Explorer**, **Copy path** (folder), **Copy filename**, **Copy full path**
- Optional **preview player** to verify the clip
- **Path mapping** for Docker/NAS paths + optional **backup drive** toggle

## Backup path option

Stash often stores paths that do not match your Windows drives (e.g. Docker `/data/...` vs `D:\Library\...`).

In **Settings**:

| Setting | Purpose |
|--------|---------|
| **Path prefix from Stash** | What Stash reports (e.g. `/data/`) |
| **Replace with on this PC** | Your main library (often a NAS mount) |
| **Backup path prefix (optional)** | A second root (archive / offline copy) |

**“Use backup path instead of NAS”** on the main window switches which root is used for copy/open/rename actions.

## Requirements

- Windows (primary target)
- Python 3.10+
- Running Stash with GraphQL reachable
- **AutoHotkey v2** — only if you use the paste helper (`.ahk`)

## Install and run

1. Run `install.bat` (optional `.venv`, then `pip install -r requirements.txt`).
2. Run `start.bat`.
3. Open **Settings**: GraphQL URL, path prefixes, optionally create the AHK script.

Settings are saved as `app_config.json` next to the app (ignored by git). See `app_config.example.json`.

## License

MIT
