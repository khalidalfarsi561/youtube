from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

import yt_commenter


@dataclass
class AutomationConfig:
    video_urls: list[str]
    cookies_path: str = "cookies.json"
    gemini_api_key: str = ""
    headless: bool = False


class QueueLogger(logging.Handler):
    def __init__(self, log_queue: "queue.Queue[tuple[str, str]]") -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname.upper()
            self.log_queue.put((level, msg))
        except Exception:
            pass


class AutomationController:
    def __init__(self, on_done: Optional[Callable[[bool, str], None]] = None) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._on_done = on_done
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._current_task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.set()
        if self._loop and self._loop.is_running() and self._current_task:
            self._loop.call_soon_threadsafe(self._current_task.cancel)

    def start(self, config: AutomationConfig) -> None:
        if self.is_running:
            raise RuntimeError("Automation is already running.")

        self._stop_event.clear()
        self._pause_event.set()

        def runner() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._run(config))
                if self._on_done:
                    self._on_done(True, "Automation finished successfully.")
            except asyncio.CancelledError:
                if self._on_done:
                    self._on_done(False, "Automation stopped.")
            except Exception as exc:
                if self._on_done:
                    self._on_done(False, str(exc))
            finally:
                try:
                    pending = asyncio.all_tasks(self._loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                self._loop.close()

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()

    async def _run(self, config: AutomationConfig) -> None:
        video_urls = config.video_urls or yt_commenter.load_video_urls()

        if config.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = config.gemini_api_key
            os.environ["GENAI_API_KEY"] = config.gemini_api_key
            yt_commenter.os.environ["GEMINI_API_KEY"] = config.gemini_api_key

        title = await yt_commenter.fetch_video_title(video_urls[0])
        comment_text = await yt_commenter.generate_comment(title)
        if not comment_text:
            raise RuntimeError("Gemini did not return a usable comment.")

        async with yt_commenter.async_playwright() as p:
            browser = await p.chromium.launch(headless=config.headless)
            context = await browser.new_context(user_agent=yt_commenter.USER_AGENT, viewport=yt_commenter.VIEWPORT)
            await _add_cookies_from_path(context, config.cookies_path)
            page = await context.new_page()

            try:
                for video_url in video_urls:
                    if self._stop_event.is_set():
                        raise asyncio.CancelledError()
                    while not self._pause_event.is_set():
                        await asyncio.sleep(0.2)
                    current_title = await yt_commenter.fetch_video_title(video_url)
                    current_comment = await yt_commenter.generate_comment(current_title) or comment_text
                    await yt_commenter.comment_on_video(page, video_url, current_comment)
                logging.info("All comments processed.")
            finally:
                try:
                    await context.close()
                finally:
                    await browser.close()


async def _add_cookies_from_path(context, cookies_path: str) -> None:
    cookies_data = yt_commenter.load_json_file(cookies_path)
    cookies = []
    for cookie in cookies_data:
        cookies.append(
            {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie["domain"],
                "path": cookie["path"],
                "expires": cookie.get("expirationDate", -1),
                "httpOnly": cookie["httpOnly"],
                "secure": cookie["secure"],
                "sameSite": "None" if cookie.get("sameSite") == "no_restriction" else "Lax",
            }
        )
    await context.add_cookies(cookies)


class GuiApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("dark-blue")
        self.title("YT Commenter Dashboard")
        self.geometry("1200x760")
        self.minsize(1080, 700)

        self.log_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._setup_logger()

        self.controller = AutomationController(on_done=self._on_done)

        self.video_urls: list[str] = self._load_urls()
        self.gemini_key_var = ctk.StringVar(value=self._read_env_key())
        self.cookies_path_var = ctk.StringVar(value="cookies.json")
        self.headless_var = ctk.BooleanVar(value=False)
        self.status_var = ctk.StringVar(value="Ready")
        self.url_var = ctk.StringVar()

        self._build_ui()
        self.after(100, self._poll_logs)

    def _setup_logger(self) -> None:
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        for handler in list(root.handlers):
            root.removeHandler(handler)
        handler = QueueLogger(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        root.addHandler(handler)

    def _load_urls(self) -> list[str]:
        path = Path("videos.txt")
        if not path.exists():
            return []
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _read_env_key(self) -> str:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip()
        return os.getenv("GEMINI_API_KEY", "")

    def _save_env_key(self, value: str) -> None:
        env_path = Path(".env")
        lines: list[str] = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith("GEMINI_API_KEY="):
                new_lines.append(f"GEMINI_API_KEY={value}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"GEMINI_API_KEY={value}")
        env_path.write_text("\n".join(new_lines).strip() + "\n", encoding="utf-8")
        os.environ["GEMINI_API_KEY"] = value
        messagebox.showinfo("Saved", "Gemini API key saved to .env")

    def _build_ui(self) -> None:
        sidebar = ctk.CTkFrame(self, corner_radius=18)
        sidebar.pack(side="left", fill="y", padx=18, pady=18)

        main = ctk.CTkFrame(self, corner_radius=18)
        main.pack(side="right", expand=True, fill="both", padx=(0, 18), pady=18)

        ctk.CTkLabel(sidebar, text="YT Commenter", font=ctk.CTkFont(size=26, weight="bold")).pack(pady=(20, 10))
        ctk.CTkLabel(sidebar, text="Dashboard", font=ctk.CTkFont(size=16)).pack(pady=(0, 20))

        ctk.CTkLabel(sidebar, text="Add YouTube URL").pack(anchor="w", padx=18)
        self.url_entry = ctk.CTkEntry(sidebar, textvariable=self.url_var, width=300)
        self.url_entry.pack(padx=18, pady=(6, 8))
        ctk.CTkButton(sidebar, text="Add URL", corner_radius=14, command=self._add_url).pack(padx=18, fill="x")
        ctk.CTkButton(sidebar, text="Refresh List", corner_radius=14, command=self._refresh_urls).pack(padx=18, pady=(8, 16), fill="x")

        ctk.CTkLabel(sidebar, text="Current URLs").pack(anchor="w", padx=18)
        self.urls_listbox = ctk.CTkTextbox(sidebar, width=320, height=160, corner_radius=14)
        self.urls_listbox.pack(padx=18, pady=(6, 16), fill="both")
        self._render_urls()

        self.headless_switch = ctk.CTkSwitch(sidebar, text="Headless Mode", variable=self.headless_var)
        self.headless_switch.pack(anchor="w", padx=18, pady=(0, 18))

        ctk.CTkLabel(sidebar, text="Gemini API Key").pack(anchor="w", padx=18)
        self.key_entry = ctk.CTkEntry(sidebar, textvariable=self.gemini_key_var, show="•", width=300)
        self.key_entry.pack(padx=18, pady=(6, 8))
        ctk.CTkButton(sidebar, text="Save API Key", corner_radius=14, command=lambda: self._save_env_key(self.gemini_key_var.get().strip())).pack(padx=18, fill="x")

        ctk.CTkLabel(sidebar, text="Cookies File").pack(anchor="w", padx=18, pady=(16, 0))
        self.cookies_entry = ctk.CTkEntry(sidebar, textvariable=self.cookies_path_var, width=300)
        self.cookies_entry.pack(padx=18, pady=(6, 8))
        ctk.CTkButton(sidebar, text="Choose cookies.json", corner_radius=14, command=self._pick_cookies).pack(padx=18, fill="x")

        ctk.CTkLabel(sidebar, textvariable=self.status_var, font=ctk.CTkFont(size=14, weight="bold")).pack(padx=18, pady=18)

        ctk.CTkLabel(main, text="Controls", font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", padx=18, pady=(18, 10))
        controls = ctk.CTkFrame(main, corner_radius=18)
        controls.pack(fill="x", padx=18, pady=(0, 18))
        ctk.CTkButton(controls, text="Start", corner_radius=14, command=self._start).pack(side="left", padx=12, pady=12, expand=True, fill="x")
        ctk.CTkButton(controls, text="Pause", corner_radius=14, command=self._pause).pack(side="left", padx=12, pady=12, expand=True, fill="x")
        ctk.CTkButton(controls, text="Stop", corner_radius=14, fg_color="#8b1e3f", hover_color="#a83252", command=self._stop).pack(side="left", padx=12, pady=12, expand=True, fill="x")

        ctk.CTkLabel(main, text="Logging Console", font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", padx=18, pady=(0, 10))
        self.log_box = ctk.CTkTextbox(main, corner_radius=18, wrap="word")
        self.log_box.pack(expand=True, fill="both", padx=18, pady=(0, 18))
        self.log_box.tag_config("INFO", foreground="#f1f1f1")
        self.log_box.tag_config("WARNING", foreground="#ffd54a")
        self.log_box.tag_config("ERROR", foreground="#ff5b5b")
        self.log_box.tag_config("DEBUG", foreground="#8ab4ff")

    def _render_urls(self) -> None:
        self.urls_listbox.delete("1.0", "end")
        for idx, url in enumerate(self.video_urls, start=1):
            self.urls_listbox.insert("end", f"{idx}. {url}\n")

    def _refresh_urls(self) -> None:
        self.video_urls = self._load_urls()
        self._render_urls()
        self._log("INFO", f"Loaded {len(self.video_urls)} URL(s).")

    def _add_url(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            return
        self.video_urls.append(url)
        Path("videos.txt").write_text("\n".join(self.video_urls) + "\n", encoding="utf-8")
        self.url_var.set("")
        self._render_urls()
        self._log("INFO", f"Added URL: {url}")

    def _pick_cookies(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if path:
            self.cookies_path_var.set(path)
            self._log("INFO", f"Selected cookies file: {path}")

    def _start(self) -> None:
        if not self.video_urls:
            messagebox.showerror("Error", "Add at least one YouTube URL first.")
            return
        config = AutomationConfig(
            video_urls=list(self.video_urls),
            cookies_path=self.cookies_path_var.get().strip() or "cookies.json",
            gemini_api_key=self.gemini_key_var.get().strip(),
            headless=bool(self.headless_var.get()),
        )
        try:
            self.controller.start(config)
            self.status_var.set("Running")
            self._log("INFO", "Automation started.")
        except Exception as exc:
            messagebox.showerror("Start failed", str(exc))
            self._log("ERROR", str(exc))

    def _pause(self) -> None:
        if self.controller.is_running:
            self.controller.pause()
            self.status_var.set("Paused")
            self._log("WARNING", "Automation paused.")

    def _stop(self) -> None:
        self.controller.stop()
        self.status_var.set("Stopping")
        self._log("WARNING", "Stopping automation...")

    def _on_done(self, success: bool, message: str) -> None:
        def _update() -> None:
            self.status_var.set("Ready" if success else "Error")
            if success:
                messagebox.showinfo("Completed", message)
                self._log("INFO", message)
            else:
                messagebox.showerror("Automation error", message)
                self._log("ERROR", message)
        self.after(0, _update)

    def _poll_logs(self) -> None:
        try:
            while True:
                level, msg = self.log_queue.get_nowait()
                self._log(level, msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_logs)

    def _log(self, level: str, message: str) -> None:
        self.log_box.insert("end", f"{message}\n", level if level in {"INFO", "WARNING", "ERROR", "DEBUG"} else "INFO")
        self.log_box.see("end")


def run_gui() -> None:
    app = GuiApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
