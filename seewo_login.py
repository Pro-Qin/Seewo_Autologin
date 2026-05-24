import pyautogui
import time
import psutil
import subprocess
import json
import tkinter as tk
from tkinter import messagebox, ttk, simpledialog
import threading
import os
import sys
import copy
from pynput import mouse

# ── 高 DPI 支持 ──
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# ──
# seewo_login.py — 希沃白板多账号自动登录工具
# Copyright (c) 2026 Qin_zzq (Pro-Qin)
# License: MIT (see LICENSE file)
# ──

# ── pyautogui ──
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3
pyautogui.size()

# ── globals ──
stop_flag = False
current_step = 0
debug_mode = False
steps = [
    "返回桌面",
    "结束EasiNote进程",
    "启动希沃白板",
    "等待希沃加载",
    "输入账号",
    "输入密码",
    "勾选用户协议",
    "确认登录",
    "进入个人版",
    "操作完成"
]

SETTINGS_FILE = "seewo_mode_settings.json"
SCHEMES_FILE  = "seewo_coordinate_schemes.json"
ACCOUNTS_FILE = "seewo_accounts.json"

# 默认4k坐标（硬编码保留）
DEFAULT_4K_COORDS = {
    "username_input": {"x": 1900, "y": 790,  "desc": "输入账号"},
    "password_input": {"x": 1900, "y": 960,  "desc": "输入密码"},
    "agreement_check":{"x": 1850, "y": 1545, "desc": "勾选用户协议"},
    "login_confirm":  {"x": 1900, "y": 1120, "desc": "确认登录"},
    "back_prepare":   {"x": 80,   "y": 2055, "desc": "进入个人版"},
}

# ── helpers ──
def mask_phone(phone):
    if not phone or len(phone) < 7:
        return phone
    return phone[:4] + "****" + phone[-2:]

def mask_password(password):
    if not password:
        return ""
    return "●" * min(len(password), 16)

def load_mode_settings():
    default = {"global_mode": "adaptive", "subject_modes": {}}
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in default.items():
                data.setdefault(k, v)
            return data
        return dict(default)
    except Exception:
        return dict(default)

def save_mode_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_coordinate_schemes():
    default = {"active_scheme": "4k", "schemes": {"4k": copy.deepcopy(DEFAULT_4K_COORDS)}}
    try:
        if os.path.exists(SCHEMES_FILE):
            with open(SCHEMES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in default.items():
                data.setdefault(k, v)
            return data
        # 文件不存在：写入默认值
        data = dict(default)
        save_coordinate_schemes(data)
        return data
    except Exception:
        return dict(default)

def save_coordinate_schemes(data):
    try:
        with open(SCHEMES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_account_data():
    try:
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 确保每个账号有 default_mode
            for k, v in data.items():
                v.setdefault("default_mode", "auto")
                v.setdefault("username", v.get("account", ""))
            return data
        else:
            sample = {
                "语文": {"username": "chinese_teacher", "password": "password123", "default_mode": "auto"},
                "数学": {"username": "math_teacher",   "password": "password456", "default_mode": "auto"}
            }
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(sample, f, ensure_ascii=False, indent=2)
            return sample
    except Exception as e:
        return None

def save_account_data(data):
    try:
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class SeewoLoginApp:
    def __init__(self, root):
        self.root = root
        self.root.title("希沃自动登录")
        self.root.resizable(False, False)

        self.style = ttk.Style()
        self.style.configure("TButton", font=("SimHei", 10))
        self.style.configure("TLabel", font=("SimHei", 12))

        self.account_data = load_account_data()
        if not self.account_data:
            messagebox.showerror("错误", "无法加载账号信息")
            self.root.destroy()
            return

        self.mode_settings = load_mode_settings()
        self.scheme_data = load_coordinate_schemes()

        self.current_subject = None
        self.current_mode = "manual"

        self.float_window = None
        self.op_window = None
        self.mode_dialog = None
        self.mode_countdown_id = None

        self.mouse_listener = None
        self.pending_input_type = None
        self.pending_input_value = ""
        self._listener_lock = threading.Lock()

        # 坐标读取状态
        self._coord_read_key = None  # 正在等待读取的操作名
        self._coord_read_listener = None

        self.all_subjects = [
            "语文", "数学", "英语", "物理", "化学",
            "生物", "政治", "历史", "地理",
        ]

        self.gmode_labels = ["自适应", "自动", "手动"]
        self.gmode_keys  = ["adaptive", "auto", "manual"]
        self.gmode_idx   = self.gmode_keys.index(
            self.mode_settings.get("global_mode", "adaptive")
        )

        self.create_main_ui()

    # ────────────────────────────────────────────
    # main UI (tabbed)
    # ────────────────────────────────────────────
    def create_main_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: 登录
        login_tab = ttk.Frame(notebook)
        notebook.add(login_tab, text="登录")
        self._build_login_tab(login_tab)

        # Tab 2: 账号管理
        account_tab = ttk.Frame(notebook)
        notebook.add(account_tab, text="账号管理")
        self._build_account_tab(account_tab)

        # Tab 3: 坐标方案
        scheme_tab = ttk.Frame(notebook)
        notebook.add(scheme_tab, text="坐标方案")
        self._build_scheme_tab(scheme_tab)

        # auto-size & position to screen x/8, y/8
        self.root.update_idletasks()
        rw = self.root.winfo_reqwidth()
        rh = self.root.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = max(rw, 480) + 10
        h = max(rh, 320) + 10
        x = max(0, sw // 8)
        y = max(0, sh // 8)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.attributes("-topmost", True)

        # 切换 tab 时自适应尺寸
        notebook.bind("<<NotebookTabChanged>>", lambda e: self._fit_window())

    def _fit_window(self):
        """自适应窗口大小到当前 tab 内容 + 微量间隙"""
        self.root.update_idletasks()
        rw = self.root.winfo_reqwidth()
        rh = self.root.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = max(rw, 480) + 10
        h = max(rh, 320) + 10
        x = max(0, sw // 8)
        y = max(0, sh // 8)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        copyright_label = ttk.Label(self.root, text="Made by Qin_zzq", font=("SimHei", 8))
        copyright_label.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)

    # ────────────────────────────────────────────
    # Tab 1: 登录
    # ────────────────────────────────────────────
    def _build_login_tab(self, parent):
        frame = ttk.Frame(parent, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="请选择学科进行登录", font=("SimHei", 14, "bold")).pack(pady=5)

        opt_frame = ttk.Frame(frame)
        opt_frame.pack(fill=tk.X, pady=5)
        self.debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="Debug模式",
                       variable=self.debug_var).pack(side=tk.LEFT)
        self.gmode_btn = ttk.Button(opt_frame, text=self.gmode_labels[self.gmode_idx],
                                     command=self._cycle_global_mode, width=8)
        self.gmode_btn.pack(side=tk.RIGHT, padx=(10, 0))
        ttk.Label(opt_frame, text="全局模式:", font=("SimHei", 10)).pack(side=tk.RIGHT)

        # 当前激活方案显示
        active = self.scheme_data.get("active_scheme", "4k")
        ttk.Label(opt_frame, text=f"坐标方案: {active}", font=("SimHei", 10),
                 foreground="gray").pack(side=tk.RIGHT, padx=(0, 15))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        for i, subj in enumerate(self.all_subjects):
            r, c = divmod(i, 4)
            state = tk.NORMAL if subj in self.account_data else tk.DISABLED
            saved = self.mode_settings["subject_modes"].get(subj, None)
            label = subj
            if saved:
                label = f"{subj}({saved[:1]})"
            btn = ttk.Button(btn_frame, text=label,
                            command=lambda s=subj: self.on_subject_click(s),
                            state=state, width=12, padding=5)
            if state == tk.DISABLED:
                btn.bind("<Double-Button-1>", lambda e, s=subj: self._jump_to_account(s))
            btn.grid(row=r, column=c, padx=5, pady=5)

        status_frame = ttk.Frame(frame)
        status_frame.pack(fill=tk.X, pady=5)
        ttk.Label(status_frame, text="状态: ").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)

    # ────────────────────────────────────────────
    # Tab 2: 账号管理
    # ────────────────────────────────────────────
    def _build_account_tab(self, parent):
        # 左侧科目列表
        left = tk.Frame(parent, width=140, bg="#f0f0f0")
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 0), pady=5)
        left.pack_propagate(False)

        tk.Label(left, text="科目", font=("SimHei", 11, "bold"), bg="#f0f0f0").pack(pady=5)
        self.acct_listbox = tk.Listbox(left, font=("SimHei", 10), exportselection=False)
        self.acct_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._refresh_account_list()
        self.acct_listbox.bind("<<ListboxSelect>>", self._on_acct_selected)

        # 右侧编辑区
        right = ttk.Frame(parent, padding="10")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=5)

        ttk.Label(right, text="编辑账号", font=("SimHei", 12, "bold")).pack(anchor=tk.W, pady=(0, 10))

        # 科目名
        rf1 = ttk.Frame(right)
        rf1.pack(fill=tk.X, pady=3)
        ttk.Label(rf1, text="科目:", width=10).pack(side=tk.LEFT)
        self.acct_subject_entry = ttk.Entry(rf1, width=22)
        self.acct_subject_entry.pack(side=tk.LEFT, padx=5)

        # 账号
        rf2 = ttk.Frame(right)
        rf2.pack(fill=tk.X, pady=3)
        ttk.Label(rf2, text="账号:", width=10).pack(side=tk.LEFT)
        self.acct_user_entry = ttk.Entry(rf2, width=22)
        self.acct_user_entry.pack(side=tk.LEFT, padx=5)

        # 密码
        rf3 = ttk.Frame(right)
        rf3.pack(fill=tk.X, pady=3)
        ttk.Label(rf3, text="密码:", width=10).pack(side=tk.LEFT)
        self.acct_pwd_entry = ttk.Entry(rf3, width=22, show="*")
        self.acct_pwd_entry.pack(side=tk.LEFT, padx=5)
        self.acct_pwd_visible = False
        ttk.Button(rf3, text="查看", command=self._toggle_pwd_visible, width=5).pack(side=tk.LEFT)

        # 默认方式
        rf4 = ttk.Frame(right)
        rf4.pack(fill=tk.X, pady=3)
        ttk.Label(rf4, text="默认方式:", width=10).pack(side=tk.LEFT)
        self.acct_mode_var = tk.StringVar(value="unknown")
        ttk.Radiobutton(rf4, text="自动", variable=self.acct_mode_var, value="auto").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(rf4, text="手动", variable=self.acct_mode_var, value="manual").pack(side=tk.LEFT)
        ttk.Radiobutton(rf4, text="未知", variable=self.acct_mode_var, value="unknown").pack(side=tk.LEFT, padx=5)

        # 按钮
        btn_frame = ttk.Frame(right)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        ttk.Button(btn_frame, text="保存", command=self._save_account).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="删除", command=self._delete_account).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self._clear_account_form).pack(side=tk.LEFT, padx=5)

    def _refresh_account_list(self):
        self.acct_listbox.delete(0, tk.END)
        # 显示全部 9 个学科，无数据的灰色标记
        for subj in self.all_subjects:
            label = subj if subj in self.account_data else f"({subj})"
            self.acct_listbox.insert(tk.END, label)
            if subj not in self.account_data:
                self.acct_listbox.itemconfig(tk.END, fg="gray")

    def _on_acct_selected(self, event):
        sel = self.acct_listbox.curselection()
        if not sel:
            return
        raw = self.acct_listbox.get(sel[0])
        subj = raw.strip("()")  # 去掉灰色标记括号
        info = self.account_data.get(subj, {})
        self.acct_subject_entry.delete(0, tk.END)
        self.acct_subject_entry.insert(0, subj)
        self.acct_user_entry.delete(0, tk.END)
        self.acct_user_entry.insert(0, info.get("username", info.get("account", "")))
        self.acct_pwd_entry.delete(0, tk.END)
        self.acct_pwd_entry.insert(0, info.get("password", ""))
        self.acct_pwd_entry.config(show="*")
        self.acct_pwd_visible = False
        dm = info.get("default_mode", None)
        self.acct_mode_var.set(dm if dm else "unknown")

    def _toggle_pwd_visible(self):
        self.acct_pwd_visible = not self.acct_pwd_visible
        self.acct_pwd_entry.config(show="" if self.acct_pwd_visible else "*")

    def _save_account(self):
        subject = self.acct_subject_entry.get().strip()
        username = self.acct_user_entry.get().strip()
        password = self.acct_pwd_entry.get()
        default_mode = self.acct_mode_var.get()

        if not subject or not username or not password:
            messagebox.showwarning("提示", "科目、账号、密码不能为空")
            return

        self.account_data[subject] = {
            "username": username,
            "password": password,
            "default_mode": default_mode if default_mode != "unknown" else ""
        }
        save_account_data(self.account_data)
        self._refresh_account_list()
        self.status_var.set(f"账号 [{subject}] 已保存")
        self._rebuild_login_tab()

    def _delete_account(self):
        subject = self.acct_subject_entry.get().strip()
        if not subject or subject not in self.account_data:
            return
        # 三次确认
        if not messagebox.askyesno("确认删除 1/3", f"确定要删除 [{subject}] 的账号吗？（第 1 次确认）"):
            return
        if not messagebox.askyesno("确认删除 2/3", f"真的要删除 [{subject}]？（第 2 次确认）"):
            return
        if not messagebox.askyesno("确认删除 3/3", f"[{subject}] 会被永久删除，确认？（第 3 次确认）"):
            return
        del self.account_data[subject]
        # 同步清理模式记忆
        self.mode_settings["subject_modes"].pop(subject, None)
        save_mode_settings(self.mode_settings)
        save_account_data(self.account_data)
        self._clear_account_form()
        self._refresh_account_list()
        self._rebuild_login_tab()
        self.status_var.set(f"账号 [{subject}] 已删除")

    def _clear_account_form(self):
        self.acct_subject_entry.delete(0, tk.END)
        self.acct_user_entry.delete(0, tk.END)
        self.acct_pwd_entry.delete(0, tk.END)
        self.acct_pwd_entry.config(show="*")
        self.acct_pwd_visible = False
        self.acct_mode_var.set("unknown")

    def _rebuild_login_tab(self):
        """刷新登录tab的科目按钮"""
        for widget in self.root.winfo_children():
            if isinstance(widget, ttk.Notebook):
                tabs = widget.tabs()
                if tabs:
                    login_tab = widget.nametowidget(tabs[0])
                    for w in login_tab.winfo_children():
                        w.destroy()
                    self._build_login_tab(login_tab)
                break

    def _jump_to_account(self, subject):
        """双击无数据科目 → 跳到账号管理 tab 并选中该科目"""
        for widget in self.root.winfo_children():
            if isinstance(widget, ttk.Notebook):
                # 切换到账号管理 tab (index 1)
                widget.select(1)
                # 在列表中选中对应科目
                for i in range(self.acct_listbox.size()):
                    item = self.acct_listbox.get(i)
                    s = item.strip("()")
                    if s == subject:
                        self.acct_listbox.selection_clear(0, tk.END)
                        self.acct_listbox.selection_set(i)
                        self.acct_listbox.see(i)
                        self._on_acct_selected(None)
                        break
                break

    # ────────────────────────────────────────────
    # Tab 3: 坐标方案管理
    # ────────────────────────────────────────────
    def _build_scheme_tab(self, parent):
        # 顶部：方案选择 + 操作按钮
        top = ttk.Frame(parent, padding="10")
        top.pack(fill=tk.X)

        ttk.Label(top, text="当前方案:", font=("SimHei", 11)).pack(side=tk.LEFT)
        self.scheme_var = tk.StringVar(value=self.scheme_data.get("active_scheme", "4k"))
        self.scheme_combo = ttk.Combobox(top, textvariable=self.scheme_var,
                                          values=list(self.scheme_data["schemes"].keys()),
                                          state="readonly", width=12)
        self.scheme_combo.pack(side=tk.LEFT, padx=5)
        self.scheme_combo.bind("<<ComboboxSelected>>", self._on_scheme_selected)

        ttk.Button(top, text="新建", command=self._new_scheme, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="重命名", command=self._rename_scheme, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="删除", command=self._delete_scheme, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="启动希沃", command=self._launch_seewo_bg, width=9).pack(side=tk.RIGHT, padx=10)

        # 操作坐标列表（可滚动）
        self.scheme_canvas = tk.Canvas(parent, bg="#fafafa", highlightthickness=0)
        self.scheme_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=10)

        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.scheme_canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=10, padx=(0, 10))
        self.scheme_canvas.configure(yscrollcommand=scrollbar.set)

        self.scheme_inner = ttk.Frame(self.scheme_canvas)
        self.scheme_canvas.create_window((0, 0), window=self.scheme_inner, anchor="nw")
        self.scheme_inner.bind("<Configure>", lambda e: self.scheme_canvas.configure(
            scrollregion=self.scheme_canvas.bbox("all")))

        self._populate_scheme_ui()

    def _populate_scheme_ui(self):
        """刷新坐标方案UI"""
        for w in self.scheme_inner.winfo_children():
            w.destroy()

        active = self.scheme_var.get()  # 尊重用户下拉选择
        schemes = self.scheme_data["schemes"]
        coords = schemes.get(active, schemes.get(self.scheme_data.get("active_scheme","4k"), {}))

        # 更新下拉框备选项（不覆盖用户选择）
        self.scheme_combo["values"] = list(schemes.keys())

        # 表头
        hdr = ttk.Frame(self.scheme_inner)
        hdr.pack(fill=tk.X, pady=(5, 2))
        ttk.Label(hdr, text="操作", width=18, font=("SimHei", 10, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text="X", width=8, font=("SimHei", 10, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text="Y", width=8, font=("SimHei", 10, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text="", width=12).pack(side=tk.LEFT)

        self._coord_entries = {}
        for key, val in coords.items():
            row = ttk.Frame(self.scheme_inner)
            row.pack(fill=tk.X, pady=1)

            ttk.Label(row, text=val.get("desc", key), width=18).pack(side=tk.LEFT, padx=2)

            x_entry = ttk.Entry(row, width=8)
            x_entry.insert(0, str(val["x"]))
            x_entry.pack(side=tk.LEFT, padx=2)

            y_entry = ttk.Entry(row, width=8)
            y_entry.insert(0, str(val["y"]))
            y_entry.pack(side=tk.LEFT, padx=2)

            read_btn = ttk.Button(row, text="读取", width=6,
                                  command=lambda k=key, x=x_entry, y=y_entry: self._read_single_coord(k, x, y))
            read_btn.pack(side=tk.LEFT, padx=5)

            self._coord_entries[key] = (x_entry, y_entry, read_btn)

        # 保存按钮
        ttk.Button(self.scheme_inner, text="保存坐标方案",
                  command=self._save_scheme_coords).pack(pady=(10, 5))

    def _on_scheme_selected(self, event):
        name = self.scheme_var.get()
        if name in self.scheme_data["schemes"]:
            self.scheme_data["active_scheme"] = name
            save_coordinate_schemes(self.scheme_data)
            self._rebuild_login_tab()
        self._populate_scheme_ui()

    def _new_scheme(self):
        name = simpledialog.askstring("新建方案", "输入方案名称:", parent=self.root)
        if not name:
            return
        if name in self.scheme_data["schemes"]:
            messagebox.showwarning("提示", f"方案 [{name}] 已存在")
            return
        # 复制当前方案为模板
        active = self.scheme_var.get()
        self.scheme_data["schemes"][name] = copy.deepcopy(
            self.scheme_data["schemes"].get(active, DEFAULT_4K_COORDS)
        )
        save_coordinate_schemes(self.scheme_data)
        self.scheme_data["active_scheme"] = name
        self.scheme_combo["values"] = list(self.scheme_data["schemes"].keys())
        self.scheme_var.set(name)
        self._populate_scheme_ui()
        self._rebuild_login_tab()
        self.status_var.set(f"方案 [{name}] 已创建")

    def _rename_scheme(self):
        old = self.scheme_var.get()
        if old not in self.scheme_data["schemes"]:
            return
        new = simpledialog.askstring("重命名", f"将 [{old}] 重命名为:", parent=self.root)
        if not new or new == old:
            return
        if new in self.scheme_data["schemes"]:
            messagebox.showwarning("提示", f"方案 [{new}] 已存在")
            return
        self.scheme_data["schemes"][new] = self.scheme_data["schemes"].pop(old)
        if self.scheme_data["active_scheme"] == old:
            self.scheme_data["active_scheme"] = new
        save_coordinate_schemes(self.scheme_data)
        self.scheme_combo["values"] = list(self.scheme_data["schemes"].keys())
        self.scheme_var.set(new)
        self._populate_scheme_ui()
        self._rebuild_login_tab()
        self.status_var.set(f"方案已重命名为 [{new}]")

    def _delete_scheme(self):
        name = self.scheme_var.get()
        if name not in self.scheme_data["schemes"]:
            return
        if len(self.scheme_data["schemes"]) <= 1:
            messagebox.showwarning("提示", "至少保留一个方案")
            return
        if not messagebox.askyesno("确认", f"删除方案 [{name}]？"):
            return
        del self.scheme_data["schemes"][name]
        if self.scheme_data["active_scheme"] == name:
            self.scheme_data["active_scheme"] = next(iter(self.scheme_data["schemes"]))
        save_coordinate_schemes(self.scheme_data)
        self.scheme_combo["values"] = list(self.scheme_data["schemes"].keys())
        self.scheme_var.set(self.scheme_data["active_scheme"])
        self._populate_scheme_ui()
        self._rebuild_login_tab()
        self.status_var.set(f"方案 [{name}] 已删除")

    def _save_scheme_coords(self):
        """保存当前方案的坐标修改"""
        active = self.scheme_var.get()
        if active not in self.scheme_data["schemes"]:
            return
        coords = self.scheme_data["schemes"][active]
        for key, (x_entry, y_entry, _) in self._coord_entries.items():
            try:
                coords[key]["x"] = int(x_entry.get())
                coords[key]["y"] = int(y_entry.get())
            except ValueError:
                pass
        save_coordinate_schemes(self.scheme_data)
        self.status_var.set(f"方案 [{active}] 坐标已保存")

    def _read_single_coord(self, key, x_entry, y_entry):
        """读取单个坐标：点击后等待下一次鼠标左键"""

        self._coord_read_key = (key, x_entry, y_entry)
        if self._coord_read_listener:
            try:
                self._coord_read_listener.stop()
            except Exception:
                pass

        def on_click(x, y, button, pressed):
            if pressed and button == mouse.Button.left:
                self.root.after(0, lambda: self._on_coord_captured(x, y))
                return False
            return True

        self._coord_read_listener = mouse.Listener(on_click=on_click)
        self._coord_read_listener.start()
        self.status_var.set("请点击屏幕目标位置读取坐标...")

    def _on_coord_captured(self, x, y):
        if self._coord_read_listener:
            try:
                self._coord_read_listener.stop()
            except Exception:
                pass
            self._coord_read_listener = None

        if not self._coord_read_key:
            return
        key, x_entry, y_entry = self._coord_read_key
        self._coord_read_key = None

        x_entry.delete(0, tk.END)
        x_entry.insert(0, str(x))
        y_entry.delete(0, tk.END)
        y_entry.insert(0, str(y))
        self.status_var.set(f"已读取坐标 ({x}, {y})  ← 可保存")

    # ────────────────────────────────────────────
    # login logic
    # ────────────────────────────────────────────
    def on_subject_click(self, subject):
        self.current_subject = subject
        gmode = self.mode_settings["global_mode"]
        subj_modes = self.mode_settings["subject_modes"]

        if gmode == "auto":
            self.current_mode = "auto"
            self._proceed(subject, "auto")
        elif gmode == "manual":
            self.current_mode = "manual"
            self._proceed(subject, "manual")
        else:
            saved = subj_modes.get(subject, None)
            if saved is not None:
                self.current_mode = saved
                self._proceed(subject, saved)
            else:
                self._show_mode_dialog(subject)

    def _proceed(self, subject, mode):
        self.hide_main_window()
        self._launch_seewo_bg()
        if mode == "auto":
            self.start_auto_login(subject)
        else:
            self.show_float_window(subject)

    def _cycle_global_mode(self):
        self.gmode_idx = (self.gmode_idx + 1) % 3
        self.mode_settings["global_mode"] = self.gmode_keys[self.gmode_idx]
        save_mode_settings(self.mode_settings)
        self.gmode_btn.config(text=self.gmode_labels[self.gmode_idx])
        self.status_var.set(f"全局模式: {self.gmode_labels[self.gmode_idx]}")

    # ────────────────────────────────────────────
    # mode dialog
    # ────────────────────────────────────────────
    def _show_mode_dialog(self, subject):
        if self.mode_dialog and self.mode_dialog.winfo_exists():
            self.mode_dialog.destroy()

        self.mode_dialog = tk.Toplevel(self.root)
        self.mode_dialog.title("选择操作模式")
        self.mode_dialog.geometry("400x250")
        self.mode_dialog.resizable(False, False)
        self.mode_dialog.transient(self.root)
        self.mode_dialog.grab_set()
        self.mode_dialog.attributes("-topmost", True)
        self.mode_dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.mode_dialog.geometry(f"400x250+{sw//8}+{sh//8}")

        ttk.Label(self.mode_dialog,
                 text=f"科目 [{subject}] 登录方式",
                 font=("SimHei", 13, "bold")).pack(pady=(20, 10))

        self.dlg_mode_var = tk.StringVar(value="auto")
        rf = ttk.Frame(self.mode_dialog); rf.pack(pady=5)
        ttk.Radiobutton(rf, text="自动模式", variable=self.dlg_mode_var, value="auto").pack(anchor=tk.W, pady=3)
        ttk.Radiobutton(rf, text="手动模式", variable=self.dlg_mode_var, value="manual").pack(anchor=tk.W, pady=3)

        self.dlg_remember_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.mode_dialog, text="记住（以后不再询问）",
                        variable=self.dlg_remember_var).pack(pady=5)

        self.dlg_countdown_var = tk.StringVar(value="15秒后自动选择自动模式")
        ttk.Label(self.mode_dialog, textvariable=self.dlg_countdown_var,
                 font=("SimHei", 9), foreground="gray").pack(pady=(5, 0))

        bf = ttk.Frame(self.mode_dialog); bf.pack(pady=(10, 15))
        ttk.Button(bf, text="确认", command=lambda: self._on_dlg_confirm(subject), width=10).pack(side=tk.LEFT, padx=10)
        ttk.Button(bf, text="取消", command=self._on_dlg_cancel, width=10).pack(side=tk.LEFT, padx=10)

        self.dlg_countdown = 15
        self._tick_dlg_countdown(subject)

    def _tick_dlg_countdown(self, subject):
        try:
            if not (self.mode_dialog and self.mode_dialog.winfo_exists()):
                return
        except Exception:
            return
        if self.dlg_countdown <= 0:
            self.dlg_mode_var.set("auto")
            self._on_dlg_confirm(subject, auto_triggered=True)
            return
        try:
            self.dlg_countdown_var.set(f"{self.dlg_countdown}秒后自动选择自动模式")
        except Exception:
            return
        self.dlg_countdown -= 1
        try:
            self.mode_countdown_id = self.mode_dialog.after(1000, lambda: self._tick_dlg_countdown(subject))
        except Exception:
            pass

    def _on_dlg_confirm(self, subject, auto_triggered=False):
        if self.mode_countdown_id and self.mode_dialog:
            try: self.mode_dialog.after_cancel(self.mode_countdown_id)
            except Exception: pass
            self.mode_countdown_id = None
        mode = self.dlg_mode_var.get()
        if self.dlg_remember_var.get():
            self.mode_settings["subject_modes"][subject] = mode
            save_mode_settings(self.mode_settings)
        self.current_mode = mode
        if self.mode_dialog and self.mode_dialog.winfo_exists():
            self.mode_dialog.destroy()
            self.mode_dialog = None
        self._proceed(subject, mode)

    def _on_dlg_cancel(self):
        if self.mode_countdown_id and self.mode_dialog:
            try: self.mode_dialog.after_cancel(self.mode_countdown_id)
            except Exception: pass
            self.mode_countdown_id = None
        if self.mode_dialog and self.mode_dialog.winfo_exists():
            self.mode_dialog.destroy()
            self.mode_dialog = None
        self.current_subject = None
        self.status_var.set("已取消")

    # ────────────────────────────────────────────
    # Seewo launcher
    # ────────────────────────────────────────────
    def _launch_seewo_bg(self):
        def _launch():
            global debug_mode
            if debug_mode: return
            for path in [
                r"C:\Program Files (x86)\Seewo\EasiNote5\swenlauncher\swenlauncher.exe",
                r"D:\EasiNote5\swenlauncher\swenlauncher.exe",
            ]:
                try:
                    subprocess.Popen(path)
                    return
                except Exception:
                    continue
            try: subprocess.Popen("swenlauncher.exe")
            except Exception: pass
        threading.Thread(target=_launch, daemon=True).start()

    def hide_main_window(self):
        self.root.withdraw()

    def show_main_window(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.update_idletasks()
        self.create_main_ui()

    # ────────────────────────────────────────────
    # auto login (uses scheme coordinates)
    # ────────────────────────────────────────────
    def _get_coords(self):
        """获取下拉框当前方案的坐标"""
        active = self.scheme_var.get()
        if not active:
            active = self.scheme_data.get("active_scheme", "4k")
        return self.scheme_data["schemes"].get(active, DEFAULT_4K_COORDS)

    def start_auto_login(self, subject):
        global stop_flag, current_step, debug_mode
        stop_flag = False
        current_step = 0
        debug_mode = self.debug_var.get()

        info = self.account_data.get(subject, {})
        username = info.get("username", info.get("account", ""))
        password = info.get("password", "")

        if not username or not password:
            messagebox.showerror("错误", f"{subject} 的账号或密码未设置")
            return

        self._show_overlay(subject)
        threading.Thread(target=self.perform_login, args=(username, password), daemon=True).start()

    def _show_overlay(self, subject):
        """底部进度覆层（简洁 tk 控件布局）"""
        if self.op_window and self.op_window.winfo_exists():
            self.op_window.destroy()

        self.op_window = tk.Toplevel(self.root)
        self.op_window.overrideredirect(True)
        self.op_window.attributes("-topmost", True)

        sw = self.op_window.winfo_screenwidth()
        sh = self.op_window.winfo_screenheight()
        # 紧凑尺寸 & 位置（同手动浮窗：屏幕左1/4中心）
        OW, OH = 280, 260
        px = max(0, min(int(sw * 0.25 - OW // 2), sw - OW))
        py = max(0, min(sh // 2 - OH // 2, sh - OH))
        self.op_window.geometry(f"{OW}x{OH}+{px}+{py}")

        frame = ttk.Frame(self.op_window, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        mode_note = "（Debug）" if debug_mode else ""
        ttk.Label(frame, text=f"自动登录{mode_note}，请勿操作电脑",
                 font=("SimHei", 11, "bold"), foreground="red").pack(pady=3)

        self.progress_var = tk.DoubleVar()
        ttk.Progressbar(frame, variable=self.progress_var, maximum=100, length=250).pack(pady=5)

        ttk.Label(frame, text="操作步骤:", font=("SimHei", 9)).pack(anchor=tk.W)

        self.step_text = tk.Text(frame, height=6, width=38, state=tk.DISABLED)
        self.step_text.pack(pady=3)

        bf = ttk.Frame(frame); bf.pack(pady=3)
        ttk.Button(bf, text="停止操作", command=self._cancel_overlay).pack()

    def _update_overlay(self, step, completed=True):
        """线程安全：通过 after 调度到主线程"""
        self.root.after(0, lambda: self._update_overlay_main(step, completed))

    def _update_overlay_main(self, step, completed):
        if not (self.op_window and self.op_window.winfo_exists()):
            return
        global current_step
        current_step = step
        total = len(steps)
        self.progress_var.set((step / total) * 100)
        self.step_text.config(state=tk.NORMAL)
        if completed:
            self.step_text.insert(tk.END, f"✓ {steps[step]}\n")
        else:
            self.step_text.insert(tk.END, f"正在进行: {steps[step]}\n")
        self.step_text.see(tk.END)
        self.step_text.config(state=tk.DISABLED)
        self.status_var.set(f"正在{steps[step]}")

    def _cancel_overlay(self):
        global stop_flag
        stop_flag = True
        self.status_var.set("操作已停止")
        self._destroy_overlay_now()
        self.show_main_window()

    def _sleep_check(self, seconds):
        """分段睡眠，可被 stop_flag 中断；返回 False 表示被中断"""
        chunk = 0.1
        elapsed = 0
        while elapsed < seconds:
            if stop_flag:
                return False
            time.sleep(chunk)
            elapsed += chunk
        return True

    def _destroy_overlay(self):
        """线程安全销毁覆层"""
        self.root.after(0, self._destroy_overlay_now)

    def _destroy_overlay_now(self):
        if self.op_window and self.op_window.winfo_exists():
            self.op_window.destroy()
            self.op_window = None

    # ────────────────────────────────────────────
    # float window
    # ────────────────────────────────────────────
    def show_float_window(self, subject):
        self._stop_click_listener()
        if self.float_window and self.float_window.winfo_exists():
            self.float_window.destroy()
            self.float_window = None

        self.float_window = tk.Toplevel(self.root)
        self.float_window.title("账号信息")
        self.float_window.resizable(False, False)
        self.float_window.attributes("-topmost", True)
        self.float_window.overrideredirect(True)

        BG = "#1a1a2e"
        self.float_window.configure(bg=BG)

        info = self.account_data.get(subject, {})
        username = info.get("username", info.get("account", ""))
        password = info.get("password", "")

        bar = tk.Frame(self.float_window, bg="#16213e", height=34)
        bar.pack(fill=tk.X); bar.pack_propagate(False)

        back_btn = tk.Label(bar, text="< 返回", font=("SimHei", 10),
                           bg="#16213e", fg="#e0e0e0", cursor="hand2")
        back_btn.pack(side=tk.LEFT, padx=(8, 0), pady=6)
        back_btn.bind("<Button-1>", lambda e: self._on_float_back())
        back_btn.bind("<Enter>", lambda e: back_btn.config(fg="#00d4ff"))
        back_btn.bind("<Leave>", lambda e: back_btn.config(fg="#e0e0e0"))

        tk.Label(bar, text=subject, font=("SimHei", 12, "bold"),
                bg="#16213e", fg="#ffffff").pack(side=tk.LEFT, expand=True, pady=6)

        toggle_label = "手动" if self.current_mode == "auto" else "自动"
        toggle_btn = tk.Label(bar, text=toggle_label, font=("SimHei", 10, "bold"),
                             bg="#0d1b36", fg="#ffd700", cursor="hand2", padx=10, pady=3)
        toggle_btn.pack(side=tk.RIGHT, padx=(0, 8), pady=4)
        toggle_btn.bind("<Button-1>", lambda e: self._on_float_toggle(subject))
        toggle_btn.bind("<Enter>", lambda e: toggle_btn.config(bg="#1a2d4a", fg="#ffe44d"))
        toggle_btn.bind("<Leave>", lambda e: toggle_btn.config(bg="#0d1b36", fg="#ffd700"))

        content = tk.Frame(self.float_window, bg=BG)
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=(20, 8))

        tk.Label(content, text="手 机 号", font=("SimHei", 10), bg=BG, fg="#8a8aaa").pack(anchor=tk.W)
        phone_lbl = tk.Label(content, text=mask_phone(username),
                            font=("Consolas", 16, "bold"), bg=BG, fg="#00d4ff", cursor="hand2")
        phone_lbl.pack(anchor=tk.W, pady=(3, 0))
        phone_lbl.bind("<Button-1>", lambda e, u=username: self._on_phone_click(u))
        phone_lbl.bind("<Enter>", lambda e: phone_lbl.config(fg="#00ffff"))
        phone_lbl.bind("<Leave>", lambda e: phone_lbl.config(fg="#00d4ff"))

        sep = tk.Frame(content, height=1, bg="#2a2a4a"); sep.pack(fill=tk.X, pady=16)

        tk.Label(content, text="密    码", font=("SimHei", 10), bg=BG, fg="#8a8aaa").pack(anchor=tk.W)
        pwd_lbl = tk.Label(content, text=mask_password(password),
                          font=("Consolas", 16, "bold"), bg=BG, fg="#ff79c6", cursor="hand2")
        pwd_lbl.pack(anchor=tk.W, pady=(3, 0))
        pwd_lbl.bind("<Button-1>", lambda e, p=password: self._on_password_click(p))
        pwd_lbl.bind("<Enter>", lambda e: pwd_lbl.config(fg="#ff99dd"))
        pwd_lbl.bind("<Leave>", lambda e: pwd_lbl.config(fg="#ff79c6"))

        tk.Label(content, text="点击手机号/密码后，点希沃输入框自动填入",
                font=("SimHei", 8), justify=tk.CENTER, bg=BG, fg="#5a5a7a").pack(side=tk.BOTTOM, pady=(8, 0))

        bottom = tk.Frame(self.float_window, bg=BG)
        bottom.pack(fill=tk.X, side=tk.BOTTOM, pady=(0, 10))
        close_lbl = tk.Label(bottom, text="关闭窗口", font=("SimHei", 10),
                            bg="#2a2a4a", fg="#e0e0e0", cursor="hand2", padx=24, pady=6)
        close_lbl.pack()
        close_lbl.bind("<Button-1>", lambda e: self._on_float_close())
        close_lbl.bind("<Enter>", lambda e: close_lbl.config(bg="#3a3a5a", fg="#ffffff"))
        close_lbl.bind("<Leave>", lambda e: close_lbl.config(bg="#2a2a4a", fg="#e0e0e0"))

        self.float_window.update_idletasks()
        req_w = self.float_window.winfo_reqwidth()
        req_h = self.float_window.winfo_reqheight()
        FW = max(req_w, 230); FH = max(req_h, 260)
        sw = self.float_window.winfo_screenwidth()
        sh = self.float_window.winfo_screenheight()
        px = max(0, min(int(sw * 0.25 - FW // 2), sw - FW))
        py = max(0, min(sh // 2 - FH // 2, sh - FH))
        self.float_window.geometry(f"{FW}x{FH}+{px}+{py}")

    def _on_float_toggle(self, subject):
        if self.current_mode == "manual":
            self.current_mode = "auto"
            self.mode_settings["subject_modes"][subject] = "auto"
            save_mode_settings(self.mode_settings)
            self._stop_click_listener()
            if self.float_window and self.float_window.winfo_exists():
                self.float_window.withdraw()
            self.start_auto_login(subject)
        else:
            self.current_mode = "manual"
            self.mode_settings["subject_modes"][subject] = "manual"
            save_mode_settings(self.mode_settings)
            global stop_flag
            stop_flag = True
            self._destroy_overlay_now()
            self._launch_seewo_bg()
            if self.float_window and self.float_window.winfo_exists():
                self.float_window.deiconify()
                self.float_window.attributes("-topmost", True)
            else:
                self.show_float_window(subject)

    # ────────────────────────────────────────────
    # phone/password click → clipboard paste
    # ────────────────────────────────────────────
    def _on_phone_click(self, username):
        import pyperclip
        with self._listener_lock:
            if self.pending_input_type is not None: return
            self.pending_input_type = "phone"
            self.pending_input_value = username
        pyperclip.copy(username)
        if self.float_window and self.float_window.winfo_exists():
            self.float_window.withdraw()
        self._start_click_listener()

    def _on_password_click(self, password):
        import pyperclip
        with self._listener_lock:
            if self.pending_input_type is not None: return
            self.pending_input_type = "password"
            self.pending_input_value = password
        pyperclip.copy(password)
        if self.float_window and self.float_window.winfo_exists():
            self.float_window.withdraw()
        self._start_click_listener()

    def _start_click_listener(self):
        self._stop_click_listener()
        def _on_click(x, y, button, pressed):
            if pressed and button == mouse.Button.left:
                self.root.after(0, lambda: self._do_paste_input(x, y))
                return False
            return True
        self.mouse_listener = mouse.Listener(on_click=_on_click)
        self.mouse_listener.start()

    def _stop_click_listener(self):
        if self.mouse_listener:
            try: self.mouse_listener.stop()
            except Exception: pass
            self.mouse_listener = None

    def _do_paste_input(self, click_x, click_y):
        self._stop_click_listener()
        with self._listener_lock:
            input_type = self.pending_input_type
            input_value = self.pending_input_value
            self.pending_input_type = None
            self.pending_input_value = ""
        if not input_value: return
        try:
            old_pause = pyautogui.PAUSE
            pyautogui.PAUSE = 0
            pyautogui.click(click_x, click_y)
            pyautogui.hotkey("ctrl", "v")
            pyautogui.PAUSE = old_pause
            self.status_var.set(f"已输入{input_type}")
        except Exception as e:
            messagebox.showerror("错误", f"粘贴失败: {e}")
        finally:
            if self.float_window is not None:
                try:
                    if self.float_window.winfo_exists():
                        self.float_window.deiconify()
                        self.float_window.attributes("-topmost", True)
                except Exception: pass

    def _on_float_back(self):
        self._stop_click_listener()
        with self._listener_lock:
            self.pending_input_type = None
            self.pending_input_value = ""
        if self.float_window and self.float_window.winfo_exists():
            self.float_window.destroy()
        self.float_window = None
        self.show_main_window()

    def _on_float_close(self):
        self._cleanup()
        self.root.quit()
        self.root.destroy()
        sys.exit(0)

    def _cleanup(self):
        self._stop_click_listener()
        with self._listener_lock:
            self.pending_input_type = None
            self.pending_input_value = ""
        self._destroy_overlay_now()
        for w in [self.float_window, self.mode_dialog]:
            if w and w.winfo_exists():
                w.destroy()
        self.float_window = self.mode_dialog = None

    # ────────────────────────────────────────────
    # perform_login (now uses scheme coordinates)
    # ────────────────────────────────────────────
    def perform_login(self, username, password):
        global debug_mode
        c = self._get_coords()
        try:
            self._update_overlay(0, False)
            if not debug_mode:
                pyautogui.hotkey("win", "d")
            if not self._sleep_check(1): return
            self._update_overlay(0)

            self._update_overlay(1, False)
            if not debug_mode:
                for proc in psutil.process_iter(["pid", "name"]):
                    if proc.info["name"] == "EasiNote.exe":
                        proc.terminate()
                        if not self._sleep_check(1): return
            elif not self._sleep_check(1): return
            self._update_overlay(1)

            self._update_overlay(2, False)
            if not debug_mode:
                launched = False
                for p in [r"C:\Program Files (x86)\Seewo\EasiNote5\swenlauncher\swenlauncher.exe",
                          r"D:\EasiNote5\swenlauncher\swenlauncher.exe"]:
                    try: subprocess.Popen(p); launched = True; break
                    except Exception: continue
                if not launched:
                    try: subprocess.Popen("swenlauncher.exe")
                    except Exception: pass
            elif not self._sleep_check(1): return
            self._update_overlay(2)

            self._update_overlay(3, False)
            if not self._sleep_check(8.5): return
            self._update_overlay(3)

            # ── 以下坐标均来自方案 ──
            self._update_overlay(4, False)
            if not debug_mode:
                pt = c["username_input"]
                pyautogui.moveTo(pt["x"], pt["y"]); pyautogui.click()
                pyautogui.typewrite(username)
            else:
                self.root.after(0, lambda: self._debug_show("账号", username))
                if not self._sleep_check(1): return
            self._update_overlay(4)

            self._update_overlay(5, False)
            if not debug_mode:
                pt = c["password_input"]
                pyautogui.moveTo(pt["x"], pt["y"]); pyautogui.click()
                pyautogui.typewrite(password)
            else:
                self.root.after(0, lambda: self._debug_show("密码", "*" * len(password)))
                if not self._sleep_check(1): return
            self._update_overlay(5)

            self._update_overlay(6, False)
            if not debug_mode:
                pt = c["agreement_check"]
                pyautogui.moveTo(pt["x"], pt["y"]); pyautogui.click()
            if not self._sleep_check(0.2): return
            self._update_overlay(6)

            self._update_overlay(7, False)
            if not debug_mode:
                pt = c["login_confirm"]
                pyautogui.moveTo(pt["x"], pt["y"]); pyautogui.click()
            if not self._sleep_check(0.2): return
            self._update_overlay(7)

            self._update_overlay(8, False)
            if not debug_mode:
                pt = c["back_prepare"]
                pyautogui.moveTo(pt["x"], pt["y"]); pyautogui.click()
            elif not self._sleep_check(1): return
            self._update_overlay(8)

            self._update_overlay(9)
            self.status_var.set("登录成功")
            self._destroy_overlay()
            self.root.after(0, self._on_auto_finished)

        except Exception as e:
            self.status_var.set(f"操作失败: {e}")
            self.root.after(0, lambda: messagebox.showerror("错误", f"操作失败: {e}"))
            self._destroy_overlay()
            self.root.after(0, self._on_auto_finished)

    def _on_auto_finished(self):
        """自动登录完成 → messagebox 提醒后退出"""
        self.current_mode = "manual"
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.update_idletasks()
        messagebox.showinfo("登录结果", "成功了吧？没成功退出账号 try again.")
        self._force_exit()

    def _force_exit(self):
        self._cleanup()
        self.root.quit()
        self.root.destroy()
        sys.exit(0)

    def _debug_show(self, label, value):
        try:
            if self.op_window and self.op_window.winfo_exists():
                self.step_text.config(state=tk.NORMAL)
                self.step_text.insert(tk.END, f"  将要输入的{label}: {value}\n")
                self.step_text.see(tk.END)
                self.step_text.config(state=tk.DISABLED)
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = SeewoLoginApp(root)
    root.mainloop()
