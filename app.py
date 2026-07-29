from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk
import keyring
import requests

APP_NAME = "Repo Manager"
DEFAULT_ROOT = Path(r"C:\Users\Hesse\Desktop\Codex")
CONFIG_DIR = Path(os.getenv("APPDATA", Path.home())) / "RepoManager"
CONFIG_FILE = CONFIG_DIR / "config.json"
GITHUB_API = "https://api.github.com"

COLORS = {
    "bg": "#F5F7FF",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFF",
    "text": "#101938",
    "muted": "#7180A2",
    "border": "#E2E7F2",
    "blue": "#4A67FF",
    "purple": "#8D49F7",
    "blue_hover": "#3B57EC",
    "soft_blue": "#EEF2FF",
    "live": "#27B768",
    "live_bg": "#E9F9EF",
    "outdated": "#F59A23",
    "outdated_bg": "#FFF3E2",
    "local": "#74819A",
    "local_bg": "#EEF1F6",
    "danger": "#E95E68",
    "danger_bg": "#FDECEF",
    "check": "#B47A17",
    "check_bg": "#FFF5DA",
}


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


class RepoManagerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.title(APP_NAME)
        self.geometry("1180x780")
        self.minsize(920, 620)
        self.configure(fg_color=COLORS["bg"])

        self.store = ConfigStore()
        self.client: GitHubClient | None = None
        self.repos: list[RepoState] = []
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        self.root_var = ctk.StringVar(value=self.store.data["root_folder"])
        self.status_var = ctk.StringVar(value="GitHub nog niet geladen")
        self.search_var = ctk.StringVar()
        self.only_favorites = ctk.BooleanVar(value=True)

        self._build_ui()
        self.after(150, self._poll_events)

        if keyring.get_password(APP_NAME, "github_token"):
            self.after(300, self.refresh)
        else:
            self.after(300, self.show_login)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=34, pady=(28, 12))
        header.grid_columnconfigure(1, weight=1)

        logo = ctk.CTkFrame(header, width=68, height=68, corner_radius=20, fg_color="#EDEBFF")
        logo.grid(row=0, column=0, rowspan=2, sticky="w")
        logo.grid_propagate(False)
        ctk.CTkLabel(
            logo,
            text="◈",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color=COLORS["purple"],
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            header,
            text=APP_NAME,
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color=COLORS["text"],
        ).grid(row=0, column=1, sticky="sw", padx=(18, 0))

        ctk.CTkLabel(
            header,
            textvariable=self.root_var,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["muted"],
        ).grid(row=1, column=1, sticky="nw", padx=(18, 0), pady=(2, 0))

        self.login_button = ctk.CTkButton(
            header,
            text="GitHub login",
            width=180,
            height=44,
            corner_radius=22,
            fg_color=COLORS["surface"],
            hover_color=COLORS["soft_blue"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.show_login,
        )
        self.login_button.grid(row=0, column=2, rowspan=2, sticky="e")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=34, pady=(8, 16))
        toolbar.grid_columnconfigure(3, weight=1)

        self.favorite_button = ctk.CTkButton(
            toolbar,
            text="★  Favorieten",
            width=140,
            height=44,
            corner_radius=14,
            fg_color=COLORS["surface"],
            hover_color=COLORS["soft_blue"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            command=self.toggle_favorites_filter,
        )
        self.favorite_button.grid(row=0, column=0, padx=(0, 10))

        self.refresh_button = ctk.CTkButton(
            toolbar,
            text="↻  GitHub vernieuwen",
            width=178,
            height=44,
            corner_radius=14,
            fg_color=COLORS["blue"],
            hover_color=COLORS["blue_hover"],
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.refresh,
        )
        self.refresh_button.grid(row=0, column=1, padx=(0, 10))

        ctk.CTkButton(
            toolbar,
            text="▣  Map openen",
            width=140,
            height=44,
            corner_radius=14,
            fg_color=COLORS["surface"],
            hover_color=COLORS["soft_blue"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            command=self.open_root,
        ).grid(row=0, column=2)

        search = ctk.CTkEntry(
            toolbar,
            textvariable=self.search_var,
            placeholder_text="Zoeken in repositories...",
            width=280,
            height=44,
            corner_radius=14,
            fg_color=COLORS["surface"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            placeholder_text_color="#9AA6BF",
        )
        search.grid(row=0, column=4, sticky="e")
        self.search_var.trace_add("write", lambda *_: self.render_cards())

        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color="#C9D1E5",
            scrollbar_button_hover_color="#AAB6D2",
        )
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=26, pady=(0, 8))
        self.scroll.grid_columnconfigure((0, 1), weight=1, uniform="cards")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=34, pady=(2, 20))
        ctk.CTkLabel(
            footer,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["muted"],
        ).pack(side="left")

        self._refresh_filter_button()

    def toggle_favorites_filter(self) -> None:
        self.only_favorites.set(not self.only_favorites.get())
        self._refresh_filter_button()
        self.render_cards()

    def _refresh_filter_button(self) -> None:
        active = self.only_favorites.get()
        self.favorite_button.configure(
            fg_color=COLORS["soft_blue"] if active else COLORS["surface"],
            border_color="#BFC9FF" if active else COLORS["border"],
            text_color=COLORS["blue"] if active else COLORS["text"],
            text="★  Favorieten" if active else "☆  Alles tonen",
        )

    def show_login(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("GitHub verbinden")
        dialog.geometry("520x300")
        dialog.resizable(False, False)
        dialog.configure(fg_color=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()

        card = ctk.CTkFrame(
            dialog,
            corner_radius=24,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            card,
            text="GitHub verbinden",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=24, pady=(24, 4))
        ctk.CTkLabel(
            card,
            text="Gebruik een fine-grained token met toegang tot je repositories.",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["muted"],
        ).pack(anchor="w", padx=24)

        token_var = ctk.StringVar(value=keyring.get_password(APP_NAME, "github_token") or "")
        token_entry = ctk.CTkEntry(
            card,
            textvariable=token_var,
            show="•",
            height=42,
            corner_radius=12,
            fg_color=COLORS["surface_alt"],
            border_color=COLORS["border"],
        )
        token_entry.pack(fill="x", padx=24, pady=(18, 10))
        ctk.CTkEntry(
            card,
            textvariable=self.root_var,
            height=42,
            corner_radius=12,
            fg_color=COLORS["surface_alt"],
            border_color=COLORS["border"],
        ).pack(fill="x", padx=24)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=20)
        ctk.CTkButton(
            row,
            text="Token maken",
            width=120,
            height=40,
            corner_radius=12,
            fg_color=COLORS["surface_alt"],
            hover_color=COLORS["soft_blue"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            command=lambda: webbrowser.open("https://github.com/settings/personal-access-tokens/new"),
        ).pack(side="left")

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

        ctk.CTkButton(
            row,
            text="Verbinden",
            width=120,
            height=40,
            corner_radius=12,
            fg_color=COLORS["blue"],
            hover_color=COLORS["blue_hover"],
            command=connect,
        ).pack(side="right")
        token_entry.focus_set()

    def refresh(self) -> None:
        token = (keyring.get_password(APP_NAME, "github_token") or "").strip()
        if not token:
            self.show_login()
            return
        self.status_var.set("GitHub en lokale mappen controleren...")
        self.refresh_button.configure(state="disabled", text="Controleren...")
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
            html_url=repo["html_url"],
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
                    self.login_button.configure(text=f"●  {username}")
                    if not self.store.data.get("favorites") and self.repos:
                        first = [repo.full_name for repo in self.repos[:3]]
                        self.store.data["favorites"] = first
                        self.store.save()
                        for repo in self.repos:
                            repo.favorite = repo.full_name in first
                    outdated = sum(repo.state == "OUTDATED" for repo in self.repos)
                    self.status_var.set(f"{len(self.repos)} repositories gecontroleerd  •  {outdated} outdated")
                    self.refresh_button.configure(state="normal", text="↻  GitHub vernieuwen")
                    self.render_cards()
                elif event == "done":
                    self.status_var.set(payload)
                    self.refresh_button.configure(state="normal", text="↻  GitHub vernieuwen")
                    self.refresh()
                elif event == "error":
                    self.status_var.set("Actie mislukt")
                    self.refresh_button.configure(state="normal", text="↻  GitHub vernieuwen")
                    messagebox.showerror(APP_NAME, payload, parent=self)
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def render_cards(self) -> None:
        for child in self.scroll.winfo_children():
            child.destroy()

        query = self.search_var.get().strip().lower()
        visible = [
            repo
            for repo in self.repos
            if (not self.only_favorites.get() or repo.favorite)
            and (not query or query in repo.name.lower())
        ]

        if not visible:
            ctk.CTkLabel(
                self.scroll,
                text="Geen repositories zichtbaar.",
                font=ctk.CTkFont(size=14),
                text_color=COLORS["muted"],
            ).grid(row=0, column=0, padx=20, pady=40, sticky="w")
            return

        for index, repo in enumerate(visible):
            row, column = divmod(index, 2)
            self._card(repo).grid(row=row, column=column, padx=10, pady=10, sticky="nsew")

    def _status_style(self, state: str) -> tuple[str, str]:
        return {
            "LIVE": (COLORS["live"], COLORS["live_bg"]),
            "OUTDATED": (COLORS["outdated"], COLORS["outdated_bg"]),
            "LOCAL": (COLORS["local"], COLORS["local_bg"]),
            "NIET LOKAAL": (COLORS["danger"], COLORS["danger_bg"]),
            "CHECK": (COLORS["check"], COLORS["check_bg"]),
        }.get(state, (COLORS["local"], COLORS["local_bg"]))

    def _card(self, repo: RepoState) -> ctk.CTkFrame:
        tint = {
            "LIVE": "#F7FFF9",
            "OUTDATED": "#FFFBF3",
            "LOCAL": "#FBFCFF",
            "NIET LOKAAL": "#FFF8FA",
            "CHECK": "#FFFCF3",
        }.get(repo.state, COLORS["surface"])

        card = ctk.CTkFrame(
            self.scroll,
            corner_radius=22,
            fg_color=tint,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 0))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top,
            text=repo.name,
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color=COLORS["text"],
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            top,
            text="×" if repo.favorite else "+",
            width=42,
            height=36,
            corner_radius=12,
            fg_color=COLORS["soft_blue"] if repo.favorite else COLORS["surface"],
            hover_color="#E4E9FF",
            border_width=1,
            border_color="#C8D0FF" if repo.favorite else COLORS["border"],
            text_color=COLORS["blue"],
            font=ctk.CTkFont(size=18, weight="bold"),
            command=lambda: self.toggle_favorite(repo),
        ).grid(row=0, column=1)

        status_color, status_bg = self._status_style(repo.state)
        badge = ctk.CTkFrame(card, corner_radius=10, fg_color=status_bg)
        badge.grid(row=1, column=0, sticky="w", padx=22, pady=(18, 0))
        ctk.CTkLabel(
            badge,
            text=f"●  {repo.state}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=status_color,
        ).pack(padx=12, pady=6)

        ctk.CTkLabel(
            card,
            text=repo.detail,
            font=ctk.CTkFont(size=13),
            text_color="#45516E",
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=22, pady=(12, 0))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=22, pady=(22, 20))
        actions.grid_columnconfigure(2, weight=1)

        if not repo.local_exists:
            ctk.CTkButton(
                actions,
                text="Klonen",
                width=110,
                height=42,
                corner_radius=12,
                fg_color=COLORS["blue"],
                hover_color=COLORS["blue_hover"],
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda: self.clone_repo(repo),
            ).grid(row=0, column=0, padx=(0, 8))
        elif repo.state != "LIVE":
            ctk.CTkButton(
                actions,
                text="Maak LIVE",
                width=118,
                height=42,
                corner_radius=12,
                fg_color=COLORS["blue"],
                hover_color=COLORS["blue_hover"],
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda: self.make_live(repo),
            ).grid(row=0, column=0, padx=(0, 8))
        else:
            ctk.CTkButton(
                actions,
                text="▣  Openen",
                width=118,
                height=42,
                corner_radius=12,
                fg_color=COLORS["surface"],
                hover_color=COLORS["soft_blue"],
                border_width=1,
                border_color=COLORS["border"],
                text_color=COLORS["text"],
                command=lambda: self.open_repo(repo),
            ).grid(row=0, column=0, padx=(0, 8))

        bat_names = [path.name for path in repo.bat_files]
        selected = ctk.StringVar(value=bat_names[0] if bat_names else "Geen .bat")

        if bat_names:
            ctk.CTkButton(
                actions,
                text="▷  Start",
                width=104,
                height=42,
                corner_radius=12,
                fg_color=COLORS["purple"],
                hover_color="#7C3BE7",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda: self.run_bat(repo, selected.get()),
            ).grid(row=0, column=1, padx=(0, 8))

        menu = ctk.CTkOptionMenu(
            actions,
            variable=selected,
            values=bat_names or ["Geen .bat"],
            width=190,
            height=42,
            corner_radius=12,
            fg_color=COLORS["surface"],
            button_color="#EEF1FF",
            button_hover_color="#E2E7FF",
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["soft_blue"],
            text_color=COLORS["text"],
            dropdown_text_color=COLORS["text"],
            font=ctk.CTkFont(size=12),
            dropdown_font=ctk.CTkFont(size=12),
        )
        menu.grid(row=0, column=3, sticky="e")
        if not bat_names:
            menu.configure(state="disabled")

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
            ["git", "clone", repo.clone_url, str(repo.local_path)],
            f"{repo.name} gekloond",
        )

    def make_live(self, repo: RepoState) -> None:
        answer = messagebox.askyesno(
            APP_NAME,
            f"Lokale wijzigingen in '{repo.name}' worden verwijderd en GitHub wordt leidend. Doorgaan?",
            parent=self,
        )
        if not answer:
            return

        command = [
            "cmd",
            "/c",
            "&&".join(
                [
                    f'git -C "{repo.local_path}" fetch --prune origin {repo.default_branch}',
                    f'git -C "{repo.local_path}" checkout -B {repo.default_branch} origin/{repo.default_branch}',
                    f'git -C "{repo.local_path}" reset --hard origin/{repo.default_branch}',
                    f'git -C "{repo.local_path}" clean -fd',
                ]
            ),
        ]
        self._run_action(command, f"{repo.name} is LIVE")

    def _run_action(self, command: list[str], success: str) -> None:
        self.status_var.set("Git-actie uitvoeren...")

        def worker() -> None:
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                result = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    creationflags=flags,
                )
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
        subprocess.Popen(
            ["cmd", "/c", "start", "", str(bat)],
            cwd=repo.local_path,
            shell=False,
        )


if __name__ == "__main__":
    RepoManagerApp().mainloop()
