"""Stash Path Copy – slim GUI to search Stash scenes and copy file paths/names.

This is a standalone tool (not a sub-program). It only reads from Stash via
GraphQL; no writes are performed. The UI mirrors the look & feel of the
"Stash Metadaten Editor" but exposes only Tab 1 (Szenen) and a reduced
right-click context menu with three entries:

    - Im Datei-Explorer öffnen
    - Pfad kopieren (nur Ordnerpfad, nicht die Datei)
    - Dateinamen kopieren

The gear (Zahnrad) settings dialog matches the original (appearance,
language, GraphQL endpoint, API key, NAS/local path prefix mapping).

A simple preview player (Play / Pause / Stop) can be opened from the
scenes card to verify which video is which.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional

import customtkinter as ctk
import requests
import tkinter as tk
from requests import HTTPError
from tkinter import filedialog, messagebox

from theme_palette import PALETTE_DARK, PALETTE_LIGHT


DEFAULT_URL = "http://localhost:9999/graphql"
APP_TITLE = "Stash Path Copy"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def app_config_path() -> Path:
    """Settings next to the EXE (frozen) or next to app.py (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "app_config.json"
    return Path(__file__).resolve().parent / "app_config.json"


def extract_stash_scene_id_from_clipboard(text: str) -> Optional[str]:
    """Parse a Stash scene id from a URL (browser address bar) or plain digits."""
    raw = (text or "").strip()
    if not raw:
        return None
    m = re.search(r"/scenes/(\d+)", raw, re.IGNORECASE)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d+", raw):
        return raw
    return None


def stash_base_url_from_endpoint(endpoint: str) -> Optional[str]:
    ep = (endpoint or "").strip().rstrip("/")
    if not ep:
        return None
    if ep.lower().endswith("/graphql"):
        return ep[: -len("/graphql")]
    return ep


def stash_scene_browser_url(endpoint: str, scene_id: str) -> Optional[str]:
    base = stash_base_url_from_endpoint(endpoint)
    sid = (scene_id or "").strip()
    if not base or not sid:
        return None
    return f"{base}/scenes/{sid}"


# ---------------------------------------------------------------------------
# i18n strings (de/en) — kept compatible with the original app where useful.
# ---------------------------------------------------------------------------
I18N: Dict[str, Dict[str, str]] = {
    "de": {
        "app_title": APP_TITLE,
        "connect": "Verbinden",
        "save_settings": "Einstellungen speichern",
        "not_connected": "Nicht verbunden",
        "search_scene_ph": "Szene suchen (Titel oder Dateipfad)",
        "search": "Suchen",
        "reload": "Neu laden",
        "scene_count": "Szenen",
        "scene_id_ph": "Szene ID",
        "load": "Laden",
        "load_clipboard": "ID aus Zwischenablage",
        "clipboard_empty_title": "Zwischenablage",
        "clipboard_empty_body": "Kein Text in der Zwischenablage (zuerst URL oder Szenen-ID kopieren).",
        "clipboard_invalid_title": "Keine Szenen-ID erkannt",
        "clipboard_invalid_body": "Erwartet wird eine reine Ziffern-ID oder eine Stash-URL mit …/scenes/123",
        "scenes_section_search": "Suchen & Treffer",
        "scenes_section_results": "Trefferliste",
        "scenes_section_loaded": "Geladene Szene",
        "scene_search_empty": "Keine Treffer — Suchbegriff ändern oder Stash/Verbindung prüfen.",
        "scene_search_enter_hint": "Enter im Suchfeld startet die Suche.",
        "scene_id_row_hint": "Klick: Szenen-ID übernehmen · Shift+Klick: nur markieren · Doppelklick: laden. Rechtsklick: Ordner öffnen, Pfad/Dateiname kopieren.",
        "scene_loaded_badge": "Geladen",
        "scenes_copied": "In Zwischenablage kopiert.",
        "context_open_explorer": "Im Datei-Explorer öffnen",
        "context_copy_path": "Pfad kopieren",
        "context_copy_filename": "Dateinamen kopieren",
        "context_copy_full_path": "Kompletten Pfad kopieren",
        "context_rename_file": "Datei umbenennen…",
        "rename_dialog_title": "Datei umbenennen",
        "rename_dialog_prompt": "Neuer Dateiname (im Ordner {folder}):",
        "rename_file_not_found_title": "Datei nicht gefunden",
        "rename_file_not_found_body": "Diese Datei ist auf dem lokalen System nicht erreichbar:\n{path}\n\nPrüfe die Pfad-Ersetzung in den Einstellungen oder ob das Laufwerk verbunden ist.",
        "rename_invalid_name_title": "Ungültiger Dateiname",
        "rename_invalid_name_body": "Der Dateiname darf keine Pfadtrenner (\\ /) und keine der folgenden Zeichen enthalten:\n< > : \" | ? *\n\nLeer oder identisch zum aktuellen Namen ist ebenfalls nicht erlaubt.",
        "rename_target_exists_title": "Zieldatei existiert bereits",
        "rename_target_exists_body": "Im selben Ordner gibt es bereits eine Datei mit diesem Namen:\n{path}\n\nUmbenennen abgebrochen.",
        "rename_confirm_title": "Datei umbenennen?",
        "rename_confirm_body": "Die Datei wird auf der Platte umbenannt:\n\nVon:  {old}\nNach: {new}\n\nOrdner: {folder}\n\nDamit Stash die Datei wieder findet, muss anschließend ein Scan in Stash laufen.\n\nFortfahren?",
        "rename_failed_title": "Umbenennen fehlgeschlagen",
        "rename_failed_body": "Die Datei konnte nicht umbenannt werden:\n{path}\n\n{error}",
        "rename_success_title": "Datei umbenannt",
        "rename_success_body": "Die Datei wurde erfolgreich umbenannt:\n{path}\n\nDamit Stash sie wieder findet, jetzt in Stash einen Scan starten (Settings → Tasks → Scan).",
        "ctx_no_path_title": "Kein Dateipfad",
        "ctx_no_path_body": "Für diese Szene ist kein Dateipfad hinterlegt.",
        "ctx_copy_path_empty": "Kein Dateipfad für diese Zeile.",
        "ctx_open_folder_failed": "Ordner konnte nicht geöffnet werden",
        "scene_selected_filename_label": "Dateiname (Auswahl)",
        "scene_selected_filename_copy_btn": "Kopieren",
        "open_in_stash": "In Stash öffnen",
        "no_scene_loaded": "Keine Szene geladen",
        "graphql_ph": "z. B. http://localhost:9999/graphql",
        "api_key_ph": "optional",
        "stash_url_missing": "Bitte die GraphQL-URL in den Einstellungen (Zahnrad) eintragen.",
        "top_err_url": "GraphQL-URL fehlt — bitte unter Einstellungen (Zahnrad) eintragen.",
        "top_err_api": "API-Zugriff fehlgeschlagen — prüfen Sie den API-Key unter Einstellungen (Zahnrad).",
        "settings_saved": "Einstellungen gespeichert",
        "settings_title": "Einstellungen",
        "settings_close": "Schließen",
        "settings_appearance": "Erscheinungsbild",
        "settings_language": "Sprache",
        "settings_stash_url": "Stash GraphQL-URL",
        "settings_api_key": "API-Schlüssel",
        "settings_player_path_section": "NAS-/Serverpfade (Ersetzung)",
        "settings_player_prefix_remote": "Pfadpräfix wie von Stash geliefert",
        "settings_player_prefix_remote_ph": "z. B. /data/",
        "settings_player_prefix_local": "Auf diesem PC ersetzen durch",
        "settings_player_prefix_local_ph": "z. B. S:\\Medien oder \\\\NAS\\Freigabe",
        "settings_player_path_hint": "Wenn Stash Linux-Pfade (Synology …) speichert und du auf Windows arbeitest: hier den Anfang des Serverpfads und den passenden lokalen Ordner eintragen (gemountete Freigabe).",
        "settings_backup_prefix_label": "Backup-Pfadpräfix (optional, gespiegelte Sicherung)",
        "settings_backup_prefix_ph": "z. B. I:\\P Sammlung\\Hauptordner",
        "settings_backup_prefix_hint": "Optional: zweites Laufwerk, auf das der NAS-Ordner gespiegelt wird. Wird das oben aktivierte Häkchen „Sicherung verwenden“ in der Trefferzeile gesetzt, beziehen sich „Kompletten Pfad kopieren“, „Pfad kopieren“, „Im Datei-Explorer öffnen“ und „Datei umbenennen…“ auf diese Sicherung statt auf das NAS. Stash selbst arbeitet weiterhin nur mit dem NAS-Pfad.",
        "topbar_use_backup": "Sicherung statt NAS verwenden",
        "topbar_use_backup_tooltip": "Wenn aktiv, beziehen sich „Kompletten Pfad kopieren“, „Pfad kopieren“, „Im Datei-Explorer öffnen“ und „Datei umbenennen…“ auf den in den Einstellungen hinterlegten Sicherungspfad.",
        "topbar_use_backup_needs_config": "Backup-Pfadpräfix in den Einstellungen eintragen, um diese Option zu aktivieren.",
        "settings_ahk_section": "AutoHotkey-Helfer",
        "settings_ahk_hint": (
            "Erzeugt ein kleines AutoHotkey-Skript (Pfadpaste.ahk), das im „Datei öffnen / Importieren“-Dialog "
            "anderer Programme per Tastendruck den kopierten kompletten Pfad direkt in das Dateinamen-Feld einsetzt "
            "und mit Enter bestätigt. Voraussetzung: AutoHotkey v2 ist installiert (autohotkey.com). "
            "Im Skript steht „F20::“ — diesen Hotkey nach Belieben auf eine freie Taste ändern (z. B. F8 oder #v)."
        ),
        "settings_ahk_export_btn": "AHK-Skript erzeugen…",
        "settings_ahk_info_btn": "Info",
        "settings_ahk_info_title": "AutoHotkey-Helfer",
        "settings_ahk_info_body": (
            "Das Skript hängt sich an einen Hotkey (Standard: F20) und prüft, ob der aktuell aktive "
            "Vordergrundfenster ein klassischer Windows-Dateidialog (Klasse #32770) ist. Wenn ja, schreibt es "
            "den kompletten Pfad aus der Zwischenablage direkt in das Dateinamen-Feld (Edit1) und drückt Enter.\n\n"
            "So nutzt du es:\n"
            "1) AutoHotkey v2 installieren (https://www.autohotkey.com).\n"
            "2) Hier auf „AHK-Skript erzeugen…“ klicken und einen Speicherort wählen.\n"
            "3) Die .ahk-Datei per Doppelklick starten – sie liegt dann unten rechts in der Taskleiste.\n"
            "4) In Stash path copy „Kompletten Pfad kopieren“ verwenden.\n"
            "5) Im Ziel-Programm den Datei-öffnen-Dialog aufrufen und den Hotkey drücken – der Pfad wird "
            "automatisch eingesetzt und bestätigt.\n\n"
            "Tipp: Möchtest du einen anderen Hotkey, öffne die .ahk mit einem Editor und ersetze „F20::“ "
            "durch eine andere Taste (z. B. „F8::“ oder „#v::“ für Win+V). Anschließend das Skript neu starten."
        ),
        "settings_ahk_save_title": "AutoHotkey-Skript speichern",
        "settings_ahk_saved_title": "Skript gespeichert",
        "settings_ahk_saved_body": "Das AutoHotkey-Skript wurde erstellt:\n{path}\n\nJetzt per Doppelklick starten (AutoHotkey v2 muss installiert sein).",
        "settings_ahk_save_failed_title": "Skript konnte nicht gespeichert werden",
        "settings_ahk_save_failed_body": "Fehler beim Schreiben der Datei:\n{path}\n\n{error}",
        "settings_player_path_info_title": "Pfadpräfixe",
        "settings_player_path_info_body": (
            "Zwei Felder — es wird nur der Anfang des Dateipfads ersetzt, den Stash für die Videodatei liefert:\n\n"
            "• Erstes Feld («Pfadpräfix wie von Stash geliefert»): Der exakte Anfang des Pfads aus Stash, z. B. /data/… auf dem Linux-NAS.\n\n"
            "• Zweites Feld («Auf diesem PC ersetzen durch»): Wie dieselbe Datei auf deinem Windows-Rechner erreichbar ist — z. B. Laufwerk S:\\… oder UNC \\\\Server\\Freigabe\\…\n\n"
            "Stash selbst ändert den Pfad nicht; die App ersetzt nur diesen Anfang.\n\n"
            "Beispiel:\nStash meldet: /data/film.mp4\nLokal: S:\\Medien\\film.mp4\n→ Remote: /data/\n→ Lokal: S:\\Medien\\"
        ),
        "lang_switched": "Sprache live umgestellt",
        "preview_player_btn": "Vorschau",
        "preview_player_window_title": "Video-Vorschau",
        "preview_player_url_label": "Stash-Szenen-URL",
        "preview_player_url_ph": "https://…/scenes/123 oder nur 123",
        "preview_player_load_btn": "Video laden",
        "preview_player_hint": "Lädt die zur Szene gehörende lokale Videodatei und spielt sie ab — nur zur Vorschau (Play / Pause / Stop). Slider zum Spulen. F11: Vollbild, Esc beenden, Leertaste: Play/Pause.",
        "preview_player_play": "Play",
        "preview_player_pause": "Pause",
        "preview_player_stop": "Stop",
        "preview_player_fullscreen_btn": "Vollbild",
        "preview_player_missing_deps_title": "Vorschau nicht verfügbar",
        "preview_player_missing_deps_body": "Für den Vorschau-Player werden „opencv-python-headless“ und „Pillow“ benötigt.\n\nInstallation:\n    pip install opencv-python-headless Pillow\n\noder einfach install.bat erneut ausführen.",
        "preview_player_bad_url_title": "Keine Szenen-ID erkannt",
        "preview_player_bad_url_body": "Bitte eine Stash-URL mit …/scenes/123 oder eine reine Zahlen-ID eingeben.",
        "preview_player_load_fail_title": "Szene konnte nicht geladen werden",
        "preview_player_no_path_title": "Kein Dateipfad",
        "preview_player_no_path_body": "Für diese Szene ist in Stash kein Dateipfad hinterlegt.",
        "preview_player_open_fail_title": "Video konnte nicht geöffnet werden",
        "preview_player_open_fail_body": "OpenCV konnte die Datei nicht öffnen:\n{path}",
        "preview_player_mapped_from": "Original (von Stash): {original}",
        "preview_player_remote_path_hint": "\n\nHinweis: Der Pfad sieht nach einem Linux-Pfad auf dem Stash-Server aus (z. B. Synology unter /data/…). Der Player läuft auf diesem Windows-Rechner und braucht eine hier sichtbare Datei — z. B. per SMB gemountet als Laufwerksbuchstabe oder UNC (\\\\Server\\Freigabe\\…). In den Einstellungen (Zahnrad) kannst du eine Präfix-Ersetzung eintragen.",
    },
    "en": {
        "app_title": APP_TITLE,
        "connect": "Connect",
        "save_settings": "Save settings",
        "not_connected": "Not connected",
        "search_scene_ph": "Search scene (title or file path)",
        "search": "Search",
        "reload": "Reload",
        "scene_count": "scenes",
        "scene_id_ph": "Scene ID",
        "load": "Load",
        "load_clipboard": "ID from clipboard",
        "clipboard_empty_title": "Clipboard",
        "clipboard_empty_body": "Clipboard is empty (copy a URL or scene id first).",
        "clipboard_invalid_title": "No scene id recognized",
        "clipboard_invalid_body": "Expected a numeric id or a Stash URL containing …/scenes/123",
        "scenes_section_search": "Search & matches",
        "scenes_section_results": "Results",
        "scenes_section_loaded": "Loaded scene",
        "scene_search_empty": "No matches — change the search term or check the Stash connection.",
        "scene_search_enter_hint": "Press Enter in the search field to search.",
        "scene_id_row_hint": "Click: pick scene id · Shift+click: mark only · Double-click: load. Right-click: open folder, copy path/filename.",
        "scene_loaded_badge": "Loaded",
        "scenes_copied": "Copied to clipboard.",
        "context_open_explorer": "Open in file explorer",
        "context_copy_path": "Copy path",
        "context_copy_filename": "Copy filename",
        "context_copy_full_path": "Copy full path",
        "context_rename_file": "Rename file…",
        "rename_dialog_title": "Rename file",
        "rename_dialog_prompt": "New file name (in folder {folder}):",
        "rename_file_not_found_title": "File not found",
        "rename_file_not_found_body": "The file is not reachable locally:\n{path}\n\nCheck the path mapping in Settings or whether the drive / share is connected.",
        "rename_invalid_name_title": "Invalid file name",
        "rename_invalid_name_body": "The file name must not contain path separators (\\ /) or any of these characters:\n< > : \" | ? *\n\nEmpty or identical to the current name is also not allowed.",
        "rename_target_exists_title": "Target file already exists",
        "rename_target_exists_body": "A file with that name already exists in the same folder:\n{path}\n\nRename aborted.",
        "rename_confirm_title": "Rename file?",
        "rename_confirm_body": "The file will be renamed on disk:\n\nFrom: {old}\nTo:   {new}\n\nFolder: {folder}\n\nFor Stash to find the file again, run a Scan in Stash afterwards.\n\nContinue?",
        "rename_failed_title": "Rename failed",
        "rename_failed_body": "The file could not be renamed:\n{path}\n\n{error}",
        "rename_success_title": "File renamed",
        "rename_success_body": "The file was renamed successfully:\n{path}\n\nRun a Stash scan now (Settings → Tasks → Scan) so Stash can find it again.",
        "ctx_no_path_title": "No file path",
        "ctx_no_path_body": "No file path is stored for this scene.",
        "ctx_copy_path_empty": "No file path for this row.",
        "ctx_open_folder_failed": "Could not open folder",
        "scene_selected_filename_label": "Filename (selection)",
        "scene_selected_filename_copy_btn": "Copy",
        "open_in_stash": "Open in Stash",
        "no_scene_loaded": "No scene loaded",
        "graphql_ph": "e.g. http://localhost:9999/graphql",
        "api_key_ph": "optional",
        "stash_url_missing": "Enter the GraphQL URL in Settings (gear icon).",
        "top_err_url": "GraphQL URL missing — add it in Settings (gear).",
        "top_err_api": "API access failed — check your API key in Settings (gear).",
        "settings_saved": "Settings saved",
        "settings_title": "Settings",
        "settings_close": "Close",
        "settings_appearance": "Appearance",
        "settings_language": "Language",
        "settings_stash_url": "Stash GraphQL URL",
        "settings_api_key": "API key",
        "settings_player_path_section": "NAS / server path mapping",
        "settings_player_prefix_remote": "Path prefix as returned by Stash",
        "settings_player_prefix_remote_ph": "e.g. /data/",
        "settings_player_prefix_local": "Replace with on this PC",
        "settings_player_prefix_local_ph": "e.g. S:\\Media or \\\\NAS\\share",
        "settings_player_path_hint": "If Stash stores Linux paths (e.g. Synology) and you work on Windows: set the server path prefix and the matching local folder (mounted share).",
        "settings_backup_prefix_label": "Backup path prefix (optional, mirrored copy)",
        "settings_backup_prefix_ph": "e.g. I:\\P Sammlung\\Hauptordner",
        "settings_backup_prefix_hint": "Optional: a second drive that mirrors the NAS folder. When the \"Use backup\" checkbox in the results bar is enabled, \"Copy full path\", \"Copy path\", \"Open in file explorer\" and \"Rename file…\" target this backup instead of the NAS. Stash itself keeps working with the NAS path only.",
        "topbar_use_backup": "Use backup instead of NAS",
        "topbar_use_backup_tooltip": "When active, \"Copy full path\", \"Copy path\", \"Open in file explorer\" and \"Rename file…\" target the backup prefix configured in Settings.",
        "topbar_use_backup_needs_config": "Set a backup path prefix in Settings to enable this option.",
        "settings_ahk_section": "AutoHotkey helper",
        "settings_ahk_hint": (
            "Generates a small AutoHotkey script (Pfadpaste.ahk) that, while a Windows file-open / import "
            "dialog is in focus, types the copied full path directly into the file-name field and presses "
            "Enter. Requires AutoHotkey v2 (autohotkey.com). The script uses \"F20::\" — change this to any "
            "free key (e.g. F8 or #v)."
        ),
        "settings_ahk_export_btn": "Create AHK script…",
        "settings_ahk_info_btn": "Info",
        "settings_ahk_info_title": "AutoHotkey helper",
        "settings_ahk_info_body": (
            "The script binds to a hotkey (default: F20) and checks whether the active foreground window is "
            "a classic Windows file dialog (class #32770). If yes, it writes the full path from the "
            "clipboard directly into the file-name field (Edit1) and presses Enter.\n\n"
            "How to use:\n"
            "1) Install AutoHotkey v2 (https://www.autohotkey.com).\n"
            "2) Click \"Create AHK script…\" and pick a location.\n"
            "3) Double-click the .ahk file – it sits in the tray.\n"
            "4) In Stash path copy use \"Copy full path\".\n"
            "5) In the target program open the file-open dialog and press the hotkey – the path is typed "
            "and confirmed automatically.\n\n"
            "Tip: to change the hotkey, open the .ahk in a text editor and replace \"F20::\" with another "
            "key (e.g. \"F8::\" or \"#v::\" for Win+V). Then restart the script."
        ),
        "settings_ahk_save_title": "Save AutoHotkey script",
        "settings_ahk_saved_title": "Script saved",
        "settings_ahk_saved_body": "The AutoHotkey script was created:\n{path}\n\nDouble-click it to launch (AutoHotkey v2 must be installed).",
        "settings_ahk_save_failed_title": "Could not save script",
        "settings_ahk_save_failed_body": "Error writing the file:\n{path}\n\n{error}",
        "settings_player_path_info_title": "Path prefix mapping",
        "settings_player_path_info_body": (
            "Two fields — only the start of the file path returned by Stash is rewritten:\n\n"
            "• First field (\"Path prefix as returned by Stash\"): the exact beginning of Stash's path, e.g. /data/… on a Linux NAS.\n\n"
            "• Second field (\"Replace with on this PC\"): how the same file is reachable on this Windows machine — e.g. S:\\… or \\\\server\\share\\…\n\n"
            "Stash does not change paths; the app only replaces this prefix.\n\n"
            "Example:\nStash: /data/movie.mp4\nLocal: S:\\Media\\movie.mp4\n→ Remote: /data/\n→ Local: S:\\Media\\"
        ),
        "lang_switched": "Language switched live",
        "preview_player_btn": "Preview",
        "preview_player_window_title": "Video preview",
        "preview_player_url_label": "Stash scene URL",
        "preview_player_url_ph": "https://…/scenes/123 or just 123",
        "preview_player_load_btn": "Load video",
        "preview_player_hint": "Loads the local video file for this scene and plays it back for verification (Play / Pause / Stop). Slider scrubs. F11: fullscreen, Esc exits, Space: play/pause.",
        "preview_player_play": "Play",
        "preview_player_pause": "Pause",
        "preview_player_stop": "Stop",
        "preview_player_fullscreen_btn": "Fullscreen",
        "preview_player_missing_deps_title": "Preview not available",
        "preview_player_missing_deps_body": "The preview player needs \"opencv-python-headless\" and \"Pillow\".\n\nInstall:\n    pip install opencv-python-headless Pillow\n\nor simply re-run install.bat.",
        "preview_player_bad_url_title": "No scene id recognized",
        "preview_player_bad_url_body": "Enter a Stash URL containing …/scenes/123 or a plain numeric id.",
        "preview_player_load_fail_title": "Could not load scene",
        "preview_player_no_path_title": "No file path",
        "preview_player_no_path_body": "Stash has no file path stored for this scene.",
        "preview_player_open_fail_title": "Could not open video",
        "preview_player_open_fail_body": "OpenCV could not open the file:\n{path}",
        "preview_player_mapped_from": "Original (from Stash): {original}",
        "preview_player_remote_path_hint": "\n\nNote: this path looks like a Linux path on the Stash host (e.g. Synology /data/...). The player runs on this Windows PC and needs a locally reachable file — mount the share (drive letter or \\\\server\\share\\...). In Settings (gear) you can set a prefix remap.",
    },
}


# ---------------------------------------------------------------------------
# UI constants
# ---------------------------------------------------------------------------
BTN_RADIUS = 10
BTN_HEIGHT_COMPACT = 36
TOP_BAR_H = 56
FONT_APP_TITLE = ("Segoe UI Black", 18)
FONT_UI = ("Segoe UI", 14)
FONT_UI_SM = ("Segoe UI", 12)
FONT_SECTION = ("Segoe UI Semibold", 15)
FONT_HINT = ("Segoe UI", 11)
FONT_BTN = ("Segoe UI Black", 10)
FONT_NAV = ("Segoe UI Semibold", 10)
FONT_NAV_ACTIVE = ("Segoe UI Black", 10)
CONN_LED_ON = "#2ecc71"


@dataclass
class SceneItem:
    scene_id: str
    title: str
    date: str
    path: str


# ---------------------------------------------------------------------------
# Stash GraphQL client (read-only subset)
# ---------------------------------------------------------------------------
class StashClient:
    def __init__(self, endpoint: str = "", api_key: str = "") -> None:
        self.endpoint = endpoint.strip()
        self.api_key = api_key.strip()

    def configure(self, endpoint: str, api_key: str = "") -> None:
        ep = endpoint.strip().rstrip("/")
        if ep and not ep.lower().endswith("/graphql"):
            ep = ep + "/graphql"
        self.endpoint = ep
        self.api_key = api_key.strip()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["ApiKey"] = self.api_key
        return headers

    def graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.endpoint:
            raise RuntimeError("GraphQL endpoint is empty.")
        payload = {"query": query, "variables": variables or {}}
        response = requests.post(self.endpoint, json=payload, headers=self._headers(), timeout=25)
        try:
            response.raise_for_status()
        except HTTPError as exc:
            snippet = response.text[:600]
            raise RuntimeError(f"HTTP {response.status_code}: {snippet}") from exc
        body = response.json()
        if "errors" in body and body["errors"]:
            first = body["errors"][0]
            raise RuntimeError(first.get("message", "Unknown GraphQL error"))
        return body.get("data", {})

    def ping(self) -> str:
        data = self.graphql("query Version { version { version } }")
        return str(data.get("version", {}).get("version", "unknown"))

    def find_scenes(self, text: str, per_page: int = 200) -> List[SceneItem]:
        query = """
        query FindScenes($filter: FindFilterType) {
          findScenes(filter: $filter) {
            scenes { id title date files { path } }
          }
        }
        """
        scenes: List[SceneItem] = []
        text_l = (text or "").strip().lower()
        seen_ids: set[str] = set()
        page = 1
        for _ in range(200):
            data = self.graphql(query, {"filter": {"page": page, "per_page": per_page}})
            raw = data.get("findScenes", {}).get("scenes", [])
            if not raw:
                break
            for scene in raw:
                scene_id = str(scene.get("id", ""))
                if not scene_id or scene_id in seen_ids:
                    continue
                seen_ids.add(scene_id)
                files = scene.get("files") or []
                path = files[0].get("path", "") if files else ""
                title = str(scene.get("title") or "")
                if text_l and text_l not in title.lower() and text_l not in str(path).lower():
                    continue
                scenes.append(
                    SceneItem(
                        scene_id=scene_id,
                        title=title,
                        date=str(scene.get("date") or ""),
                        path=str(path),
                    )
                )
            if len(raw) < per_page:
                break
            page += 1
        return scenes

    def get_scene_details(self, scene_id: str) -> Dict[str, Any]:
        query = """
        query FindScene($id: ID!) {
          findScene(id: $id) {
            id title date files { path duration }
          }
        }
        """
        data = self.graphql(query, {"id": scene_id})
        scene = data.get("findScene")
        if not scene:
            raise RuntimeError("Scene not found.")
        return scene


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self) -> None:
        self._themed_buttons: List[tuple[Any, str, int, Optional[int], Optional[tuple]]] = []
        self._geom_save_after_id: Optional[str] = None
        self._last_saved_geometry = ""
        self._load_config()
        self._settings_dialog: Any = None
        self._settings_appearance_seg: Any = None
        self._settings_inner: Any = None
        self._settings_endpoint_entry: Any = None
        self._settings_api_key_entry: Any = None
        self._settings_prefix_remote_entry: Any = None
        self._settings_prefix_local_entry: Any = None
        self._settings_prefix_backup_entry: Any = None
        self._settings_dialog_labels: list[tuple[ctk.CTkLabel, str]] = []
        self.lang_en_btn: Any = None
        self.lang_de_btn: Any = None

        self._pal: Dict[str, str] = dict(
            PALETTE_LIGHT if self.config_appearance == "light" else PALETTE_DARK
        )
        if self.config_appearance == "light":
            ctk.set_appearance_mode("light")
        elif self.config_appearance == "system":
            ctk.set_appearance_mode("system")
            self._pal = dict(PALETTE_DARK)
        else:
            ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=self._pal["bg"])

        self._endpoint_var = tk.StringVar(value=self.config_endpoint)
        self._api_key_var = tk.StringVar(value=self.config_api_key)
        self._appearance = ctk.StringVar(value=self.config_appearance)
        self.status_var = tk.StringVar(value=self.tr("not_connected"))
        self._use_backup_var = tk.BooleanVar(
            value=bool((self.config_path_map or {}).get("use_backup", False))
        )

        self.title(self.tr("app_title"))
        self._apply_window_geometry_from_config()

        self.client = StashClient(DEFAULT_URL, "")
        self.scene_rows: List[SceneItem] = []
        self.scene_line_to_id: Dict[int, str] = {}
        self._scene_list_selected_line: Optional[int] = None
        self.current_scene: Optional[Dict[str, Any]] = None
        self._connection_ok = False
        self._preview_player_win: Any = None

        self._build_ui()
        self._apply_config_to_widgets()
        self._sync_palette()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close_request)
        self.bind("<Configure>", self._on_app_configure_maybe_save_geom, add="+")
        if getattr(self, "_config_file_was_missing", False):
            self.after(200, self._save_initial_config_if_needed)

    # ---- config ---------------------------------------------------------
    def _load_config(self) -> None:
        path = app_config_path()
        self._config_file_was_missing = not path.is_file()
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        self.config_endpoint = str(cfg.get("endpoint", DEFAULT_URL))
        self.config_api_key = str(cfg.get("api_key", ""))
        self.lang_code = str(cfg.get("language", "de")).lower()
        if self.lang_code not in I18N:
            self.lang_code = "de"
        self.config_appearance = str(cfg.get("appearance", "dark")).lower()
        if self.config_appearance not in ("dark", "light", "system"):
            self.config_appearance = "dark"
        self.config_last_scene_search = str(cfg.get("last_scene_search", ""))
        path_map = cfg.get("path_map") or cfg.get("marker_player") or {}
        if isinstance(path_map, dict):
            self.config_path_map: Dict[str, Any] = {
                "path_prefix_remote": str(path_map.get("path_prefix_remote", "") or ""),
                "path_prefix_local": str(path_map.get("path_prefix_local", "") or ""),
                "path_prefix_backup": str(path_map.get("path_prefix_backup", "") or ""),
                "use_backup": bool(path_map.get("use_backup", False)),
            }
        else:
            self.config_path_map = {
                "path_prefix_remote": "",
                "path_prefix_local": "",
                "path_prefix_backup": "",
                "use_backup": False,
            }
        pp = cfg.get("preview_player") or {}
        if isinstance(pp, dict):
            self.config_preview_player: Dict[str, Any] = {
                "geometry": str(pp.get("geometry", "") or "").strip(),
            }
        else:
            self.config_preview_player = {"geometry": ""}
        self.config_window_geometry = str(cfg.get("window_geometry", "") or "").strip()

    def _save_config(self, notify: bool = True) -> None:
        self._sync_vars_from_settings_entries_if_alive()
        appearance = self.config_appearance
        if hasattr(self, "_appearance"):
            appearance = (self._appearance.get() or "dark").strip().lower()
            self.config_appearance = appearance
        last_search = ""
        if hasattr(self, "scene_search_entry"):
            try:
                last_search = self.scene_search_entry.get().strip()
            except tk.TclError:
                last_search = ""
        win_geo = str(getattr(self, "config_window_geometry", "") or "").strip()
        try:
            if self.winfo_exists() and self.winfo_viewable():
                w, h = self.winfo_width(), self.winfo_height()
                if w >= 200 and h >= 200:
                    win_geo = self.geometry().strip()
                    self.config_window_geometry = win_geo
        except tk.TclError:
            pass
        cfg = {
            "endpoint": self._endpoint_var.get().strip(),
            "api_key": self._api_key_var.get().strip(),
            "language": self.lang_code,
            "appearance": appearance,
            "last_scene_search": last_search,
            "path_map": dict(getattr(self, "config_path_map", {}) or {}),
            "preview_player": dict(getattr(self, "config_preview_player", {}) or {}),
            "window_geometry": win_geo,
        }
        try:
            with open(app_config_path(), "w", encoding="utf-8", newline="\n") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.config_endpoint = str(cfg.get("endpoint", "") or "")
        self.config_api_key = str(cfg.get("api_key", "") or "")
        if notify:
            self.status_var.set(self.tr("settings_saved"))

    def _save_initial_config_if_needed(self) -> None:
        if not getattr(self, "_config_file_was_missing", False):
            return
        try:
            self._save_config(notify=False)
        except Exception:
            pass
        self._config_file_was_missing = False

    def _apply_config_to_widgets(self) -> None:
        self._endpoint_var.set(self.config_endpoint)
        self._api_key_var.set(self.config_api_key)
        self._update_language_buttons()
        if getattr(self, "config_last_scene_search", "") and hasattr(self, "scene_search_entry"):
            try:
                self.scene_search_entry.delete(0, "end")
                self.scene_search_entry.insert(0, self.config_last_scene_search)
            except tk.TclError:
                pass

    # ---- geometry persistence ------------------------------------------
    def _apply_window_geometry_from_config(self) -> None:
        geo = str(getattr(self, "config_window_geometry", "") or "").strip()
        if not geo:
            self.geometry("1100x780")
            return
        try:
            self.geometry(geo)
        except tk.TclError:
            self.geometry("1100x780")

    def _on_app_configure_maybe_save_geom(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        aid = getattr(self, "_geom_save_after_id", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
        self._geom_save_after_id = self.after(500, self._flush_window_geometry_to_config)

    def _flush_window_geometry_to_config(self) -> None:
        self._geom_save_after_id = None
        try:
            if not self.winfo_exists() or not self.winfo_viewable():
                return
            w, h = self.winfo_width(), self.winfo_height()
            if w < 200 or h < 200:
                return
            g = self.geometry().strip()
            if g == getattr(self, "_last_saved_geometry", ""):
                return
            self._last_saved_geometry = g
            self.config_window_geometry = g
            self._save_config(notify=False)
        except tk.TclError:
            pass

    def _on_app_close_request(self) -> None:
        try:
            if self.winfo_exists() and self.winfo_viewable():
                w, h = self.winfo_width(), self.winfo_height()
                if w >= 200 and h >= 200:
                    self.config_window_geometry = self.geometry().strip()
        except tk.TclError:
            pass
        try:
            self._sync_vars_from_settings_entries_if_alive()
            self._save_config(notify=False)
        except Exception:
            pass
        win = getattr(self, "_preview_player_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.destroy()
            except tk.TclError:
                pass
            self._preview_player_win = None
        self.destroy()

    # ---- translation ----------------------------------------------------
    def tr(self, key: str) -> str:
        lang_map = I18N.get(self.lang_code, I18N["en"])
        return lang_map.get(key, key)

    # ---- top-bar / banner ----------------------------------------------
    def _clear_top_banner(self) -> None:
        if not hasattr(self, "top_alert_label"):
            return
        self.top_alert_label.configure(text="")
        self.top_alert_label.grid_remove()

    def _set_top_banner(self, text: str) -> None:
        if not hasattr(self, "top_alert_label"):
            return
        t = (text or "").strip()
        if not t:
            self._clear_top_banner()
            return
        self.top_alert_label.configure(text=t)
        self.top_alert_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))

    def _format_connect_error(self, exc: BaseException, api_key_used: bool) -> str:
        raw = str(exc).lower()
        if api_key_used and any(
            x in raw for x in ("401", "403", "unauthorized", "forbidden", "apikey", "api key", "invalid api")
        ):
            return self.tr("top_err_api")
        return str(exc)[:280]

    def _apply_connection_led_colors(self) -> None:
        if not hasattr(self, "conn_led"):
            return
        p = self._pal
        col = CONN_LED_ON if self._connection_ok else p["stop"]
        try:
            self.conn_led.configure(fg_color=col, border_color=p["btn_rim"])
        except tk.TclError:
            pass

    def _set_connection_led(self, ok: bool) -> None:
        self._connection_ok = bool(ok)
        self._apply_connection_led_colors()

    # ---- button factory ------------------------------------------------
    def _button_kw(
        self,
        variant: str = "ghost",
        *,
        height: int = 40,
        font: Optional[tuple] = None,
        width: Optional[int] = None,
    ) -> Dict[str, Any]:
        p = self._pal
        base_font = font or FONT_BTN
        kw: Dict[str, Any] = dict(
            corner_radius=BTN_RADIUS,
            font=base_font,
            height=height,
            border_width=2,
            border_color=p["btn_rim"],
        )
        if width is not None:
            kw["width"] = width
        if variant == "ghost":
            kw.update(fg_color=p["panel_elev"], hover_color=p["border"], text_color=p["text"])
        elif variant == "primary":
            kw.update(
                fg_color=p["cyan_dim"],
                hover_color=p["cyan"],
                text_color=p["text"],
                border_color=p["primary_border"],
            )
        elif variant == "primary_emphasis":
            kw.update(
                fg_color=p["cyan_dim"],
                hover_color=p["cyan"],
                text_color=p["text"],
                border_color=p["primary_border"],
                font=("Segoe UI Black", 11),
            )
        elif variant == "nav_idle":
            kw.update(
                fg_color=p["panel_elev"],
                hover_color=p["border"],
                text_color=p["muted"],
                font=FONT_NAV,
            )
        elif variant == "nav_active":
            kw.update(
                fg_color=p["cyan_dim"],
                hover_color=p["cyan"],
                text_color=p["text"],
                border_color=p["cyan"],
                font=FONT_NAV_ACTIVE,
            )
        return kw

    def _mk_btn(
        self,
        parent: Any,
        variant: str,
        *,
        text: str = "",
        command: Any = None,
        height: Optional[int] = None,
        width: Optional[int] = None,
        font: Optional[tuple] = None,
    ) -> ctk.CTkButton:
        h = BTN_HEIGHT_COMPACT if height is None else height
        btn = ctk.CTkButton(parent, text=text, command=command, **self._button_kw(variant, height=h, font=font, width=width))
        self._themed_buttons.append((btn, variant, h, width, font))
        return btn

    # ---- styling helpers ------------------------------------------------
    def _refresh_ctk_entry_draw(self, w: ctk.CTkEntry) -> None:
        try:
            if not w.winfo_exists():
                return
        except tk.TclError:
            return
        draw = getattr(w, "_draw", None)
        if callable(draw):
            try:
                draw(False)
            except TypeError:
                draw()

    def _schedule_entry_placeholder_refresh(self, w: ctk.CTkEntry) -> None:
        try:
            self.after(50, lambda: self._refresh_ctk_entry_draw(w))
        except tk.TclError:
            pass

    def _style_entry(self, w: ctk.CTkEntry) -> None:
        p = self._pal
        try:
            w.configure(placeholder_text_color=p["muted"])
        except tk.TclError:
            pass
        w.configure(fg_color=p["panel_elev"], border_color=p["border"], text_color=p["text"])
        self._schedule_entry_placeholder_refresh(w)

    def _style_textbox(self, w: ctk.CTkTextbox) -> None:
        p = self._pal
        w.configure(fg_color=p["panel_elev"], border_color=p["border"], text_color=p["text"])

    # ---- UI build -------------------------------------------------------
    def _build_ui(self) -> None:
        self._themed_buttons.clear()
        self._settings_dialog = None
        self._settings_appearance_seg = None
        self._settings_inner = None
        self._settings_endpoint_entry = None
        self._settings_api_key_entry = None
        self._settings_prefix_remote_entry = None
        self._settings_prefix_local_entry = None
        self._settings_dialog_labels.clear()
        self.lang_en_btn = None
        self.lang_de_btn = None

        p = self._pal
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top bar -----------------------------------------------------------
        self._frame_top = ctk.CTkFrame(self, fg_color=p["panel"], corner_radius=0, height=TOP_BAR_H)
        self._frame_top.grid(row=0, column=0, sticky="ew")
        self._frame_top.grid_columnconfigure(1, weight=1)

        self._title_label = ctk.CTkLabel(
            self._frame_top,
            text=self.tr("app_title"),
            font=FONT_APP_TITLE,
            text_color=p["text"],
            fg_color="transparent",
        )
        self._title_label.grid(row=0, column=0, padx=(16, 12), pady=10, sticky="w")

        self._top_mid = ctk.CTkFrame(self._frame_top, fg_color="transparent")
        self._top_mid.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        self._top_mid.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            self._top_mid,
            textvariable=self.status_var,
            font=FONT_UI,
            text_color=p["muted"],
            fg_color="transparent",
        )
        self.status_label.grid(row=0, column=0, sticky="ew")

        self.top_alert_label = ctk.CTkLabel(
            self._top_mid,
            text="",
            font=FONT_HINT,
            text_color=p["stop"],
            fg_color="transparent",
            wraplength=520,
            justify="center",
        )
        self.top_alert_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.top_alert_label.grid_remove()

        actions = ctk.CTkFrame(self._frame_top, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="e", padx=(4, 12), pady=6)

        self.conn_led = ctk.CTkFrame(
            actions,
            width=14,
            height=14,
            corner_radius=7,
            fg_color=p["stop"],
            border_width=1,
            border_color=p["btn_rim"],
        )
        self.conn_led.pack(side="left", padx=(0, 8))
        self.conn_led.pack_propagate(False)

        self._mk_btn(actions, "primary_emphasis", text=self.tr("connect"), command=self.connect, width=120).pack(
            side="left", padx=(0, 6)
        )
        self._mk_btn(
            actions,
            "primary",
            text=self.tr("save_settings"),
            command=lambda: self._save_config(notify=True),
            width=160,
        ).pack(side="left", padx=(0, 6))

        gear_kw = dict(self._button_kw("ghost", height=BTN_HEIGHT_COMPACT, width=40))
        self.gear_btn = ctk.CTkButton(
            actions,
            text="\u2699",
            command=self._open_settings_dialog,
            **gear_kw,
        )
        self.gear_btn.pack(side="left", padx=(8, 0))
        self._themed_buttons.append((self.gear_btn, "ghost", BTN_HEIGHT_COMPACT, 40, None))

        # Body --------------------------------------------------------------
        self._frame_body = ctk.CTkFrame(self, fg_color=p["bg"])
        self._frame_body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 10))
        self._frame_body.grid_columnconfigure(0, weight=1)
        self._frame_body.grid_rowconfigure(0, weight=1)

        self._content = ctk.CTkFrame(
            self._frame_body,
            fg_color=p["panel"],
            corner_radius=10,
            border_width=1,
            border_color=p["border"],
        )
        self._content.grid(row=0, column=0, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self.page_scenes = ctk.CTkFrame(self._content, fg_color="transparent")
        self.page_scenes.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 8))
        self.page_scenes.grid_columnconfigure(0, weight=1)

        self._build_page_scenes(self.page_scenes)

    # ---- Scenes tab UI --------------------------------------------------
    def _build_page_scenes(self, tab: ctk.CTkFrame) -> None:
        p = self._pal
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Search & match
        self.scenes_search_card = ctk.CTkFrame(
            tab, fg_color=p["panel_elev"], corner_radius=10, border_width=1, border_color=p["border"]
        )
        self.scenes_search_card.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 6))
        self.scenes_search_card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self.scenes_search_card,
            text=self.tr("scenes_section_search"),
            font=FONT_SECTION,
            text_color=p["text"],
            fg_color="transparent",
        ).grid(row=0, column=0, columnspan=5, sticky="w", padx=10, pady=(8, 4))

        self.scene_search_entry = ctk.CTkEntry(self.scenes_search_card, placeholder_text=self.tr("search_scene_ph"))
        self.scene_search_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        self._style_entry(self.scene_search_entry)
        self.scene_search_entry.bind("<Return>", self._on_scene_search_return)

        self._mk_btn(self.scenes_search_card, "primary", text=self.tr("search"), command=self.search_scenes).grid(
            row=1, column=2, padx=8, pady=6
        )
        self._mk_btn(self.scenes_search_card, "ghost", text=self.tr("reload"), command=self.reload_current_scene).grid(
            row=1, column=3, padx=8, pady=6
        )

        self.scene_search_enter_hint = ctk.CTkLabel(
            self.scenes_search_card,
            text=self.tr("scene_search_enter_hint"),
            font=FONT_HINT,
            text_color=p["muted"],
            fg_color="transparent",
        )
        self.scene_search_enter_hint.grid(row=2, column=0, columnspan=5, sticky="w", padx=10, pady=(0, 4))

        self.scene_id_entry = ctk.CTkEntry(self.scenes_search_card, placeholder_text=self.tr("scene_id_ph"))
        self.scene_id_entry.grid(row=3, column=1, sticky="ew", padx=8, pady=(0, 6))
        self._style_entry(self.scene_id_entry)
        self.scene_id_entry.bind("<KeyRelease>", lambda _e: self._refresh_scene_loaded_indicator())

        self._mk_btn(self.scenes_search_card, "primary_emphasis", text=self.tr("load"), command=self.load_scene_by_id).grid(
            row=3, column=2, padx=8, pady=(0, 6)
        )
        self._mk_btn(
            self.scenes_search_card,
            "ghost",
            text=self.tr("open_in_stash"),
            command=self.open_scene_in_stash,
        ).grid(row=3, column=3, padx=8, pady=(0, 6))
        self._mk_btn(
            self.scenes_search_card,
            "ghost",
            text=self.tr("load_clipboard"),
            command=self.load_scene_from_clipboard,
        ).grid(row=3, column=4, padx=8, pady=(0, 6))
        self._mk_btn(
            self.scenes_search_card,
            "ghost",
            text=self.tr("preview_player_btn"),
            command=self.open_preview_player,
        ).grid(row=3, column=5, padx=(4, 8), pady=(0, 6))

        self.scene_id_row_hint = ctk.CTkLabel(
            self.scenes_search_card,
            text=self.tr("scene_id_row_hint"),
            font=FONT_HINT,
            text_color=p["muted"],
            fg_color="transparent",
            justify="left",
            wraplength=780,
        )
        self.scene_id_row_hint.grid(row=4, column=0, columnspan=6, sticky="ew", padx=10, pady=(0, 8))

        # Results
        self.scenes_results_card = ctk.CTkFrame(
            tab, fg_color=p["panel_elev"], corner_radius=10, border_width=1, border_color=p["border"]
        )
        self.scenes_results_card.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        self.scenes_results_card.grid_columnconfigure(0, weight=1)
        self.scenes_results_card.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(
            self.scenes_results_card,
            text=self.tr("scenes_section_results"),
            font=FONT_SECTION,
            text_color=p["text"],
            fg_color="transparent",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))

        count_row = ctk.CTkFrame(self.scenes_results_card, fg_color="transparent")
        count_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
        count_row.grid_columnconfigure(1, weight=1)
        self.scene_count_label = ctk.CTkLabel(
            count_row, text=f"0 {self.tr('scene_count')}", font=FONT_UI, text_color=p["text"], fg_color="transparent"
        )
        self.scene_count_label.grid(row=0, column=0, sticky="w", padx=2)
        self.scene_empty_hint = ctk.CTkLabel(
            count_row,
            text="",
            font=FONT_HINT,
            text_color=p["muted"],
            fg_color="transparent",
            justify="left",
        )
        self.scene_empty_hint.grid(row=0, column=1, sticky="w", padx=12)

        self.scene_list_text = ctk.CTkTextbox(self.scenes_results_card)
        self.scene_list_text.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 4))
        self.scene_list_text.configure(state="normal")
        self._style_textbox(self.scene_list_text)
        self.after(0, self._wire_scene_match_list)

        # Selected filename row
        sel_file_row = ctk.CTkFrame(self.scenes_results_card, fg_color="transparent")
        sel_file_row.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 8))
        sel_file_row.grid_columnconfigure(1, weight=1)
        self.scene_selected_filename_label = ctk.CTkLabel(
            sel_file_row,
            text=self.tr("scene_selected_filename_label"),
            font=FONT_UI_SM,
            text_color=p["muted"],
            fg_color="transparent",
        )
        self.scene_selected_filename_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.scene_selected_file_entry = ctk.CTkEntry(sel_file_row)
        self.scene_selected_file_entry.grid(row=0, column=1, sticky="ew")
        self._style_entry(self.scene_selected_file_entry)
        self._mk_btn(
            sel_file_row,
            "ghost",
            text=self.tr("scene_selected_filename_copy_btn"),
            command=self._copy_scene_selected_filename_clipboard,
            width=88,
        ).grid(row=0, column=2, padx=(8, 0))

        # Backup toggle: switches "Copy full path", "Copy path", "Open in explorer"
        # and "Rename file" to the optional backup drive (configured in Settings).
        self._backup_toggle_row = ctk.CTkFrame(
            self.scenes_results_card, fg_color="transparent"
        )
        self._backup_toggle_row.grid(row=5, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._backup_toggle_row.grid_columnconfigure(1, weight=1)
        self._backup_toggle_chk = ctk.CTkCheckBox(
            self._backup_toggle_row,
            text=self.tr("topbar_use_backup"),
            variable=self._use_backup_var,
            command=self._on_use_backup_toggle,
        )
        self._backup_toggle_chk.grid(row=0, column=0, sticky="w")
        self._backup_toggle_hint = ctk.CTkLabel(
            self._backup_toggle_row,
            text="",
            font=FONT_HINT,
            text_color=p["muted"],
            fg_color="transparent",
            anchor="w",
            justify="left",
        )
        self._backup_toggle_hint.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self._refresh_backup_toggle_state()

        # Loaded scene
        self.scenes_loaded_card = ctk.CTkFrame(
            tab, fg_color=p["panel_elev"], corner_radius=10, border_width=1, border_color=p["border"]
        )
        self.scenes_loaded_card.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.scenes_loaded_card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self.scenes_loaded_card,
            text=self.tr("scenes_section_loaded"),
            font=FONT_SECTION,
            text_color=p["text"],
            fg_color="transparent",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 4))

        loaded_row = ctk.CTkFrame(self.scenes_loaded_card, fg_color="transparent")
        loaded_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        loaded_row.grid_columnconfigure(1, weight=1)
        self.scene_loaded_badge = ctk.CTkLabel(
            loaded_row,
            text=self.tr("scene_loaded_badge"),
            font=FONT_UI_SM,
            text_color=p["cyan"],
            fg_color="transparent",
        )
        self.scene_loaded_badge.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.scene_loaded_badge.grid_remove()

        self.scene_meta_label = ctk.CTkLabel(
            loaded_row,
            text=self.tr("no_scene_loaded"),
            font=FONT_UI,
            text_color=p["muted"],
            fg_color="transparent",
            justify="left",
            wraplength=920,
        )
        self.scene_meta_label.grid(row=0, column=1, sticky="ew")
        self._refresh_scene_loaded_indicator()

    # ---- scene list helpers --------------------------------------------
    def _scene_list_inner(self) -> Optional[tk.Text]:
        if not hasattr(self, "scene_list_text"):
            return None
        inner = getattr(self.scene_list_text, "_textbox", None)
        return inner if isinstance(inner, tk.Text) else None

    def _wire_scene_match_list(self) -> None:
        try:
            self.update_idletasks()
        except tk.TclError:
            pass
        inner = self._scene_list_inner()
        if hasattr(self, "scene_list_text"):
            try:
                self.scene_list_text.configure(cursor="arrow")
            except tk.TclError:
                pass
        if inner is not None:
            try:
                inner.configure(cursor="arrow")
            except tk.TclError:
                pass
            inner.bind("<Button-3>", self.on_scene_list_context_menu)
            inner.bind("<ButtonRelease-1>", self.on_scene_list_release)
            inner.bind("<Double-Button-1>", self.on_scene_list_double)
            inner.bind("<KeyPress>", self._on_scene_list_key_press)
            inner.bind("<<Paste>>", lambda _e: "break")

    def _apply_scene_list_selection_style(self) -> None:
        inner = self._scene_list_inner()
        if inner is None:
            return
        pal = self._pal
        inner.tag_configure("scene_sel", background=pal["cyan_dim"], foreground=pal["text"])

    def _clear_scene_list_selection(self) -> None:
        self._scene_list_selected_line = None
        inner = self._scene_list_inner()
        if inner is not None:
            inner.tag_remove("scene_sel", "1.0", "end")
        self._refresh_scene_selection_filename_field(None)

    def _set_scene_list_selection_line(self, line: int) -> None:
        inner = self._scene_list_inner()
        if inner is not None:
            inner.tag_remove("scene_sel", "1.0", "end")
            inner.tag_add("scene_sel", f"{line}.0", f"{line}.end")
        self._refresh_scene_selection_filename_field(line)

    def _scene_display_title(self, scene: SceneItem) -> str:
        title = (scene.title or "").strip()
        if title:
            return title
        raw_path = (scene.path or "").strip()
        if raw_path:
            try:
                return PurePath(raw_path).name
            except Exception:
                pass
        return "<no title>"

    # ---- list events ----------------------------------------------------
    def _on_scene_search_return(self, _event: Any = None) -> str:
        self.search_scenes()
        return "break"

    def _nav_scene_list_line(self, delta: int) -> None:
        if not self.scene_line_to_id:
            return
        lines = sorted(self.scene_line_to_id.keys())
        if not lines:
            return
        lo, hi = lines[0], lines[-1]
        cur = self._scene_list_selected_line
        if cur is None:
            cur = lo if delta > 0 else hi
        else:
            cur = int(cur) + int(delta)
        cur = max(lo, min(hi, cur))
        sid = self.scene_line_to_id.get(cur, "")
        if not sid:
            return
        self._scene_list_selected_line = cur
        self._set_scene_list_selection_line(cur)
        self.scene_id_entry.delete(0, "end")
        self.scene_id_entry.insert(0, sid)

    def _on_scene_list_key_press(self, event: tk.Event) -> Optional[str]:
        if event.keysym in ("Up", "Down"):
            self._nav_scene_list_line(-1 if event.keysym == "Up" else 1)
            return "break"
        if event.keysym in ("Return", "KP_Enter"):
            self.load_scene_by_id()
            return "break"
        if event.keysym in ("Tab", "ISO_Left_Tab", "Escape"):
            return None
        state = int(getattr(event, "state", 0) or 0)
        ctrl = (state & 0x0004) != 0
        if ctrl and event.keysym and str(event.keysym).lower() in ("c", "a", "insert"):
            return None
        return "break"

    def on_scene_list_release(self, event: tk.Event) -> Optional[str]:
        inner = self._scene_list_inner()
        if inner is None or getattr(event, "widget", None) is not inner:
            return None
        try:
            index = inner.index(f"@{event.x},{event.y}")
            line = int(str(index).split(".", 1)[0])
        except Exception:
            return None
        scene_id = self.scene_line_to_id.get(line, "")
        if not scene_id:
            self._clear_scene_list_selection()
            return "break"
        self._scene_list_selected_line = line
        self._set_scene_list_selection_line(line)
        shift = (getattr(event, "state", 0) & 0x0001) != 0
        if not shift:
            self.scene_id_entry.delete(0, "end")
            self.scene_id_entry.insert(0, scene_id)
        try:
            inner.focus_set()
        except tk.TclError:
            pass
        return "break"

    def on_scene_list_double(self, event: tk.Event) -> Optional[str]:
        inner = self._scene_list_inner()
        if inner is None or getattr(event, "widget", None) is not inner:
            return None
        try:
            index = inner.index(f"@{event.x},{event.y}")
            line = int(str(index).split(".", 1)[0])
        except Exception:
            return None
        scene_id = self.scene_line_to_id.get(line, "")
        if not scene_id:
            return "break"
        self.scene_id_entry.delete(0, "end")
        self.scene_id_entry.insert(0, scene_id)
        self._scene_list_selected_line = line
        self._set_scene_list_selection_line(line)
        self.load_scene_by_id()
        return "break"

    # ---- right-click context menu (3 items only) ------------------------
    def on_scene_list_context_menu(self, event: tk.Event) -> Optional[str]:
        inner = self._scene_list_inner()
        if inner is None:
            return "break"
        try:
            index = inner.index(f"@{event.x},{event.y}")
            line = int(str(index).split(".", 1)[0])
        except Exception:
            return "break"
        scene_id = self.scene_line_to_id.get(line, "")
        if not scene_id:
            return "break"
        path = ""
        if 1 <= line <= len(self.scene_rows):
            path = (self.scene_rows[line - 1].path or "").strip()
        self._scene_list_selected_line = line
        self._set_scene_list_selection_line(line)
        self._post_match_context_menu(event, path)
        return "break"

    def _post_match_context_menu(self, event: tk.Event, path: str) -> None:
        menu = tk.Menu(self, tearoff=0)
        pth = path
        line = self._scene_list_selected_line
        menu.add_command(
            label=self.tr("context_open_explorer"),
            command=lambda pt=pth: self._open_folder_in_explorer(pt),
        )
        menu.add_command(
            label=self.tr("context_copy_full_path"),
            command=lambda pt=pth: self._copy_scene_full_path_menu(pt),
        )
        menu.add_command(
            label=self.tr("context_copy_path"),
            command=lambda pt=pth: self._copy_scene_folder_menu(pt),
        )
        menu.add_command(
            label=self.tr("context_copy_filename"),
            command=lambda pt=pth: self._copy_scene_filename_menu(pt),
        )
        menu.add_separator()
        menu.add_command(
            label=self.tr("context_rename_file"),
            command=lambda pt=pth, ln=line: self._rename_scene_file_menu(pt, ln),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except tk.TclError:
                pass

    # ---- clipboard helpers ---------------------------------------------
    def _clipboard_set(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        try:
            self.status_var.set(self.tr("scenes_copied"))
        except tk.TclError:
            pass

    def _copy_scene_folder_menu(self, path: str) -> None:
        """Copy only the parent folder path of the scene's file (not the file itself)."""
        raw = (path or "").strip()
        if not raw:
            messagebox.showwarning(self.tr("ctx_no_path_title"), self.tr("ctx_copy_path_empty"))
            return
        mapped = self.apply_path_map(raw, use_backup=self._use_backup_active())
        try:
            p = Path(mapped)
            folder = str(p) if p.is_dir() else str(p.parent)
        except Exception:
            folder = str(PurePath(mapped).parent)
        if not folder or folder in (".", ""):
            messagebox.showwarning(self.tr("ctx_no_path_title"), self.tr("ctx_copy_path_empty"))
            return
        self._clipboard_set(folder)

    def _copy_scene_filename_menu(self, path: str) -> None:
        raw = (path or "").strip()
        if not raw:
            messagebox.showwarning(self.tr("ctx_no_path_title"), self.tr("ctx_copy_path_empty"))
            return
        mapped = self.apply_path_map(raw)
        try:
            base = PurePath(mapped).name
        except Exception:
            base = ""
        if not base:
            messagebox.showwarning(self.tr("ctx_no_path_title"), self.tr("ctx_copy_path_empty"))
            return
        self._clipboard_set(base)
    
    def _copy_scene_full_path_menu(self, path: str) -> None:
        raw = (path or "").strip()
        if not raw:
            messagebox.showwarning(self.tr("ctx_no_path_title"), self.tr("ctx_copy_path_empty"))
            return
        mapped = self.apply_path_map(raw, use_backup=self._use_backup_active())
        if not mapped:
            messagebox.showwarning(self.tr("ctx_no_path_title"), self.tr("ctx_copy_path_empty"))
            return
        self._clipboard_set(mapped)

    # ---- rename file on disk -------------------------------------------
    _RENAME_INVALID_CHARS = set('<>:"|?*')

    @classmethod
    def _is_valid_filename(cls, name: str, old_name: str) -> bool:
        n = (name or "").strip()
        if not n or n == old_name:
            return False
        if "/" in n or "\\" in n:
            return False
        if any(ch in cls._RENAME_INVALID_CHARS for ch in n):
            return False
        if any(ord(ch) < 32 for ch in n):
            return False
        return True

    @staticmethod
    def _replace_basename_in_remote_path(remote_path: str, new_basename: str) -> str:
        """Return *remote_path* with the trailing file name replaced by *new_basename*,
        preserving the original separator style (so Linux paths stay Linux paths)."""
        if not remote_path:
            return new_basename
        i = max(remote_path.rfind("/"), remote_path.rfind("\\"))
        if i < 0:
            return new_basename
        return remote_path[: i + 1] + new_basename

    def _rename_scene_file_menu(self, path: str, line: Optional[int]) -> None:
        raw = (path or "").strip()
        if not raw:
            messagebox.showwarning(self.tr("ctx_no_path_title"), self.tr("ctx_no_path_body"))
            return
        use_backup = self._use_backup_active()
        mapped = self.apply_path_map(raw, use_backup=use_backup)
        local = Path(mapped)
        if not local.is_file():
            messagebox.showerror(
                self.tr("rename_file_not_found_title"),
                self.tr("rename_file_not_found_body").format(path=str(local)),
            )
            return

        old_name = local.name
        folder = str(local.parent)

        # Ask for new name (default: current filename so the user only edits the part they want).
        from tkinter import simpledialog
        new_name = simpledialog.askstring(
            self.tr("rename_dialog_title"),
            self.tr("rename_dialog_prompt").format(folder=folder),
            initialvalue=old_name,
            parent=self,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not self._is_valid_filename(new_name, old_name):
            messagebox.showerror(
                self.tr("rename_invalid_name_title"),
                self.tr("rename_invalid_name_body"),
            )
            return

        target = local.with_name(new_name)
        if target.exists():
            messagebox.showerror(
                self.tr("rename_target_exists_title"),
                self.tr("rename_target_exists_body").format(path=str(target)),
            )
            return

        if not messagebox.askyesno(
            self.tr("rename_confirm_title"),
            self.tr("rename_confirm_body").format(old=old_name, new=new_name, folder=folder),
        ):
            return

        try:
            os.rename(str(local), str(target))
        except OSError as exc:
            messagebox.showerror(
                self.tr("rename_failed_title"),
                self.tr("rename_failed_body").format(path=str(local), error=str(exc)),
            )
            return

        # In backup mode we do NOT update the in-memory remote path, because Stash
        # still references the original NAS file (which is untouched here). On a
        # mirror sync the NAS will eventually pick up the new name, then a Stash
        # rescan will reconcile. In primary mode, however, the NAS file itself was
        # renamed, so we mirror the change locally for a consistent UI until scan.
        if not use_backup:
            new_remote = self._replace_basename_in_remote_path(raw, new_name)
            if line is not None and 1 <= line <= len(self.scene_rows):
                try:
                    self.scene_rows[line - 1].path = new_remote
                except Exception:
                    pass
            cur = getattr(self, "current_scene", None)
            if isinstance(cur, dict):
                try:
                    files = cur.get("files") or []
                    if files and isinstance(files[0], dict):
                        cur_file_path = str(files[0].get("path", "") or "")
                        if cur_file_path == raw:
                            files[0]["path"] = new_remote
                            title = str(cur.get("title") or "(untitled)")
                            sid = str(cur.get("id", ""))
                            shown = self.apply_path_map(new_remote) or new_remote
                            try:
                                self.scene_meta_label.configure(
                                    text=f"Loaded: {sid} | {title} | {shown}"
                                )
                            except tk.TclError:
                                pass
                except Exception:
                    pass

            try:
                self._refresh_scene_selection_filename_field(line)
            except Exception:
                pass

            try:
                sync = getattr(self, "_sync_preview_player_to_current_scene", None)
                if callable(sync):
                    sync()
            except Exception:
                pass

        messagebox.showinfo(
            self.tr("rename_success_title"),
            self.tr("rename_success_body").format(path=str(target)),
        )

    def _refresh_scene_selection_filename_field(self, line: Optional[int]) -> None:
        if not hasattr(self, "scene_selected_file_entry"):
            return
        text = ""
        if line is not None and line >= 1:
            rows = getattr(self, "scene_rows", None) or []
            if line <= len(rows):
                raw = (rows[line - 1].path or "").strip()
                if raw:
                    mapped = self.apply_path_map(raw)
                    try:
                        text = PurePath(mapped).name
                    except Exception:
                        text = ""
        try:
            self.scene_selected_file_entry.delete(0, "end")
            if text:
                self.scene_selected_file_entry.insert(0, text)
        except tk.TclError:
            pass

    def _copy_scene_selected_filename_clipboard(self) -> None:
        if not hasattr(self, "scene_selected_file_entry"):
            return
        try:
            fn = self.scene_selected_file_entry.get().strip()
        except tk.TclError:
            return
        if not fn:
            messagebox.showwarning(self.tr("ctx_no_path_title"), self.tr("ctx_copy_path_empty"))
            return
        self._clipboard_set(fn)

    def apply_path_map(self, path: str, use_backup: bool = False) -> str:
        """Rewrite the start of the path according to the configured prefix mapping.

        When ``use_backup`` is True and a backup prefix is configured, the remote
        prefix is replaced with the backup prefix instead of the primary local one.
        If no backup prefix is set, the call silently falls back to the primary
        mapping — callers can therefore pass the toggle state unconditionally.
        """
        raw = (path or "").strip()
        if not raw:
            return raw
        mp = getattr(self, "config_path_map", None) or {}
        pre = str(mp.get("path_prefix_remote", "") or "").strip()
        loc = str(mp.get("path_prefix_local", "") or "").strip()
        bak = str(mp.get("path_prefix_backup", "") or "").strip()
        target = bak if (use_backup and bak) else loc
        if not pre or not target:
            return raw
        if not raw.startswith(pre):
            return raw
        suffix = raw[len(pre) :].lstrip("/")
        tgt_base = target.rstrip("/\\")
        if not suffix:
            return str(os.path.normpath(tgt_base))
        if os.name == "nt":
            suffix = suffix.replace("/", "\\")
        return str(os.path.normpath(os.path.join(tgt_base, suffix)))

    def _backup_available(self) -> bool:
        """True only if both remote and backup prefixes are configured."""
        mp = getattr(self, "config_path_map", None) or {}
        return bool(
            str(mp.get("path_prefix_remote", "") or "").strip()
            and str(mp.get("path_prefix_backup", "") or "").strip()
        )

    def _use_backup_active(self) -> bool:
        """Effective backup-mode state — only True if the toggle is on AND a backup
        prefix is configured (otherwise the toggle is meaningless)."""
        try:
            return bool(self._use_backup_var.get()) and self._backup_available()
        except (tk.TclError, AttributeError):
            return False

    def _refresh_backup_toggle_state(self) -> None:
        """Enable / disable the backup checkbox depending on whether a backup
        prefix is configured. Updates the helper hint label next to it as well."""
        chk = getattr(self, "_backup_toggle_chk", None)
        hint = getattr(self, "_backup_toggle_hint", None)
        if chk is None or hint is None:
            return
        try:
            chk.configure(text=self.tr("topbar_use_backup"))
        except tk.TclError:
            pass
        available = self._backup_available()
        try:
            chk.configure(state=("normal" if available else "disabled"))
        except tk.TclError:
            pass
        if not available:
            try:
                if bool(self._use_backup_var.get()):
                    self._use_backup_var.set(False)
                    mp = dict(getattr(self, "config_path_map", None) or {})
                    mp["use_backup"] = False
                    self.config_path_map = mp
            except tk.TclError:
                pass
            try:
                hint.configure(text=self.tr("topbar_use_backup_needs_config"))
            except tk.TclError:
                pass
        else:
            try:
                hint.configure(text=self.tr("topbar_use_backup_tooltip"))
            except tk.TclError:
                pass

    def _on_use_backup_toggle(self) -> None:
        """Persist the toggle state in the config so it survives a restart."""
        try:
            mp = dict(getattr(self, "config_path_map", None) or {})
            mp["use_backup"] = bool(self._use_backup_var.get())
            self.config_path_map = mp
            self._save_config(notify=False)
        except Exception:
            pass

    def _open_folder_in_explorer(self, path: str) -> None:
        raw = (path or "").strip()
        if not raw:
            messagebox.showwarning(self.tr("ctx_no_path_title"), self.tr("ctx_no_path_body"))
            return
        mapped = self.apply_path_map(raw, use_backup=self._use_backup_active())
        try:
            p = Path(mapped)
            folder = str(p) if p.is_dir() else str(p.parent)
        except Exception:
            folder = str(PurePath(mapped).parent)
        if not folder or folder in (".", ""):
            messagebox.showwarning(self.tr("ctx_no_path_title"), self.tr("ctx_no_path_body"))
            return
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            messagebox.showerror(self.tr("ctx_open_folder_failed"), str(exc))

    # ---- connection & search -------------------------------------------
    def connect(self) -> None:
        self._sync_vars_from_settings_entries_if_alive()
        endpoint = self._endpoint_var.get().strip()
        api_key = self._api_key_var.get().strip()
        self._clear_top_banner()
        if not endpoint:
            self.status_var.set(self.tr("not_connected"))
            self._set_top_banner(self.tr("top_err_url"))
            self._set_connection_led(False)
            return
        self.client.configure(endpoint, api_key)
        self._endpoint_var.set(self.client.endpoint)
        try:
            version = self.client.ping()
            self.status_var.set(f"Connected: Stash {version}")
            self._clear_top_banner()
            self._set_connection_led(True)
            self._save_config(notify=False)
            self.search_scenes()
        except Exception as exc:
            self.status_var.set(f"Error: {exc}")
            self._set_connection_led(False)
            self._set_top_banner(self._format_connect_error(exc, bool(api_key)))
            messagebox.showerror("Connection failed", str(exc))

    def _render_scene_list(self, selected_id: Optional[str] = None) -> None:
        """Re-render the results textbox from ``self.scene_rows``.

        If ``selected_id`` is given, the matching row is highlighted so the user
        can immediately right-click it (e.g. to rename / copy path / open folder).
        """
        self.scene_line_to_id = {}
        try:
            self.scene_list_text.delete("1.0", "end")
        except tk.TclError:
            pass
        for idx, scene in enumerate(self.scene_rows, start=1):
            display_title = self._scene_display_title(scene)
            line = f"{idx:03d} | id={scene.scene_id} | {display_title}\n"
            try:
                self.scene_list_text.insert("end", line)
            except tk.TclError:
                pass
            self.scene_line_to_id[idx] = scene.scene_id
        self._apply_scene_list_selection_style()
        try:
            self.scene_count_label.configure(
                text=f"{len(self.scene_rows)} {self.tr('scene_count')}"
            )
        except tk.TclError:
            pass
        try:
            if not self.scene_rows:
                self.scene_empty_hint.configure(text=self.tr("scene_search_empty"))
            else:
                self.scene_empty_hint.configure(text="")
        except tk.TclError:
            pass
        if selected_id:
            for ln, sid in self.scene_line_to_id.items():
                if sid == selected_id:
                    self._scene_list_selected_line = ln
                    self._set_scene_list_selection_line(ln)
                    break
        else:
            self._scene_list_selected_line = None
            self._refresh_scene_selection_filename_field(None)

    def search_scenes(self) -> None:
        try:
            text = self.scene_search_entry.get().strip()
            scenes = self.client.find_scenes(text)
        except Exception as exc:
            messagebox.showerror("Search failed", str(exc))
            return

        self.scene_rows = scenes
        self._render_scene_list(selected_id=None)
        try:
            self._save_config(notify=False)
        except Exception:
            pass
        self.after(10, lambda: self.scene_id_entry.focus_set())

    def reload_current_scene(self) -> None:
        if not self.current_scene:
            return
        sid = str(self.current_scene.get("id", ""))
        if not sid:
            return
        self.scene_id_entry.delete(0, "end")
        self.scene_id_entry.insert(0, sid)
        self.load_scene_by_id()

    def _scene_item_from_details(self, scene: Dict[str, Any]) -> SceneItem:
        sid = str(scene.get("id", "") or "")
        title = str(scene.get("title") or "")
        date = str(scene.get("date") or "")
        files = scene.get("files") or []
        path = ""
        if files and isinstance(files[0], dict):
            path = str(files[0].get("path", "") or "")
        return SceneItem(scene_id=sid, title=title, date=date, path=path)

    def _ensure_scene_in_results(self, scene: Dict[str, Any]) -> str:
        """Make sure the just-loaded scene shows up in the results list so it can
        be right-clicked. Returns the scene id of the entry now present in the list."""
        item = self._scene_item_from_details(scene)
        if not item.scene_id:
            return ""
        for idx, existing in enumerate(self.scene_rows):
            if existing.scene_id == item.scene_id:
                # Refresh data in-place (title / path may have changed since the search).
                self.scene_rows[idx] = item
                return item.scene_id
        # Prepend so the freshly loaded scene is easy to find at the top.
        self.scene_rows = [item] + list(self.scene_rows)
        return item.scene_id

    def load_scene_by_id(self) -> None:
        scene_id = self.scene_id_entry.get().strip()
        if not scene_id:
            messagebox.showwarning("Scene ID missing", "Please enter a scene ID.")
            return
        ln = self._scene_list_selected_line
        if ln is not None and self.scene_line_to_id.get(ln) != scene_id:
            self._clear_scene_list_selection()
        try:
            scene = self.client.get_scene_details(scene_id)
            self.current_scene = scene
            files = scene.get("files") or []
            raw_path = files[0].get("path", "") if files else ""
            mapped = self.apply_path_map(raw_path) if raw_path else ""
            title = str(scene.get("title") or "(untitled)")
            shown = mapped or raw_path
            self.scene_meta_label.configure(text=f"Loaded: {scene_id} | {title} | {shown}")
            self._sync_preview_player_to_current_scene()
            placed_id = self._ensure_scene_in_results(scene)
            if placed_id:
                self._render_scene_list(selected_id=placed_id)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
        finally:
            self._refresh_scene_loaded_indicator()

    def _sync_preview_player_to_current_scene(self) -> None:
        """If the preview player is open, tell it to reload from the currently loaded scene."""
        win = getattr(self, "_preview_player_win", None)
        if win is None:
            return
        try:
            if not win.winfo_exists():
                self._preview_player_win = None
                return
        except tk.TclError:
            self._preview_player_win = None
            return
        sync = getattr(win, "sync_scene_from_editor", None)
        if callable(sync):
            try:
                sync()
            except Exception:
                pass

    def load_scene_from_clipboard(self) -> None:
        try:
            raw = self.clipboard_get()
        except tk.TclError:
            messagebox.showwarning(self.tr("clipboard_empty_title"), self.tr("clipboard_empty_body"))
            return
        sid = extract_stash_scene_id_from_clipboard(raw)
        if not sid:
            messagebox.showwarning(self.tr("clipboard_invalid_title"), self.tr("clipboard_invalid_body"))
            return
        self.scene_id_entry.delete(0, "end")
        self.scene_id_entry.insert(0, sid)
        self.load_scene_by_id()

    def open_preview_player(self) -> None:
        """Open (or focus) the lightweight preview player window."""
        win = getattr(self, "_preview_player_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.wm_deiconify()
                    win.lift()
                    win.focus_force()
                    return
            except tk.TclError:
                pass
            self._preview_player_win = None
        try:
            from preview_player import PreviewPlayer
        except ImportError as exc:
            messagebox.showerror(
                self.tr("preview_player_missing_deps_title"),
                f"{self.tr('preview_player_missing_deps_body')}\n\n({exc})",
            )
            return
        try:
            self._preview_player_win = PreviewPlayer(self, self.tr)
        except Exception as exc:
            self._preview_player_win = None
            messagebox.showerror(self.tr("preview_player_load_fail_title"), str(exc))

    def open_scene_in_stash(self, scene_id: Optional[str] = None) -> None:
        sid = self.scene_id_entry.get().strip() if scene_id is None else str(scene_id).strip()
        if not sid:
            messagebox.showwarning("Scene ID missing", "Please enter or select a scene ID first.")
            return
        url = stash_scene_browser_url(self._endpoint_var.get(), sid)
        if not url:
            self._set_top_banner(self.tr("top_err_url"))
            messagebox.showwarning("URL missing", self.tr("stash_url_missing"))
            return
        try:
            webbrowser.open(url)
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))

    def _refresh_scene_loaded_indicator(self) -> None:
        if not hasattr(self, "scene_loaded_badge") or not hasattr(self, "scene_meta_label"):
            return
        p = self._pal
        try:
            self.scene_loaded_badge.configure(text_color=p["cyan"])
        except tk.TclError:
            return
        sid = self.scene_id_entry.get().strip() if hasattr(self, "scene_id_entry") else ""
        cur = self.current_scene
        if cur and sid and str(cur.get("id", "")) == sid:
            self.scene_loaded_badge.configure(text=self.tr("scene_loaded_badge"))
            self.scene_loaded_badge.grid(row=0, column=0, sticky="w", padx=(0, 8))
        else:
            self.scene_loaded_badge.grid_remove()

    # ---- palette / theme ------------------------------------------------
    def _on_appearance_change(self, _value: str) -> None:
        self._sync_palette()
        self._save_config(notify=False)

    def _sync_palette(self) -> None:
        choice = (self._appearance.get() or "dark").strip().lower() if hasattr(self, "_appearance") else "dark"
        if choice == "light":
            self._pal = dict(PALETTE_LIGHT)
            ctk.set_appearance_mode("light")
        elif choice == "system":
            ctk.set_appearance_mode("system")
            self._pal = dict(PALETTE_DARK)
        else:
            self._pal = dict(PALETTE_DARK)
            ctk.set_appearance_mode("dark")
        p = self._pal
        if not hasattr(self, "_frame_top"):
            return
        self.configure(fg_color=p["bg"])
        self._frame_top.configure(fg_color=p["panel"])
        self._frame_body.configure(fg_color=p["bg"])
        self._content.configure(fg_color=p["panel"], border_color=p["border"])
        self._title_label.configure(text_color=p["text"])
        self.status_label.configure(text_color=p["muted"])
        if hasattr(self, "top_alert_label"):
            self.top_alert_label.configure(text_color=p["stop"])
        self._apply_connection_led_colors()
        alive_tb = []
        for tup in self._themed_buttons:
            try:
                if tup[0].winfo_exists():
                    alive_tb.append(tup)
            except Exception:
                continue
        self._themed_buttons = alive_tb
        for btn, variant, h, w, font in self._themed_buttons:
            btn.configure(**self._button_kw(variant, height=h, font=font, width=w))
        seg = getattr(self, "_settings_appearance_seg", None)
        if seg is not None:
            try:
                if seg.winfo_exists():
                    seg.configure(
                        fg_color=p["panel"],
                        selected_color=p["cyan_dim"],
                        selected_hover_color=p["cyan"],
                        unselected_color=p["panel"],
                        unselected_hover_color=p["border"],
                        text_color=p["text"],
                    )
            except tk.TclError:
                pass
        for name in ("scenes_search_card", "scenes_results_card", "scenes_loaded_card"):
            w = getattr(self, name, None)
            if w is not None:
                try:
                    w.configure(fg_color=p["panel_elev"], border_color=p["border"])
                except tk.TclError:
                    pass
        self._restyle_status_labels()
        self._restyle_entries()
        if hasattr(self, "scene_list_text"):
            try:
                self._style_textbox(self.scene_list_text)
            except tk.TclError:
                pass
        self._apply_scene_list_selection_style()
        self._restyle_settings_dialog()
        self._update_language_buttons()
        win = getattr(self, "_preview_player_win", None)
        if win is not None:
            try:
                if win.winfo_exists() and hasattr(win, "sync_palette_from_app"):
                    win.sync_palette_from_app()
            except tk.TclError:
                pass

    def _restyle_status_labels(self) -> None:
        p = self._pal
        mapping = (
            ("scene_count_label", "text"),
            ("scene_search_enter_hint", "muted"),
            ("scene_id_row_hint", "muted"),
            ("scene_empty_hint", "muted"),
            ("scene_selected_filename_label", "muted"),
            ("scene_loaded_badge", "cyan"),
            ("scene_meta_label", "muted"),
        )
        for name, key in mapping:
            w = getattr(self, name, None)
            if w is not None:
                try:
                    w.configure(text_color=p[key])
                except tk.TclError:
                    pass

    def _restyle_entries(self) -> None:
        for name in (
            "scene_search_entry",
            "scene_id_entry",
            "scene_selected_file_entry",
        ):
            w = getattr(self, name, None)
            if w is not None:
                try:
                    if w.winfo_exists():
                        self._style_entry(w)
                except tk.TclError:
                    pass

    # ---- Settings dialog (gear icon) -----------------------------------
    def _open_settings_dialog(self) -> None:
        dlg = getattr(self, "_settings_dialog", None)
        if dlg is not None:
            try:
                alive = bool(dlg.winfo_exists())
            except tk.TclError:
                alive = False
            if alive:
                try:
                    dlg.wm_deiconify()
                    dlg.lift()
                    dlg.focus_force()
                    return
                except tk.TclError:
                    pass
            self._close_settings_dialog()

        p = self._pal
        self._settings_dialog = ctk.CTkToplevel(self)
        self._settings_dialog.title(self.tr("settings_title"))
        dlg_w, dlg_h = 540, 680
        try:
            self.update_idletasks()
            main_x = int(self.winfo_rootx())
            main_y = int(self.winfo_rooty())
            main_w = max(int(self.winfo_width()), dlg_w)
            main_h = max(int(self.winfo_height()), dlg_h)
            x = main_x + max(0, (main_w - dlg_w) // 2)
            y = main_y + max(40, (main_h - dlg_h) // 4)
            self._settings_dialog.geometry(f"{dlg_w}x{dlg_h}+{x}+{y}")
        except tk.TclError:
            self._settings_dialog.geometry(f"{dlg_w}x{dlg_h}")
        self._settings_dialog.minsize(460, 420)
        self._settings_dialog.transient(self)
        self._settings_dialog.configure(fg_color=p["bg"])
        self._settings_dialog.protocol("WM_DELETE_WINDOW", self._close_settings_dialog)
        self._settings_dialog.bind("<Destroy>", self._on_settings_dialog_destroy, add="+")

        # Outer container: scrollable body on top, fixed button row at the bottom.
        # This guarantees that the save / close buttons are reachable at any window size.
        outer = ctk.CTkFrame(self._settings_dialog, fg_color=p["bg"])
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        btn_row = ctk.CTkFrame(outer, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", pady=(10, 0))
        btn_row.grid_columnconfigure(0, weight=1)

        self._settings_inner = ctk.CTkScrollableFrame(outer, fg_color=p["bg"], corner_radius=0)
        self._settings_inner.pack(side="top", fill="both", expand=True)
        try:
            self._settings_inner.grid_columnconfigure(0, weight=1)
        except tk.TclError:
            pass

        def _lbl(text: str, key: str = "text") -> ctk.CTkLabel:
            lab = ctk.CTkLabel(
                self._settings_inner,
                text=text,
                font=FONT_SECTION,
                text_color=p[key],
                fg_color="transparent",
            )
            self._settings_dialog_labels.append((lab, key))
            return lab

        r = 0
        _lbl(self.tr("settings_appearance")).grid(row=r, column=0, sticky="w", pady=(0, 4))
        r += 1
        self._settings_appearance_seg = ctk.CTkSegmentedButton(
            self._settings_inner,
            values=["dark", "light", "system"],
            variable=self._appearance,
            command=self._on_appearance_change,
            font=FONT_UI_SM,
            fg_color=p["panel"],
            selected_color=p["cyan_dim"],
            selected_hover_color=p["cyan"],
            unselected_color=p["panel"],
            unselected_hover_color=p["border"],
            text_color=p["text"],
        )
        self._settings_appearance_seg.grid(row=r, column=0, sticky="ew", pady=(0, 10))
        r += 1

        _lbl(self.tr("settings_language")).grid(row=r, column=0, sticky="w", pady=(8, 4))
        r += 1
        lang_row = ctk.CTkFrame(self._settings_inner, fg_color="transparent")
        lang_row.grid(row=r, column=0, sticky="w", pady=(0, 10))
        self.lang_en_btn = ctk.CTkButton(
            lang_row,
            text="EN",
            command=lambda: self.on_language_change("en"),
            **self._button_kw("nav_idle", height=BTN_HEIGHT_COMPACT, width=48),
        )
        self.lang_en_btn.grid(row=0, column=0, padx=(0, 6))
        self.lang_de_btn = ctk.CTkButton(
            lang_row,
            text="DE",
            command=lambda: self.on_language_change("de"),
            **self._button_kw("nav_idle", height=BTN_HEIGHT_COMPACT, width=48),
        )
        self.lang_de_btn.grid(row=0, column=1)
        self._update_language_buttons()
        r += 1

        _lbl(self.tr("settings_stash_url")).grid(row=r, column=0, sticky="w", pady=(8, 4))
        r += 1
        self._settings_endpoint_entry = ctk.CTkEntry(
            self._settings_inner,
            placeholder_text=self.tr("graphql_ph"),
            height=36,
        )
        self._settings_endpoint_entry.grid(row=r, column=0, sticky="ew", pady=(0, 8))
        self._style_entry(self._settings_endpoint_entry)
        r += 1

        _lbl(self.tr("settings_api_key")).grid(row=r, column=0, sticky="w", pady=(8, 4))
        r += 1
        self._settings_api_key_entry = ctk.CTkEntry(
            self._settings_inner,
            placeholder_text=self.tr("api_key_ph"),
            show="*",
            height=36,
        )
        self._settings_api_key_entry.grid(row=r, column=0, sticky="ew", pady=(0, 16))
        self._style_entry(self._settings_api_key_entry)
        r += 1

        sec_path_map = ctk.CTkFrame(self._settings_inner, fg_color="transparent")
        sec_path_map.grid(row=r, column=0, sticky="ew", pady=(8, 4))
        sec_path_map.grid_columnconfigure(0, weight=1)
        lab_pp = ctk.CTkLabel(
            sec_path_map,
            text=self.tr("settings_player_path_section"),
            font=FONT_SECTION,
            text_color=p["text"],
            fg_color="transparent",
        )
        self._settings_dialog_labels.append((lab_pp, "text"))
        lab_pp.grid(row=0, column=0, sticky="w")
        self._mk_btn(
            sec_path_map,
            "ghost",
            text="(I)",
            width=36,
            command=self._show_settings_player_path_info,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        r += 1

        pr_lbl = ctk.CTkLabel(
            self._settings_inner,
            text=self.tr("settings_player_prefix_remote"),
            font=FONT_UI_SM,
            text_color=p["muted"],
            fg_color="transparent",
        )
        self._settings_dialog_labels.append((pr_lbl, "muted"))
        pr_lbl.grid(row=r, column=0, sticky="w", pady=(0, 2))
        r += 1
        self._settings_prefix_remote_entry = ctk.CTkEntry(
            self._settings_inner,
            placeholder_text=self.tr("settings_player_prefix_remote_ph"),
            height=36,
        )
        self._settings_prefix_remote_entry.grid(row=r, column=0, sticky="ew", pady=(0, 8))
        self._style_entry(self._settings_prefix_remote_entry)
        r += 1

        pl_lbl = ctk.CTkLabel(
            self._settings_inner,
            text=self.tr("settings_player_prefix_local"),
            font=FONT_UI_SM,
            text_color=p["muted"],
            fg_color="transparent",
        )
        self._settings_dialog_labels.append((pl_lbl, "muted"))
        pl_lbl.grid(row=r, column=0, sticky="w", pady=(0, 2))
        r += 1
        self._settings_prefix_local_entry = ctk.CTkEntry(
            self._settings_inner,
            placeholder_text=self.tr("settings_player_prefix_local_ph"),
            height=36,
        )
        self._settings_prefix_local_entry.grid(row=r, column=0, sticky="ew", pady=(0, 6))
        self._style_entry(self._settings_prefix_local_entry)
        r += 1

        ph_lab = ctk.CTkLabel(
            self._settings_inner,
            text=self.tr("settings_player_path_hint"),
            font=FONT_HINT,
            text_color=p["muted"],
            fg_color="transparent",
            justify="left",
            wraplength=460,
        )
        self._settings_dialog_labels.append((ph_lab, "muted"))
        ph_lab.grid(row=r, column=0, sticky="ew", pady=(0, 8))
        r += 1

        # Backup prefix (optional) — mirrored drive used for rename/copy-full-path.
        bak_lbl = ctk.CTkLabel(
            self._settings_inner,
            text=self.tr("settings_backup_prefix_label"),
            font=FONT_UI_SM,
            text_color=p["muted"],
            fg_color="transparent",
        )
        self._settings_dialog_labels.append((bak_lbl, "muted"))
        bak_lbl.grid(row=r, column=0, sticky="w", pady=(0, 2))
        r += 1
        self._settings_prefix_backup_entry = ctk.CTkEntry(
            self._settings_inner,
            placeholder_text=self.tr("settings_backup_prefix_ph"),
            height=36,
        )
        self._settings_prefix_backup_entry.grid(row=r, column=0, sticky="ew", pady=(0, 6))
        self._style_entry(self._settings_prefix_backup_entry)
        r += 1

        bh_lab = ctk.CTkLabel(
            self._settings_inner,
            text=self.tr("settings_backup_prefix_hint"),
            font=FONT_HINT,
            text_color=p["muted"],
            fg_color="transparent",
            justify="left",
            wraplength=460,
        )
        self._settings_dialog_labels.append((bh_lab, "muted"))
        bh_lab.grid(row=r, column=0, sticky="ew", pady=(0, 12))
        r += 1

        # --- AutoHotkey helper section ----------------------------------
        sec_ahk = ctk.CTkFrame(self._settings_inner, fg_color="transparent")
        sec_ahk.grid(row=r, column=0, sticky="ew", pady=(8, 4))
        sec_ahk.grid_columnconfigure(0, weight=1)
        lab_ahk = ctk.CTkLabel(
            sec_ahk,
            text=self.tr("settings_ahk_section"),
            font=FONT_SECTION,
            text_color=p["text"],
            fg_color="transparent",
        )
        self._settings_dialog_labels.append((lab_ahk, "text"))
        lab_ahk.grid(row=0, column=0, sticky="w")
        self._mk_btn(
            sec_ahk,
            "ghost",
            text="(I)",
            width=36,
            command=self._show_settings_ahk_info,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        r += 1

        ahk_hint = ctk.CTkLabel(
            self._settings_inner,
            text=self.tr("settings_ahk_hint"),
            font=FONT_HINT,
            text_color=p["muted"],
            fg_color="transparent",
            justify="left",
            wraplength=460,
        )
        self._settings_dialog_labels.append((ahk_hint, "muted"))
        ahk_hint.grid(row=r, column=0, sticky="ew", pady=(0, 6))
        r += 1

        ahk_row = ctk.CTkFrame(self._settings_inner, fg_color="transparent")
        ahk_row.grid(row=r, column=0, sticky="w", pady=(0, 12))
        self._mk_btn(
            ahk_row,
            "primary",
            text=self.tr("settings_ahk_export_btn"),
            command=self._export_ahk_script,
            width=200,
        ).grid(row=0, column=0, padx=(0, 8))
        self._mk_btn(
            ahk_row,
            "ghost",
            text=self.tr("settings_ahk_info_btn"),
            command=self._show_settings_ahk_info,
            width=80,
        ).grid(row=0, column=1)
        r += 1

        self._populate_settings_entries_from_vars()

        # btn_row was created earlier as the fixed bottom row of the outer container.
        ctk.CTkButton(
            btn_row,
            text=self.tr("save_settings"),
            command=lambda: self._save_config(notify=True),
            **self._button_kw("primary", width=160),
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkButton(
            btn_row,
            text=self.tr("settings_close"),
            command=self._close_settings_dialog,
            **self._button_kw("ghost", width=120),
        ).grid(row=0, column=1, sticky="e")

        self._settings_dialog.after(80, self._settings_dialog_focus_first)
        self._settings_dialog.after(120, self._settings_dialog_redraw_placeholders)

    def _show_settings_player_path_info(self) -> None:
        messagebox.showinfo(
            self.tr("settings_player_path_info_title"),
            self.tr("settings_player_path_info_body"),
        )

    def _show_settings_ahk_info(self) -> None:
        messagebox.showinfo(
            self.tr("settings_ahk_info_title"),
            self.tr("settings_ahk_info_body"),
        )

    def _export_ahk_script(self) -> None:
        """Write a ready-to-use AutoHotkey v2 script to a user-chosen location.

        The script pastes the clipboard (full path) into the active Windows file dialog
        (#32770 class) by setting Edit1 directly and pressing Enter. Default hotkey: F20.
        Users can edit the .ahk file to change the hotkey.
        """
        default_dir = os.path.join(os.path.expanduser("~"), "Documents", "AutoHotkey")
        try:
            os.makedirs(default_dir, exist_ok=True)
        except OSError:
            default_dir = os.path.expanduser("~")
        try:
            target = filedialog.asksaveasfilename(
                parent=self._settings_dialog if getattr(self, "_settings_dialog", None) else self,
                title=self.tr("settings_ahk_save_title"),
                defaultextension=".ahk",
                initialdir=default_dir,
                initialfile="Pfadpaste.ahk",
                filetypes=[("AutoHotkey Script", "*.ahk"), ("All files", "*.*")],
            )
        except tk.TclError:
            target = ""
        if not target:
            return
        script = (
            "#Requires AutoHotkey v2.0\n"
            "\n"
            "; Stash path copy — Pfadpaste helper.\n"
            "; Aktiv nur, wenn ein klassischer Windows-Dateidialog im Vordergrund ist (#32770).\n"
            "; F20 ist der Standard-Hotkey — einfach unten ersetzen, wenn du eine andere Taste willst,\n"
            "; z. B. F8::, ^!v::  (Strg+Alt+V) oder #v:: (Win+V). Danach das Skript neu starten.\n"
            "F20:: {\n"
            "    if !WinActive(\"ahk_class #32770\") {\n"
            "        return\n"
            "    }\n"
            "\n"
            "    pfad := A_Clipboard\n"
            "    if (pfad == \"\") {\n"
            "        return\n"
            "    }\n"
            "\n"
            "    ; Schreibt den kompletten Pfad direkt in das Dateinamen-Feld (Edit1).\n"
            "    ControlSetText(pfad, \"Edit1\", \"A\")\n"
            "\n"
            "    ; Bestätigt das Dialogfeld (Enter). Auskommentieren, falls nicht gewünscht.\n"
            "    ControlSend(\"{Enter}\", \"Edit1\", \"A\")\n"
            "}\n"
        )
        try:
            with open(target, "w", encoding="utf-8", newline="\r\n") as fh:
                fh.write(script)
        except OSError as exc:
            messagebox.showerror(
                self.tr("settings_ahk_save_failed_title"),
                self.tr("settings_ahk_save_failed_body").format(path=target, error=str(exc)),
            )
            return
        messagebox.showinfo(
            self.tr("settings_ahk_saved_title"),
            self.tr("settings_ahk_saved_body").format(path=target),
        )

    def _settings_dialog_redraw_placeholders(self) -> None:
        try:
            dlg = getattr(self, "_settings_dialog", None)
            if dlg is not None and dlg.winfo_exists():
                dlg.update_idletasks()
        except tk.TclError:
            pass
        for w in (
            getattr(self, "_settings_endpoint_entry", None),
            getattr(self, "_settings_api_key_entry", None),
            getattr(self, "_settings_prefix_remote_entry", None),
            getattr(self, "_settings_prefix_local_entry", None),
            getattr(self, "_settings_prefix_backup_entry", None),
        ):
            if w is None:
                continue
            try:
                if not w.winfo_exists():
                    continue
            except tk.TclError:
                continue
            try:
                if not w.get():
                    activate = getattr(w, "_activate_placeholder", None)
                    if callable(activate):
                        activate()
            except (tk.TclError, AttributeError):
                pass
            try:
                if w.winfo_exists():
                    self._refresh_ctk_entry_draw(w)
            except tk.TclError:
                pass

    def _settings_dialog_focus_first(self) -> None:
        w = getattr(self, "_settings_endpoint_entry", None)
        if w is not None:
            try:
                if w.winfo_exists():
                    w.focus_set()
            except tk.TclError:
                pass

    def _clear_settings_dialog_refs(self) -> None:
        self._settings_dialog = None
        self._settings_appearance_seg = None
        self._settings_inner = None
        self._settings_endpoint_entry = None
        self._settings_api_key_entry = None
        self._settings_prefix_remote_entry = None
        self._settings_prefix_local_entry = None
        self._settings_prefix_backup_entry = None
        self._settings_dialog_labels.clear()
        self.lang_en_btn = None
        self.lang_de_btn = None

    def _on_settings_dialog_destroy(self, event: tk.Event) -> None:
        dlg = getattr(self, "_settings_dialog", None)
        if dlg is None or event.widget is not dlg:
            return
        self._clear_settings_dialog_refs()

    def _close_settings_dialog(self) -> None:
        self._sync_vars_from_settings_entries_if_alive()
        try:
            self._save_config(notify=False)
        except Exception:
            pass
        dlg = getattr(self, "_settings_dialog", None)
        if dlg is not None:
            try:
                dlg.destroy()
            except tk.TclError:
                pass
        self._clear_settings_dialog_refs()

    def _sync_vars_from_settings_entries_if_alive(self) -> None:
        w_ep = getattr(self, "_settings_endpoint_entry", None)
        w_ak = getattr(self, "_settings_api_key_entry", None)
        if w_ep is not None:
            try:
                if w_ep.winfo_exists():
                    self._endpoint_var.set(w_ep.get())
            except tk.TclError:
                pass
        if w_ak is not None:
            try:
                if w_ak.winfo_exists():
                    self._api_key_var.set(w_ak.get())
            except tk.TclError:
                pass
        w_pr = getattr(self, "_settings_prefix_remote_entry", None)
        w_pl = getattr(self, "_settings_prefix_local_entry", None)
        w_pb = getattr(self, "_settings_prefix_backup_entry", None)
        if w_pr is not None and w_pl is not None:
            try:
                if w_pr.winfo_exists() and w_pl.winfo_exists():
                    mp = dict(getattr(self, "config_path_map", None) or {})
                    mp["path_prefix_remote"] = w_pr.get().strip()
                    mp["path_prefix_local"] = w_pl.get().strip()
                    if w_pb is not None and w_pb.winfo_exists():
                        mp["path_prefix_backup"] = w_pb.get().strip()
                    self.config_path_map = mp
                    self._refresh_backup_toggle_state()
            except tk.TclError:
                pass

    def _populate_settings_entries_from_vars(self) -> None:
        w_ep = getattr(self, "_settings_endpoint_entry", None)
        w_ak = getattr(self, "_settings_api_key_entry", None)
        if w_ep is not None:
            try:
                if w_ep.winfo_exists():
                    w_ep.delete(0, "end")
                    w_ep.insert(0, self._endpoint_var.get())
            except tk.TclError:
                pass
        if w_ak is not None:
            try:
                if w_ak.winfo_exists():
                    w_ak.delete(0, "end")
                    w_ak.insert(0, self._api_key_var.get())
            except tk.TclError:
                pass
        mp = dict(getattr(self, "config_path_map", None) or {})
        w_pr = getattr(self, "_settings_prefix_remote_entry", None)
        w_pl = getattr(self, "_settings_prefix_local_entry", None)
        w_pb = getattr(self, "_settings_prefix_backup_entry", None)
        if w_pr is not None:
            try:
                if w_pr.winfo_exists():
                    w_pr.delete(0, "end")
                    w_pr.insert(0, str(mp.get("path_prefix_remote", "") or ""))
            except tk.TclError:
                pass
        if w_pl is not None:
            try:
                if w_pl.winfo_exists():
                    w_pl.delete(0, "end")
                    w_pl.insert(0, str(mp.get("path_prefix_local", "") or ""))
            except tk.TclError:
                pass
        if w_pb is not None:
            try:
                if w_pb.winfo_exists():
                    w_pb.delete(0, "end")
                    w_pb.insert(0, str(mp.get("path_prefix_backup", "") or ""))
            except tk.TclError:
                pass

    def _restyle_settings_dialog(self) -> None:
        dlg = getattr(self, "_settings_dialog", None)
        if dlg is None:
            return
        try:
            if not dlg.winfo_exists():
                return
        except tk.TclError:
            return
        p = self._pal
        try:
            dlg.configure(fg_color=p["bg"])
        except tk.TclError:
            pass
        inner = getattr(self, "_settings_inner", None)
        if inner is not None:
            try:
                inner.configure(fg_color=p["bg"])
            except tk.TclError:
                pass
        for lbl, key in list(self._settings_dialog_labels):
            try:
                if lbl.winfo_exists():
                    lbl.configure(text_color=p[key])
            except tk.TclError:
                pass
        for name in (
            "_settings_endpoint_entry",
            "_settings_api_key_entry",
            "_settings_prefix_remote_entry",
            "_settings_prefix_local_entry",
        ):
            w = getattr(self, name, None)
            if w is not None:
                try:
                    if w.winfo_exists():
                        self._style_entry(w)
                except tk.TclError:
                    pass

    # ---- language buttons ----------------------------------------------
    def _update_language_buttons(self) -> None:
        en = getattr(self, "lang_en_btn", None)
        de = getattr(self, "lang_de_btn", None)
        if en is None or de is None:
            return
        try:
            if not en.winfo_exists() or not de.winfo_exists():
                return
        except tk.TclError:
            return
        en.configure(
            **self._button_kw(
                "nav_active" if self.lang_code == "en" else "nav_idle",
                height=BTN_HEIGHT_COMPACT,
                width=48,
            )
        )
        de.configure(
            **self._button_kw(
                "nav_active" if self.lang_code == "de" else "nav_idle",
                height=BTN_HEIGHT_COMPACT,
                width=48,
            )
        )

    def on_language_change(self, new_code: str) -> None:
        if new_code == self.lang_code:
            return
        self._sync_vars_from_settings_entries_if_alive()
        endpoint_val = self._endpoint_var.get().strip()
        api_key_val = self._api_key_var.get().strip()
        search_val = self.scene_search_entry.get().strip() if hasattr(self, "scene_search_entry") else ""
        scene_id_val = self.scene_id_entry.get().strip() if hasattr(self, "scene_id_entry") else ""
        self.lang_code = new_code
        self._save_config(notify=False)
        win = getattr(self, "_preview_player_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.destroy()
            except tk.TclError:
                pass
            self._preview_player_win = None
        for child in self.winfo_children():
            child.destroy()
        self._build_ui()
        self._endpoint_var.set(endpoint_val)
        self._api_key_var.set(api_key_val)
        self.scene_search_entry.delete(0, "end")
        self.scene_search_entry.insert(0, search_val)
        self.scene_id_entry.delete(0, "end")
        self.scene_id_entry.insert(0, scene_id_val)
        self._update_language_buttons()
        self.status_var.set(self.tr("lang_switched"))
        self._sync_palette()
        self.title(self.tr("app_title"))


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()
