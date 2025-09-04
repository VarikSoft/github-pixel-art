import os
import time
import math
import random
import threading
import datetime as dt
import tkinter as tk
from urllib.parse import quote
from tkinter import filedialog, messagebox
from git import Repo
import requests

# ===== GitHub-like dark theme =====
C_BG      = "#0d1117"
C_CANVAS  = "#0d1117"
C_EMPTY   = "#161b22"
C_LV1     = "#0e4429"
C_LV2     = "#006d32"
C_LV3     = "#26a641"
C_LV4     = "#39d353"
C_TEXT    = "#c9d1d9"
C_SUBTEXT = "#8b949e"
C_ACCENT  = "#238636"
C_ACCENT_H= "#2ea043"
C_DIV     = "#30363d"

BTN_W = 26

CELL = 11
GAP  = 3
ROWS, COLS = 7, 53
LEFT_MARGIN = 36
TOP_MARGIN  = 22

# «визуальная ширина» метки месяца и минимальный зазор (в колонках)
MONTH_LABEL_COLS = 2
MONTH_LABEL_GAP  = 2

# ===== date helpers =====
def sunday_of_week(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)

def saturday_of_week(d: dt.date) -> dt.date:
    return sunday_of_week(d) + dt.timedelta(days=6)

def calc_range_current():
    today = dt.date.today()
    end = saturday_of_week(today)
    start = sunday_of_week(end) - dt.timedelta(weeks=COLS-1)
    return start, end

def calc_range_for_year(year: int):
    last_day = dt.date(year, 12, 31)
    end = saturday_of_week(last_day)
    start = sunday_of_week(end) - dt.timedelta(weeks=COLS-1)
    return start, end

def month_label_positions(start_date: dt.date, end_date: dt.date):
    """(col_index, 'Jan') — первая колонка месяца (1-е число)."""
    labels = []
    y, m = start_date.year, start_date.month
    first = dt.date(y, m, 1)
    if first < start_date:
        m += 1
        if m > 12: m = 1; y += 1
    while True:
        d = dt.date(y, m, 1)
        if d > end_date: break
        x = (d - start_date).days // 7
        if 0 <= x < COLS:
            labels.append((x, d.strftime("%b")))
        m += 1
        if m > 12: m = 1; y += 1
    return labels

# ===== small UI =====
def inputbox(root, title, prompt, initial=""):
    top = tk.Toplevel(root); top.title(title); top.configure(bg=C_BG); top.grab_set()
    top.resizable(False, False)
    tk.Label(top, text=prompt, bg=C_BG, fg=C_TEXT, justify="left", wraplength=520).pack(padx=12, pady=(12,6))
    e = tk.Entry(top, width=64, bg=C_EMPTY, fg=C_TEXT, insertbackground=C_TEXT, relief="solid", bd=1, highlightthickness=0)
    e.insert(0, initial or ""); e.pack(padx=12, pady=(0,10), fill="x"); e.focus_set()
    val = {"v": None}
    def ok(_=None): val["v"] = e.get().strip(); top.destroy()
    tk.Button(top, text="OK", command=ok, bg=C_ACCENT, fg="white",
              activebackground=C_ACCENT_H, bd=0, padx=10, pady=6).pack(pady=(0,12))
    top.bind("<Return>", ok); top.wait_window(); return val["v"]

def api_headers(token: str):
    return {"Accept":"application/vnd.github+json","Authorization":f"token {token}",
            "X-GitHub-Api-Version":"2022-11-28","User-Agent":"pixel-art-bot"}

def get_user_login_id(token: str):
    r = requests.get("https://api.github.com/user", headers=api_headers(token), timeout=15)
    r.raise_for_status(); j = r.json()
    return j["login"], j["id"]

def build_noreply_email(login: str, uid: int):
    return f"{uid}+{login}@users.noreply.github.com"

class App:
    def __init__(self, root):
        self.root = root
        root.title("GitHub Pixel Art Bot")
        root.configure(bg=C_BG)
        root.resizable(False, False)

        # state
        self.repo_path   = None
        self.remote_url  = None
        self.token       = None
        self.git_user_name  = None
        self.git_user_email = None

        self.year_mode  = tk.StringVar(value="current")
        self.year_value = tk.IntVar(value=dt.date.today().year)
        self.start_date = None
        self.end_date   = None

        # density
        self.min_commits = 1
        self.max_commits = 1
        self.use_fixed_levels = tk.BooleanVar(value=True)
        self.lv_counts = [None,
                          tk.IntVar(value=1),
                          tk.IntVar(value=3),
                          tk.IntVar(value=6),
                          tk.IntVar(value=10)]

        # safe mode
        self.safe_mode = tk.BooleanVar(value=True)
        self.batch_weeks = tk.IntVar(value=2)
        self.batch_delay = tk.IntVar(value=5)

        # brighten-on-repass
        self.brighten_repass = tk.BooleanVar(value=True)
        self.drag_brighten_active = False

        # grid: 0..4
        self.grid = [[0 for _ in range(COLS)] for _ in range(ROWS)]

        self.status_var = tk.StringVar(value="Ready.")
        self.step = 1

        # блок возврата на Step 1 после перехода дальше
        self.setup_locked = False

        # drag state
        self.painting = False
        self.paint_level = 1
        self.last_cell = None

        # layout
        self.frame = tk.Frame(root, bg=C_BG); self.frame.pack(fill="both", expand=True)
        self.status = tk.Label(root, textvariable=self.status_var, anchor="w", bg=C_BG, fg=C_SUBTEXT)
        self.status.pack(fill="x", padx=10, pady=(0,8))

        self.footer = None
        self.next_btn = None

        self.render_step1()

    # ---------- STEP 1 ----------
    def render_step1(self):
        if self.setup_locked:
            self.render_step2(); return

        self.clear_frame(); self.step = 1
        self.titlebar("Step 1 of 3 — Setup")
        self.subtitle("Choose or create a local repo, then authenticate with GitHub.\nYou can also create a PRIVATE repo via the GitHub API.")

        grid = tk.Frame(self.frame, bg=C_BG); grid.pack(fill="x", padx=12, pady=6)
        for i in range(2): grid.grid_columnconfigure(i, weight=1)

        tk.Button(grid, text="Create Local Repo…", command=self.create_local_repo, **self.btn()).grid(row=0, column=0, sticky="ew", padx=(0,6), pady=4)
        tk.Button(grid, text="Pick Local Repo…",    command=self.pick_local_repo,   **self.btn()).grid(row=0, column=1, sticky="ew", padx=(6,0), pady=4)
        tk.Button(grid, text="Enter Token / Existing URL…", command=self.set_github_info, **self.btn()).grid(row=1, column=0, sticky="ew", padx=(0,6), pady=4)
        tk.Button(grid, text="Create PRIVATE Repo via API…", command=self.create_remote_repo_private, **self.btn()).grid(row=1, column=1, sticky="ew", padx=(6,0), pady=4)
        tk.Button(grid, text="Enter Identity Manually…", command=self.set_git_identity, **self.btn()).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4,0))

        chk = tk.LabelFrame(self.frame, text="Checklist", bg=C_BG, fg=C_TEXT, bd=1, relief="solid", labelanchor="nw")
        chk.configure(highlightbackground=C_DIV); chk.pack(fill="x", padx=12, pady=(10,0))
        self.chk_repo   = tk.Label(chk, text="• Local repository: not set", bg=C_BG, fg=C_SUBTEXT)
        self.chk_remote = tk.Label(chk, text="• Remote URL (GitHub): not set", bg=C_BG, fg=C_SUBTEXT)
        self.chk_id     = tk.Label(chk, text="• Git identity: not set", bg=C_BG, fg=C_SUBTEXT)
        self.chk_repo.pack(anchor="w", padx=8, pady=(6,2))
        self.chk_remote.pack(anchor="w", padx=8, pady=2)
        self.chk_id.pack(anchor="w", padx=8, pady=(2,8))
        self.refresh_checklist()

        self.footer_nav(prev_cb=None, next_cb=self._go_step2)
        self.set_next_enabled(bool(self.repo_path and self.remote_url))

    def _go_step2(self):
        self.setup_locked = True
        self.render_step2()

    # ---------- STEP 2 ----------
    def render_step2(self):
        self.setup_locked = True
        self.clear_frame(); self.step = 2
        self.titlebar("Step 2 of 3 — Period & Identity")
        self.subtitle("Pick the 53-week window. Your Git identity is shown below (read-only on this step).")

        box = tk.LabelFrame(self.frame, text="Contribution period", bg=C_BG, fg=C_TEXT, bd=1, relief="solid", labelanchor="nw")
        box.configure(highlightbackground=C_DIV); box.pack(fill="x", padx=12, pady=(8,6))

        tk.Radiobutton(box, text="Current (last 53 weeks)", variable=self.year_mode, value="current",
                       bg=C_BG, fg=C_TEXT, selectcolor=C_BG, activebackground=C_BG)\
            .grid(row=0, column=0, sticky="w", padx=8, pady=6)
        tk.Radiobutton(box, text="Specific year:", variable=self.year_mode, value="year",
                       bg=C_BG, fg=C_TEXT, selectcolor=C_BG, activebackground=C_BG)\
            .grid(row=1, column=0, sticky="w", padx=8, pady=6)
        tk.Spinbox(box, from_=2008, to=2100, width=6, textvariable=self.year_value,
                   bg=C_EMPTY, fg=C_TEXT, insertbackground=C_TEXT, relief="solid", bd=1)\
            .grid(row=1, column=1, sticky="w", padx=(6,8))

        info = tk.LabelFrame(self.frame, text="Git identity (read-only)", bg=C_BG, fg=C_TEXT, bd=1, relief="solid", labelanchor="nw")
        info.configure(highlightbackground=C_DIV); info.pack(fill="x", padx=12, pady=(8,10))
        tk.Label(info, text=self.identity_str(), bg=C_BG, fg=C_SUBTEXT).pack(anchor="w", padx=10, pady=(6,8))

        self.footer_nav(prev_cb=None, next_cb=self.render_step3)

    # ---------- STEP 3 ----------
    def render_step3(self):
        if self.year_mode.get() == "current":
            self.start_date, self.end_date = calc_range_current()
        else:
            self.start_date, self.end_date = calc_range_for_year(self.year_value.get())

        self.clear_frame(); self.step = 3
        self.titlebar("Step 3 of 3 — Draw & Push")
        self.subtitle("LEFT paints; RIGHT erases. With 'Brighten on re-pass' ON, LMB increases level step-by-step. With it OFF, LMB paints max level.")

        width  = LEFT_MARGIN + COLS*(CELL+GAP)
        height = TOP_MARGIN  + ROWS*(CELL+GAP) + 60
        self.canvas = tk.Canvas(self.frame, width=width, height=height, bg=C_CANVAS, highlightthickness=0)
        self.canvas.pack(padx=10, pady=(6,10))
        # bindings
        self.canvas.bind("<Button-1>", self._paint_draw_start)
        self.canvas.bind("<B1-Motion>", self._paint_draw_drag)
        self.canvas.bind("<ButtonRelease-1>", self._paint_end)
        self.canvas.bind("<Button-3>", self._paint_erase_start)
        self.canvas.bind("<B3-Motion>", self._paint_erase_drag)
        self.canvas.bind("<ButtonRelease-3>", self._paint_end)

        self.draw_grid()

        ctrl_top = tk.Frame(self.frame, bg=C_BG); ctrl_top.pack(fill="x", padx=12, pady=(0,6))
        tk.Checkbutton(ctrl_top, text="Safe Mode (push in batches)",
                       variable=self.safe_mode, onvalue=True, offvalue=False,
                       bg=C_BG, fg=C_TEXT, selectcolor=C_BG, activebackground=C_BG)\
            .grid(row=0, column=0, sticky="w", padx=(0,8))
        tk.Label(ctrl_top, text="Weeks/batch:", bg=C_BG, fg=C_SUBTEXT).grid(row=0, column=1, sticky="e")
        tk.Spinbox(ctrl_top, from_=1, to=10, width=3, textvariable=self.batch_weeks,
                   bg=C_EMPTY, fg=C_TEXT, insertbackground=C_TEXT, relief="solid", bd=1)\
            .grid(row=0, column=2, sticky="w", padx=(4,12))
        tk.Label(ctrl_top, text="Delay (sec):", bg=C_BG, fg=C_SUBTEXT).grid(row=0, column=3, sticky="e")
        tk.Spinbox(ctrl_top, from_=0, to=120, width=4, textvariable=self.batch_delay,
                   bg=C_EMPTY, fg=C_TEXT, insertbackground=C_TEXT, relief="solid", bd=1)\
            .grid(row=0, column=4, sticky="w", padx=(4,18))
        tk.Checkbutton(ctrl_top, text="Brighten on re-pass (LMB)",
                       variable=self.brighten_repass, onvalue=True, offvalue=False,
                       bg=C_BG, fg=C_TEXT, selectcolor=C_BG, activebackground=C_BG)\
            .grid(row=0, column=5, sticky="w")

        dens = tk.Frame(self.frame, bg=C_BG); dens.pack(fill="x", padx=12, pady=(0,2))
        tk.Checkbutton(dens, text="Use fixed level counts",
                       variable=self.use_fixed_levels, onvalue=True, offvalue=False,
                       bg=C_BG, fg=C_TEXT, selectcolor=C_BG, activebackground=C_BG)\
            .grid(row=0, column=0, sticky="w")
        tk.Label(dens, text="L1", bg=C_BG, fg=C_SUBTEXT).grid(row=0, column=1, padx=(12,2), sticky="e")
        tk.Spinbox(dens, from_=1, to=50, width=3, textvariable=self.lv_counts[1],
                   bg=C_EMPTY, fg=C_TEXT, insertbackground=C_TEXT, relief="solid", bd=1)\
            .grid(row=0, column=2, sticky="w")
        tk.Label(dens, text="L2", bg=C_BG, fg=C_SUBTEXT).grid(row=0, column=3, padx=(12,2), sticky="e")
        tk.Spinbox(dens, from_=1, to=50, width=3, textvariable=self.lv_counts[2],
                   bg=C_EMPTY, fg=C_TEXT, insertbackground=C_TEXT, relief="solid", bd=1)\
            .grid(row=0, column=4, sticky="w")
        tk.Label(dens, text="L3", bg=C_BG, fg=C_SUBTEXT).grid(row=0, column=5, padx=(12,2), sticky="e")
        tk.Spinbox(dens, from_=1, to=50, width=3, textvariable=self.lv_counts[3],
                   bg=C_EMPTY, fg=C_TEXT, insertbackground=C_TEXT, relief="solid", bd=1)\
            .grid(row=0, column=6, sticky="w")
        tk.Label(dens, text="L4", bg=C_BG, fg=C_SUBTEXT).grid(row=0, column=7, padx=(12,2), sticky="e")
        tk.Spinbox(dens, from_=1, to=50, width=3, textvariable=self.lv_counts[4],
                   bg=C_EMPTY, fg=C_TEXT, insertbackground=C_TEXT, relief="solid", bd=1)\
            .grid(row=0, column=8, sticky="w")

        ctrl = tk.Frame(self.frame, bg=C_BG); ctrl.pack(fill="x", padx=12, pady=(2,6))
        for i in range(3): ctrl.grid_columnconfigure(i, weight=1)
        tk.Button(ctrl, text="Commit density…", command=self.set_commit_mode, **self.btn()).grid(row=0, column=0, sticky="ew", padx=(0,6), pady=4)
        tk.Button(ctrl, text="Clear", command=self.clear_grid, **self.btn()).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        tk.Button(ctrl, text="Push to GitHub", command=self.push_threaded, **self.btn(primary=True)).grid(row=0, column=2, sticky="ew", padx=(6,0), pady=4)

        self.footer_nav(prev_cb=self.render_step2, next_cb=None)

    # ---------- drawing ----------
    def draw_round_cell(self, x0, y0, fill, r=2):
        # рисуем «капсулой»: два прямоугольника + 4 овала по углам
        x1, y1 = x0 + CELL, y0 + CELL
        self.canvas.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline="")
        self.canvas.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, outline="")
        self.canvas.create_oval(x0, y0, x0 + 2*r, y0 + 2*r, fill=fill, outline=fill)
        self.canvas.create_oval(x1 - 2*r, y0, x1, y0 + 2*r, fill=fill, outline=fill)
        self.canvas.create_oval(x0, y1 - 2*r, x0 + 2*r, y1, fill=fill, outline=fill)
        self.canvas.create_oval(x1 - 2*r, y1 - 2*r, x1, y1, fill=fill, outline=fill)

    def draw_grid(self):
        self.canvas.delete("all")

        # month labels — левый край первой колонки месяца + анти-наезд
        last_end = -999
        for x, label in month_label_positions(self.start_date, self.end_date):
            if x >= last_end + MONTH_LABEL_GAP:
                self.canvas.create_text(
                    LEFT_MARGIN + x * (CELL + GAP),
                    TOP_MARGIN - 12,
                    text=label, fill=C_SUBTEXT,
                    font=("Arial", 8), anchor="w"
                )
                last_end = x + MONTH_LABEL_COLS

        # weekdays
        for y, label in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
            self.canvas.create_text(
                LEFT_MARGIN - 12,
                TOP_MARGIN + y * (CELL + GAP) + CELL // 2,
                text=label, fill=C_SUBTEXT, font=("Arial", 8), anchor="e"
            )

        # cells — КЛАССИЧЕСКИЕ квадратные
        palette = [C_EMPTY, C_LV1, C_LV2, C_LV3, C_LV4]
        for y in range(ROWS):
            for x in range(COLS):
                level = self.grid[y][x]
                fill = palette[level] if 0 <= level <= 4 else C_EMPTY
                x0 = LEFT_MARGIN + x * (CELL + GAP)
                y0 = TOP_MARGIN + y * (CELL + GAP)
                self.canvas.create_rectangle(
                    x0, y0, x0 + CELL, y0 + CELL,
                    fill=fill, outline=C_CANVAS  # outline в цвет фона, как раньше
                )

        # date range + legend
        self.canvas.create_text(
            LEFT_MARGIN + COLS * (CELL + GAP) // 2,
            TOP_MARGIN + ROWS * (CELL + GAP) + 12,
            text=f"{self.start_date:%Y-%m-%d} … {self.end_date:%Y-%m-%d}",
            fill=C_SUBTEXT, font=("Arial", 8)
        )

        lx = LEFT_MARGIN
        ly = TOP_MARGIN + ROWS * (CELL + GAP) + 30
        self.canvas.create_text(lx, ly + 6, text="Less", fill=C_SUBTEXT, font=("Arial", 8), anchor="w")
        for i, c in enumerate([C_EMPTY, C_LV1, C_LV2, C_LV3, C_LV4]):
            x0 = lx + 38 + i * (CELL + GAP)
            self.canvas.create_rectangle(x0, ly, x0 + CELL, ly + CELL, fill=c, outline=C_CANVAS)
        self.canvas.create_text(lx + 38 + 5 * (CELL + GAP) + 8, ly + 6, text="More", fill=C_SUBTEXT, font=("Arial", 8), anchor="w")

    def cell_at(self, event):
        x = (event.x - LEFT_MARGIN) // (CELL+GAP)
        y = (event.y - TOP_MARGIN)  // (CELL+GAP)
        if 0 <= x < COLS and 0 <= y < ROWS:
            return int(y), int(x)
        return None, None

    # --- LMB: brighten behavior per checkbox
    def _paint_draw_start(self, e):
        y, x = self.cell_at(e)
        if y is None: return
        if self.brighten_repass.get():
            new_level = min(4, self.grid[y][x] + 1)  # шаг к светлее
        else:
            new_level = 4  # сразу максимум
        self.grid[y][x] = new_level
        self.paint_level = new_level
        self.painting = True
        self.last_cell = (y, x)
        self.drag_brighten_active = bool(self.brighten_repass.get())
        self.draw_grid()

    def _paint_draw_drag(self, e):
        if not self.painting: return
        y, x = self.cell_at(e)
        if y is None: return
        if (y, x) != self.last_cell:
            if self.drag_brighten_active:
                self.grid[y][x] = min(4, self.grid[y][x] + 1)  # вход в ячейку — ещё светлее
            else:
                self.grid[y][x] = 4  # максимум
            self.last_cell = (y, x)
            self.draw_grid()

    # --- RMB: erase
    def _paint_erase_start(self, e):
        y, x = self.cell_at(e)
        if y is None: return
        self.grid[y][x] = 0
        self.painting = True
        self.last_cell = (y, x)
        self.draw_grid()

    def _paint_erase_drag(self, e):
        if not self.painting: return
        y, x = self.cell_at(e)
        if y is None: return
        if (y, x) != self.last_cell:
            self.grid[y][x] = 0
            self.last_cell = (y, x)
            self.draw_grid()

    def _paint_end(self, _e):
        self.painting = False
        self.last_cell = None

    def clear_grid(self):
        for y in range(ROWS):
            for x in range(COLS):
                self.grid[y][x] = 0
        self.draw_grid()

    # ---------- density dialog (optional range mode) ----------
    def set_commit_mode(self):
        txt = inputbox(self.root, "Commit density",
                       "Enter:\n1 = one commit\nN = fixed number\nM-N = range\n\n"
                       "Tip: with 'Use fixed level counts' ON, these values are ignored.")
        if not txt: return
        try:
            if "-" in txt:
                m, n = map(int, txt.split("-", 1))
                if m < 1 or n < m: raise ValueError
                self.min_commits, self.max_commits = m, n
            else:
                n = int(txt)
                if n < 1: raise ValueError
                self.min_commits = self.max_commits = n
            self.set_status(f"Commit density (range): {self.min_commits}…{self.max_commits}")
        except Exception:
            messagebox.showerror("Invalid format", "Examples: 1, 5, 2-7")

    # ---------- repo / GitHub ----------
    def create_local_repo(self):
        path = filedialog.askdirectory(title="Choose folder for new local repo")
        if not path: return
        Repo.init(path)
        self.repo_path = path
        self.refresh_checklist(); self.set_status("Local repo created.")

    def pick_local_repo(self):
        path = filedialog.askdirectory(title="Pick an existing local git repo")
        if not path: return
        if not os.path.isdir(os.path.join(path, ".git")):
            messagebox.showerror("Not a repo", "Selected folder has no .git"); return
        self.repo_path = path
        self.refresh_checklist(); self.set_status("Local repo selected.")

    def set_github_info(self):
        self.token = inputbox(self.root, "GitHub Token", "Personal Access Token (scope: repo):", self.token or "")
        self.remote_url = inputbox(self.root, "GitHub Repo URL", "HTTPS URL: https://github.com/OWNER/REPO.git", self.remote_url or "")
        if self.token and not (self.git_user_name and self.git_user_email):
            login, uid = get_user_login_id(self.token)
            self.git_user_name = login
            self.git_user_email = build_noreply_email(login, uid)
        self.refresh_checklist(); self.set_status("GitHub token & URL set.")

    def set_git_identity(self):
        name = inputbox(self.root, "Git user.name", "Name for commits (as on GitHub):", self.git_user_name or "")
        email = inputbox(self.root, "Git user.email", "Email (prefer GitHub no-reply):", self.git_user_email or "")
        if name: self.git_user_name = name
        if email: self.git_user_email = email
        self.refresh_checklist(); self.set_status(f"Identity set: {self.identity_str()}")

    def create_remote_repo_private(self):
        if not self.token:
            self.token = inputbox(self.root, "GitHub Token", "Personal Access Token (scope: repo):", self.token or "")
            if not self.token: return
        owner = inputbox(self.root, "Owner/Org (optional)", "Leave empty for your account, or enter org:", "")
        repo_name = inputbox(self.root, "Repository name", "e.g. github-pixel-art", "")
        if not repo_name:
            messagebox.showerror("Required", "Repository name is required"); return
        description = inputbox(self.root, "Description (optional)", "Short description:", "")
        try:
            headers = api_headers(self.token)
            payload = {"name": repo_name, "description": description, "private": True, "auto_init": False}
            url = f"https://api.github.com/orgs/{owner}/repos" if owner else "https://api.github.com/user/repos"
            r = requests.post(url, headers=headers, json=payload, timeout=20); r.raise_for_status()
            data = r.json()
            self.remote_url = data["clone_url"]
            if not (self.git_user_name and self.git_user_email): self.set_github_info()
            self.refresh_checklist(); self.set_status(f"Private repo created: {data['full_name']}")
            messagebox.showinfo("OK", f"Created private repo {data['full_name']}")
        except Exception as e:
            messagebox.showerror("GitHub API error", str(e))

    # ---------- push pipeline ----------
    def push_threaded(self):
        threading.Thread(target=self.make_commits_and_push, daemon=True).start()

    def sync_with_remote(self, repo, branch: str):
        try:
            remote = repo.remote("origin"); remote.fetch()
        except Exception:
            return
        remote_branches = {ref.name.split("/",1)[1] for ref in remote.refs if "/" in ref.name}
        if branch not in remote_branches:
            return
        try: repo.git.branch("--set-upstream-to", f"origin/{branch}", branch)
        except Exception: pass
        try:
            repo.git.merge("--ff-only", f"origin/{branch}"); return
        except Exception:
            pass
        try:
            repo.git.merge("--no-edit", "--allow-unrelated-histories", f"origin/{branch}")
        except Exception:
            try: repo.git.rebase(f"origin/{branch}")
            except Exception: pass

    def commits_for_level(self, level: int) -> int:
        if level <= 0: return 0
        if self.use_fixed_levels.get():
            return max(1, int(self.lv_counts[level].get()))
        lo, hi = self.min_commits, self.max_commits
        if hi < lo: hi = lo
        if lo == hi: return lo
        span = hi - lo
        b0 = lo
        b1 = lo + math.ceil(span*1/4)
        b2 = lo + math.ceil(span*2/4)
        b3 = lo + math.ceil(span*3/4)
        b4 = hi
        lows  = [b0, b1, b2, b3]
        highs = [b1, b2, b3, b4]
        l = max(lows[level-1], lo)
        h = max(l, highs[level-1])
        return random.randint(l, h)

    def make_commits_for_columns(self, repo: Repo, x_columns, total_days_counter):
        for x in x_columns:
            for y in range(ROWS):
                level = self.grid[y][x]
                if level > 0:
                    day = self.start_date + dt.timedelta(weeks=x, days=y)
                    count = self.commits_for_level(level)
                    for _ in range(count):
                        env = os.environ.copy()
                        env["GIT_AUTHOR_NAME"] = self.git_user_name or "author"
                        env["GIT_AUTHOR_EMAIL"] = self.git_user_email or "author@users.noreply.github.com"
                        env["GIT_COMMITTER_NAME"] = env["GIT_AUTHOR_NAME"]
                        env["GIT_COMMITTER_EMAIL"] = env["GIT_AUTHOR_EMAIL"]
                        iso = day.strftime("%Y-%m-%dT12:00:00+00:00")
                        env["GIT_AUTHOR_DATE"] = iso; env["GIT_COMMITTER_DATE"] = iso
                        with open("pixels.txt", "a", encoding="utf-8") as f: f.write(f"{iso}\n")
                        repo.git.add("pixels.txt"); repo.git.commit("-m", f"Pixel {x},{y}", env=env)
                    total_days_counter["done"] += 1
                    self.set_status(f"Committing days: {total_days_counter['done']}/{total_days_counter['total']}…")

    def make_commits_and_push(self):
        try:
            self.disable_ui(True); self.set_status("Preparing repository…")

            if not (self.git_user_name and self.git_user_email):
                messagebox.showwarning("Identity","Git identity is not set. Your contributions may not count.\nUse 'Enter identity manually' on Step 1.")

            repo = Repo(self.repo_path); os.chdir(self.repo_path)

            # identity + silence credential helper
            try:
                with repo.config_writer() as cw:
                    cw.set_value("user","name", self.git_user_name or "author")
                    cw.set_value("user","email", self.git_user_email or "author@users.noreply.github.com")
                    cw.set_value("credential","helper","")
            except Exception:
                repo.git.config("user.name", self.git_user_name or "author")
                repo.git.config("user.email", self.git_user_email or "author@users.noreply.github.com")
                try: repo.git.config("credential.helper","")
                except Exception: pass

            # origin with token
            auth_url = self.auth_url(self.remote_url, self.token)
            if "origin" not in [r.name for r in repo.remotes]:
                repo.create_remote("origin", auth_url)
            else:
                try: repo.remote("origin").set_url(auth_url)
                except Exception: repo.git.remote("set-url","origin", auth_url)

            # initial commit
            if not repo.head.is_valid():
                with open("pixels.txt","w",encoding="utf-8") as f: f.write("init\n")
                repo.git.add("pixels.txt"); repo.git.commit("-m","init")

            active_cols = [x for x in range(COLS) if any(self.grid[y][x] > 0 for y in range(ROWS))]
            total_days = sum(1 for x in active_cols for y in range(ROWS) if self.grid[y][x] > 0)
            if total_days == 0:
                self.set_status("Nothing selected."); return
            counter = {"done":0,"total":total_days}

            try: branch = repo.active_branch.name
            except Exception:
                repo.git.checkout("-b","main"); branch = "main"
            if branch == "master":
                try: repo.git.branch("-M","main"); branch = "main"
                except Exception: pass

            self.sync_with_remote(repo, branch)

            if self.safe_mode.get():
                n = max(1, int(self.batch_weeks.get()))
                batches = [active_cols[i:i+n] for i in range(0, len(active_cols), n)]
                first_push = True
                for idx, cols in enumerate(batches, start=1):
                    self.set_status(f"Batch {idx}/{len(batches)}: weeks {cols[0]}…{cols[-1]}")
                    self.make_commits_for_columns(repo, cols, counter)
                    try:
                        if first_push: repo.git.push("-u","origin",branch); first_push = False
                        else:          repo.git.push("origin",branch)
                    except Exception as e:
                        if messagebox.askyesno("Push issue","Remote ahead. Force-with-lease?"):
                            repo.git.push("--force-with-lease","origin",branch)
                        else:
                            raise e
                    delay = max(0, int(self.batch_delay.get()))
                    if idx < len(batches) and delay > 0:
                        self.set_status(f"Pushed batch {idx}. Cooling down {delay}s…")
                        time.sleep(delay)
            else:
                self.set_status("Creating commits…")
                self.make_commits_for_columns(repo, active_cols, counter)
                self.set_status("Pushing…")
                try:
                    repo.git.push("-u","origin",branch)
                except Exception as e:
                    if messagebox.askyesno("Push issue","Remote ahead. Force-with-lease?"):
                        repo.git.push("--force-with-lease","origin",branch)
                    else:
                        raise e

            self.set_status("Done! Commits pushed.")
            messagebox.showinfo("Almost there",
                "Commits pushed.\nProfile → Contribution settings: enable “Include private contributions”.")
        except Exception as e:
            self.set_status(f"Error: {e}")
            messagebox.showerror("Error", str(e))
        finally:
            self.disable_ui(False)

    # ---------- misc ----------
    def identity_str(self):
        n = self.git_user_name or "(not set)"
        e = self.git_user_email or "(not set)"
        return f"Current: {n} <{e}>"

    def refresh_checklist(self):
        if hasattr(self, "chk_repo"):
            self.chk_repo.config(text=f"• Local repository: {'OK' if self.repo_path else 'not set'}",
                                 fg=C_TEXT if self.repo_path else C_SUBTEXT)
        if hasattr(self, "chk_remote"):
            self.chk_remote.config(text=f"• Remote URL (GitHub): {'OK' if self.remote_url else 'not set'}",
                                   fg=C_TEXT if self.remote_url else C_SUBTEXT)
        if hasattr(self, "chk_id"):
            have_id = bool(self.git_user_name and self.git_user_email)
            self.chk_id.config(text=f"• Git identity: {'OK' if have_id else 'not set'}",
                               fg=C_TEXT if have_id else C_SUBTEXT)
        if self.step == 1:
            self.set_next_enabled(bool(self.repo_path and self.remote_url))
            self.root.update_idletasks()

    @staticmethod
    def auth_url(url: str, token: str) -> str:
        if url and url.startswith("https://") and token:
            return url.replace("https://", f"https://x-access-token:{quote(token, safe='')}@")
        return url

    def set_status(self, text: str):
        self.status_var.set(text); self.root.update_idletasks()

    def clear_frame(self):
        for w in getattr(self, "frame", []).winfo_children(): w.destroy()

    def titlebar(self, text):
        tk.Label(self.frame, text=text, bg=C_BG, fg=C_TEXT, font=("Arial", 14, "bold")).pack(anchor="w", padx=12, pady=(10,2))
        tk.Frame(self.frame, height=1, bg=C_DIV).pack(fill="x", padx=12, pady=(0,8))

    def subtitle(self, text):
        tk.Label(self.frame, text=text, bg=C_BG, fg=C_SUBTEXT, justify="left", wraplength=820)\
            .pack(anchor="w", padx=12, pady=(0,8))

    def btn(self, primary=False):
        base = dict(bg=C_EMPTY, fg=C_TEXT, activebackground="#21262d", bd=0, padx=10, pady=8, width=BTN_W)
        if primary: base.update(bg=C_ACCENT, fg="white", activebackground=C_ACCENT_H)
        return base

    def footer_nav(self, prev_cb=None, next_cb=None):
        if self.footer is not None:
            self.footer.destroy()
        self.footer = tk.Frame(self.frame, bg=C_BG)
        self.footer.pack(fill="x", pady=(10,6), padx=12)

        if prev_cb:
            tk.Button(self.footer, text="← Back", command=prev_cb, **self.btn()).pack(side="left")
        else:
            tk.Label(self.footer, text="", bg=C_BG).pack(side="left")

        tk.Label(self.footer, text=f"Step {self.step}/3", bg=C_BG, fg=C_SUBTEXT).pack(side="left", padx=10)

        self.next_btn = tk.Button(self.footer, text="Next →",
                                  command=(next_cb if next_cb else (lambda: None)),
                                  **self.btn(primary=True))
        if next_cb is None:
            self.next_btn.configure(state="disabled", bg="#1f6f3c")
        self.next_btn.pack(side="right")

    def set_next_enabled(self, enabled: bool):
        if getattr(self, "next_btn", None):
            self.next_btn.configure(state=("normal" if enabled else "disabled"),
                                    bg=(C_ACCENT if enabled else "#1f6f3c"))

    def disable_ui(self, flag: bool):
        for w in self.root.winfo_children():
            try: w.configure(state=("disabled" if flag else "normal"))
            except tk.TclError: pass

# ---- run ----
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()