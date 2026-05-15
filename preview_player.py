"""Simple video preview player – Play/Pause/Stop only.

Standalone helper window that lets the user verify which video is which.
No markers, no I/O keys, no Stash writes. The video file path comes from
the loaded scene (or from a scene id / Stash URL pasted in the URL field).

Requires OpenCV (``opencv-python-headless``) and Pillow at runtime. If they
are missing, opening the player shows a friendly error from ``app.py``.
"""

from __future__ import annotations

import math
import re
import sys
import time
import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable, Optional

import customtkinter as ctk

from app import BTN_HEIGHT_COMPACT, FONT_HINT, FONT_UI, FONT_UI_SM

try:
    import cv2  # type: ignore
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover - runtime check
    cv2 = None  # type: ignore
    Image = None  # type: ignore


def _extract_scene_id(text: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None
    m = re.search(r"/scenes/(\d+)", raw, re.IGNORECASE)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d+", raw):
        return raw
    return None


def _format_hhmmss(total_sec: float) -> str:
    total = int(math.floor(float(total_sec)))
    if total < 0:
        total = 0
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _open_cv_video_capture(path: str) -> Any:
    """Open ``cv2.VideoCapture`` preferring FFmpeg/MSMF to avoid CV_IMAGES picks."""
    if cv2 is None:
        raise RuntimeError("OpenCV is not installed")
    p = str(path).strip()
    apis: list[int] = []
    ff = getattr(cv2, "CAP_FFMPEG", None)
    if ff is not None:
        apis.append(int(ff))
    if sys.platform == "win32":
        for attr in ("CAP_MSMF", "CAP_DSHOW"):
            c = getattr(cv2, attr, None)
            if c is not None:
                apis.append(int(c))
    seen: set[int] = set()
    ordered: list[int] = []
    for x in apis:
        if x not in seen:
            seen.add(x)
            ordered.append(x)
    for api in ordered:
        cap = None
        try:
            cap = cv2.VideoCapture(p, api)
            if cap.isOpened():
                return cap
        finally:
            if cap is not None and not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass
    return cv2.VideoCapture(p)


class PreviewPlayer(ctk.CTkToplevel):
    """Lightweight preview-only player (Play / Pause / Stop)."""

    def __init__(self, app: Any, get_tr: Callable[[str], str]) -> None:
        super().__init__(app, fg_color=app._pal["bg"])
        self.app = app
        self._tr = get_tr
        self.title(self._tr("preview_player_window_title"))
        self.minsize(640, 480)
        self.transient(app)

        self._cap: Any = None
        self._fps = 30.0
        self._total_frames = 0
        self._current_frame = 0
        self._is_playing = False
        self._last_tick = 0.0
        self._ctk_img: Optional[ctk.CTkImage] = None
        self._width = 640
        self._height = 360
        self._fullscreen = False
        self._geom_before_fs = ""
        self._last_window_geometry = ""
        self._resize_after_id: Optional[str] = None
        self._last_draw_size: tuple[int, int] = (0, 0)
        self._geom_save_after_id: Optional[str] = None

        # Restore last position/size; default near the main window.
        pp_cfg = getattr(self.app, "config_preview_player", None) or {}
        saved_geo = str(pp_cfg.get("geometry", "") or "").strip()
        if saved_geo:
            try:
                self.geometry(saved_geo)
            except tk.TclError:
                self._apply_default_geometry()
        else:
            self._apply_default_geometry()

        self._card = ctk.CTkFrame(self, corner_radius=10, border_width=1)
        self._card.pack(fill="both", expand=True, padx=12, pady=12)
        root = self._card

        # --- URL row -------------------------------------------------------
        top = ctk.CTkFrame(root, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 6))
        top.grid_columnconfigure(1, weight=1)

        self._url_title_lbl = ctk.CTkLabel(
            top,
            text=self._tr("preview_player_url_label"),
            font=FONT_UI_SM,
            fg_color="transparent",
        )
        self._url_title_lbl.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.url_entry = ctk.CTkEntry(top, placeholder_text=self._tr("preview_player_url_ph"))
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=4)
        prefill = self._guess_scene_url()
        if prefill:
            self.url_entry.insert(0, prefill)
        else:
            sid_only = self._current_editor_scene_id()
            if sid_only:
                self.url_entry.insert(0, sid_only)
        self.url_entry.bind("<Return>", lambda e: self._load_video())
        self.app._style_entry(self.url_entry)
        self.load_btn = self.app._mk_btn(
            top,
            "primary",
            text=self._tr("preview_player_load_btn"),
            command=self._load_video,
            width=100,
            height=BTN_HEIGHT_COMPACT,
        )
        self.load_btn.grid(row=0, column=2, padx=(8, 0))

        # --- Hint ----------------------------------------------------------
        self._hint_lbl = ctk.CTkLabel(
            root,
            text=self._tr("preview_player_hint"),
            font=FONT_HINT,
            fg_color="transparent",
            wraplength=820,
            justify="left",
        )
        self._hint_lbl.pack(fill="x", padx=10, pady=(0, 6))

        # --- Tool row (fullscreen) ----------------------------------------
        tool_row = ctk.CTkFrame(root, fg_color="transparent")
        tool_row.pack(fill="x", padx=10, pady=(0, 4))
        self.fs_btn = self.app._mk_btn(
            tool_row,
            "ghost",
            text=self._tr("preview_player_fullscreen_btn"),
            command=self._toggle_fullscreen,
            width=100,
            height=BTN_HEIGHT_COMPACT,
        )
        self.fs_btn.pack(side="left", padx=(0, 6))

        # The transport / slider / time row are packed FIRST with side="bottom" so they
        # stay anchored to the bottom of the window even when a tall (portrait) video is
        # loaded. The video container takes the remaining middle space.
        # --- Transport (Play / Pause / Stop) ------------------------------
        transport = ctk.CTkFrame(root, fg_color="transparent")
        transport.pack(side="bottom", padx=10, pady=(0, 12))
        # --- Slider -------------------------------------------------------
        self.slider = ctk.CTkSlider(
            root, from_=0, to=1, number_of_steps=1, command=self._on_slider, height=18
        )
        self.slider.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        # --- Time label ---------------------------------------------------
        self.time_label = ctk.CTkLabel(
            root,
            text="—",
            font=("Segoe UI Semibold", 14),
            fg_color="transparent",
        )
        self.time_label.pack(side="bottom", fill="x", padx=10, pady=(0, 4))

        # --- Video display (middle, fills remaining space) ----------------
        # Wrap the CTkLabel in a frame with geometry propagation disabled so the
        # CTkImage cannot force the parent / window to grow with portrait videos.
        self.video_container = ctk.CTkFrame(root, fg_color=app._pal["panel"], corner_radius=8)
        self.video_container.pack(fill="both", expand=True, padx=10, pady=6)
        self.video_container.pack_propagate(False)
        self.video_label = ctk.CTkLabel(self.video_container, text="", corner_radius=8)
        self.video_label.pack(fill="both", expand=True)
        self.video_label.bind("<Button-1>", lambda e: self.focus_set())
        self.play_btn = self.app._mk_btn(
            transport,
            "primary",
            text=self._tr("preview_player_play"),
            command=self._play,
            width=100,
            height=BTN_HEIGHT_COMPACT,
        )
        self.play_btn.grid(row=0, column=0, padx=6)
        self.pause_btn = self.app._mk_btn(
            transport,
            "ghost",
            text=self._tr("preview_player_pause"),
            command=self._pause,
            width=100,
            height=BTN_HEIGHT_COMPACT,
        )
        self.pause_btn.grid(row=0, column=1, padx=6)
        self.stop_btn = self.app._mk_btn(
            transport,
            "ghost",
            text=self._tr("preview_player_stop"),
            command=self._stop,
            width=100,
            height=BTN_HEIGHT_COMPACT,
        )
        self.stop_btn.grid(row=0, column=2, padx=6)

        self.sync_palette_from_app()
        self.after(1, self._remember_initial_geometry)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<KeyPress>", self._on_key_press)
        self.url_entry.bind("<KeyPress>", self._on_url_key_for_global)
        self.bind("<Configure>", self._on_player_configure)
        self.after(100, self.focus_set)
        # Auto-load the video immediately once the event loop is idle, so the
        # currently-loaded scene from the main window shows up right after opening.
        if self.url_entry.get().strip():
            self.after_idle(self._try_initial_autoload)

    # ------------------------------------------------------------------
    # palette / styling helpers (mirror app's _sync_palette behaviour)
    # ------------------------------------------------------------------
    def _style_sliders(self) -> None:
        p = self.app._pal
        try:
            self.slider.configure(
                fg_color=p["border"],
                progress_color=p["cyan_dim"],
                button_color=p["cyan"],
                button_hover_color=p["cyan_hover"],
            )
        except tk.TclError:
            pass

    def sync_palette_from_app(self) -> None:
        p = dict(self.app._pal)
        try:
            self.configure(fg_color=p["bg"])
        except tk.TclError:
            return
        try:
            self._card.configure(fg_color=p["panel_elev"], border_color=p["border"])
        except tk.TclError:
            pass
        try:
            self.app._style_entry(self.url_entry)
        except tk.TclError:
            pass
        for w in (self._url_title_lbl, self.time_label):
            try:
                w.configure(text_color=p["text"])
            except tk.TclError:
                pass
        try:
            self._hint_lbl.configure(text_color=p["muted"])
        except tk.TclError:
            pass
        try:
            self._hint_lbl.configure(wraplength=max(320, int(self.winfo_width()) - 48))
        except tk.TclError:
            pass
        try:
            self.video_label.configure(fg_color=p["panel"])
        except (tk.TclError, ValueError):
            pass
        try:
            self.video_container.configure(fg_color=p["panel"])
        except (tk.TclError, ValueError):
            pass
        self._style_sliders()
        self._update_time_label()

    # ------------------------------------------------------------------
    # geometry / fullscreen
    # ------------------------------------------------------------------
    def _apply_default_geometry(self) -> None:
        """Open near the main window (centered horizontally, slightly below the top)."""
        dlg_w, dlg_h = 900, 680
        try:
            self.app.update_idletasks()
            main_x = int(self.app.winfo_rootx())
            main_y = int(self.app.winfo_rooty())
            main_w = max(int(self.app.winfo_width()), dlg_w)
            main_h = max(int(self.app.winfo_height()), dlg_h)
            x = main_x + max(0, (main_w - dlg_w) // 2)
            y = main_y + max(40, (main_h - dlg_h) // 4)
            self.geometry(f"{dlg_w}x{dlg_h}+{x}+{y}")
        except tk.TclError:
            self.geometry(f"{dlg_w}x{dlg_h}")

    def _remember_initial_geometry(self) -> None:
        try:
            self._last_window_geometry = self.winfo_geometry()
        except tk.TclError:
            pass

    def _schedule_geometry_save(self) -> None:
        """Debounced write of the current geometry into the app config."""
        if self._geom_save_after_id is not None:
            try:
                self.after_cancel(self._geom_save_after_id)
            except (tk.TclError, ValueError):
                pass
            self._geom_save_after_id = None
        self._geom_save_after_id = self.after(600, self._flush_geometry_to_config)

    def _flush_geometry_to_config(self) -> None:
        self._geom_save_after_id = None
        try:
            if not self.winfo_exists() or self._fullscreen:
                return
            g = (self.winfo_geometry() or "").strip()
            if not g:
                return
            pp = dict(getattr(self.app, "config_preview_player", None) or {})
            if pp.get("geometry") == g:
                return
            pp["geometry"] = g
            self.app.config_preview_player = pp
            saver = getattr(self.app, "_save_config", None)
            if callable(saver):
                try:
                    saver(notify=False)
                except Exception:
                    pass
        except tk.TclError:
            pass

    def _on_player_configure(self, event: tk.Event) -> None:
        if getattr(event, "widget", None) is not self:
            return
        try:
            self._hint_lbl.configure(wraplength=max(320, int(self.winfo_width()) - 48))
        except tk.TclError:
            pass
        if not self._fullscreen:
            try:
                self._last_window_geometry = self.winfo_geometry()
            except tk.TclError:
                pass
            self._schedule_geometry_save()
        self._schedule_resize_redraw()

    def _schedule_resize_redraw(self) -> None:
        """Debounced redraw of the current video frame when the window size changes."""
        if self._cap is None:
            return
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except (tk.TclError, ValueError):
                pass
            self._resize_after_id = None
        self._resize_after_id = self.after(120, self._do_resize_redraw)

    def _do_resize_redraw(self) -> None:
        self._resize_after_id = None
        if self._cap is None or self._is_playing:
            return
        try:
            self._draw_frame()
        except Exception:
            pass

    def _toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            try:
                self._geom_before_fs = self.winfo_geometry()
            except tk.TclError:
                self._geom_before_fs = ""
            self.attributes("-fullscreen", True)
        else:
            self.attributes("-fullscreen", False)
            if self._geom_before_fs:
                try:
                    self.geometry(self._geom_before_fs)
                except tk.TclError:
                    pass
        # Force a redraw of the current frame at the new window size, even when paused.
        if self._cap is not None:
            self.after(180, self._do_resize_redraw)
            self.after(360, self._do_resize_redraw)

    # ------------------------------------------------------------------
    # URL / scene helpers
    # ------------------------------------------------------------------
    def _on_url_key_for_global(self, event: tk.Event) -> Optional[str]:
        if event.keysym in ("F11", "Escape"):
            self._on_key_press(event)
            return "break"
        return None

    def _current_editor_scene_id(self) -> str:
        try:
            scene = getattr(self.app, "current_scene", None) or {}
            sid = str(scene.get("id", "")).strip()
            if sid:
                return sid
        except Exception:
            pass
        try:
            entry = getattr(self.app, "scene_id_entry", None)
            if entry is not None:
                raw = entry.get().strip()
                if re.fullmatch(r"\d+", raw):
                    return raw
        except Exception:
            pass
        return ""

    def _guess_scene_url(self) -> str:
        try:
            scene = getattr(self.app, "current_scene", None) or {}
            sid = str(scene.get("id", "")).strip()
            if not sid:
                return ""
            ep = getattr(self.app.client, "endpoint", "") or ""
            base = ep.rstrip("/")
            if base.lower().endswith("/graphql"):
                base = base[: -len("/graphql")]
            if base:
                return f"{base}/scenes/{sid}"
        except Exception:
            pass
        return ""

    def _try_initial_autoload(self) -> None:
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if not self.url_entry.get().strip():
            return
        self._load_video(silent=True)

    def sync_scene_from_editor(self) -> None:
        """Main window loaded a new scene: align the URL field and reload the local file."""
        try:
            if cv2 is None or not self.winfo_exists():
                return
        except Exception:
            return
        prefill = self._guess_scene_url() or self._current_editor_scene_id()
        if not prefill:
            return
        try:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, prefill)
        except tk.TclError:
            return
        if _extract_scene_id(prefill):
            self._load_video(silent=True)

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------
    def _load_video(self, silent: bool = False) -> None:
        if cv2 is None or Image is None:
            if not silent:
                messagebox.showerror(
                    self._tr("preview_player_missing_deps_title"),
                    self._tr("preview_player_missing_deps_body"),
                    parent=self,
                )
            return
        raw = self.url_entry.get().strip()
        sid = _extract_scene_id(raw)
        if not sid:
            if not silent:
                messagebox.showwarning(
                    self._tr("preview_player_bad_url_title"),
                    self._tr("preview_player_bad_url_body"),
                    parent=self,
                )
            return
        path = ""
        # Re-use the already-loaded scene data from the main window if the ids match
        # (avoids a redundant GraphQL round-trip so opening feels instantaneous).
        cur = getattr(self.app, "current_scene", None) or {}
        if str(cur.get("id", "")).strip() == sid:
            files = cur.get("files") or []
            path = str(files[0].get("path", "")).strip() if files else ""
        if not path:
            try:
                data = self.app.client.get_scene_details(sid)
            except Exception as exc:
                if not silent:
                    messagebox.showerror(
                        self._tr("preview_player_load_fail_title"), str(exc), parent=self
                    )
                return
            files = data.get("files") or []
            path = str(files[0].get("path", "")).strip() if files else ""
        if not path:
            if not silent:
                messagebox.showerror(
                    self._tr("preview_player_no_path_title"),
                    self._tr("preview_player_no_path_body"),
                    parent=self,
                )
            return

        self._release_cap()
        path_open = self.app.apply_path_map(path)
        cap = _open_cv_video_capture(path_open)
        if not cap.isOpened():
            if not silent:
                body = self._tr("preview_player_open_fail_body").format(path=path_open)
                if path_open != path.strip():
                    body += "\n\n" + self._tr("preview_player_mapped_from").format(original=path.strip())
                if sys.platform == "win32":
                    ps = path_open.strip()
                    if ps.startswith("/") and not ps.startswith("//"):
                        body += self._tr("preview_player_remote_path_hint")
                messagebox.showerror(self._tr("preview_player_open_fail_title"), body, parent=self)
            try:
                cap.release()
            except Exception:
                pass
            return

        self._cap = cap
        self._fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if self._fps <= 0.1:
            self._fps = 30.0
        self._total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if self._total_frames <= 0:
            self._total_frames = max(1, int(cap.get(cv2.CAP_PROP_POS_FRAMES) or 1))
        self._width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
        self._height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 360)
        self._current_frame = 0
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        hi = max(0, self._total_frames - 1)
        to_val = max(1, hi)
        n_steps = max(1, self._total_frames - 1) if self._total_frames > 1 else 1
        self.slider.configure(from_=0, to=to_val, number_of_steps=n_steps)
        self.slider.set(0)
        self._style_sliders()
        self._is_playing = False
        self._draw_frame()
        self.focus_set()

    def _release_cap(self) -> None:
        self._is_playing = False
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _on_close(self) -> None:
        if self._fullscreen:
            try:
                self.attributes("-fullscreen", False)
            except tk.TclError:
                pass
            self._fullscreen = False
        if self._geom_save_after_id is not None:
            try:
                self.after_cancel(self._geom_save_after_id)
            except (tk.TclError, ValueError):
                pass
            self._geom_save_after_id = None
        self._flush_geometry_to_config()
        self._release_cap()
        try:
            if getattr(self.app, "_preview_player_win", None) is self:
                self.app._preview_player_win = None
        except Exception:
            pass
        self.destroy()

    # ------------------------------------------------------------------
    # playback / drawing
    # ------------------------------------------------------------------
    def _current_seconds(self) -> float:
        if self._fps > 0:
            return self._current_frame / self._fps
        return 0.0

    def _update_time_label(self) -> None:
        sec = self._current_seconds()
        dur = (self._total_frames / self._fps) if self._fps > 0 else 0.0
        try:
            self.time_label.configure(
                text=f"{_format_hhmmss(sec)}  /  {_format_hhmmss(dur)}  ·  Frame {self._current_frame + 1}/{max(1, self._total_frames)}"
            )
        except tk.TclError:
            pass

    def _draw_frame(self) -> None:
        if self._cap is None or cv2 is None or Image is None:
            return
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, self._current_frame)
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        else:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(frame)

        self.update_idletasks()
        self.video_container.update_idletasks()
        # Use the actual size of the video container — pack_propagate(False) keeps
        # this stable regardless of the displayed CTkImage size.
        cont_w = int(self.video_container.winfo_width())
        cont_h = int(self.video_container.winfo_height())
        if cont_w <= 1 or cont_h <= 1:
            # Fall back to the window size before the layout is established.
            cont_w = max(int(self.winfo_width()) - 40, 320)
            cont_h = max(int(self.winfo_height()) - 320, 200)
        avail_w = max(60, cont_w - 4)
        avail_h = max(60, cont_h - 4)
        src_w = max(1, int(self._width))
        src_h = max(1, int(self._height))
        ar = src_w / src_h
        disp_w = int(avail_w)
        disp_h = int(round(disp_w / ar))
        if disp_h > avail_h:
            disp_h = int(avail_h)
            disp_w = max(2, int(round(disp_h * ar)))
        disp_w = max(2, min(disp_w, avail_w))
        disp_h = max(2, min(disp_h, avail_h))

        self._ctk_img = ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=(disp_w, disp_h))
        self.video_label.configure(image=self._ctk_img)
        try:
            self.slider.configure(command=None)
            self.slider.set(self._current_frame)
        finally:
            self.slider.configure(command=self._on_slider)
        self._update_time_label()

    def _on_slider(self, value: float) -> None:
        if self._cap is None:
            return
        was_playing = self._is_playing
        self._is_playing = False
        try:
            self._current_frame = int(round(float(value)))
        except (TypeError, ValueError):
            self._current_frame = 0
        self._current_frame = max(0, min(max(0, self._total_frames - 1), self._current_frame))
        self._draw_frame()
        if was_playing:
            # Resume playback at the new position.
            self._play()

    def _play(self) -> None:
        if self._cap is None:
            return
        if self._is_playing:
            return
        if self._current_frame >= max(0, self._total_frames - 1):
            self._current_frame = 0
            self._draw_frame()
        self._is_playing = True
        self._last_tick = time.time()
        self._play_tick()

    def _pause(self) -> None:
        if not self._is_playing:
            return
        self._is_playing = False
        self._draw_frame()

    def _stop(self) -> None:
        self._is_playing = False
        if self._cap is None:
            return
        self._current_frame = 0
        self._draw_frame()

    def _play_tick(self) -> None:
        if not self._is_playing or self._cap is None:
            return
        now = time.time()
        dt = now - self._last_tick
        self._last_tick = now
        effective_fps = float(self._fps) if self._fps > 0.1 else 30.0
        advance = max(1, int(effective_fps * dt))
        self._current_frame = min(self._total_frames - 1, self._current_frame + advance)
        self._draw_frame()
        if self._current_frame >= self._total_frames - 1:
            self._is_playing = False
            return
        delay_ms = max(1, int(1000 / max(0.25, effective_fps)))
        self.after(delay_ms, self._play_tick)

    # ------------------------------------------------------------------
    # keyboard
    # ------------------------------------------------------------------
    def _on_key_press(self, event: tk.Event) -> None:
        keysym = event.keysym
        if keysym == "Escape":
            if self._fullscreen:
                self._toggle_fullscreen()
            return
        if keysym == "F11":
            self._toggle_fullscreen()
            return
        w = event.widget
        if isinstance(w, (ctk.CTkEntry, tk.Entry)):
            return
        if self._cap is None:
            return
        if keysym == "space":
            if self._is_playing:
                self._pause()
            else:
                self._play()
            return
