# Stash Path Copy

A small desktop app for **[Stash](https://github.com/stashapp/stash)** users who need the **real file path** on disk — without digging through NAS folders by hand.

Search scenes in your Stash library (title or path), then copy the folder path, copy the filename, or open the folder in Explorer. Optional **preview player** to confirm you picked the right clip.

**Read-only:** the app only queries Stash over GraphQL. It does not change your Stash database.

## Backup path option

Stash often stores paths that do not match your Windows drives (e.g. Docker `/data/...` vs `D:\Library\...`).

In **Settings** you can map:

| Setting | Purpose |
|--------|---------|
| **Path prefix from Stash** | What Stash reports (e.g. `/data/`) |
| **Replace with on this PC** | Your main library (often a NAS mount) |
| **Backup path prefix (optional)** | A second root (archive / offline copy) |

On the main window, **“Use backup path instead of NAS”** switches which root is used; the rest of the path stays the same.

## Requirements

- Windows (primary target)
- Python 3.10+
- Running Stash with GraphQL reachable
- **FFmpeg** not required; preview uses OpenCV

## Install and run

1. Run `install.bat` (optional `.venv`, then `pip install -r requirements.txt`).
2. Run `start.bat`.
3. Open **Settings** and set your GraphQL URL and path prefixes.

Settings are saved as `app_config.json` next to the app (ignored by git). See `app_config.example.json` for a template.

## License

MIT
