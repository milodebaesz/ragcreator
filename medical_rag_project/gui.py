"""
RAGCreator GUI

Three tabs:
  1. Pipeline  — project management, PDF selection, run steps 1-5, live log
  2. Results   — browse, edit, and delete recommendation chunks
  3. Test      — keyword search through recommendations

Projects are stored as sub-folders of data/.
The active project is remembered across sessions in rag_config.json.
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

PROJECT_ROOT = Path(__file__).parent

# Load .env from project root into os.environ (won't overwrite existing vars)
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=False)
    except ImportError:
        # Fallback: simple manual parser
        for _line in _env_file.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
SCRIPTS_DIR  = PROJECT_ROOT / "scripts"
BASE_DATA    = PROJECT_ROOT / "data"
CONFIG_FILE  = PROJECT_ROOT / "rag_config.json"

STEPS = [
    ("1. PDF → Markdown",          "1_pdf_to_markdown.py"),
    ("2. Extract Recommendations", "2_extract_guideline_structure.py"),
    ("3. Generate Embeddings",     "4_embed_and_store.py"),
    ("4. Upload to MongoDB",       "5_upload_to_mongodb.py"),
]

REC_CLASSES     = ["Class I", "Class IIa", "Class IIb", "Class III", "Class IV"]
EVIDENCE_LEVELS = ["A", "B", "C", "NR"]

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
C = {
    "bg":       "#F1F5F9",   # main window background
    "card":     "#FFFFFF",   # panel / card background
    "border":   "#E2E8F0",   # subtle border
    "accent":   "#4472BE",   # primary blue (muted professional)
    "accent_h": "#3663B0",   # hover blue
    "danger":   "#EF4444",   # delete red
    "success":  "#10B981",   # save green
    "sec_bg":   "#1E3A5F",   # section header background (dark navy)
    "sec_fg":   "#F8FAFC",   # section header text
    "row_alt":  "#F8FAFC",   # alternating row
    "sel_bg":   "#DBEAFE",   # selection highlight
    "sel_fg":   "#1E40AF",   # selection text
    "txt":      "#0F172A",   # primary text
    "muted":    "#64748B",   # secondary / muted text
    "bar_bg":   "#0F172A",   # project bar background (deep slate)
    "bar_fg":   "#E2E8F0",   # project bar text
}

_MACOS = sys.platform == "darwin"
_WIN   = sys.platform == "win32"
FONT  = ("Helvetica Neue", 13) if _MACOS else ("Segoe UI", 11) if _WIN else ("Helvetica", 12)
FONTS = ("Helvetica Neue", 12) if _MACOS else ("Segoe UI", 10) if _WIN else ("Helvetica", 11)
FONTB = ("Helvetica Neue", 13, "bold") if _MACOS else ("Segoe UI", 11, "bold") if _WIN else ("Helvetica", 12, "bold")
FONTM = ("Menlo", 12) if _MACOS else ("Consolas", 11)


def setup_style():
    s = ttk.Style()
    s.theme_use("clam")

    s.configure(".",
                 background=C["bg"], foreground=C["txt"],
                 font=FONT, bordercolor=C["border"], troughcolor=C["bg"])

    # Frames
    s.configure("TFrame",      background=C["bg"])
    s.configure("Card.TFrame", background=C["card"])
    s.configure("TLabelframe", background=C["bg"], bordercolor=C["border"], relief="solid")
    s.configure("TLabelframe.Label", background=C["bg"], foreground=C["accent"], font=FONTB)

    # Notebook
    s.configure("TNotebook",     background=C["bg"], borderwidth=0, tabmargins=0)
    s.configure("TNotebook.Tab", background=C["border"], foreground=C["muted"],
                padding=(22, 10), font=FONT)
    s.map("TNotebook.Tab",
          background=[("selected", C["card"]), ("active", "#E2E8F0")],
          foreground=[("selected", C["accent"]), ("active", C["txt"])],
          expand=[("selected", [1, 1, 1, 0])])

    # Buttons
    s.configure("TButton",
                background=C["card"], foreground=C["txt"],
                padding=(10, 5), relief="flat", borderwidth=1,
                bordercolor=C["border"], font=FONTS)
    s.map("TButton",
          background=[("active", "#E2E8F0"), ("pressed", C["border"])],
          relief=[("pressed", "flat")])

    # Primary button (blue)
    s.configure("Primary.TButton",
                background=C["accent"], foreground="#FFFFFF",
                padding=(12, 6), relief="flat", font=FONTS, borderwidth=0)
    s.map("Primary.TButton",
          background=[("active", C["accent_h"]), ("pressed", C["accent_h"])],
          foreground=[("active", "#FFFFFF")])

    # Danger button (red)
    s.configure("Danger.TButton",
                background="#FEE2E2", foreground=C["danger"],
                padding=(10, 5), relief="flat", font=FONTS, borderwidth=1,
                bordercolor="#FECACA")
    s.map("Danger.TButton",
          background=[("active", "#FECACA")])

    # Entry / Combobox
    s.configure("TEntry",
                fieldbackground=C["card"], foreground=C["txt"],
                bordercolor=C["border"], insertcolor=C["accent"],
                padding=(6, 4))
    s.map("TEntry", bordercolor=[("focus", C["accent"])])
    s.configure("TCombobox",
                fieldbackground=C["card"], foreground=C["txt"],
                bordercolor=C["border"], arrowcolor=C["muted"], padding=(4, 4))
    s.map("TCombobox", fieldbackground=[("readonly", C["card"])])

    # Scrollbar
    s.configure("TScrollbar",
                background=C["bg"], troughcolor=C["bg"],
                arrowcolor=C["muted"], bordercolor=C["bg"])

    # Treeview
    s.configure("Treeview",
                background=C["card"], fieldbackground=C["card"],
                foreground=C["txt"], rowheight=28,
                bordercolor=C["border"], relief="flat", font=FONTS)
    s.configure("Treeview.Heading",
                background=C["bg"], foreground=C["muted"],
                relief="flat", font=FONTS, padding=(4, 4))
    s.map("Treeview.Heading", background=[("active", C["border"])])
    s.map("Treeview",
          background=[("selected", C["sel_bg"])],
          foreground=[("selected", C["sel_fg"])])

    # Separator
    s.configure("TSeparator", background=C["border"])

    # Progressbar
    s.configure("TProgressbar", troughcolor=C["border"], background=C["accent"])

    return s


# ---------------------------------------------------------------------------
# Config / project helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"active": "default", "projects": ["default"], "project_meta": {}}


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def get_data_dir(project: str) -> Path:
    """Each project lives in data/<project>/  (default project → data/default/)."""
    d = BASE_DATA / project
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_files(project: str) -> dict[int, Path]:
    d = get_data_dir(project)
    return {
        1: d / "guideline.md",
        2: d / "rag_chunks.json",
        3: d / "embeddings.json",
    }


def load_json(path: Path) -> list | None:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_json(path: Path, data: list) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# New-project dialog (name + guideline year)
# ---------------------------------------------------------------------------

def _ask_new_project(parent) -> tuple[str, str] | None:
    """Modal dialog asking for project name and guideline year.
    Returns (name, year) or None if cancelled."""
    dlg = tk.Toplevel(parent)
    dlg.title("New Guideline Project")
    dlg.resizable(False, False)
    dlg.grab_set()

    ttk.Label(dlg, text="Project name:", width=16).grid(row=0, column=0, padx=12, pady=(14, 4), sticky="w")
    name_var = tk.StringVar()
    ttk.Entry(dlg, textvariable=name_var, width=28).grid(row=0, column=1, padx=(0, 12), pady=(14, 4))

    ttk.Label(dlg, text="Guideline year:", width=16).grid(row=1, column=0, padx=12, pady=4, sticky="w")
    year_var = tk.StringVar()
    ttk.Entry(dlg, textvariable=year_var, width=28).grid(row=1, column=1, padx=(0, 12), pady=4)

    result: list[tuple | None] = [None]

    def _ok():
        name = name_var.get().strip().replace(" ", "_")
        year = year_var.get().strip()
        if not name:
            messagebox.showwarning("Invalid", "Project name cannot be empty.", parent=dlg)
            return
        result[0] = (name, year)
        dlg.destroy()

    def _cancel():
        dlg.destroy()

    btn_row = ttk.Frame(dlg)
    btn_row.grid(row=2, column=0, columnspan=2, pady=(8, 12))
    ttk.Button(btn_row, text="Create", command=_ok, style="Primary.TButton").pack(side="left", padx=6)
    ttk.Button(btn_row, text="Cancel", command=_cancel).pack(side="left", padx=6)

    dlg.bind("<Return>", lambda _: _ok())
    dlg.bind("<Escape>", lambda _: _cancel())
    parent.wait_window(dlg)
    return result[0]


# ---------------------------------------------------------------------------
# Project bar — shared across the whole window
# ---------------------------------------------------------------------------

class ProjectBar(tk.Frame):
    def __init__(self, parent, cfg: dict, on_change):
        super().__init__(parent, background=C["bar_bg"], pady=8, padx=12)
        self._cfg = cfg
        self._on_change = on_change

        tk.Label(self, text="RAGCreator", background=C["bar_bg"],
                 foreground="#FFFFFF", font=FONTB).pack(side="left")
        tk.Label(self, text="  |  ", background=C["bar_bg"],
                 foreground="#475569").pack(side="left")
        tk.Label(self, text="Guideline project:", background=C["bar_bg"],
                 foreground=C["bar_fg"], font=FONTS).pack(side="left")

        self._var = tk.StringVar(value=cfg["active"])
        self._cb = ttk.Combobox(self, textvariable=self._var,
                                values=cfg["projects"], width=26, state="readonly",
                                font=FONTS)
        self._cb.pack(side="left", padx=(8, 12))
        self._cb.bind("<<ComboboxSelected>>", self._select)

        ttk.Button(self, text="+ New",  command=self._new,
                   style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(self, text="Delete", command=self._delete).pack(side="left")

        self._path_var = tk.StringVar()
        tk.Label(self, textvariable=self._path_var,
                 background=C["bar_bg"], foreground="#94A3B8",
                 font=("Helvetica", 10)).pack(side="left", padx=(16, 0))
        self._refresh_path()

    def _refresh_path(self):
        self._path_var.set(f"  {get_data_dir(self._var.get())}")

    def _select(self, _=None):
        name = self._var.get()
        self._cfg["active"] = name
        save_config(self._cfg)
        self._refresh_path()
        self._on_change(name)

    def _new(self):
        result = _ask_new_project(self)
        if not result:
            return
        name, year = result
        if name not in self._cfg["projects"]:
            self._cfg["projects"].append(name)
        self._cfg["active"] = name
        self._cfg.setdefault("project_meta", {})[name] = {"year": year}
        self._cb["values"] = self._cfg["projects"]
        self._var.set(name)
        save_config(self._cfg)
        get_data_dir(name)
        self._refresh_path()
        self._on_change(name)

    def _delete(self):
        name = self._var.get()
        if name == "default":
            messagebox.showwarning("Cannot delete",
                                   "The 'default' project cannot be deleted.")
            return
        data_dir = get_data_dir(name)
        has_files = data_dir.exists() and any(data_dir.iterdir())
        detail = f"\nThis will also delete all files in:\n{data_dir}" if has_files else ""
        if not messagebox.askyesno(
            "Delete project",
            f"Permanently delete project '{name}'?{detail}",
            icon="warning",
            parent=self,
        ):
            return
        if data_dir.exists():
            shutil.rmtree(data_dir)
        self._cfg["projects"].remove(name)
        self._cfg["active"] = "default"
        self._cb["values"] = self._cfg["projects"]
        self._var.set("default")
        save_config(self._cfg)
        self._refresh_path()
        self._on_change("default")

    @property
    def active(self) -> str:
        return self._var.get()


# ---------------------------------------------------------------------------
# Pipeline Tab
# ---------------------------------------------------------------------------

class PipelineTab(ttk.Frame):
    def __init__(self, parent, get_project, on_step_done, get_config=None):
        super().__init__(parent, padding=10)
        self._get_project = get_project
        self._get_config = get_config or (lambda: {})
        self.on_step_done = on_step_done
        self.pdf_path  = tk.StringVar()
        self.api_key   = tk.StringVar(value=os.getenv("OPENAI_API_KEY", ""))
        self.mongo_uri  = tk.StringVar(value=os.getenv("MONGODB_URI", ""))
        self.mongo_db   = tk.StringVar(value=os.getenv("MONGODB_DB", "rag_db"))
        self.mongo_coll = tk.StringVar(value=os.getenv("MONGODB_COLL", "rag_chunks"))
        self._running = False
        self._log_queue: queue.Queue = queue.Queue()
        self._build_ui()
        self._poll_log()

    def _build_ui(self):
        # PDF
        file_frame = ttk.LabelFrame(self, text="PDF Input", padding=8)
        file_frame.pack(fill="x", pady=(0, 8))
        ttk.Entry(file_frame, textvariable=self.pdf_path, width=60).pack(
            side="left", expand=True, fill="x")
        ttk.Button(file_frame, text="Browse…", command=self._browse_pdf).pack(
            side="left", padx=(6, 0))

        # API Configuration (collapsible, collapsed by default)
        self._api_collapsed = True
        self._api_toggle_btn = ttk.Button(
            self, text="▶  API Configuration  (steps 3 & 4)",
            command=self._toggle_api)
        self._api_toggle_btn.pack(fill="x", pady=(0, 8))

        self._api_inner = ttk.LabelFrame(self, text="", padding=8)
        # Not packed yet — shown on toggle

        key_row = ttk.Frame(self._api_inner)
        key_row.pack(fill="x", pady=(0, 6))
        ttk.Label(key_row, text="OpenAI API Key:", width=16).pack(side="left")
        ttk.Entry(key_row, textvariable=self.api_key, show="*").pack(
            side="left", expand=True, fill="x")

        uri_row = ttk.Frame(self._api_inner)
        uri_row.pack(fill="x", pady=(0, 6))
        ttk.Label(uri_row, text="MongoDB URI:", width=16).pack(side="left")
        ttk.Entry(uri_row, textvariable=self.mongo_uri, show="*").pack(
            side="left", expand=True, fill="x")

        db_row = ttk.Frame(self._api_inner)
        db_row.pack(fill="x")
        ttk.Label(db_row, text="Database:", width=16).pack(side="left")
        ttk.Entry(db_row, textvariable=self.mongo_db, width=18).pack(
            side="left", padx=(0, 16))
        ttk.Label(db_row, text="Collection:").pack(side="left")
        ttk.Entry(db_row, textvariable=self.mongo_coll, width=18).pack(
            side="left", padx=(4, 0))

        save_row = ttk.Frame(self._api_inner)
        save_row.pack(fill="x", pady=(8, 0))
        ttk.Button(save_row, text="Opslaan in .env", command=self._save_env).pack(side="right")

        # Step buttons
        btn_frame = ttk.LabelFrame(self, text="Pipeline Steps", padding=10)
        btn_frame.pack(fill="x", pady=(0, 8))
        self.step_buttons = []
        steps_row = ttk.Frame(btn_frame)
        steps_row.pack(fill="x", pady=(0, 8))
        for i, (label, _) in enumerate(STEPS):
            btn = ttk.Button(steps_row, text=label, command=lambda s=i: self._run_step(s))
            btn.pack(side="left", padx=(0, 6), expand=True, fill="x")
            self.step_buttons.append(btn)
        ttk.Button(btn_frame, text="▶  Run All Steps", command=self._run_all,
                   style="Primary.TButton").pack(fill="x")

        # Log
        log_frame = ttk.LabelFrame(self, text="Output Log", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            log_frame, wrap="word", state="disabled",
            font=FONTM, bg="#0F172A", fg="#94D2BD",
            insertbackground="#94D2BD", selectbackground=C["accent"],
            relief="flat", padx=8, pady=6,
        )
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        ttk.Button(self, text="Clear Log", command=self._clear_log).pack(anchor="e", pady=(4, 0))

    def _save_env(self):
        """Write API keys and MongoDB settings to PROJECT_ROOT/.env."""
        env_path = PROJECT_ROOT / ".env"
        lines = []
        if env_path.exists():
            # Keep any existing lines that we don't manage
            managed = {"OPENAI_API_KEY", "MONGODB_URI", "MONGODB_DB", "MONGODB_COLL"}
            for line in env_path.read_text().splitlines():
                key = line.split("=", 1)[0].strip()
                if key not in managed:
                    lines.append(line)
        lines += [
            f'OPENAI_API_KEY="{self.api_key.get().strip()}"',
            f'MONGODB_URI="{self.mongo_uri.get().strip()}"',
            f'MONGODB_DB="{self.mongo_db.get().strip()}"',
            f'MONGODB_COLL="{self.mongo_coll.get().strip()}"',
        ]
        env_path.write_text("\n".join(lines) + "\n")
        messagebox.showinfo("Opgeslagen", f"Instellingen opgeslagen in {env_path}")

    def _browse_pdf(self):
        path = filedialog.askopenfilename(
            title="Select Guideline PDF",
            filetypes=[("PDF files", "*.pdf")],
        )
        if path:
            self.pdf_path.set(path)

    def _toggle_api(self):
        if self._api_collapsed:
            self._api_inner.pack(after=self._api_toggle_btn, fill="x", pady=(0, 8))
            self._api_toggle_btn.configure(text="▼  API Configuration  (steps 3 & 4)")
            self._api_collapsed = False
        else:
            self._api_inner.pack_forget()
            self._api_toggle_btn.configure(text="▶  API Configuration  (steps 3 & 4)")
            self._api_collapsed = True

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _log(self, text: str):
        self._log_queue.put(text)

    def _poll_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(50, self._poll_log)

    def _set_buttons_state(self, state: str):
        for btn in self.step_buttons:
            btn.configure(state=state)

    def _run_step(self, step_index: int):
        if self._running:
            messagebox.showwarning("Busy", "A step is already running.")
            return
        self._start_script(step_index)

    def _run_all(self):
        if self._running:
            messagebox.showwarning("Busy", "A step is already running.")
            return
        self._run_sequence(0)

    def _run_sequence(self, step_index: int):
        if step_index >= len(STEPS):
            self._log("\n✓ All steps completed.\n")
            return
        self._start_script(step_index, on_done=lambda: self._run_sequence(step_index + 1))

    def _start_script(self, step_index: int, on_done=None):
        label, script_name = STEPS[step_index]
        script_path = SCRIPTS_DIR / script_name
        project = self._get_project()
        data_dir = get_data_dir(project)

        # Copy PDF to project data dir under its original filename
        pdf_src = self.pdf_path.get().strip()
        if pdf_src and Path(pdf_src).exists():
            dest = data_dir / Path(pdf_src).name
            if Path(pdf_src).resolve() != dest.resolve():
                shutil.copy2(pdf_src, dest)
                self._log(f"Copied PDF to {dest}\n")

        cfg = self._get_config()
        year = cfg.get("project_meta", {}).get(project, {}).get("year", "")

        pdf_name = Path(pdf_src).name if pdf_src and Path(pdf_src).exists() else ""

        env = os.environ.copy()
        env["RAG_DATA_DIR"] = str(data_dir)
        env["RAG_PROJECT_TITLE"] = project
        if pdf_name:
            env["RAG_PDF_NAME"] = pdf_name
        if year:
            env["RAG_GUIDELINE_YEAR"] = year
        if self.api_key.get().strip():
            env["OPENAI_API_KEY"] = self.api_key.get().strip()
        if self.mongo_uri.get().strip():
            env["MONGODB_URI"] = self.mongo_uri.get().strip()
        if self.mongo_db.get().strip():
            env["MONGODB_DB"] = self.mongo_db.get().strip()
        if self.mongo_coll.get().strip():
            env["MONGODB_COLL"] = self.mongo_coll.get().strip()

        self._log(f"\n{'─'*60}\n▶ Running: {label}  [{project}]\n{'─'*60}\n")
        self._running = True
        self._set_buttons_state("disabled")

        def worker():
            try:
                proc = subprocess.Popen(
                    [sys.executable, str(script_path)],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, env=env, cwd=str(PROJECT_ROOT),
                )
                for line in proc.stdout:
                    self._log(line)
                proc.wait()
                status = "✓ Done" if proc.returncode == 0 else f"✗ Failed (exit {proc.returncode})"
                self._log(f"\n{status}: {label}\n")
            except Exception as e:
                self._log(f"\n[ERROR] Could not start script: {e}\n")
            finally:
                self._running = False
                self.after(0, lambda: self._set_buttons_state("normal"))
                self.after(0, self.on_step_done)
                if on_done:
                    self.after(100, on_done)

        threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Results Tab — browse, edit, delete
# ---------------------------------------------------------------------------

class ResultsTab(ttk.Frame):
    def __init__(self, parent, get_project):
        super().__init__(parent, padding=10)
        self._get_project = get_project
        self._chunks: list[dict] = []
        self._filtered: list[dict] = []
        self._selected_index: int | None = None
        self._dirty = False
        self._manual_counter = 0
        self._build_ui()

    def _build_ui(self):
        # ── Top controls ──────────────────────────────────────────
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))

        ttk.Button(top, text="Reload", command=self.reload).pack(side="left", padx=(0, 8))
        ttk.Button(top, text="Save all changes", command=self._save_all,
                   style="Primary.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(top, text="+ Nieuwe aanbeveling", command=self._add_chunk).pack(
            side="left", padx=(0, 16))

        self.stats_var = tk.StringVar(value="No data loaded.")
        ttk.Label(top, textvariable=self.stats_var, foreground="#555").pack(side="left")

        # ── Filters ───────────────────────────────────────────────
        flt = ttk.LabelFrame(self, text="Filters", padding=6)
        flt.pack(fill="x", pady=(0, 6))

        ttk.Label(flt, text="Class:").pack(side="left")
        self.class_var = tk.StringVar(value="All")
        self.class_cb = ttk.Combobox(flt, textvariable=self.class_var, width=12, state="readonly")
        self.class_cb.pack(side="left", padx=(4, 12))
        self.class_cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_list())

        ttk.Label(flt, text="Evidence:").pack(side="left")
        self.evid_var = tk.StringVar(value="All")
        self.evid_cb = ttk.Combobox(flt, textvariable=self.evid_var, width=6, state="readonly")
        self.evid_cb.pack(side="left", padx=(4, 12))
        self.evid_cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_list())

        ttk.Label(flt, text="Disease:").pack(side="left")
        self.disease_var = tk.StringVar(value="All")
        self.disease_cb = ttk.Combobox(flt, textvariable=self.disease_var, width=10, state="readonly")
        self.disease_cb.pack(side="left", padx=(4, 12))
        self.disease_cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_list())

        ttk.Label(flt, text="Topic:").pack(side="left")
        self.topic_var = tk.StringVar(value="All")
        self.topic_cb = ttk.Combobox(flt, textvariable=self.topic_var, width=16, state="readonly")
        self.topic_cb.pack(side="left", padx=(4, 0))
        self.topic_cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_list())

        # ── Horizontal split: list | edit panel ───────────────────
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True)

        # Left — treeview
        left = ttk.Frame(pane)
        pane.add(left, weight=2)

        cols = ("class", "evidence", "disease", "topic", "preview")
        self.tree = ttk.Treeview(left, columns=cols, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Section  (count)")
        self.tree.column("#0", width=220, stretch=False)
        for col, w in zip(cols, (90, 80, 80, 110, 380)):
            self.tree.heading(col, text=col.replace("_", " ").capitalize())
            self.tree.column(col, width=w, stretch=(col == "preview"))
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Right — edit panel
        right = ttk.Frame(pane, padding=8, style="Card.TFrame")
        pane.add(right, weight=1)

        ttk.Label(right, text="Recommendation text", font=FONTB,
                  background=C["card"]).pack(anchor="w", pady=(0, 4))
        self.edit_text = tk.Text(right, wrap="word", font=FONTS, height=10,
                                 relief="flat", bd=1,
                                 bg=C["card"], fg=C["txt"],
                                 selectbackground=C["sel_bg"],
                                 insertbackground=C["accent"],
                                 highlightthickness=1,
                                 highlightbackground=C["border"],
                                 highlightcolor=C["accent"],
                                 padx=6, pady=6)
        self.edit_text.pack(fill="both", expand=True, pady=(0, 8))

        # Class III warning banner — always packed, content toggled in _on_select
        self._class3_warning = tk.Label(right, text="",
            background=C["card"], foreground=C["danger"],
            font=FONTB, anchor="w", padx=8, pady=0,
            relief="flat", bd=0)
        self._class3_warning.pack(fill="x", pady=(0, 2))

        meta_frame = ttk.LabelFrame(right, text="Metadata", padding=6)
        meta_frame.pack(fill="x", pady=(0, 8))

        for row_widgets in [
            [("Class:",    "edit_class",   REC_CLASSES,     10),
             ("Evidence:", "edit_evidence", EVIDENCE_LEVELS,  6)],
            [("Disease:",  "edit_disease", [],              12),
             ("Topic:",    "edit_topic",   [],              14)],
        ]:
            row = ttk.Frame(meta_frame)
            row.pack(fill="x", pady=2)
            for label, attr, values, width in row_widgets:
                ttk.Label(row, text=label, width=9).pack(side="left")
                var = tk.StringVar()
                cb = ttk.Combobox(row, textvariable=var, values=values, width=width)
                cb.pack(side="left", padx=(0, 12))
                setattr(self, f"{attr}_var", var)
                setattr(self, f"{attr}_cb", cb)

        # Read-only info fields
        info_row = ttk.Frame(meta_frame)
        info_row.pack(fill="x", pady=(4, 0))
        ttk.Label(info_row, text="Guideline:", width=9).pack(side="left")
        self._info_guideline_var = tk.StringVar()
        ttk.Label(info_row, textvariable=self._info_guideline_var,
                  foreground=C["muted"], font=FONTS).pack(side="left", padx=(0, 6))
        self._info_year_var = tk.StringVar()
        ttk.Label(info_row, textvariable=self._info_year_var,
                  foreground=C["muted"], font=FONTS).pack(side="left")

        tbl_row = ttk.Frame(meta_frame)
        tbl_row.pack(fill="x", pady=(2, 0))
        ttk.Label(tbl_row, text="Table:", width=9).pack(side="left")
        self._info_table_title_var = tk.StringVar()
        self._table_entry = ttk.Entry(tbl_row, textvariable=self._info_table_title_var, font=FONTS)
        self._table_entry.pack(side="left", expand=True, fill="x")

        refs_row = ttk.Frame(meta_frame)
        refs_row.pack(fill="x", pady=(2, 0))
        ttk.Label(refs_row, text="Refs:", width=9).pack(side="left")
        self._info_refs_var = tk.StringVar()
        self._refs_entry = ttk.Entry(refs_row, textvariable=self._info_refs_var, font=FONTS)
        self._refs_entry.pack(side="left", expand=True, fill="x")
        ttk.Label(refs_row, text="  (komma-gescheiden nrs)", foreground=C["muted"],
                  font=("Helvetica", 9)).pack(side="left")

        btn_row = ttk.Frame(right, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="Save changes",    command=self._save_chunk,
                   style="Primary.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Delete selected", command=self._delete_chunk,
                   style="Danger.TButton").pack(side="left")

        self._set_edit_state("disabled")

    # ── Data loading ──────────────────────────────────────────────

    def reload(self):
        files = project_files(self._get_project())
        self._chunks = load_json(files[2]) or []
        self._dirty = False
        self._selected_index = None
        self._set_edit_state("disabled")
        self._update_filter_options()
        self._refresh_list()

    def _update_filter_options(self):
        def values(key):
            return sorted({c["metadata"].get(key, "") for c in self._chunks if c.get("metadata")})

        diseases = values("disease")
        topics   = values("topic")
        classes  = values("class")
        evidences = values("evidence")

        self.class_cb["values"]   = ["All"] + classes
        self.evid_cb["values"]    = ["All"] + evidences
        self.disease_cb["values"] = ["All"] + diseases
        self.topic_cb["values"]   = ["All"] + topics

        # Dynamic options for edit fields
        self.edit_disease_cb["values"] = diseases
        self.edit_topic_cb["values"]   = topics

        for var, cb in [(self.class_var, self.class_cb),
                        (self.evid_var,  self.evid_cb),
                        (self.disease_var, self.disease_cb),
                        (self.topic_var,  self.topic_cb)]:
            if var.get() not in cb["values"]:
                var.set("All")

    def _refresh_list(self):
        cl = self.class_var.get()
        ev = self.evid_var.get()
        di = self.disease_var.get()
        to = self.topic_var.get()

        self._filtered = [
            c for c in self._chunks
            if (cl == "All" or c["metadata"].get("class")   == cl)
            and (ev == "All" or c["metadata"].get("evidence") == ev)
            and (di == "All" or c["metadata"].get("disease")  == di)
            and (to == "All" or c["metadata"].get("topic")    == to)
        ]

        for row in self.tree.get_children():
            self.tree.delete(row)

        # Group by table_title — each table is a collapsible parent with count
        sections: dict[str, list[dict]] = {}
        for chunk in self._filtered:
            tbl = chunk["metadata"].get("table_title") or chunk["metadata"].get("section", "—")
            sections.setdefault(tbl, []).append(chunk)

        self.tree.tag_configure("section",
                                background=C["sec_bg"],
                                foreground=C["sec_fg"],
                                font=FONTB)
        self.tree.tag_configure("class3",
                                foreground=C["danger"],
                                font=FONTB)

        for sec, chunks in sections.items():
            sec_iid = f"sec::{sec}"
            label = sec if len(sec) <= 70 else sec[:67] + "…"
            self.tree.insert("", "end", iid=sec_iid,
                             text=f"{label}  ({len(chunks)})",
                             values=("", "", "", "", ""),
                             open=True, tags=("section",))
            for chunk in chunks:
                m = chunk.get("metadata", {})
                cls = m.get("class", "")
                tags = ("class3",) if cls in ("Class III", "Class III?") else ()
                raw = chunk.get("text", "")
                preview = raw.split("\n\n", 1)[-1] if "\n\n" in raw else raw
                self.tree.insert(sec_iid, "end", iid=chunk["id"], values=(
                    cls,
                    m.get("evidence", ""),
                    m.get("disease", ""),
                    m.get("topic", ""),
                    preview[:140].replace("\n", " "),
                ), tags=tags)

        total = len(self._chunks)
        shown = len(self._filtered)
        dirty = " • unsaved changes" if self._dirty else ""
        self.stats_var.set(
            f"{shown} of {total} recommendations in {len(sections)} tables{dirty}"
        )

    # ── Selection / editing ───────────────────────────────────────

    def _on_select(self, _event):
        sel = self.tree.selection()
        # Filter out section header rows
        chunk_sel = [s for s in sel if not s.startswith("sec::")]

        if len(chunk_sel) == 1:
            chunk_id = chunk_sel[0]
            idx = next((i for i, c in enumerate(self._chunks) if c["id"] == chunk_id), None)
            if idx is None:
                return
            self._selected_index = idx
            chunk = self._chunks[idx]
            m = chunk.get("metadata", {})
            self._set_edit_state("normal")
            self.edit_text.delete("1.0", "end")
            self.edit_text.insert("end", chunk.get("text", ""))
            cls = m.get("class", "")
            self.edit_class_var.set(cls)
            self.edit_evidence_var.set(m.get("evidence", ""))
            self.edit_disease_var.set(m.get("disease", ""))
            self.edit_topic_var.set(m.get("topic", ""))
            if cls in ("Class III", "Class III?"):
                self._class3_warning.config(
                    text="⚠  Contraïndicatie — Class III: niet aanbevolen",
                    background="#FEF2F2", pady=4)
            else:
                self._class3_warning.config(text="", background=C["card"], pady=0)
            self._info_guideline_var.set(m.get("guideline", ""))
            year = m.get("year", "")
            self._info_year_var.set(f"({year})" if year else "")
            self._info_table_title_var.set(m.get("table_title", ""))
            ref_ids = m.get("ref_ids", [])
            self._info_refs_var.set(", ".join(str(i) for i in ref_ids))

        elif len(chunk_sel) > 1:
            self._selected_index = None
            self._set_edit_state("disabled")
            self.edit_text.configure(state="normal")
            self.edit_text.delete("1.0", "end")
            self.edit_text.insert("end",
                f"{len(chunk_sel)} recommendations geselecteerd.\n"
                "Klik 'Delete selected' om ze te verwijderen.")
            self.edit_text.configure(state="disabled")

        else:
            self._selected_index = None
            self._set_edit_state("disabled")
            self._info_guideline_var.set("")
            self._info_year_var.set("")
            self._info_table_title_var.set("")
            self._info_refs_var.set("")
            self._class3_warning.config(text="", background=C["card"], pady=0)

    def _set_edit_state(self, state: str):
        tk_state = "normal" if state == "normal" else "disabled"
        self.edit_text.configure(state=tk_state)
        self._table_entry.configure(state=tk_state)
        self._refs_entry.configure(state=tk_state)
        for attr in ("edit_class_cb", "edit_evidence_cb", "edit_disease_cb", "edit_topic_cb"):
            getattr(self, attr).configure(state="readonly" if state == "normal" else "disabled")

    def _save_chunk(self):
        if self._selected_index is None:
            return
        chunk = self._chunks[self._selected_index]
        chunk["text"] = self.edit_text.get("1.0", "end").strip()
        chunk["metadata"]["class"]    = self.edit_class_var.get()
        chunk["metadata"]["evidence"] = self.edit_evidence_var.get()
        chunk["metadata"]["disease"]  = self.edit_disease_var.get()
        chunk["metadata"]["topic"]       = self.edit_topic_var.get()
        chunk["metadata"]["table_title"] = self._info_table_title_var.get().strip()
        # Parse manually edited ref_ids (comma-separated integers, ignore invalid)
        raw_refs = self._info_refs_var.get()
        new_ids = []
        for part in raw_refs.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                new_ids.append(int(part))
        chunk["metadata"]["ref_ids"] = new_ids
        self._dirty = True
        self._refresh_list()
        # Re-select the same item
        self.tree.selection_set(chunk["id"])
        self.tree.see(chunk["id"])

    def _add_chunk(self):
        self._manual_counter += 1
        new_id = f"rec_manual_{self._manual_counter}"
        # Avoid collisions with existing IDs
        existing_ids = {c["id"] for c in self._chunks}
        while new_id in existing_ids:
            self._manual_counter += 1
            new_id = f"rec_manual_{self._manual_counter}"
        project = self._get_project()
        new_chunk = {
            "id": new_id,
            "text": "",
            "metadata": {
                "type": "recommendation",
                "class": "Class I",
                "evidence": "A",
                "disease": "general",
                "topic": "general",
                "section": "",
                "table_title": "",
                "ref_ids": [],
                "references": [],
                "guideline": project,
                "year": "",
            },
        }
        self._chunks.append(new_chunk)
        self._dirty = True
        self._update_filter_options()
        self._refresh_list()
        # Select the new item so the user can start editing immediately
        self.tree.selection_set(new_id)
        self.tree.see(new_id)

    def _delete_chunk(self):
        sel = self.tree.selection()
        chunk_ids = {s for s in sel if not s.startswith("sec::")}
        if not chunk_ids:
            return
        n = len(chunk_ids)
        label = f"{n} recommendations" if n > 1 else f"recommendation '{next(iter(chunk_ids))}'"
        if not messagebox.askyesno(
            "Delete",
            f"Delete {label}?\n\nChanges will be saved immediately.",
            parent=self,
        ):
            return
        self._chunks = [c for c in self._chunks if c["id"] not in chunk_ids]
        self._selected_index = None
        self._set_edit_state("disabled")
        self._dirty = True
        self._save_all()
        self._update_filter_options()
        self._refresh_list()

    def _save_all(self):
        if not self._chunks:
            return
        files = project_files(self._get_project())
        save_json(files[2], self._chunks)
        self._dirty = False
        self._refresh_list()


# ---------------------------------------------------------------------------
# Test / Search Tab
# ---------------------------------------------------------------------------

class TestTab(ttk.Frame):
    def __init__(self, parent, get_project):
        super().__init__(parent, padding=10)
        self._get_project = get_project
        self._chunks: list[dict] = []
        self._result_items: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        search_frame = ttk.LabelFrame(self, text="Keyword Search", padding=8)
        search_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(search_frame, text="Query:").pack(side="left")
        self.query_var = tk.StringVar()
        entry = ttk.Entry(search_frame, textvariable=self.query_var, width=42)
        entry.pack(side="left", expand=True, fill="x", padx=(6, 6))
        entry.bind("<Return>", lambda _: self._search())
        ttk.Button(search_frame, text="Search",      command=self._search).pack(side="left")
        ttk.Button(search_frame, text="Reload Data", command=self.reload).pack(side="right")

        pane = ttk.PanedWindow(self, orient="vertical")
        pane.pack(fill="both", expand=True)

        list_frame = ttk.Frame(pane)
        pane.add(list_frame, weight=1)
        self.results_list = tk.Listbox(
            list_frame, font=FONTS, activestyle="none",
            bg=C["card"], fg=C["txt"],
            selectbackground=C["sel_bg"], selectforeground=C["sel_fg"],
            borderwidth=0, highlightthickness=1,
            highlightbackground=C["border"], highlightcolor=C["accent"],
            relief="flat",
        )
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.results_list.yview)
        self.results_list.configure(yscrollcommand=vsb.set)
        self.results_list.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.results_list.bind("<<ListboxSelect>>", self._on_select)

        detail_frame = ttk.LabelFrame(pane, text="Full Text", padding=6)
        pane.add(detail_frame, weight=1)
        self.detail_text = tk.Text(
            detail_frame, wrap="word", font=FONTS, state="disabled",
            bg=C["card"], fg=C["txt"],
            selectbackground=C["sel_bg"],
            relief="flat", padx=8, pady=6,
            highlightthickness=0,
        )
        vsb2 = ttk.Scrollbar(detail_frame, command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=vsb2.set)
        self.detail_text.pack(side="left", fill="both", expand=True)
        vsb2.pack(side="right", fill="y")

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", pady=(4, 0))

    def reload(self):
        files = project_files(self._get_project())
        self._chunks = load_json(files[2]) or []
        self.status_var.set(f"Loaded {len(self._chunks)} recommendations.")

    def _search(self):
        query = self.query_var.get().strip().lower()
        if not query:
            return
        if not self._chunks:
            self.reload()
        matches = [c for c in self._chunks if query in c.get("text", "").lower()
                   or query in json.dumps(c.get("metadata", {})).lower()]
        self._result_items = matches
        self.results_list.delete(0, "end")
        for item in matches:
            m = item.get("metadata", {})
            raw = item.get("text", "")
            preview = raw.split("\n\n", 1)[-1] if "\n\n" in raw else raw
            label = f"[{m.get('class','')} {m.get('evidence','')}] {preview[:100].replace(chr(10),' ')}"
            self.results_list.insert("end", label)
        self.status_var.set(f"{len(matches)} results for '{query}'.")

    def _on_select(self, _event):
        sel = self.results_list.curselection()
        if not sel:
            return
        item = self._result_items[sel[0]]
        m = item.get("metadata", {})
        guideline = m.get("guideline", "—")
        year = m.get("year", "")
        header = (
            f"ID         : {item.get('id','—')}\n"
            f"Class      : {m.get('class','—')}   Evidence: {m.get('evidence','—')}\n"
            f"Disease    : {m.get('disease','—')}\n"
            f"Topic      : {m.get('topic','—')}\n"
            f"Guideline  : {guideline}" + (f"  ({year})" if year else "") + "\n"
            f"{'─'*60}\n\n"
        )
        # Resolved references
        ref_ids = m.get("ref_ids", [])
        references = m.get("references", [])
        if ref_ids:
            ref_lines = [f"\n{'─'*60}\nReferences ({len(ref_ids)}):"]
            shown = min(5, len(references))
            for i, ref_text in enumerate(references[:shown]):
                ref_lines.append(f"  [{ref_ids[i]}] {ref_text}")
            if len(ref_ids) > shown:
                ref_lines.append(f"  + {len(ref_ids) - shown} meer")
            ref_block = "\n".join(ref_lines)
        else:
            ref_block = ""
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("end", header + item.get("text", "") + ref_block)
        self.detail_text.configure(state="disabled")


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RAGCreator")
        self.geometry("1400x900")
        self.minsize(1000, 660)
        self.configure(background=C["bg"])

        setup_style()
        self._cfg = load_config()

        # Project bar at top (dark banner)
        self._project_bar = ProjectBar(self, self._cfg, on_change=self._on_project_change)
        self._project_bar.pack(fill="x", side="top")

        # Status bar at bottom
        self._status_var = tk.StringVar(value="Ready.")
        status_bar = tk.Label(self, textvariable=self._status_var,
                              background=C["bar_bg"], foreground="#64748B",
                              anchor="w", font=FONTS,
                              padx=14, pady=5)
        status_bar.pack(fill="x", side="bottom")

        # Notebook
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        self._results_tab = ResultsTab(nb, get_project=lambda: self._project_bar.active)
        self._test_tab    = TestTab(nb,    get_project=lambda: self._project_bar.active)

        def on_step_done():
            self._results_tab.reload()
            self._test_tab.reload()
            self._update_status()

        self._pipeline_tab = PipelineTab(nb,
                                         get_project=lambda: self._project_bar.active,
                                         get_config=lambda: self._cfg,
                                         on_step_done=on_step_done)

        nb.add(self._pipeline_tab, text="  Pipeline  ")
        nb.add(self._results_tab,  text="  Results  ")
        nb.add(self._test_tab,     text="  Search  ")

        # Load data for active project
        self._results_tab.reload()
        self._test_tab.reload()
        self._update_status()

    def _on_project_change(self, _name: str):
        self._results_tab.reload()
        self._test_tab.reload()
        self._update_status()

    def _update_status(self):
        project = self._project_bar.active
        data_dir = get_data_dir(project)
        parts = []
        for label, filename in [("MD", "guideline.md"), ("chunks", "rag_chunks.json"),
                                 ("embed", "embeddings.json")]:
            if (data_dir / filename).exists():
                parts.append(f"✓ {label}")
        self._status_var.set(
            f"Project: {project}   |   " + ("  ".join(parts) if parts else "No files yet")
        )


if __name__ == "__main__":
    app = App()
    app.mainloop()
