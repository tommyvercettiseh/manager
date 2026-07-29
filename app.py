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
        self.geometry("1120x720")
        self.minsize(900, 560)
        self.configure(bg="#0d1117")

        self.store = ConfigStore()
        self.client: GitHubClient | None = None
        self.repos: list[RepoState] = []
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        self.root_var = tk.StringVar(value=self.store.data["root_folder"])
        self.status_var = tk.StringVar(value="GitHub nog niet geladen")
        self.search_var = tk.StringVar()
        self.only_favorites = tk.BooleanVar(value=True)

        self._configure_style()
        self._build_ui()
        self.after(150, self._poll_events)

        if keyring.get_password(APP_NAME, "github_token"):
            self.after(250, self.refresh)
        else:
            self.after(250, self.show_login)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", padding=(12, 8), borderwidth=0)
        style.configure("Primary.TButton", background="#3478f6", foreground="white")
        style.map("Primary.TButton", background=[("active", "#4b89f7")])
        style.configure("Secondary.TButton", background="#1d2632", foreground="#dbe4ee")
        style.map("Secondary.TButton", background=[("active", "#283544")])
        style.configure("Danger.TButton", background="#d74b4b", foreground="white")
        style.map("Danger.TButton", background=[("active", "#e05c5c")])
        style.configure("TCheckbutton", background="#111821", foreground="#dbe4ee")
        style.configure("TEntry", fieldbackground="#18212c", foreground="white")

    def _build_ui(self) -> None:
        shell = tk.Frame(self, bg="#111821", highlightthickness=1, highlightbackground="#263241")
        shell.pack(fill="both", expand=True, padx=22, pady=22)

        header = tk.Frame(shell, bg="#111821")
        header.pack(fill="x", padx=24, pady=(22, 10))

        title_box = tk.Frame(header, bg="#111821")
        title_box.pack(side="left")
        tk.Label(title_box, text=APP_NAME, bg="#111821", fg="#f5f7fa", font=("Segoe UI", 23, "bold")).pack(anchor="w")
        tk.Label(title_box, textvariable=self.root_var, bg="#111821", fg="#8290a2", font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        self.login_button = ttk.Button(header, text="GitHub login", style="Secondary.TButton", command=self.show_login)
        self.login_button.pack(side="right")

        controls = tk.Frame(shell, bg="#111821")
        controls.pack(fill="x", padx=24, pady=(6, 14))
        ttk.Checkbutton(controls, text="Favorieten", variable=self.only_favorites, command=self.render_cards).pack(side="left")
        ttk.Button(controls, text="↻ GitHub vernieuwen", style="Primary.TButton", command=self.refresh).pack(side="left", padx=(10, 0))
        ttk.Button(controls, text="Map openen", style="Secondary.TButton", command=self.open_root).pack(side="left", padx=(10, 0))
        search = ttk.Entry(controls, textvariable=self.search_var, width=30)
        search.pack(side="right")
        self.search_var.trace_add("write", lambda *_: self.render_cards())

        self.canvas = tk.Canvas(shell, bg="#111821", highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=self.canvas.yview)
        self.cards = tk.Frame(self.canvas, bg="#111821")
        self.cards_window = self.canvas.create_window((0, 0), window=self.cards, anchor="nw")
        self.cards.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.cards_window, width=event.width))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True, padx=(24, 0), pady=(0, 8))
        scrollbar.pack(side="right", fill="y", padx=(0, 16), pady=(0, 8))

        tk.Label(shell, textvariable=self.status_var, bg="#111821", fg="#8290a2", font=("Segoe UI", 9)).pack(anchor="w", padx=24, pady=(4, 16))

    def show_login(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("GitHub verbinden")
        dialog.geometry("500x250")
        dialog.resizable(False, False)
        dialog.configure(bg="#111821")
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(dialog, text="GitHub verbinden", bg="#111821", fg="white", font=("Segoe UI", 19, "bold")).pack(anchor="w", padx=22, pady=(20, 4))
        tk.Label(dialog, text="Plak een fine-grained GitHub-token.", bg="#111821", fg="#8290a2").pack(anchor="w", padx=22)

        token_var = tk.StringVar(value=keyring.get_password(APP_NAME, "github_token") or "")
        token_entry = ttk.Entry(dialog, textvariable=token_var, show="•")
        token_entry.pack(fill="x", padx=22, pady=(16, 10))
        ttk.Entry(dialog, textvariable=self.root_var).pack(fill="x", padx=22)

        row = tk.Frame(dialog, bg="#111821")
        row.pack(fill="x", padx=22, pady=18)
        ttk.Button(row, text="Token maken", style="Secondary.TButton", command=lambda: webbrowser.open("https://github.com/settings/personal-access-tokens/new")).pack(side="left")

        def connect() -> None:
            token = token_var.get().strip()
            root = self.root_var.get().strip()
            if not token or not root:
                messagebox.showerror(APP_NAME, "Vul een token en lokale map in.", parent=dialog)
                return
            keyring.set_password(APP_NAME, "github_token", token)
            self.store.data["root_folder"] = root
            self.store.save()
            dialog.destroy()
            self.refresh()

        ttk.Button(row, text="Verbinden", style="Primary.TButton", command=connect).pack(side="right")
        token_entry.focus_set()

    def refresh(self) -> None:
        token = (keyring.get_password(APP_NAME, "github_token") or "").strip()
        if not token:
            self.show_login()
            return
        self.status_var.set("GitHub en lokale mappen controleren...")
        self.client = GitHubClient(token)
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _load_worker(self) -> None:
        try:
            assert self.client is not None
            user = self.client.get_user()
            repos = self.client.list_repos()
            states = [self._inspect_repo(repo) for repo in repos if not repo.get("archived")]
            self.events.put(("loaded", (user.get("login", "GitHub"), states)))
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            self.events.put(("error", f"GitHub fout {code}. Controleer je token."))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    @staticmethod
    def _git(local_path: Path, *args: str, timeout: int = 30) -> str:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            ["git", "-C", str(local_path), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
        return result.stdout.strip()

    def _inspect_repo(self, repo: dict[str, Any]) -> RepoState:
        root = Path(self.root_var.get())
        local_path = root / repo["name"]
        full_name = repo["full_name"]
        default_branch = repo.get("default_branch") or "main"
        favorite = full_name in self.store.data.get("favorites", [])
        bat_files = sorted(local_path.glob("*.bat")) if local_path.exists() else []
        common = dict(
            name=repo["name"],
            full_name=full_name,
            clone_url=repo["clone_url"],
            default_branch=default_branch,
            local_path=local_path,
            favorite=favorite,
            bat_files=bat_files,
        )

        if not local_path.exists():
            return RepoState(local_exists=False, state="NIET LOKAAL", detail="Alleen op GitHub", **common)
        if not (local_path / ".git").exists():
            return RepoState(local_exists=True, state="LOCAL", detail="Map is geen Git-repository", **common)

        try:
            remote_url = self._git(local_path, "remote", "get-url", "origin")
            normalized_remote = remote_url.lower().removesuffix(".git").replace("git@github.com:", "github.com/")
            expected = f"github.com/{full_name}".lower()
            if expected not in normalized_remote:
                return RepoState(local_exists=True, state="CHECK", detail="Origin wijst naar andere repository", **common)

            self._git(local_path, "fetch", "--prune", "origin", default_branch, timeout=60)
            remote_ref = f"origin/{default_branch}"
            self._git(local_path, "rev-parse", "--verify", remote_ref)

            counts = self._git(local_path, "rev-list", "--left-right", "--count", f"HEAD...{remote_ref}").split()
            if len(counts) != 2:
                raise ValueError("Ongeldige Git-status")
            ahead, behind = map(int, counts)
            dirty = bool(self._git(local_path, "status", "--porcelain"))
            current_branch = self._git(local_path, "branch", "--show-current") or "detached"

            if behind > 0:
                detail = f"{behind} commit(s) achter GitHub"
                if ahead > 0:
                    detail += f", {ahead} lokaal vooruit"
                state = "OUTDATED"
            elif dirty:
                state, detail = "LOCAL", "Lokale wijzigingen aanwezig"
            elif ahead > 0:
                state, detail = "LOCAL", f"{ahead} lokale commit(s) vooruit"
            elif current_branch != default_branch:
                state, detail = "LOCAL", f"Lokale branch: {current_branch}"
            else:
                state, detail = "LIVE", f"1:1 met GitHub/{default_branch}"
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            state, detail = "CHECK", f"Status niet betrouwbaar: {str(exc)[:80]}"

        return RepoState(local_exists=True, state=state, detail=detail, **common)

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "loaded":
                    username, self.repos = payload
                    self.login_button.configure(text=f"● {username}")
                    if not self.store.data.get("favorites") and self.repos:
                        first = [repo.full_name for repo in self.repos[:3]]
                        self.store.data["favorites"] = first
                        self.store.save()
                        for repo in self.repos:
                            repo.favorite = repo.full_name in first
                    not_live = sum(repo.state != "LIVE" for repo in self.repos)
                    self.status_var.set(f"{len(self.repos)} repositories gecontroleerd • {not_live} niet LIVE")
                    self.render_cards()
                elif event == "done":
                    self.status_var.set(payload)
                    self.refresh()
                elif event == "error":
                    self.status_var.set("Actie mislukt")
                    messagebox.showerror(APP_NAME, payload, parent=self)
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def render_cards(self) -> None:
        for child in self.cards.winfo_children():
            child.destroy()

        query = self.search_var.get().strip().lower()
        visible = [
            repo for repo in self.repos
            if (not self.only_favorites.get() or repo.favorite)
            and (not query or query in repo.name.lower())
        ]
        width = max(self.canvas.winfo_width(), 1)
        columns = 3 if width >= 980 else 2 if width >= 640 else 1

        if not visible:
            tk.Label(self.cards, text="Geen repositories zichtbaar.", bg="#111821", fg="#8290a2").grid(row=0, column=0, pady=30)
            return

        for index, repo in enumerate(visible):
            row, column = divmod(index, columns)
            self._card(repo).grid(row=row, column=column, padx=8, pady=8, sticky="nsew")
        for column in range(columns):
            self.cards.grid_columnconfigure(column, weight=1, uniform="cards")

    def _card(self, repo: RepoState) -> tk.Frame:
        card = tk.Frame(self.cards, bg="#18212c", highlightthickness=1, highlightbackground="#2b3948", padx=16, pady=15)
        top = tk.Frame(card, bg="#18212c")
        top.pack(fill="x")
        tk.Label(top, text=repo.name, bg="#18212c", fg="#f5f7fa", font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Button(top, text="×" if repo.favorite else "+", style="Primary.TButton" if repo.favorite else "Secondary.TButton", width=3, command=lambda: self.toggle_favorite(repo)).pack(side="right")

        colors = {
            "LIVE": "#3bd58b",
            "OUTDATED": "#ffad42",
            "LOCAL": "#9aa7b6",
            "NIET LOKAAL": "#ef6b73",
            "CHECK": "#d9a441",
        }
        tk.Label(card, text=f"●  {repo.state}", bg="#18212c", fg=colors.get(repo.state, "#9aa7b6"), font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(14, 5))
        tk.Label(card, text=repo.detail, bg="#18212c", fg="#c1cad5", font=("Segoe UI", 9)).pack(anchor="w")

        actions = tk.Frame(card, bg="#18212c")
        actions.pack(fill="x", pady=(16, 0))

        if not repo.local_exists:
            ttk.Button(actions, text="Klonen", style="Primary.TButton", command=lambda: self.clone_repo(repo)).pack(side="left")
        elif repo.state != "LIVE":
            ttk.Button(actions, text="Maak LIVE", style="Danger.TButton", command=lambda: self.make_live(repo)).pack(side="left")
        else:
            ttk.Button(actions, text="Openen", style="Secondary.TButton", command=lambda: self.open_repo(repo)).pack(side="left")

        bat_names = [path.name for path in repo.bat_files]
        selected = tk.StringVar(value=bat_names[0] if bat_names else "Geen .bat")
        menu = ttk.OptionMenu(actions, selected, selected.get(), *bat_names)
        menu.pack(side="right")
        if bat_names:
            ttk.Button(actions, text="Start", style="Primary.TButton", command=lambda: self.run_bat(repo, selected.get())).pack(side="right", padx=(0, 7))
        else:
            menu.state(["disabled"])
        return card

    def toggle_favorite(self, repo: RepoState) -> None:
        repo.favorite = not repo.favorite
        favorites = set(self.store.data.get("favorites", []))
        if repo.favorite:
            favorites.add(repo.full_name)
        else:
            favorites.discard(repo.full_name)
        self.store.data["favorites"] = sorted(favorites)
        self.store.save()
        self.render_cards()

    def clone_repo(self, repo: RepoState) -> None:
        Path(self.root_var.get()).mkdir(parents=True, exist_ok=True)
        self._run_action(
            ["git", "clone", "--branch", repo.default_branch, repo.clone_url, str(repo.local_path)],
            f"{repo.name} gekloond en LIVE",
        )

    def make_live(self, repo: RepoState) -> None:
        confirmed = messagebox.askyesno(
            "Lokale map overschrijven",
            (
                f"GitHub wordt de enige waarheid voor {repo.name}.\n\n"
                "Alle lokale wijzigingen, lokale commits en niet-opgeslagen Git-bestanden "
                "worden verwijderd. Doorgaan?"
            ),
            parent=self,
        )
        if not confirmed:
            return

        self.status_var.set(f"{repo.name} exact gelijkmaken aan GitHub...")

        def worker() -> None:
            try:
                self._git(repo.local_path, "fetch", "--prune", "origin", repo.default_branch, timeout=60)
                self._git(repo.local_path, "checkout", "-B", repo.default_branch, f"origin/{repo.default_branch}")
                self._git(repo.local_path, "reset", "--hard", f"origin/{repo.default_branch}")
                self._git(repo.local_path, "clean", "-fd")
                self.events.put(("done", f"{repo.name} is nu exact LIVE"))
            except subprocess.CalledProcessError as exc:
                message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
                self.events.put(("error", message))
            except (OSError, subprocess.SubprocessError) as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _run_action(self, command: list[str], success: str) -> None:
        self.status_var.set("Git-actie uitvoeren...")

        def worker() -> None:
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=120, creationflags=flags)
                self.events.put(("done", result.stdout.strip() or success))
            except subprocess.CalledProcessError as exc:
                self.events.put(("error", exc.stderr.strip() or str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def open_repo(self, repo: RepoState) -> None:
        if repo.local_path.exists():
            os.startfile(repo.local_path)  # type: ignore[attr-defined]

    def open_root(self) -> None:
        root = Path(self.root_var.get())
        root.mkdir(parents=True, exist_ok=True)
        os.startfile(root)  # type: ignore[attr-defined]

    def run_bat(self, repo: RepoState, name: str) -> None:
        bat = repo.local_path / name
        if not bat.exists():
            messagebox.showerror(APP_NAME, "Dit .bat-bestand bestaat niet meer.")
            return
        subprocess.Popen(["cmd", "/c", "start", "", str(bat)], cwd=repo.local_path, shell=False)


if __name__ == "__main__":
    RepoManagerApp().mainloop()
