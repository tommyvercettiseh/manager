from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

import keyring
import requests

APP_NAME = "Repo Manager"
DEFAULT_ROOT = Path(r"C:\Users\Hesse\Desktop\Codex")
CONFIG_DIR = Path(os.getenv("APPDATA", Path.home())) / "RepoManager"
CONFIG_FILE = CONFIG_DIR / "config.json"
GITHUB_API = "https://api.github.com"


@dataclass
class RepoState:
    name: str
    full_name: str
    clone_url: str
    html_url: str
    default_branch: str
    local_path: Path
    local_exists: bool
    state: str
    detail: str
    favorite: bool
    bat_files: list[Path]


class ConfigStore:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {
            "root_folder": str(DEFAULT_ROOT),
            "favorites": [],
        }
        self.load()

    def load(self) -> None:
        try:
            if CONFIG_FILE.exists():
                saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    self.data.update(saved)
        except (OSError, json.JSONDecodeError):
            pass

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


class GitHubClient:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "Repo-Manager",
            }
        )

    def get_user(self) -> dict[str, Any]:
        response = self.session.get(f"{GITHUB_API}/user", timeout=15)
        response.raise_for_status()
        return response.json()

    def list_repos(self) -> list[dict[str, Any]]:
        repos: list[dict[str, Any]] = []
        page = 1
        while True:
            response = self.session.get(
                f"{GITHUB_API}/user/repos",
                params={
                    "affiliation": "owner,collaborator,organization_member",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 100,
                    "page": page,
                },
                timeout=20,
            )
            response.raise_for_status()
            batch = response.json()
            repos.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return repos


class RepoManagerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1220x780")
        self.minsize(980, 620)
        self.configure(bg="#0b0f14")

        self.config_store = ConfigStore()
        self.client: GitHubClient | None = None
        self.username = ""
        self.repos: list[RepoState] = []
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        self.search_var = tk.StringVar()
        self.only_favorites_var = tk.BooleanVar(value=True)
        self.root_var = tk.StringVar(value=self.config_store.data["root_folder"])
        self.status_var = tk.StringVar(value="Log in om je repositories te laden")

        self._configure_style()
        self._build_ui()
        self.after(150, self._poll_events)

        if keyring.get_password(APP_NAME, "github_token"):
            self.after(250, self.refresh_repositories)
        else:
            self.after(250, self.show_login)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#10161e")
        style.configure("TLabel", background="#10161e", foreground="#dce3ea")
        style.configure("TButton", padding=8)
        style.configure("TEntry", fieldbackground="#171f29", foreground="#ffffff")
        style.configure("Primary.TButton", background="#2a6ff2", foreground="#ffffff", borderwidth=0, padding=(14, 9))
        style.map("Primary.TButton", background=[("active", "#3b7df4")])
        style.configure("Secondary.TButton", background="#202a35", foreground="#dce3ea", borderwidth=0, padding=(12, 8))
        style.map("Secondary.TButton", background=[("active", "#2a3644")])
        style.configure("TCheckbutton", background="#10161e", foreground="#dce3ea")

    def _build_ui(self) -> None:
        outer = tk.Frame(self, bg="#0b0f14")
        outer.pack(fill="both", expand=True, padx=24, pady=24)
        panel = tk.Frame(outer, bg="#10161e", highlightthickness=1, highlightbackground="#1c2530")
        panel.pack(fill="both", expand=True)
        header = tk.Frame(panel, bg="#10161e")
        header.pack(fill="x", padx=28, pady=(24, 14))
        title_box = tk.Frame(header, bg="#10161e")
        title_box.pack(side="left")
        tk.Label(title_box, text=APP_NAME, bg="#10161e", fg="#f5f7fa", font=("Segoe UI", 24, "bold")).pack(anchor="w")
        tk.Label(title_box, textvariable=self.root_var, bg="#10161e", fg="#8c9aaa", font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))
        self.account_button = ttk.Button(header, text="GitHub login", style="Secondary.TButton", command=self.show_login)
        self.account_button.pack(side="right")
        controls = tk.Frame(panel, bg="#10161e")
        controls.pack(fill="x", padx=28, pady=(0, 18))
        ttk.Checkbutton(controls, text="Alleen favorieten", variable=self.only_favorites_var, command=self.render_cards).pack(side="left")
        ttk.Button(controls, text="Vernieuwen", style="Secondary.TButton", command=self.refresh_repositories).pack(side="left", padx=(10, 0))
        ttk.Button(controls, text="Map openen", style="Secondary.TButton", command=self.open_root_folder).pack(side="left", padx=(10, 0))
        ttk.Entry(controls, textvariable=self.search_var, width=32).pack(side="right")
        self.search_var.trace_add("write", lambda *_: self.render_cards())
        self.canvas = tk.Canvas(panel, bg="#10161e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self.canvas.yview)
        self.cards_frame = tk.Frame(self.canvas, bg="#10161e")
        self.cards_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.cards_frame.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resize_cards_window)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True, padx=(28, 0), pady=(0, 8))
        scrollbar.pack(side="right", fill="y", padx=(0, 18), pady=(0, 8))
        footer = tk.Frame(panel, bg="#10161e")
        footer.pack(fill="x", padx=28, pady=(4, 18))
        tk.Label(footer, textvariable=self.status_var, bg="#10161e", fg="#718092", font=("Segoe UI", 9)).pack(side="left")

    def _resize_cards_window(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.cards_window, width=event.width)
        self.after_idle(self.render_cards)

    def show_login(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("GitHub login")
        dialog.geometry("520x285")
        dialog.resizable(False, False)
        dialog.configure(bg="#10161e")
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(dialog, text="GitHub verbinden", bg="#10161e", fg="#f5f7fa", font=("Segoe UI", 20, "bold")).pack(anchor="w", padx=24, pady=(22, 4))
        tk.Label(dialog, text="Gebruik een fine-grained token met alleen toegang tot je repositories.", bg="#10161e", fg="#8c9aaa", font=("Segoe UI", 10)).pack(anchor="w", padx=24)
        token_var = tk.StringVar(value=keyring.get_password(APP_NAME, "github_token") or "")
        token_entry = ttk.Entry(dialog, textvariable=token_var, show="•", width=58)
        token_entry.pack(fill="x", padx=24, pady=(18, 12))
        ttk.Entry(dialog, textvariable=self.root_var).pack(fill="x", padx=24, pady=(0, 12))
        links = tk.Frame(dialog, bg="#10161e")
        links.pack(fill="x", padx=24)
        ttk.Button(links, text="Token maken", style="Secondary.TButton", command=lambda: webbrowser.open("https://github.com/settings/personal-access-tokens/new")).pack(side="left")

        def save_and_connect() -> None:
            token = token_var.get().strip()
            root = self.root_var.get().strip()
            if not token:
                messagebox.showerror("Token ontbreekt", "Vul eerst een GitHub-token in.", parent=dialog)
                return
            if not root:
                messagebox.showerror("Map ontbreekt", "Vul de lokale projectmap in.", parent=dialog)
                return
            keyring.set_password(APP_NAME, "github_token", token)
            self.config_store.data["root_folder"] = root
            self.config_store.save()
            dialog.destroy()
            self.refresh_repositories()

        ttk.Button(links, text="Verbinden", style="Primary.TButton", command=save_and_connect).pack(side="right")
        token_entry.focus_set()

    def refresh_repositories(self) -> None:
        token = (keyring.get_password(APP_NAME, "github_token") or "").strip()
        if not token:
            self.show_login()
            return
        self.status_var.set("Repositories laden...")
        self.client = GitHubClient(token)
        threading.Thread(target=self._load_repositories_worker, daemon=True).start()

    def _load_repositories_worker(self) -> None:
        try:
            assert self.client is not None
            user = self.client.get_user()
            repos = self.client.list_repos()
            states = [self._inspect_repo(repo) for repo in repos if not repo.get("archived")]
            self.events.put(("loaded", (user.get("login", "GitHub"), states)))
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            self.events.put(("error", f"GitHub gaf foutcode {status}. Controleer je token."))
        except (requests.RequestException, OSError, subprocess.SubprocessError) as exc:
            self.events.put(("error", str(exc)))

    def _inspect_repo(self, repo: dict[str, Any]) -> RepoState:
        root = Path(self.root_var.get())
        local_path = root / repo["name"]
        favorite = repo["full_name"] in self.config_store.data.get("favorites", [])
        bat_files = sorted(local_path.glob("*.bat")) if local_path.exists() else []
        common = dict(name=repo["name"], full_name=repo["full_name"], clone_url=repo["clone_url"], html_url=repo["html_url"], default_branch=repo.get("default_branch") or "main", local_path=local_path, favorite=favorite, bat_files=bat_files)
        if not local_path.exists():
            return RepoState(local_exists=False, state="NIET LOKAAL", detail="Alleen op GitHub", **common)
        if not (local_path / ".git").exists():
            return RepoState(local_exists=True, state="LOCAL", detail="Map is geen Git-repository", **common)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            subprocess.run(["git", "-C", str(local_path), "fetch", "--quiet", "origin"], check=True, capture_output=True, text=True, timeout=30, creationflags=flags)
            branch = subprocess.run(["git", "-C", str(local_path), "branch", "--show-current"], check=True, capture_output=True, text=True, timeout=10, creationflags=flags).stdout.strip() or repo.get("default_branch") or "main"
            counts = subprocess.run(["git", "-C", str(local_path), "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"], check=True, capture_output=True, text=True, timeout=10, creationflags=flags).stdout.strip().split()
            ahead, behind = map(int, counts)
            dirty = bool(subprocess.run(["git", "-C", str(local_path), "status", "--porcelain"], check=True, capture_output=True, text=True, timeout=10, creationflags=flags).stdout.strip())
            if dirty:
                state, detail = "LOCAL", "Lokale wijzigingen aanwezig"
            elif ahead and behind:
                state, detail = "LOCAL", f"{ahead} vooruit en {behind} achter"
            elif behind:
                state, detail = "OUTDATED", f"{behind} commit(s) achter"
            elif ahead:
                state, detail = "LOCAL", f"{ahead} lokale commit(s)"
            else:
                state, detail = "LIVE", "1:1 met GitHub"
        except (subprocess.SubprocessError, ValueError):
            state, detail = "LOCAL", "Status kon niet worden bepaald"
        return RepoState(local_exists=True, state=state, detail=detail, **common)

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "loaded":
                    self.username, self.repos = payload
                    self.account_button.configure(text=f"● {self.username}")
                    if not self.config_store.data.get("favorites") and self.repos:
                        first = [repo.full_name for repo in self.repos[:3]]
                        self.config_store.data["favorites"] = first
                        self.config_store.save()
                        for repo in self.repos:
                            repo.favorite = repo.full_name in first
                    self.status_var.set(f"{len(self.repos)} repositories gevonden")
                    self.render_cards()
                elif event == "action_done":
                    self.status_var.set(payload)
                    self.refresh_repositories()
                elif event == "error":
                    self.status_var.set("Actie mislukt")
                    messagebox.showerror(APP_NAME, payload, parent=self)
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def render_cards(self) -> None:
        for child in self.cards_frame.winfo_children():
            child.destroy()
        query = self.search_var.get().strip().lower()
        visible = [repo for repo in self.repos if (not self.only_favorites_var.get() or repo.favorite) and (not query or query in repo.name.lower() or query in repo.full_name.lower())]
        width = max(self.canvas.winfo_width(), 1)
        columns = 3 if width >= 1050 else 2 if width >= 700 else 1
        if not visible:
            tk.Label(self.cards_frame, text="Geen repositories om te tonen.", bg="#10161e", fg="#718092", font=("Segoe UI", 12)).grid(row=0, column=0, padx=8, pady=30, sticky="w")
            return
        for index, repo in enumerate(visible):
            row, column = divmod(index, columns)
            self._create_card(repo).grid(row=row, column=column, padx=8, pady=8, sticky="nsew")
        for column in range(columns):
            self.cards_frame.grid_columnconfigure(column, weight=1, uniform="cards")

    def _create_card(self, repo: RepoState) -> tk.Frame:
        card = tk.Frame(self.cards_frame, bg="#151c25", highlightthickness=1, highlightbackground="#25303c", padx=18, pady=16)
        top = tk.Frame(card, bg="#151c25")
        top.pack(fill="x")
        tk.Label(top, text=repo.name, bg="#151c25", fg="#f4f7fa", font=("Segoe UI", 13, "bold")).pack(side="left", anchor="w")
        ttk.Button(top, text="×" if repo.favorite else "+", style="Primary.TButton" if repo.favorite else "Secondary.TButton", width=3, command=lambda r=repo: self.toggle_favorite(r)).pack(side="right")
        colors = {"LIVE": "#39d98a", "OUTDATED": "#ffb547", "LOCAL": "#8c9aaa", "NIET LOKAAL": "#e96767"}
        tk.Label(card, text=f"●  {repo.state}", bg="#151c25", fg=colors.get(repo.state, "#8c9aaa"), font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(16, 6))
        tk.Label(card, text=repo.detail, bg="#151c25", fg="#aab5c2", font=("Segoe UI", 10)).pack(anchor="w")
        tk.Label(card, text=str(repo.local_path), bg="#151c25", fg="#718092", font=("Segoe UI", 8), wraplength=330, justify="left").pack(anchor="w", pady=(4, 14))
        actions = tk.Frame(card, bg="#151c25")
        actions.pack(fill="x", side="bottom")
        if not repo.local_exists:
            primary_text, primary_command = "Klonen", lambda r=repo: self.clone_repo(r)
        elif repo.state == "OUTDATED":
            primary_text, primary_command = "Updaten", lambda r=repo: self.update_repo(r)
        else:
            primary_text, primary_command = "Openen", lambda r=repo: self.open_repo(r)
        ttk.Button(actions, text=primary_text, style="Primary.TButton", command=primary_command).pack(side="left")
        bat_names = [path.name for path in repo.bat_files]
        selected_bat = tk.StringVar(value=bat_names[0] if bat_names else "Geen .bat")
        menu = ttk.OptionMenu(actions, selected_bat, selected_bat.get(), *bat_names)
        menu.pack(side="right", padx=(8, 0))
        if not bat_names:
            menu.state(["disabled"])
        else:
            ttk.Button(actions, text="Start", style="Secondary.TButton", command=lambda r=repo, v=selected_bat: self.run_bat(r, v.get())).pack(side="right")
        return card

    def toggle_favorite(self, repo: RepoState) -> None:
        repo.favorite = not repo.favorite
        favorites = set(self.config_store.data.get("favorites", []))
        favorites.add(repo.full_name) if repo.favorite else favorites.discard(repo.full_name)
        self.config_store.data["favorites"] = sorted(favorites)
        self.config_store.save()
        self.render_cards()

    def clone_repo(self, repo: RepoState) -> None:
        root = Path(self.root_var.get())
        root.mkdir(parents=True, exist_ok=True)
        self._run_git_action(["git", "clone", repo.clone_url, str(repo.local_path)], f"{repo.name} klonen")

    def update_repo(self, repo: RepoState) -> None:
        self._run_git_action(["git", "-C", str(repo.local_path), "pull", "--ff-only"], f"{repo.name} updaten")

    def _run_git_action(self, command: list[str], description: str) -> None:
        self.status_var.set(f"Bezig met {description.lower()}...")
        def worker() -> None:
            try:
                result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                self.events.put(("action_done", result.stdout.strip() or description))
            except subprocess.CalledProcessError as exc:
                self.events.put(("error", exc.stderr.strip() or str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def open_repo(self, repo: RepoState) -> None:
        if repo.local_path.exists():
            os.startfile(repo.local_path)  # type: ignore[attr-defined]

    def open_root_folder(self) -> None:
        root = Path(self.root_var.get())
        root.mkdir(parents=True, exist_ok=True)
        os.startfile(root)  # type: ignore[attr-defined]

    def run_bat(self, repo: RepoState, name: str) -> None:
        bat = repo.local_path / name
        if not bat.exists():
            messagebox.showerror(APP_NAME, "Het gekozen .bat-bestand bestaat niet meer.")
            return
        subprocess.Popen(["cmd", "/c", "start", "", str(bat)], cwd=repo.local_path, shell=False)


if __name__ == "__main__":
    RepoManagerApp().mainloop()
