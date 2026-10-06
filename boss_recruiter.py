import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading, time, json, os, random, datetime, sys, traceback, shutil, subprocess, re, csv, ctypes
from pathlib import Path

DP_IMPORT_ERROR = ""
try:
    from DrissionPage import Chromium, ChromiumPage, ChromiumOptions
    HAS_DP = True
except Exception:
    HAS_DP = False
    DP_IMPORT_ERROR = traceback.format_exc()

try:
    import requests
except Exception:
    requests = None

CFG_FILE = os.path.join(os.path.expanduser('~'), 'boss_recruiter_cfg.json')
REC_URL = 'https://www.zhipin.com/web/chat/recommend'
APP_DIR = Path(__file__).resolve().parent
AI_MODULES_DIR = str(APP_DIR / 'ai_modules')
if AI_MODULES_DIR not in sys.path:
    sys.path.insert(0, AI_MODULES_DIR)
BROWSER_DIR = APP_DIR / 'browser_runtime'
USER_DATA_DIR = BROWSER_DIR / 'user_data'
CACHE_DIR = BROWSER_DIR / 'cache'
DEDUP_FILE = APP_DIR / 'contacted_fingerprints.json'
LOG_ROOT = APP_DIR / 'logs'
DEBUG_PORT = 9333

DEF = {
    'job': '采购专员',
    'exclude_words': '兼职,实习,在读,学生,猎头',
    'include_words': '',
    'include_mode': '包含任一词',
    'greeting': '您好！我们公司正在招聘{职位}，看到您的简历非常契合，诚邀了解一下，期待您的回复！\n您好，我们正在招聘{职位}，您的经历与岗位方向很匹配，方便聊一下吗？',
    'iMin': '机器自适应',
    'iMax': '机器自适应',
    'maxN': '100',
    'gender': '不限',
    'gender_unknown_pass': '1',
    'active_filter': '不限',
    'company_include': '',
    'company_block': '',
    'age_min': '不限',
    'age_max': '不限',
    'education_filter': '不限',
    'salary_min_k': '',
    'salary_max_k': '',
    'job_hop_filter': '不限',
    'daily_max': '150',
    'work_start': '09:00',
    'work_end': '22:00',
    'work_start_enabled': '1',
    'work_end_enabled': '1',
    'break_after_min': '0',
    'break_pause_min_sec': '30',
    'break_pause_max_sec': '300',
    'daily_count': '0',
    'daily_count_date': '',
    'weekly_count': '0',
    'weekly_count_key': '',
}

ACTIVE_LEVELS = {
    '刚刚活跃': 0,
    '今日活跃': 1,
    '3日内活跃': 2,
    '本周活跃': 3,
    '不限': 99,
}
ACTIVE_PATTERNS = [
    ('刚刚活跃', re.compile(r'刚刚活跃')),
    ('今日活跃', re.compile(r'今日活跃|日内活跃')),
    ('3日内活跃', re.compile(r'3日内活跃|近3日活跃')),
    ('本周活跃', re.compile(r'本周活跃')),
]

MODE_DISPLAY_TO_INTERNAL = {
    '包含任一词': '任一',
    '必须全部词': '全部',
    '关闭包含词': '关闭',
    '任一': '任一',
    '全部': '全部',
    '关闭': '关闭',
}
MODE_INTERNAL_TO_DISPLAY = {
    '任一': '包含任一词',
    '全部': '必须全部词',
    '关闭': '关闭包含词',
}
EDU_RANK = {
    '不限': 0,
    '初中及以下': 1,
    '中专/中技': 2,
    '高中': 3,
    '大专': 4,
    '本科': 5,
    '硕士': 6,
    '博士': 7,
}
EDU_PATTERNS = [
    ('博士', re.compile(r'博士')),
    ('硕士', re.compile(r'硕士|研究生')),
    ('本科', re.compile(r'本科')),
    ('大专', re.compile(r'大专|专科')),
    ('高中', re.compile(r'高中')),
    ('中专/中技', re.compile(r'中专/中技|中专|中技')),
    ('初中及以下', re.compile(r'初中及以下|初中')),
]

HOP_FILTER_LIMITS = {
    '不限': None,
    '不超过3次/3年': 3,
    '不超过2次/3年': 2,
    '不超过1次/3年': 1,
}


def load_cfg():
    c = dict(DEF)
    try:
        if os.path.exists(CFG_FILE):
            raw = json.load(open(CFG_FILE, encoding='utf-8'))
            if 'filters' in raw and 'exclude_words' not in raw:
                raw['exclude_words'] = raw.get('filters', '')
            if str(raw.get('daily_max', '')).strip() in {'', '60', '100'}:
                raw['daily_max'] = '150'
            if str(raw.get('work_start_enabled', '')).strip() == '':
                raw['work_start_enabled'] = c.get('work_start_enabled', '1')
            if str(raw.get('work_end_enabled', '')).strip() == '':
                raw['work_end_enabled'] = c.get('work_end_enabled', '1')
            if str(raw.get('break_after_min', '')).strip() == '':
                raw['break_after_min'] = c.get('break_after_min', '0')
            if str(raw.get('break_pause_min_sec', '')).strip() == '':
                raw['break_pause_min_sec'] = c.get('break_pause_min_sec', '30')
            if str(raw.get('break_pause_max_sec', '')).strip() == '':
                raw['break_pause_max_sec'] = c.get('break_pause_max_sec', '300')
            c.update(raw)
    except Exception:
        pass
    return c


def save_cfg(c):
    try:
        json.dump(c, open(CFG_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    except Exception:
        pass


def _read_reg_app_path(name):
    try:
        import winreg
    except Exception:
        return None
    keys = [
        (winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\App Paths'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths'),
    ]
    for root, sub in keys:
        try:
            with winreg.OpenKey(root, sub + '\\' + name) as k:
                val, _ = winreg.QueryValueEx(k, None)
                if val:
                    return val
        except Exception:
            pass
    return None


def find_browser_path():
    # 优先用 Chrome（对 DrissionPage 远程调试最稳定），找不到再用 Edge 兜底
    local = os.environ.get('LOCALAPPDATA', '')
    pf = os.environ.get('PROGRAMFILES', '')
    pfx86 = os.environ.get('PROGRAMFILES(X86)', '')
    chrome_candidates = [
        os.path.join(local, 'Google', 'Chrome', 'Bin', 'chrome.exe'),
        os.path.join(pf, 'Google', 'Chrome', 'Bin', 'chrome.exe'),
        os.path.join(pfx86, 'Google', 'Chrome', 'Bin', 'chrome.exe'),
        os.path.join(local, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(pfx86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    ]
    edge_candidates = [
        os.path.join(local, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(pfx86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    ]
    reg_chrome = _read_reg_app_path('chrome.exe')
    if reg_chrome:
        chrome_candidates.append(reg_chrome)
    reg_edge = _read_reg_app_path('msedge.exe')
    if reg_edge:
        edge_candidates.append(reg_edge)
    for name in ('chrome.exe', 'chrome'):
        p = shutil.which(name)
        if p:
            chrome_candidates.append(p)
    for name in ('msedge.exe', 'msedge'):
        p = shutil.which(name)
        if p:
            edge_candidates.append(p)

    found_chrome = []
    for p in chrome_candidates:
        if p and os.path.exists(p) and p not in found_chrome:
            found_chrome.append(p)
    found_edge = []
    for p in edge_candidates:
        if p and os.path.exists(p) and p not in found_edge:
            found_edge.append(p)

    if found_chrome:
        return found_chrome[0], found_chrome + found_edge
    if found_edge:
        return found_edge[0], found_edge
    return None, []


def wait_debug_port(port, timeout=15):
    import socket
    if requests is None:
        return False, 'requests 未安装，无法检测调试端口。'
    url = f'http://127.0.0.1:{port}/json/version'
    end = time.time() + timeout
    last_err = ''
    sess = requests.Session()
    sess.trust_env = False
    while time.time() < end:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1.2):
                pass
            r = sess.get(url, timeout=1.5, proxies={'http': None, 'https': None})
            if r.ok and 'Browser' in r.text:
                return True, r.text[:300]
            last_err = f'HTTP {r.status_code}'
        except Exception as e:
            last_err = str(e)
        time.sleep(0.5)
    return False, last_err


class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind('<Enter>', self.show)
        widget.bind('<Leave>', self.hide)

    def show(self, _event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{x}+{y}')
        label = tk.Label(
            tw,
            text=self.text,
            justify='left',
            bg='#111827',
            fg='white',
            relief='solid',
            borderwidth=1,
            padx=8,
            pady=6,
            font=('微软雅黑', 9),
            wraplength=260,
        )
        label.pack()

    def hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class App:
    def __init__(self, root):
        self.root = root
        self.root.title('星途招聘助手')

        self.browser = None
        self.page = None
        self.browser_proc = None
        self.running = False
        self.paused = False
        self.stop_requested = False
        self.opening = False
        self.cfg = load_cfg()
        self.cnt = {'ok': 0, 'skip': 0, 'fail': 0, 'sniffed': 0}
        self.processed_fp = set()
        self.run_dir = None
        self.log_file_path = None
        self.journal_file_path = None
        self.matched_csv_path = None
        self.skipped_csv_path = None
        self.last_scroll_debug = ''
        self.marquee_entries = []
        self.marquee_paused = False
        self.marquee_text_id = None
        self.ai_panel = None
        self._ai_panel_import_error = ''
        try:
            from ai_panel import AIPanel
            self.ai_panel = AIPanel(
                self.root,
                get_page=lambda: self.page,
                job_title_getter=lambda: self.v_job.get(),
                main_log=self.log,
                constraints_getter=self._ai_constraints_text,
                main_running_getter=lambda: self.running,
            )
        except Exception as e:
            self._ai_panel_import_error = f'{type(e).__name__}: {e}'
        self._build()
        self._update_daily_display()

    def _open_ai_panel(self):
        if self.ai_panel is None:
            messagebox.showerror(
                'AI功能未就绪',
                'AI模块加载失败，请确认 ai_modules 文件夹与 boss_recruiter.py 在同一目录下，'
                '并已安装 requests 库。\n\n错误详情：\n' + (self._ai_panel_import_error or '未知'))
            return
        self.ai_panel.open_advanced()

    # ---------- UI ----------
    def _help_icon(self, parent, text, row, col):
        lbl = tk.Label(parent, text='*', font=('微软雅黑', 10),
                       fg='#9ca3af', bg='white',
                       cursor='question_arrow')
        lbl.grid(row=row, column=col, sticky='e', padx=(6, 0))
        ToolTip(lbl, text)
        return lbl

    def _section(self, parent, title):
        return tk.LabelFrame(
            parent,
            text=f'  {title}  ',
            font=('微软雅黑', 9, 'bold'),
            bg='white',
            fg='#333',
            bd=0,
            highlightbackground='#e0e3e8',
            highlightcolor='#e0e3e8',
            highlightthickness=1,
            padx=10,
            pady=6,
            relief='flat',
        )

    def _hover_color(self, hex_color, factor=0.86):
        c = (hex_color or '').lstrip('#')
        try:
            r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return hex_color
        return '#%02x%02x%02x' % (int(r * factor), int(g * factor), int(b * factor))

    def _bind_hover(self, w, base, hover=None):
        hover = hover or self._hover_color(base)
        def _enter(_e):
            if str(w.cget('state')) != 'disabled':
                w.config(bg=hover)
        def _leave(_e):
            w.config(bg=base)
        w.bind('<Enter>', _enter)
        w.bind('<Leave>', _leave)

    def _apply_focus_style(self):
        try:
            st = ttk.Style(self.root)
            st.map('TCombobox', fieldbackground=[('focus', '#eaf1ff'), ('!focus', 'white')])
        except Exception:
            pass
        try:
            ttk.Style(self.root).map('TCombobox', bordercolor=[('focus', '#2563eb')])
        except Exception:
            pass
        def _walk(w):
            for child in list(w.winfo_children()):
                try:
                    if isinstance(child, tk.Entry) and not isinstance(child, ttk.Entry):
                        child.config(highlightthickness=1,
                                     highlightbackground='#d1d5db',
                                     highlightcolor='#2563eb')
                except Exception:
                    pass
                _walk(child)
        _walk(self.root)

    def _build(self):
        self.root.geometry('1480x1020')
        self.root.minsize(1300, 900)
        self.root.configure(bg='#f2f3f5')

        header = tk.Frame(self.root, bg='#1e1e2e', height=76)
        header.pack(fill='x')
        header.pack_propagate(False)
        tk.Label(
            header, text='星途招聘助手',
            font=('微软雅黑', 17, 'bold'),
            fg='white', bg='#1e1e2e'
        ).pack(anchor='w', padx=24, pady=(14, 2))
        tk.Label(
            header,
            text='智能筛选 · 多话术',
            font=('微软雅黑', 9),
            fg='#9db8e8', bg='#1e1e2e'
        ).pack(anchor='w', padx=24)

        top_cards = tk.Frame(self.root, bg='#f2f3f5', pady=8)
        top_cards.pack(fill='x', padx=16)
        self.card_browser = tk.Label(top_cards, text='浏览器：未连接', bg='white', fg='#333',
                                     font=('微软雅黑', 10), padx=10, pady=8,
                                     highlightbackground='#e0e3e8', highlightthickness=1)
        self.card_browser.pack(side='left', fill='x', expand=True, padx=(0, 6))
        self.card_run = tk.Label(top_cards, text='运行状态：待机', bg='white', fg='#333',
                                 font=('微软雅黑', 10), padx=10, pady=8,
                                 highlightbackground='#e0e3e8', highlightthickness=1)
        self.card_run.pack(side='left', fill='x', expand=True, padx=6)
        self.card_today = tk.Label(top_cards, text='今日沟通：0 / 150', bg='white', fg='#333',
                                   font=('微软雅黑', 10), padx=10, pady=8,
                                   highlightbackground='#e0e3e8', highlightthickness=1)
        self.card_today.pack(side='left', fill='x', expand=True, padx=6)
        self.card_week = tk.Label(top_cards, text='本周沟通：0', bg='white', fg='#333',
                                  font=('微软雅黑', 10), padx=10, pady=8,
                                  highlightbackground='#e0e3e8', highlightthickness=1)
        self.card_week.pack(side='left', fill='x', expand=True, padx=6)
        self.card_sniffed = tk.Label(top_cards, text='筛选简历：0', bg='white', fg='#333',
                                     font=('微软雅黑', 10), padx=10, pady=8,
                                     highlightbackground='#e0e3e8', highlightthickness=1)
        self.card_sniffed.pack(side='left', fill='x', expand=True, padx=(6, 0))
        for _c in (self.card_browser, self.card_run, self.card_today, self.card_week, self.card_sniffed):
            self._bind_hover(_c, 'white', '#eef2f7')

        # 左侧面板加滚动条，防止内容过多时按钮被挤出窗口
        main = tk.Frame(self.root, bg='#f2f3f5')
        main.pack(fill='both', expand=True, padx=16, pady=(2, 12))
        main.grid_columnconfigure(0, weight=0)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        left_col = tk.Frame(main, bg='#f2f3f5')
        left_col.grid(row=0, column=0, sticky='nsew')
        left_col.grid_rowconfigure(0, weight=1)
        left_col.grid_columnconfigure(0, weight=1)

        left_canvas = tk.Canvas(left_col, bg='#f2f3f5', width=720, highlightthickness=0, bd=0)
        left_canvas.grid(row=0, column=0, sticky='nsew')
        left = tk.Frame(left_canvas, bg='#f2f3f5')
        left_canvas.create_window((0, 0), window=left, anchor='nw')

        def _on_left_cfg(e):
            left_canvas.itemconfig('all', width=e.width)
            left_canvas.configure(scrollregion=left_canvas.bbox('all'))

        left.bind('<Configure>', _on_left_cfg)
        left_canvas.bind('<Configure>', _on_left_cfg)
        # 鼠标滚轮支持
        def _on_mousewheel(e):
            left_canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        left_canvas.bind('<Enter>', lambda e: left_canvas.bind_all('<MouseWheel>', _on_mousewheel))
        left_canvas.bind('<Leave>', lambda e: left_canvas.unbind_all('<MouseWheel>'))
        right = tk.Frame(main, bg='#f2f3f5')
        right.grid(row=0, column=1, sticky='nsew', padx=(16, 0))
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        cfg = self.cfg
        self.v_job = tk.StringVar(value=cfg['job'])
        self.v_include = tk.StringVar(value=cfg.get('include_words', ''))
        self.v_active = tk.StringVar(value=cfg.get('active_filter', '不限'))
        self.v_company_include = tk.StringVar(value=cfg.get('company_include', ''))
        self.v_company_block = tk.StringVar(value=cfg.get('company_block', ''))
        self.v_age_min = tk.StringVar(value=cfg.get('age_min', '不限'))
        self.v_age_max = tk.StringVar(value=cfg.get('age_max', '不限'))
        self.v_exclude = tk.StringVar(value=cfg.get('exclude_words', ''))
        self.v_gender = tk.StringVar(value=cfg.get('gender', '不限'))
        self.v_gender_unknown_pass = tk.BooleanVar(value=str(cfg.get('gender_unknown_pass', '1')) != '0')
        self.v_edu = tk.StringVar(value=cfg.get('education_filter', '不限'))
        self.v_salary_min = tk.StringVar(value=cfg.get('salary_min_k', ''))
        self.v_salary_max = tk.StringVar(value=cfg.get('salary_max_k', ''))
        self.v_hop_filter = tk.StringVar(value=cfg.get('job_hop_filter', '不限'))
        self.v_imin = tk.StringVar(value=cfg.get('iMin', '机器自适应'))
        self.v_imax = tk.StringVar(value=cfg.get('iMax', '机器自适应'))
        self.v_maxn = tk.StringVar(value=cfg['maxN'])
        self.v_daily_max = tk.StringVar(value=cfg.get('daily_max', '150'))
        self.v_work_start = tk.StringVar(value=cfg.get('work_start', '09:00'))
        self.v_work_end = tk.StringVar(value=cfg.get('work_end', '22:00'))
        self.v_work_start_enabled = tk.BooleanVar(value=str(cfg.get('work_start_enabled', '1')) == '1')
        self.v_work_end_enabled = tk.BooleanVar(value=str(cfg.get('work_end_enabled', '1')) == '1')
        self.v_break_after_min = tk.StringVar(value=cfg.get('break_after_min', '0'))
        self.v_break_pause_min_sec = tk.StringVar(value=cfg.get('break_pause_min_sec', '30'))
        self.v_break_pause_max_sec = tk.StringVar(value=cfg.get('break_pause_max_sec', '300'))

        age_values = ['不限'] + [str(i) for i in range(18, 61)]
        time_values = [f'{h:02d}:{m:02d}' for h in range(24) for m in (0, 30)]
        interval_values = ['机器自适应', '10', '15', '20', '25', '30', '40', '50', '60', '75', '90', '120', '150', '180']
        limit_values = [str(i) for i in range(10, 501, 10)]
        degree_values = ['不限', '初中及以下', '中专/中技', '高中', '大专', '本科', '硕士', '博士']
        active_values = ['不限', '刚刚活跃', '今日活跃', '3日内活跃', '本周活跃']

        s1 = self._section(left, '精准筛选')
        s1.pack(fill='x', pady=(0, 4))
        for i in range(1, 5):
            s1.grid_columnconfigure(i, weight=1)

        tk.Label(s1, text='招聘岗位：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=0, column=0, sticky='w')
        tk.Entry(s1, textvariable=self.v_job, font=('微软雅黑', 10), relief='solid', bd=1).grid(row=0, column=1, columnspan=3, sticky='ew', padx=(8, 0))
        self._help_icon(s1, '用于岗位匹配，例如“结构工程师”会自动抽取“结构工程师 / 结构”作为岗位关键词。', 0, 4)

        tk.Label(s1, text='简历关键词：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=1, column=0, sticky='w', pady=(6, 0))
        tk.Entry(s1, textvariable=self.v_include, font=('微软雅黑', 10), relief='solid', bd=1).grid(row=1, column=1, columnspan=3, sticky='ew', padx=(8, 0), pady=(6, 0))
        self._help_icon(s1, '例如：ebike, 电动自行车, 自行车。多个关键词用逗号分隔，默认命中任一词；会在简历摘要、工作经历、优势说明等整段文本里检索。', 1, 4)

        tk.Label(s1, text='活跃度：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=2, column=0, sticky='w', pady=(6, 0))
        ttk.Combobox(s1, textvariable=self.v_active, values=active_values, state='readonly', width=12).grid(row=2, column=1, sticky='w', padx=(8, 0), pady=(6, 0))
        tk.Label(s1, text='目标公司词：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=2, column=2, sticky='e', pady=(6, 0))
        tk.Entry(s1, textvariable=self.v_company_include, font=('微软雅黑', 10), relief='solid', bd=1).grid(row=2, column=3, sticky='ew', padx=(8, 0), pady=(6, 0))
        self._help_icon(s1, '选择“今日活跃”时，会放行“刚刚活跃 + 今日活跃”；填写目标公司词时，至少命中其一才放行。', 2, 4)

        tk.Label(s1, text='屏蔽公司词：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=3, column=0, sticky='w', pady=(6, 0))
        tk.Entry(s1, textvariable=self.v_company_block, font=('微软雅黑', 10), relief='solid', bd=1).grid(row=3, column=1, columnspan=3, sticky='ew', padx=(8, 0), pady=(6, 0))
        self._help_icon(s1, '命中任一屏蔽公司词即排除，例如：外包、劳务派遣、代招。多个词用逗号分隔。', 3, 4)

        tk.Label(s1, text='年龄：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=4, column=0, sticky='w', pady=(6, 0))
        age_frame = tk.Frame(s1, bg='white')
        age_frame.grid(row=4, column=1, sticky='w', padx=(8, 0), pady=(6, 0))
        ttk.Combobox(age_frame, textvariable=self.v_age_min, values=age_values, width=7, state='readonly').pack(side='left')
        tk.Label(age_frame, text='至', bg='white', fg='#475569', font=('微软雅黑', 9)).pack(side='left', padx=4)
        ttk.Combobox(age_frame, textvariable=self.v_age_max, values=age_values, width=7, state='readonly').pack(side='left')
        tk.Label(s1, text='排除：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=4, column=2, sticky='e', pady=(6, 0))
        tk.Entry(s1, textvariable=self.v_exclude, font=('微软雅黑', 10), relief='solid', bd=1).grid(row=4, column=3, sticky='ew', padx=(8, 0), pady=(6, 0))
        self._help_icon(s1, '排除词优先级最高，例如：兼职、实习、在读、学生、猎头。', 4, 4)

        tk.Label(s1, text='性别：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=5, column=0, sticky='w', pady=(6, 0))
        gender_wrap = tk.Frame(s1, bg='white')
        gender_wrap.grid(row=5, column=1, sticky='w', padx=(8, 0), pady=(6, 0))
        ttk.Combobox(gender_wrap, textvariable=self.v_gender, values=['不限', '男', '女'], width=7, state='readonly').pack(side='left')
        tk.Checkbutton(gender_wrap, text='未知放行', variable=self.v_gender_unknown_pass, bg='white', fg='#475569', font=('微软雅黑', 9), activebackground='white').pack(side='left', padx=(8, 0))
        tk.Label(s1, text='学历：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=5, column=2, sticky='e', pady=(6, 0))
        ttk.Combobox(s1, textvariable=self.v_edu, values=degree_values, width=12, state='readonly').grid(row=5, column=3, sticky='w', padx=(8, 0), pady=(6, 0))
        self._help_icon(s1, '学历按最低要求放行，例如选“本科”则硕士、博士也放行。', 5, 4)

        tk.Label(s1, text='薪资：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=6, column=0, sticky='w', pady=(6, 0))
        salary_frame = tk.Frame(s1, bg='white')
        salary_frame.grid(row=6, column=1, sticky='w', padx=(8, 0), pady=(6, 0))
        tk.Entry(salary_frame, textvariable=self.v_salary_min, font=('微软雅黑', 10), relief='solid', bd=1, width=7).pack(side='left')
        tk.Label(salary_frame, text='~', bg='white', fg='#475569', font=('微软雅黑', 9)).pack(side='left', padx=4)
        tk.Entry(salary_frame, textvariable=self.v_salary_max, font=('微软雅黑', 10), relief='solid', bd=1, width=7).pack(side='left')
        tk.Label(salary_frame, text='K/月', bg='white', fg='#64748b', font=('微软雅黑', 9)).pack(side='left', padx=(6, 0))
        tk.Label(s1, text='跳槽频率：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=6, column=2, sticky='e', pady=(6, 0))
        ttk.Combobox(s1, textvariable=self.v_hop_filter, values=['不限', '不超过3次/3年', '不超过2次/3年', '不超过1次/3年'], width=14, state='readonly').grid(row=6, column=3, sticky='w', padx=(8, 0), pady=(6, 0))
        self._help_icon(s1, '薪资按候选人预期薪资区间过滤；跳槽频率仅在卡片明确写出“X年/X家公司”之类信息时才会触发过滤，避免误报。', 6, 4)

        s2 = self._section(left, '执行计划')
        s2.pack(fill='x', pady=(0, 4))
        for i in range(1, 6):
            s2.grid_columnconfigure(i, weight=1)
        tk.Label(s2, text='定时开始时间：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=0, column=0, sticky='w')
        start_wrap = tk.Frame(s2, bg='white')
        start_wrap.grid(row=0, column=1, sticky='w', padx=(8, 0))
        tk.Checkbutton(start_wrap, text='启用', variable=self.v_work_start_enabled, bg='white', fg='#475569', font=('微软雅黑', 9), activebackground='white').pack(side='left')
        ttk.Combobox(start_wrap, textvariable=self.v_work_start, values=time_values, width=10, state='readonly').pack(side='left', padx=(6, 0))
        tk.Label(s2, text='定时结束时间：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=0, column=2, sticky='e')
        end_wrap = tk.Frame(s2, bg='white')
        end_wrap.grid(row=0, column=3, sticky='w', padx=(8, 0))
        tk.Checkbutton(end_wrap, text='启用', variable=self.v_work_end_enabled, bg='white', fg='#475569', font=('微软雅黑', 9), activebackground='white').pack(side='left')
        ttk.Combobox(end_wrap, textvariable=self.v_work_end, values=time_values, width=10, state='readonly').pack(side='left', padx=(6, 0))
        self._help_icon(s2, '开始时间和结束时间只有在勾选“启用”后才会生效；两项都不勾选时，不启用定时限制。', 0, 4)

        tk.Label(s2, text='最短间隔时间：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=1, column=0, sticky='w', pady=(6, 0))
        ttk.Combobox(s2, textvariable=self.v_imin, values=interval_values, width=12, state='normal').grid(row=1, column=1, sticky='w', padx=(8, 0), pady=(6, 0))
        tk.Label(s2, text='最长间隔时间：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=1, column=2, sticky='e', pady=(6, 0))
        ttk.Combobox(s2, textvariable=self.v_imax, values=interval_values, width=12, state='normal').grid(row=1, column=3, sticky='w', padx=(8, 0), pady=(6, 0))
        self._help_icon(s2, '单位为秒，可手动输入更长时间，也可选择“机器自适应”让程序自动在较自然的区间内随机等待。', 1, 4)

        tk.Label(s2, text='今天沟通上限：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=2, column=0, sticky='w', pady=(6, 0))
        ttk.Combobox(s2, textvariable=self.v_daily_max, values=limit_values, width=12, state='normal').grid(row=2, column=1, sticky='w', padx=(8, 0), pady=(6, 0))
        self.btn_reset_daily = tk.Button(s2, text='恢复150', command=self._reset_daily_limit_default, font=('微软雅黑', 9), relief='flat', bg='#e5eefc', fg='#0a2f6b', padx=10, pady=5, cursor='hand2')
        self.btn_reset_daily.grid(row=2, column=2, sticky='w', padx=(8, 0), pady=(6, 0))
        self._bind_hover(self.btn_reset_daily, '#e5eefc')
        tk.Label(s2, text='单轮扫描上限：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=2, column=3, sticky='e', pady=(6, 0))
        ttk.Combobox(s2, textvariable=self.v_maxn, values=limit_values, width=12, state='normal').grid(row=2, column=4, sticky='w', padx=(8, 0), pady=(6, 0))
        self._help_icon(s2, '今天沟通上限默认 150，可手动修改；单轮扫描上限用于控制本次运行最多处理多少位候选人。', 2, 5)

        tk.Label(s2, text='连续运行时长：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=3, column=0, sticky='w', pady=(6, 0))
        break_run_frame = tk.Frame(s2, bg='white')
        break_run_frame.grid(row=3, column=1, sticky='w', padx=(8, 0), pady=(6, 0))
        tk.Entry(break_run_frame, textvariable=self.v_break_after_min, font=('微软雅黑', 10), relief='solid', bd=1, width=8).pack(side='left')
        tk.Label(break_run_frame, text='分钟', bg='white', fg='#64748b', font=('微软雅黑', 9)).pack(side='left', padx=(6, 0))
        tk.Label(s2, text='暂停时长：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=3, column=2, sticky='e', pady=(6, 0))
        break_pause_frame = tk.Frame(s2, bg='white')
        break_pause_frame.grid(row=3, column=3, sticky='w', padx=(8, 0), pady=(6, 0))
        tk.Entry(break_pause_frame, textvariable=self.v_break_pause_min_sec, font=('微软雅黑', 10), relief='solid', bd=1, width=7).pack(side='left')
        tk.Label(break_pause_frame, text='~', bg='white', fg='#475569', font=('微软雅黑', 9)).pack(side='left', padx=4)
        tk.Entry(break_pause_frame, textvariable=self.v_break_pause_max_sec, font=('微软雅黑', 10), relief='solid', bd=1, width=7).pack(side='left')
        tk.Label(break_pause_frame, text='秒', bg='white', fg='#64748b', font=('微软雅黑', 9)).pack(side='left', padx=(6, 0))
        self._help_icon(s2, '连续运行多少分钟后，中途暂停一次；暂停时长可设置为 30 秒到 2 小时。暂停时会模拟点击左侧其他模块，再自动回到“推荐牛人”。填 0 表示关闭此功能。', 3, 4)

        tk.Label(s2, text='今天沟通次数：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=4, column=0, sticky='w', pady=(10, 0))
        self.lab_plan_today = tk.Label(s2, text='0', bg='#f8fafc', fg='#0a2f6b', font=('微软雅黑', 10, 'bold'), relief='solid', bd=1, padx=12, pady=6)
        self.lab_plan_today.grid(row=4, column=1, sticky='w', padx=(8, 0), pady=(10, 0))
        tk.Label(s2, text='本周沟通次数：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=4, column=2, sticky='e', pady=(10, 0))
        self.lab_plan_week = tk.Label(s2, text='0', bg='#f8fafc', fg='#0a2f6b', font=('微软雅黑', 10, 'bold'), relief='solid', bd=1, padx=12, pady=6)
        self.lab_plan_week.grid(row=4, column=3, sticky='w', padx=(8, 0), pady=(10, 0))

        tk.Label(s2, text='筛选简历数：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=5, column=0, sticky='w', pady=(6, 0))
        self.lab_plan_sniffed = tk.Label(s2, text='0', bg='#f8fafc', fg='#0a2f6b', font=('微软雅黑', 10, 'bold'), relief='solid', bd=1, padx=12, pady=6)
        self.lab_plan_sniffed.grid(row=5, column=1, sticky='w', padx=(8, 0), pady=(6, 0))
        tk.Label(s2, text='说明：', bg='white', fg='#64748b', font=('微软雅黑', 9)).grid(row=5, column=2, sticky='e', pady=(6, 0))
        tk.Label(s2, text='筛选简历数 = 本轮累计嗅探并判定过的候选人数量', bg='white', fg='#64748b', font=('微软雅黑', 9), wraplength=220, justify='left').grid(row=5, column=3, sticky='w', padx=(8, 0), pady=(6, 0))

        s3 = self._section(left, '沟通话术')
        s3.pack(fill='x', pady=(0, 4))
        s3.grid_columnconfigure(1, weight=1)
        tk.Label(s3, text='话术模板：', bg='white', fg='#1f2937', font=('微软雅黑', 10)).grid(row=0, column=0, sticky='nw')
        self.txt_greet = tk.Text(s3, height=4, font=('微软雅黑', 10), relief='solid', bd=1, wrap='word')
        self.txt_greet.insert('1.0', cfg['greeting'])
        self.txt_greet.grid(row=0, column=1, sticky='ew', padx=(8, 0))
        self._help_icon(s3, '支持多行模板：每一行视为一条独立话术，发送时会随机抽取其中一条；支持变量 {职位}。', 0, 2)


        btn_row = tk.Frame(left, bg='#f2f3f5')
        btn_row.pack(fill='x', pady=(2, 4))
        for i in range(5):
            btn_row.grid_columnconfigure(i, weight=1, uniform='btn')
        btn_style = dict(fg='white', font=('微软雅黑', 11), relief='flat', bd=0, padx=10, pady=8, cursor='hand2')
        self.btn_open = tk.Button(btn_row, text='① 启动浏览器', command=self._open, bg='#1d4ed8', **btn_style)
        self.btn_open.grid(row=0, column=0, sticky='ew', padx=(0, 3))
        self.btn_start = tk.Button(btn_row, text='② 开始招聘', command=self._start, bg='#0f9d7a', **btn_style)
        self.btn_start.grid(row=0, column=1, sticky='ew', padx=3)
        self.btn_pause = tk.Button(btn_row, text='暂停', command=self._pause, bg='#f59e0b', state='disabled', **btn_style)
        self.btn_pause.grid(row=0, column=2, sticky='ew', padx=3)
        self.btn_stop = tk.Button(btn_row, text='停止', command=self._stop, bg='#dc2626', state='disabled', **btn_style)
        self.btn_stop.grid(row=0, column=3, sticky='ew', padx=3)
        self.btn_reset = tk.Button(btn_row, text='重置', command=self._reset_all_settings, bg='#64748b', **btn_style)
        self.btn_reset.grid(row=0, column=4, sticky='ew', padx=(3, 0))
        for _b, _base in ((self.btn_open, '#1d4ed8'), (self.btn_start, '#0f9d7a'),
                          (self.btn_pause, '#f59e0b'), (self.btn_stop, '#dc2626'),
                          (self.btn_reset, '#64748b')):
            self._bind_hover(_b, _base)

        # AI快捷操作：知识库入口 + 启停按钮，常驻不折叠，紧跟在①②按钮组下方，填补这里原本的空白
        if self.ai_panel is not None:
            ai_quick = self.ai_panel.build_quick_actions(left)
            ai_quick.pack(fill='x', pady=(6, 4))
        else:
            ai_err = self._section(left, 'AI自动回复 / 复聊唤醒')
            ai_err.pack(fill='x', pady=(6, 4))
            tk.Label(ai_err, text=f'AI模块加载失败：{self._ai_panel_import_error}\n请确认 ai_modules 文件夹与本文件在同一目录下。',
                     bg='white', fg='#dc2626', justify='left', wraplength=680).pack(anchor='w')

        # AI完整设置面板（可折叠，默认收起）放在左下角（原"滚动播报"的位置，见下方 left_col row=1）
        if self.ai_panel is not None:
            ai_full = self.ai_panel.build_full_panel(left_col)
            ai_full.grid(row=1, column=0, sticky='ew', pady=(8, 0))

        # 滚动播报组件仍在后台创建（内部逻辑多处引用），只是不再显示在界面上
        marquee_sec = self._section(left_col, '滚动播报')
        marquee_row = tk.Frame(marquee_sec, bg='white')
        marquee_row.pack(fill='x', padx=5, pady=(0, 4))
        marquee_row.grid_columnconfigure(0, weight=1)
        marquee_row.grid_columnconfigure(1, minsize=14)
        marquee_row.grid_columnconfigure(2, weight=0)

        marquee_box = tk.Frame(marquee_row, bg='white', highlightbackground='#e0e3e8', highlightthickness=1, bd=0)
        marquee_box.grid(row=0, column=0, sticky='nsew')
        self.marquee_canvas = tk.Canvas(marquee_box, height=44, bg='#f7f8fa', highlightthickness=0, bd=0)
        self.marquee_canvas.pack(fill='x', expand=True, padx=1, pady=1)

        btn_box = tk.Frame(marquee_row, bg='white')
        btn_box.grid(row=0, column=2, sticky='e')
        marquee_btn_style = dict(font=('微软雅黑', 10), relief='flat', fg='white', padx=16, pady=10, cursor='hand2')
        self.btn_marquee_pause = tk.Button(btn_box, text='暂停播报', command=self._toggle_marquee_pause, bg='#555', **marquee_btn_style)
        self.btn_marquee_pause.pack(side='left', padx=(0, 8), fill='y')
        self.btn_marquee_clear = tk.Button(btn_box, text='清空播报', command=self._clear_marquee, bg='#888', **marquee_btn_style)
        self.btn_marquee_clear.pack(side='left', fill='y')
        self._bind_hover(self.btn_marquee_pause, '#555')
        self._bind_hover(self.btn_marquee_clear, '#888')

        self.marquee_canvas.bind('<Configure>', lambda e: self._refresh_marquee())
        self.root.after(200, self._start_marquee_anim)

        right_status = self._section(right, '运行概览')
        right_status.grid(row=0, column=0, sticky='ew')
        right_status.grid_columnconfigure(1, weight=1)
        self.v_status = tk.StringVar(value='就绪：请先启动浏览器')
        self.v_cnt = tk.StringVar(value='成功 0    跳过 0    失败 0    筛选 0')
        tk.Label(right_status, text='当前状态', bg='white', fg='#64748b', font=('微软雅黑', 9)).grid(row=0, column=0, sticky='w')
        tk.Label(right_status, textvariable=self.v_status, bg='white', fg='#333', font=('微软雅黑', 11, 'bold')).grid(row=0, column=1, sticky='w')
        tk.Label(right_status, text='本次统计', bg='white', fg='#888', font=('微软雅黑', 9)).grid(row=1, column=0, sticky='w', pady=(6, 0))
        tk.Label(right_status, textvariable=self.v_cnt, bg='white', fg='#333', font=('微软雅黑', 11, 'bold')).grid(row=1, column=1, sticky='w', pady=(6, 0))

        right_export = self._section(right, '运行结果与导出')
        right_export.grid(row=1, column=0, sticky='ew', pady=(10, 10))
        tk.Label(right_export, text='本次运行会自动生成 run.log、journal.jsonl、matched_candidates.csv、skipped_candidates.csv 和异常截图。', bg='white', fg='#475569', font=('微软雅黑', 9), justify='left', wraplength=700).pack(anchor='w')
        exp_btn = tk.Frame(right_export, bg='white')
        exp_btn.pack(fill='x', pady=(6, 0))
        self.btn_open_logdir = tk.Button(exp_btn, text='打开日志目录', command=self._open_log_dir, font=('微软雅黑', 9), relief='flat', bg='#555', fg='white', padx=12, pady=6)
        self.btn_open_logdir.pack(side='left')
        self.btn_clear_log = tk.Button(exp_btn, text='清空日志窗口', command=self._clear_log, font=('微软雅黑', 9), relief='flat', bg='#777', fg='white', padx=12, pady=6)
        self.btn_clear_log.pack(side='left', padx=(8, 0))
        self._bind_hover(self.btn_open_logdir, '#555')
        self._bind_hover(self.btn_clear_log, '#777')

        right_log = self._section(right, '实时日志')
        right_log.grid(row=2, column=0, sticky='nsew')
        self.log_box = scrolledtext.ScrolledText(right_log, font=('Consolas', 10), bg='#081a36', fg='#e5efff', relief='flat', wrap='word', state='disabled')
        self.log_box.pack(fill='both', expand=True, padx=5, pady=5)
        for tag, color in [('ok', '#67e8f9'), ('warn', '#fbbf24'), ('err', '#f87171'), ('info', '#93c5fd'), ('sep', '#60a5fa')]:
            self.log_box.tag_config(tag, foreground=color)
        self._apply_focus_style()

    # ---------- artifacts ----------
    def _ensure_run_artifacts(self):
        if self.run_dir and self.log_file_path and self.journal_file_path:
            return
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        self.run_dir = LOG_ROOT / ts
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_file_path = self.run_dir / 'run.log'
        self.journal_file_path = self.run_dir / 'journal.jsonl'
        self.matched_csv_path = self.run_dir / 'matched_candidates.csv'
        self.skipped_csv_path = self.run_dir / 'skipped_candidates.csv'
        self._init_csv(self.matched_csv_path, ['ts', 'tab', 'name', 'gender', 'age', 'education', 'active', 'job', 'salary', 'fp', 'matched_words', 'company_hits'])
        self._init_csv(self.skipped_csv_path, ['ts', 'tab', 'name', 'gender', 'age', 'education', 'active', 'job', 'salary', 'fp', 'reason', 'detail'])

    def _init_csv(self, path, header):
        if path.exists():
            return
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            csv.writer(f).writerow(header)

    def _append_csv(self, path, row):
        try:
            with open(path, 'a', encoding='utf-8-sig', newline='') as f:
                csv.writer(f).writerow(row)
        except Exception:
            pass

    def _append_file_line(self, path, line):
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception:
            pass

    def _record_event(self, kind, **data):
        self._ensure_run_artifacts()
        payload = {'ts': datetime.datetime.now().isoformat(timespec='seconds'), 'kind': kind, **data}
        self._append_file_line(self.journal_file_path, json.dumps(payload, ensure_ascii=False) + '\n')

    def _take_snapshot(self, name_prefix='snapshot'):
        try:
            if not self.page:
                return None
            self._ensure_run_artifacts()
            snap_dir = self.run_dir / 'screenshots'
            snap_dir.mkdir(parents=True, exist_ok=True)
            fp = snap_dir / f'{name_prefix}_{datetime.datetime.now().strftime("%H%M%S")}.png'
            self.page.get_screenshot(path=str(fp), full_page=False)
            return str(fp)
        except Exception:
            return None

    def _load_dedup(self):
        """加载跨会话已沟通候选人指纹"""
        try:
            if DEDUP_FILE.exists():
                data = json.loads(DEDUP_FILE.read_text(encoding='utf-8'))
                return set(data.get('fingerprints', []))
        except Exception:
            pass
        return set()

    def _save_dedup_fp(self, fp):
        """持久化一个已沟通指纹"""
        try:
            current = set()
            if DEDUP_FILE.exists():
                data = json.loads(DEDUP_FILE.read_text(encoding='utf-8'))
                current = set(data.get('fingerprints', []))
            current.add(fp)
            DEDUP_FILE.write_text(json.dumps(
                {'fingerprints': sorted(current), 'updated': datetime.datetime.now().isoformat()},
                ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass

    # ---------- helpers ----------
    def log(self, msg, tag='info'):
        self._ensure_run_artifacts()
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        line = f'[{ts}] {msg}\n'
        self._append_file_line(self.log_file_path, line)
        def _do():
            self.log_box.config(state='normal')
            self.log_box.insert('end', line, tag)
            self.log_box.config(state='disabled')
            self.log_box.see('end')
        self.root.after(0, _do)

    def log_sep(self, label):
        self.log(f'─── {label} ───', 'sep')

    def _clear_log(self):
        self.log_box.config(state='normal')
        self.log_box.delete('1.0', 'end')
        self.log_box.config(state='disabled')

    def _open_log_dir(self):
        self._ensure_run_artifacts()
        target = self.run_dir if self.run_dir else LOG_ROOT
        try:
            os.startfile(str(target))
        except Exception as e:
            messagebox.showinfo('日志目录', f'日志目录：{target}\n\n打开失败：{e}')

    def st(self, msg):
        self.root.after(0, lambda: self.v_status.set(msg))
        def _cards():
            self.card_run.config(text=f'运行状态：{msg}')
        self.root.after(0, _cards)

    def upd_cnt(self):
        def _():
            c = self.cnt
            self.v_cnt.set(f"✅{c['ok']}  ⏭{c['skip']}  ❌{c['fail']}  🔎{c.get('sniffed', 0)}")
        self.root.after(0, _)
        self.root.after(0, self._update_daily_display)

    def _update_daily_display(self):
        cfg = self.cfg
        today = datetime.date.today().isoformat()
        changed = False
        if cfg.get('daily_count_date') != today:
            cfg['daily_count_date'] = today
            cfg['daily_count'] = '0'
            changed = True
        week_key = self._get_week_key()
        if cfg.get('weekly_count_key') != week_key:
            cfg['weekly_count_key'] = week_key
            cfg['weekly_count'] = '0'
            changed = True
        if changed:
            save_cfg(cfg)
        used = int(str(cfg.get('daily_count', '0') or '0'))
        total = int(str(cfg.get('daily_max', '0') or '0')) if str(cfg.get('daily_max', '0')).isdigit() else 0
        week_used = int(str(cfg.get('weekly_count', '0') or '0'))
        sniffed = int(self.cnt.get('sniffed', 0) or 0)
        if hasattr(self, 'card_today'):
            self.card_today.config(text=f'今日沟通：{used} / {total or "∞"}')
        if hasattr(self, 'card_week'):
            self.card_week.config(text=f'本周沟通：{week_used}')
        if hasattr(self, 'card_sniffed'):
            self.card_sniffed.config(text=f'筛选简历：{sniffed}')
        if hasattr(self, 'lab_plan_today'):
            self.lab_plan_today.config(text=str(used))
        if hasattr(self, 'lab_plan_week'):
            self.lab_plan_week.config(text=str(week_used))
        if hasattr(self, 'lab_plan_sniffed'):
            self.lab_plan_sniffed.config(text=str(sniffed))

    def _normalize_text(self, text):
        return re.sub(r'\s+', ' ', str(text or '')).strip()

    def _parse_words(self, raw):
        text = str(raw or '')
        for sep in ['，', '；', ';', '\n', '|', '｜', '/', '、']:
            text = text.replace(sep, ',')
        return [w.strip() for w in text.split(',') if w.strip()]

    def _parse_time(self, s):
        s = self._normalize_text(s)
        m = re.match(r'^(\d{1,2}):(\d{2})$', s)
        if not m:
            raise ValueError('时间格式应为 HH:MM')
        h, mi = int(m.group(1)), int(m.group(2))
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            raise ValueError('时间无效')
        return datetime.time(h, mi)

    def _within_work_window(self):
        use_start = str(self.cfg.get('work_start_enabled', '1')) == '1'
        use_end = str(self.cfg.get('work_end_enabled', '1')) == '1'
        if not use_start and not use_end:
            return True, '未启用定时限制'
        try:
            start_t = self._parse_time(self.cfg.get('work_start', '09:00'))
            end_t = self._parse_time(self.cfg.get('work_end', '22:00'))
        except Exception:
            return True, '时段格式异常，已跳过时段限制'
        now = datetime.datetime.now().time()
        if use_start and use_end:
            if start_t <= end_t:
                ok = start_t <= now <= end_t
            else:
                ok = now >= start_t or now <= end_t
            desc = f'启用开始 {start_t.strftime("%H:%M")} / 结束 {end_t.strftime("%H:%M")}'
        elif use_start:
            ok = now >= start_t
            desc = f'仅启用开始 {start_t.strftime("%H:%M")}'
        else:
            ok = now <= end_t
            desc = f'仅启用结束 {end_t.strftime("%H:%M")}'
        return ok, desc

    def _get_week_key(self):
        today = datetime.date.today()
        iso_year, iso_week, _ = today.isocalendar()
        return f'{iso_year}-W{iso_week:02d}'

    def _parse_interval_value(self, raw):
        s = self._normalize_text(raw)
        if s in {'', '机器自适应', '自动', '自适应'}:
            return None
        return float(s)

    def _resolve_interval_range(self, c):
        mn = self._parse_interval_value(c.get('iMin', ''))
        mx = self._parse_interval_value(c.get('iMax', ''))
        auto = False
        if mn is None and mx is None:
            mn, mx = 18.0, 42.0
            auto = True
        elif mn is None:
            mn = max(10.0, min(24.0, float(mx) * 0.6))
            auto = True
        elif mx is None:
            mx = max(float(mn) + 8.0, float(mn) * 1.8)
            auto = True
        mn = float(mn)
        mx = float(mx)
        if mx < mn:
            mn, mx = mx, mn
        return mn, mx, auto

    def _get_greeting_templates(self):
        raw = self.cfg.get('greeting', '')
        lines = [self._normalize_text(x) for x in str(raw).splitlines() if self._normalize_text(x)]
        return lines or ['您好{name}，我们公司正在招聘{职位}，看到您的简历非常契合，诚邀了解一下，期待您的回复！']

    def _pick_greeting(self, job, name=''):
        templates = self._get_greeting_templates()
        msg = random.choice(templates)
        msg = msg.replace('{职位}', job)
        if name:
            msg = msg.replace('{name}', name)
        return msg

    def _ensure_daily_count(self):
        today = datetime.date.today().isoformat()
        if self.cfg.get('daily_count_date') != today:
            self.cfg['daily_count_date'] = today
            self.cfg['daily_count'] = '0'
            save_cfg(self.cfg)
        return int(str(self.cfg.get('daily_count', '0') or '0'))

    def _inc_daily_count(self):
        used = self._ensure_daily_count() + 1
        self.cfg['daily_count'] = str(used)
        save_cfg(self.cfg)
        self.root.after(0, self._update_daily_display)

    def _ensure_weekly_count(self):
        week_key = self._get_week_key()
        if self.cfg.get('weekly_count_key') != week_key:
            self.cfg['weekly_count_key'] = week_key
            self.cfg['weekly_count'] = '0'
            save_cfg(self.cfg)
        return int(str(self.cfg.get('weekly_count', '0') or '0'))

    def _inc_weekly_count(self):
        used = self._ensure_weekly_count() + 1
        self.cfg['weekly_count'] = str(used)
        save_cfg(self.cfg)
        self.root.after(0, self._update_daily_display)

    def _daily_limit_reached(self):
        used = self._ensure_daily_count()
        try:
            limit = int(str(self.cfg.get('daily_max', '0') or '0'))
        except Exception:
            return False, used, 0
        return (limit > 0 and used >= limit), used, limit

    def _wait_if_paused(self):
        while self.paused and not self.stop_requested:
            time.sleep(0.2)
        return not self.stop_requested

    def _sleep_interruptible(self, seconds, step=0.2):
        end = time.time() + max(0, float(seconds))
        while time.time() < end:
            if self.stop_requested:
                return False
            if self.paused and not self._wait_if_paused():
                return False
            time.sleep(min(step, max(0, end - time.time())))
        return not self.stop_requested

    def _format_seconds_cn(self, seconds):
        sec = int(max(0, round(float(seconds))))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        parts = []
        if h:
            parts.append(f'{h}小时')
        if m:
            parts.append(f'{m}分钟')
        if s or not parts:
            parts.append(f'{s}秒')
        return ''.join(parts)

    def _resolve_break_plan(self, c):
        after_raw = self._normalize_text(c.get('break_after_min', '0'))
        pause_min_raw = self._normalize_text(c.get('break_pause_min_sec', '30'))
        pause_max_raw = self._normalize_text(c.get('break_pause_max_sec', '300'))
        after_min = float(after_raw or '0')
        pause_min = int(float(pause_min_raw or '30'))
        pause_max = int(float(pause_max_raw or '300'))
        pause_min = max(30, min(7200, pause_min))
        pause_max = max(30, min(7200, pause_max))
        if pause_max < pause_min:
            pause_min, pause_max = pause_max, pause_min
        return after_min, pause_min, pause_max

    def _click_sidebar_nav(self, p, label):
        selectors = [f'text:{label}', f'xpath://span[normalize-space()="{label}"]', f'xpath://div[normalize-space()="{label}"]']
        for sel in selectors:
            try:
                el = p.ele(sel, timeout=1.5)
                if not el:
                    continue
                try:
                    try:
                        el.scroll.to_see()
                    except Exception:
                        pass
                    self._sleep_interruptible(random.uniform(0.25, 0.6))
                    el.click()
                except Exception:
                    try:
                        el.click(by_js=True)
                    except Exception:
                        continue
                self.log(f'象征性切换左侧模块：{label}', 'info')
                return self._sleep_interruptible(random.uniform(0.6, 1.2))
            except Exception:
                pass
        self.log(f'未找到左侧模块：{label}', 'warn')
        return True

    def _try_synced_reply_during_break(self):
        """同步模式：切到沟通页回一轮未读消息，再回到推荐页。返回是否执行了回复。"""
        if self.ai_panel is None or not self.ai_panel.reply_synced_enabled():
            return False
        p = self.page
        if not p:
            return False
        try:
            self.log('中途暂停：顺带检查并回复未读消息...', 'info')
            p.get('https://www.zhipin.com/web/chat/index')
            if not self._sleep_interruptible(2.5):
                return True
            self.ai_panel.engine.reply_once()
            return True
        except Exception as e:
            self.log(f'中途回复未读消息异常: {e}', 'warn')
            return False
        finally:
            try:
                p.get(REC_URL)
                self._sleep_interruptible(2.0)
            except Exception:
                pass

    def _run_scheduled_break(self, p, pause_seconds):
        pause_seconds = max(30, min(7200, int(pause_seconds)))
        self.log(f'达到连续运行阈值，进入中途暂停 {pause_seconds} 秒。', 'warn')
        self.st(f'中途暂停中，剩余 {pause_seconds} 秒')
        # 同步模式：暂停开始时先回一轮未读消息，更像真人"边招人边回消息"
        self._try_synced_reply_during_break()
        navs = ['职位管理', '搜索', '沟通', '推荐牛人']
        started = time.monotonic()
        idx = 0
        while self.running and not self.stop_requested:
            remain = pause_seconds - int(time.monotonic() - started)
            if remain <= 0:
                break
            if self.paused and not self._wait_if_paused():
                return False
            label = navs[idx % len(navs)]
            idx += 1
            self._click_sidebar_nav(p, label)
            if label != '推荐牛人':
                self._click_sidebar_nav(p, '推荐牛人')
            chunk = min(max(3, remain), random.randint(6, 18))
            self.st(f'中途暂停中，剩余 {remain} 秒')
            if not self._sleep_interruptible(chunk):
                return False
        try:
            if 'recommend' not in (p.url or ''):
                self.log('中途暂停结束，返回推荐牛人页...', 'info')
                p.get(REC_URL)
                if not self._sleep_interruptible(2.0):
                    return False
            else:
                self._click_sidebar_nav(p, '推荐牛人')
        except Exception as e:
            self.log(f'返回推荐牛人页异常: {e}', 'warn')
        self.log('中途暂停结束，恢复执行。', 'ok')
        self.st('恢复执行中...')
        return True

    def _set_opening(self, on_off: bool):
        self.opening = on_off
        def _():
            self.btn_open.config(state='disabled' if on_off or self.running else 'normal')
            if on_off:
                self.btn_start.config(state='disabled')
            elif self.page:
                self.btn_start.config(state='normal')
        self.root.after(0, _)

    def _reset_daily_limit_default(self):
        self.v_daily_max.set('150')

    def _toggle_marquee_pause(self):
        self.marquee_paused = not self.marquee_paused
        if hasattr(self, 'btn_marquee_pause'):
            self.btn_marquee_pause.config(text='继续播报' if self.marquee_paused else '暂停播报')
        self.log('【播报】已暂停' if self.marquee_paused else '【播报】已恢复', 'info')

    def _clear_marquee(self):
        self.marquee_entries = []
        self._refresh_marquee()
        self.log('【播报】已清空滚动信息', 'info')

    def _refresh_marquee(self):
        if not hasattr(self, 'marquee_canvas'):
            return
        text = '   ｜   '.join(self.marquee_entries) if self.marquee_entries else '暂无滚动播报'
        self.marquee_canvas.delete('all')
        w = max(self.marquee_canvas.winfo_width(), 320)
        if self.marquee_entries:
            if len(self.marquee_entries) == 1:
                text = (text + '   ｜   ') * 4
            elif len(text) < 60:
                text = text + '   ｜   ' + text
        self.marquee_text_id = self.marquee_canvas.create_text(w, 22, text=text, anchor='w', fill='#555', font=('微软雅黑', 14))

    def _start_marquee_anim(self):
        if hasattr(self, 'marquee_canvas'):
            if self.marquee_text_id is None:
                self._refresh_marquee()
            if not self.marquee_paused and self.marquee_text_id is not None:
                try:
                    self.marquee_canvas.move(self.marquee_text_id, -2, 0)
                    box = self.marquee_canvas.bbox(self.marquee_text_id)
                    canvas_w = self.marquee_canvas.winfo_width()
                    if box and box[2] < 0:
                        self.marquee_canvas.coords(self.marquee_text_id, canvas_w, 24)
                except Exception:
                    pass
        self.root.after(40, self._start_marquee_anim)

    def _push_marquee_message(self, info, status='命中', salary_override=''):
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        name = info.get('name', '') or '候选人'
        age = info.get('age', '')
        edu = info.get('education', '') or '学历未知'
        salary = salary_override or info.get('salary', '') or '薪资未知'
        job = info.get('job', '') or '岗位未知'
        active = info.get('active', '') or '活跃未知'
        age_text = f'{age}岁' if str(age).strip() else ''
        msg = f'[{status}] {ts}  {name}  {age_text}  {edu}  {salary}  {job}  {active}'
        self.marquee_entries.append(self._normalize_text(msg))
        self.marquee_entries = self.marquee_entries[-24:]
        self.root.after(0, self._refresh_marquee)

    def _reset_all_settings(self):
        if self.running or self.opening:
            messagebox.showwarning('提示', '请先停止当前任务，再执行重置。')
            return
        if not messagebox.askyesno('确认重置', '确认重置左侧所有设置与本次计数吗？\n\n说明：今日沟通次数会清零，本周沟通数据会保留。'):
            return
        self.v_job.set(DEF['job'])
        self.v_include.set('')
        self.v_active.set('不限')
        self.v_company_include.set('')
        self.v_company_block.set('')
        self.v_age_min.set('不限')
        self.v_age_max.set('不限')
        self.v_exclude.set(DEF['exclude_words'])
        self.v_gender.set('不限')
        self.v_gender_unknown_pass.set(True)
        self.v_edu.set('不限')
        self.v_salary_min.set('')
        self.v_salary_max.set('')
        self.v_hop_filter.set('不限')
        self.v_imin.set('机器自适应')
        self.v_imax.set('机器自适应')
        self.v_maxn.set('100')
        self.v_daily_max.set('150')
        self.v_work_start.set('09:00')
        self.v_work_end.set('22:00')
        self.v_work_start_enabled.set(True)
        self.v_work_end_enabled.set(True)
        self.v_break_after_min.set('0')
        self.v_break_pause_min_sec.set('30')
        self.v_break_pause_max_sec.set('300')
        self.txt_greet.delete('1.0', 'end')
        self.txt_greet.insert('1.0', DEF['greeting'])

        weekly_count = str(self.cfg.get('weekly_count', '0') or '0')
        weekly_key = self.cfg.get('weekly_count_key', self._get_week_key()) or self._get_week_key()
        self.cfg = dict(DEF)
        self.cfg['daily_count'] = '0'
        self.cfg['daily_count_date'] = datetime.date.today().isoformat()
        self.cfg['weekly_count'] = weekly_count
        self.cfg['weekly_count_key'] = weekly_key
        save_cfg(self.cfg)
        self.cnt = {'ok': 0, 'skip': 0, 'fail': 0, 'sniffed': 0}
        self.processed_fp = set()
        self._update_daily_display()
        self.upd_cnt()
        self.st('已重置左侧设置，保留本周沟通统计')
        self.log('【重置】左侧设置与本次计数已重置；本周沟通数据已保留。', 'warn')

    def _read_cfg(self):
        c = self.cfg
        c['job'] = self.v_job.get().strip()
        c['exclude_words'] = self.v_exclude.get().strip()
        c['include_words'] = self.v_include.get().strip()
        c['include_mode'] = '任一'
        c['greeting'] = self.txt_greet.get('1.0', 'end').strip()
        c['iMin'] = self.v_imin.get().strip()
        c['iMax'] = self.v_imax.get().strip()
        c['maxN'] = self.v_maxn.get().strip()
        c['gender'] = self.v_gender.get().strip() or '不限'
        c['gender_unknown_pass'] = '1' if self.v_gender_unknown_pass.get() else '0'
        c['active_filter'] = self.v_active.get().strip() or '不限'
        c['company_include'] = self.v_company_include.get().strip()
        c['company_block'] = self.v_company_block.get().strip()
        c['age_min'] = self.v_age_min.get().strip() or '不限'
        c['age_max'] = self.v_age_max.get().strip() or '不限'
        c['education_filter'] = self.v_edu.get().strip() or '不限'
        c['salary_min_k'] = self.v_salary_min.get().strip()
        c['salary_max_k'] = self.v_salary_max.get().strip()
        c['job_hop_filter'] = self.v_hop_filter.get().strip() or '不限'
        c['daily_max'] = self.v_daily_max.get().strip() or '150'
        c['work_start'] = self.v_work_start.get().strip()
        c['work_end'] = self.v_work_end.get().strip()
        c['work_start_enabled'] = '1' if self.v_work_start_enabled.get() else '0'
        c['work_end_enabled'] = '1' if self.v_work_end_enabled.get() else '0'
        c['break_after_min'] = self.v_break_after_min.get().strip() or '0'
        c['break_pause_min_sec'] = self.v_break_pause_min_sec.get().strip() or '30'
        c['break_pause_max_sec'] = self.v_break_pause_max_sec.get().strip() or '300'


        return c

    def _ai_constraints_text(self):
        """把岗位硬性要求（年龄/性别/学历等）拼成一句，喂给AI，避免它乱承诺（比如年龄超标还回"能行"）。"""
        def val(var):
            try:
                s = (var.get() or '').strip()
            except Exception:
                s = ''
            return s
        parts = []
        age_min = val(self.v_age_min)
        age_max = val(self.v_age_max)
        has_min = age_min not in ('', '不限')
        has_max = age_max not in ('', '不限')
        if has_min and has_max:
            parts.append(f'年龄要求 {age_min}~{age_max} 岁')
        elif has_min:
            parts.append(f'年龄要求 {age_min} 岁及以上')
        elif has_max:
            parts.append(f'年龄要求 {age_max} 岁及以下')
        gender = val(self.v_gender)
        if gender not in ('', '不限'):
            parts.append(f'性别要求：{gender}')
        edu = val(self.v_edu)
        if edu not in ('', '不限'):
            parts.append(f'学历要求：{edu} 及以上')
        return '；'.join(parts)

    def _derive_job_keywords(self, job_text):
        raw = self._normalize_text(job_text)
        if not raw:
            return []

        # ── 步骤1：清洗掉地点/薪资/下划线等非职位内容 ──────────────
        # 处理下划线分隔（如"人事行政专员_东莞5-7K" → "人事行政专员"）
        raw = raw.split('_')[0].strip()
        # 去掉薪资：5-7K、8000-12000 等
        raw = re.sub(r'\d+(?:-\d+)?[Kk万]?(?:/月|/年)?', '', raw).strip()
        # 去掉城市名（常见）
        cities = ['东莞', '广州', '深圳', '佛山', '中山', '珠海', '惠州', '北京',
                  '上海', '杭州', '成都', '武汉', '西安', '南京', '苏州', '天津']
        for city in cities:
            raw = raw.replace(city, '').strip()
        # 去掉括号里内容（含行业标注如"（行业）"）
        raw = re.sub(r'[（(][^）)]*[）)]', '', raw).strip()
        raw = re.sub(r'\s+', ' ', raw).strip()

        if not raw:
            return []

        parts = self._parse_words(raw) or [raw]
        out = []

        # ── 步骤2：拆词 ──────────────────────────────────────────────
        suffixes = ['专员', '助理', '主管', '经理', '工程师', '文员', '跟单',
                    '采购员', '操作员', '业务员', '管理员', 'buyer', '总监',
                    '部长', '组长', '督导', '顾问', '代表', '协调员']
        for p in parts:
            p = self._normalize_text(p).strip()
            if not p:
                continue
            # 加入完整词
            if p not in out:
                out.append(p)
            # 按"/"拆分（如"人事/行政专员"）
            if '/' in p or '／' in p:
                for seg in re.split(r'[/／]', p):
                    seg = seg.strip()
                    if seg and len(seg) >= 2 and seg not in out:
                        out.append(seg)
            # 按后缀拆出前缀（如"人事行政专员" → "人事行政"）
            for s in suffixes:
                if p.endswith(s) and len(p) > len(s):
                    base = p[:-len(s)].strip()
                    if len(base) >= 2 and base not in out:
                        out.append(base)
            # 按"行政"这类复合词拆出子词
            # "人事行政专员" → 同时产生"人事"、"行政"
            compound_splits = ['人事行政', '行政人事', '人力资源', '招聘培训',
                               '财务会计', '仓库物流', '采购供应', '质量品控']
            for compound in compound_splits:
                if compound in p:
                    halves = [compound[:len(compound)//2], compound[len(compound)//2:]]
                    for h in halves:
                        if h and len(h) >= 2 and h not in out:
                            out.append(h)

        # ── 步骤3：加入同义词/近义词映射 ───────────────────────────
        synonyms = {
            '人事': ['人力资源', 'HR', '招聘'],
            '行政': ['行政文员', '行政助理', '行政专员'],
            '人力资源': ['人事', 'HR', '人力'],
            '招聘': ['招聘专员', '人事专员', '猎头'],
            '采购': ['采购专员', '采购员', '供应链', 'buyer'],
            '仓库': ['仓储', '物流', '仓管'],
            '财务': ['会计', '出纳', '财会'],
            '跟单': ['业务跟单', '生产跟单', '外贸跟单'],
        }
        extra = []
        for kw in list(out):
            for key, syns in synonyms.items():
                if key in kw:
                    for syn in syns:
                        if syn not in out and syn not in extra:
                            extra.append(syn)
        out.extend(extra)

        return [w for w in out if w]

    def _extract_profile(self, card_text):
        text = self._normalize_text(card_text)
        clean = text.replace('开聊可直接给牛人打电话', ' ')
        clean = re.sub(r'(刚刚活跃|今日活跃|本周活跃|3日内活跃|日内活跃)', ' ', clean)
        clean = re.sub(r'^(?:面议|\d+(?:-\d+)?K)\s*', '', clean, flags=re.I)

        name = ''
        m = re.search(r'([\u4e00-\u9fa5A-Za-z·]{2,10})(?=\s\d{1,2}岁)', clean)
        if m:
            cand = m.group(1).strip()
            if cand not in {'牛人打电话', '打招呼', '联系TA', '确认', '发送', '刚刚活跃', '今日活跃', '本周活跃', '3日内活跃'}:
                name = cand
        if not name:
            m2 = re.match(r'([\u4e00-\u9fa5A-Za-z·]{2,10})\s', clean)
            if m2:
                cand = m2.group(1).strip()
                if cand not in {'牛人打电话', '打招呼', '联系TA', '确认', '发送'}:
                    name = cand

        m_age = re.search(r'(\d{1,2})岁', text)
        m_salary = re.match(r'^(面议|\d+(?:-\d+)?K)', text, flags=re.I)
        m_job = re.search(r'(?:期望|最近关注)([^\s]{2,40})', text)
        edu = self._parse_degree(text)
        active = self._parse_active(text)
        gender = self._parse_gender(text)
        return {
            'name': name or '候选人',
            'age': m_age.group(1) if m_age else '',
            'salary': m_salary.group(1) if m_salary else '',
            'job': m_job.group(1) if m_job else '',
            'education': edu,
            'active': active,
            'gender': gender,
        }

    def _parse_gender(self, card_text):
        text = self._normalize_text(card_text)
        if re.search(r'女士|小姐|女性|女生', text):
            return '女'
        if re.search(r'先生|男性|男生', text):
            return '男'
        return '未知'

    def _parse_active(self, card_text):
        text = self._normalize_text(card_text)
        for label, pattern in ACTIVE_PATTERNS:
            if pattern.search(text):
                return label
        return '未知'

    def _parse_degree(self, card_text):
        text = self._normalize_text(card_text)
        for label, pattern in EDU_PATTERNS:
            if pattern.search(text):
                return label
        return '未知'

    def _role_match(self, card_text, job_keywords):
        if not job_keywords:
            return True, job_keywords
        text = self._normalize_text(card_text)
        full_lower = text.lower()
        # 优先在"期望岗位"字段+卡片头部匹配
        head = re.split(r'优势|工作描述|自我评价|项目经验|教育经历', text, maxsplit=1)[0]
        profile = self._extract_profile(text)
        target = self._normalize_text(' '.join([profile.get('job', ''), head[:300]])).lower()
        hits = [w for w in job_keywords if w.lower() in target]
        if hits:
            return True, hits
        # 宽松兜底：搜索简历全文（避免"期望"字段写法不一致漏判）
        full_hits = [w for w in job_keywords if w.lower() in full_lower]
        return bool(full_hits), full_hits

    def _active_match(self, card_text, setting):
        actual = self._parse_active(card_text)
        if setting == '不限':
            return True, actual
        if actual == '未知':
            return False, actual
        return ACTIVE_LEVELS.get(actual, 99) <= ACTIVE_LEVELS.get(setting, 99), actual

    def _gender_match(self, card_text):
        setting = self.cfg.get('gender', '不限')
        actual = self._parse_gender(card_text)
        if setting == '不限':
            return True, actual
        if actual == '未知':
            return bool(str(self.cfg.get('gender_unknown_pass', '1')) != '0'), actual
        return actual == setting, actual

    def _age_match(self, card_text):
        min_s = str(self.cfg.get('age_min', '不限'))
        max_s = str(self.cfg.get('age_max', '不限'))
        m = re.search(r'(\d{1,2})岁', self._normalize_text(card_text))
        actual = int(m.group(1)) if m else None
        if min_s == '不限' and max_s == '不限':
            return True, actual
        if actual is None:
            return False, None
        if min_s != '不限' and actual < int(min_s):
            return False, actual
        if max_s != '不限' and actual > int(max_s):
            return False, actual
        return True, actual

    def _education_match(self, card_text):
        setting = self.cfg.get('education_filter', '不限')
        actual = self._parse_degree(card_text)
        if setting == '不限':
            return True, actual
        if actual == '未知':
            return False, actual
        return EDU_RANK.get(actual, 0) >= EDU_RANK.get(setting, 0), actual

    def _parse_salary_range(self, card_text):
        text = self._normalize_text(card_text)
        m = re.search(r'(?i)(面议|\d+(?:\.\d+)?\s*(?:-|~|—|至)\s*\d+(?:\.\d+)?\s*K|\d+(?:\.\d+)?\s*K)', text)
        if not m:
            return None, None, ''
        raw = m.group(1).upper().replace(' ', '')
        if '面议' in raw:
            return None, None, '面议'
        nums = re.findall(r'\d+(?:\.\d+)?', raw)
        if not nums:
            return None, None, raw
        if len(nums) == 1:
            val = float(nums[0])
            return val, val, f'{nums[0]}K'
        lo, hi = float(nums[0]), float(nums[1])
        if hi < lo:
            lo, hi = hi, lo
        return lo, hi, f'{nums[0]}-{nums[1]}K'

    def _salary_match(self, card_text):
        def _to_float(v):
            v = self._normalize_text(v)
            if not v:
                return None
            try:
                return float(v)
            except Exception:
                return None
        min_v = _to_float(self.cfg.get('salary_min_k', ''))
        max_v = _to_float(self.cfg.get('salary_max_k', ''))
        if min_v is not None and max_v is not None and min_v > max_v:
            min_v, max_v = max_v, min_v
        actual_lo, actual_hi, actual_raw = self._parse_salary_range(card_text)
        if min_v is None and max_v is None:
            return True, actual_raw or '不限'
        if actual_raw == '面议':
            return False, '面议'
        if actual_lo is None or actual_hi is None:
            return False, '未知'
        if min_v is not None and actual_hi < min_v:
            return False, f'{actual_lo:g}-{actual_hi:g}K'
        if max_v is not None and actual_lo > max_v:
            return False, f'{actual_lo:g}-{actual_hi:g}K'
        return True, f'{actual_lo:g}-{actual_hi:g}K'

    def _parse_explicit_company_years(self, card_text):
        text = self._normalize_text(card_text)
        patterns = [
            (re.compile(r'(?:近)?(\d+(?:\.\d+)?)年[^。；，,\n]{0,24}?(\d+)家公司'), 'yc'),
            (re.compile(r'(\d+)家公司[^。；，,\n]{0,24}?(?:近)?(\d+(?:\.\d+)?)年'), 'cy'),
            (re.compile(r'(\d+(?:\.\d+)?)年内[^。；，,\n]{0,24}?(\d+)家公司'), 'yc'),
        ]
        for pattern, kind in patterns:
            m = pattern.search(text)
            if not m:
                continue
            if kind == 'yc':
                years = float(m.group(1))
                companies = int(m.group(2))
            else:
                companies = int(m.group(1))
                years = float(m.group(2))
            if years <= 0 or companies <= 0:
                continue
            return years, companies, m.group(0)
        return None

    def _job_hop_match(self, card_text):
        setting = self.cfg.get('job_hop_filter', '不限')
        limit = HOP_FILTER_LIMITS.get(setting)
        if limit is None:
            return True, '不限'
        parsed = self._parse_explicit_company_years(card_text)
        if not parsed:
            return True, '未发现明确X家公司'
        years, companies, snippet = parsed
        jumps = max(companies - 1, 0)
        per_3y = jumps * 3.0 / max(years, 0.1)
        return per_3y <= float(limit) + 1e-6, f'{snippet} => {per_3y:.1f}次/3年'

    def _include_match(self, card_text, include_words, mode):
        if not include_words:
            return True, []
        mode = MODE_DISPLAY_TO_INTERNAL.get(mode, mode)
        if mode not in {'任一', '全部'}:
            mode = '任一'
        text = self._normalize_text(card_text).lower()
        hits = [w for w in include_words if w.lower() in text]
        if mode == '全部':
            miss = [w for w in include_words if w.lower() not in text]
            return len(miss) == 0, hits
        return len(hits) > 0, hits

    def _match_exclude_word(self, card_text, words):
        if not words:
            return None
        text = self._normalize_text(card_text).lower()
        head = re.split(r'优势|工作描述|自我评价|项目经验|教育经历', text, maxsplit=1)[0]
        focus = head[:220]
        for w in words:
            if w.lower() in focus:
                return w
        return None

    def _company_filter(self, card_text):
        include_words = self._parse_words(self.cfg.get('company_include', ''))
        block_words = self._parse_words(self.cfg.get('company_block', ''))
        if not include_words and not block_words:
            return True, [], []
        text = self._normalize_text(card_text).lower()
        include_hits = [w for w in include_words if w.lower() in text]
        block_hits = [w for w in block_words if w.lower() in text]
        if block_hits:
            return False, include_hits, block_hits
        if include_words and not include_hits:
            return False, include_hits, block_hits
        return True, include_hits, block_hits

    def _btn_fp(self, btn):
        card = self._get_card_text(btn)
        info = self._extract_profile(card)
        key = '|'.join([info.get('name', ''), info.get('age', ''), info.get('job', ''), info.get('salary', '')]).strip('|')
        return key or card[:120] or str(id(btn))

    def _find_greet_btns(self, p):
        try:
            items = p.run_js(r"""
                const WORDS = ['打招呼', '打个招呼', '立即沟通', '联系TA'];
                document.querySelectorAll('[data-greet-id]').forEach(el => el.removeAttribute('data-greet-id'));
                function isVisible(el){
                    if(!el) return false;
                    const s = getComputedStyle(el);
                    if(s.display==='none' || s.visibility==='hidden' || s.opacity==='0') return false;
                    const r = el.getBoundingClientRect();
                    return r.width>6 && r.height>6 && r.bottom>=0 && r.top<=innerHeight;
                }
                function toClickable(el){
                    let n = el;
                    for(let i=0;i<6 && n;i++,n=n.parentElement){
                        const tag=(n.tagName||'').toUpperCase();
                        const role=(n.getAttribute('role')||'').toLowerCase();
                        const s=getComputedStyle(n);
                        if(tag==='BUTTON' || tag==='A' || role==='button' || typeof n.onclick==='function' || s.cursor==='pointer') return n;
                    }
                    return el;
                }
                function cardTextOf(el){
                    let n = el;
                    for(let i=0;i<10 && n;i++,n=n.parentElement){
                        const txt=(n.innerText||'').replace(/\s+/g,' ').trim();
                        if(txt.length>40 && /岁|年|K|k|期望|本科|大专|中专|最近关注|优势/.test(txt)) return txt.slice(0, 800);
                    }
                    return (el.innerText||'').replace(/\s+/g,' ').trim();
                }
                const nodes=[...document.querySelectorAll('button,a,span,div')];
                const seen = new Set();
                const out = [];
                let idx=0;
                for(const node of nodes){
                    const txt=(node.innerText||node.textContent||'').replace(/\s+/g,' ').trim();
                    if(!WORDS.includes(txt)) continue;
                    const clickable = toClickable(node);
                    if(!isVisible(clickable)) continue;
                    const card = cardTextOf(clickable);
                    if(!card || card.length<20 || card===txt) continue;
                    const rect = clickable.getBoundingClientRect();
                    const key = `${Math.round(rect.left)}_${Math.round(rect.top)}_${Math.round(rect.width)}_${Math.round(rect.height)}_${card.slice(0,60)}`;
                    if(seen.has(key)) continue;
                    seen.add(key);
                    const gid = `g_${Date.now()}_${++idx}`;
                    clickable.setAttribute('data-greet-id', gid);
                    out.push({gid, text: txt, top: Math.round(rect.top), left: Math.round(rect.left), card_text: card});
                }
                out.sort((a,b)=>(a.top-b.top)||(a.left-b.left));
                return out;
            """) or []
        except Exception as e:
            self.log(f'  JS抓取按钮异常: {e}', 'warn')
            items = []

        result = []
        for info in items:
            gid = info.get('gid')
            try:
                el = p.ele(f'css:[data-greet-id="{gid}"]', timeout=0.8)
                if el:
                    result.append(el)
            except Exception:
                pass
        if result:
            self.log(f'  JS可见按钮 → {len(result)}个', 'info')
            return result

        result = []
        seen = set()
        for keyword in ['打招呼', '打个招呼', '立即沟通', '联系TA']:
            try:
                els = p.eles(f'text:{keyword}', timeout=1.0)
                self.log(f'  text:{keyword} → {len(els)}个', 'info')
                for el in els:
                    if id(el) not in seen:
                        seen.add(id(el))
                        result.append(el)
            except Exception:
                pass
        return result

    def _get_card_text(self, btn):
        el = btn
        for _ in range(10):
            try:
                el = el.parent()
                t = self._normalize_text(el.text or '')
                if len(t) > 40 and any(k in t for k in ['岁', '年', 'K', '期望', '本科', '大专', '最近关注']):
                    return t
            except Exception:
                break
        try:
            return self._normalize_text(btn.text or '')
        except Exception:
            return ''

    def _get_name(self, btn):
        return self._extract_profile(self._get_card_text(btn)).get('name', '候选人')

    def _smart_click_btn(self, btn):
        try:
            btn.scroll.to_see()
        except Exception:
            pass
        try:
            btn.click()
            return True
        except Exception:
            pass
        try:
            btn.run_js('this.click()')
            return True
        except Exception:
            return False

    def _get_scroll_state(self, p):
        try:
            result = p.run_js(r"""
                function getWords(){ return ['打招呼','打个招呼','立即沟通','联系TA']; }
                function isVisible(el){
                    if(!el) return false;
                    const s = getComputedStyle(el);
                    if(s.display==='none' || s.visibility==='hidden' || s.opacity==='0') return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 6 && r.height > 6 && r.bottom >= 0 && r.top <= innerHeight;
                }
                function toClickable(el){
                    let n = el;
                    for(let i=0;i<8 && n;i++,n=n.parentElement){
                        const tag=(n.tagName||'').toUpperCase();
                        const role=(n.getAttribute('role')||'').toLowerCase();
                        const s=getComputedStyle(n);
                        if(tag==='BUTTON' || tag==='A' || role==='button' || typeof n.onclick==='function' || s.cursor==='pointer') return n;
                    }
                    return el;
                }
                function visibleButtons(){
                    const words = getWords();
                    const nodes = [...document.querySelectorAll('button,a,[role="button"],span,div')];
                    const out = [];
                    const seen = new Set();
                    for(const node of nodes){
                        const txt = (node.innerText || node.textContent || '').replace(/\s+/g,' ').trim();
                        if(!words.includes(txt)) continue;
                        const clickable = toClickable(node);
                        if(!isVisible(clickable)) continue;
                        const r = clickable.getBoundingClientRect();
                        const key = `${Math.round(r.left)}_${Math.round(r.top)}_${Math.round(r.width)}_${Math.round(r.height)}`;
                        if(seen.has(key)) continue;
                        seen.add(key);
                        out.push(clickable);
                    }
                    out.sort((a,b)=>a.getBoundingClientRect().top - b.getBoundingClientRect().top);
                    return out;
                }
                function shortName(el){
                    if(!el) return 'document';
                    const id = (el.id || '').trim();
                    const cls = String(el.className || '').trim().split(/\s+/).filter(Boolean);
                    if(id) return id;
                    if(cls.length) return cls[0];
                    return (el.tagName || 'document').toLowerCase();
                }
                function scoreScrollable(el){
                    if(!el || el===document.body || el===document.documentElement) return -1;
                    const r = el.getBoundingClientRect();
                    const sh = el.scrollHeight || 0;
                    const ch = el.clientHeight || 0;
                    if(r.width < 260 || r.height < 180) return -1;
                    if(sh <= ch + 12) return -1;
                    const s = getComputedStyle(el);
                    const oy = s.overflowY || s.overflow || '';
                    let score = (sh - ch) * 10 + r.height;
                    const name = `${el.id || ''} ${el.className || ''}`.toLowerCase();
                    if(['auto','scroll','overlay'].includes(oy)) score += 100000;
                    if(r.right > innerWidth * 0.55 && r.left < innerWidth * 0.98) score += 4000;
                    if(/recommend-wrap/.test(name)) score += 250000;
                    else if(/recommend|candidate|list|wrap|geek/.test(name)) score += 18000;
                    return score;
                }
                function bestFromNode(node){
                    let cur = node, best = null, bestScore = -1;
                    for(let i=0;i<18 && cur;i++,cur=cur.parentElement){
                        const s = scoreScrollable(cur);
                        if(s > bestScore){ best = cur; bestScore = s; }
                    }
                    return best;
                }
                function pickScrollable(){
                    const btns = visibleButtons();
                    const candidates = [];
                    for(const btn of btns){
                        const direct = bestFromNode(btn);
                        if(direct) candidates.push(direct);
                        const r = btn.getBoundingClientRect();
                        const pts = [
                            [Math.min(innerWidth-16, Math.max(16, r.right + 12)), Math.min(innerHeight-16, Math.max(16, r.top + r.height*0.5))],
                            [Math.min(innerWidth-16, Math.max(16, r.left + r.width*0.75)), Math.min(innerHeight-16, Math.max(16, r.top + r.height*0.7))],
                            [Math.min(innerWidth-16, Math.max(16, innerWidth*0.82)), Math.min(innerHeight-16, Math.max(16, r.top + r.height*0.6))],
                        ];
                        for(const [x,y] of pts){
                            const hit = document.elementFromPoint(x,y);
                            const cand = bestFromNode(hit);
                            if(cand) candidates.push(cand);
                        }
                    }
                    candidates.sort((a,b)=>scoreScrollable(b)-scoreScrollable(a));
                    return candidates[0] || null;
                }
                const sc = pickScrollable();
                const bodyText = (document.body.innerText || '').replace(/\s+/g,' ');
                const footerText = bodyText.slice(-320);
                const bottomTip = /到底了|没有更多了|没有更多牛人|已全部加载|已经到底|暂无更多|没有更多结果|暂无结果|没有更多内容|没有更多候选人/.test(bodyText);
                const loading = /正在加载中|加载中\.\.\.|加载中…|努力加载中/.test(bodyText);
                if(sc){
                    const r = sc.getBoundingClientRect();
                    const wheelX = Math.round(Math.min(innerWidth-20, Math.max(20, Math.max(r.left + 80, r.right - 36))));
                    const wheelY = Math.round(Math.min(innerHeight-20, Math.max(20, r.top + r.height * 0.58)));
                    return {
                        type:'inner',
                        pos: Math.round(sc.scrollTop),
                        clientH: Math.round(sc.clientHeight),
                        scrollH: Math.round(sc.scrollHeight),
                        atBottom: sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 120,
                        bottomTip: bottomTip,
                        loading: loading,
                        footer: footerText,
                        tag: (sc.tagName||'').toLowerCase(),
                        cls: (sc.className||'').toString().slice(0,160),
                        container_name: shortName(sc),
                        rectLeft: Math.round(r.left),
                        rectTop: Math.round(r.top),
                        rectRight: Math.round(r.right),
                        rectBottom: Math.round(r.bottom),
                        rectHeight: Math.round(r.height),
                        rectWidth: Math.round(r.width),
                        wheel_x: wheelX,
                        wheel_y: wheelY,
                    };
                }
                return {
                    type:'document',
                    pos: Math.round(window.scrollY),
                    clientH: Math.round(window.innerHeight),
                    scrollH: Math.round(document.documentElement.scrollHeight),
                    atBottom: window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 120,
                    bottomTip: bottomTip,
                    loading: loading,
                    footer: footerText,
                    tag:'document',
                    cls:'',
                    container_name:'document',
                    rectLeft:0,
                    rectTop:0,
                    rectRight:Math.round(window.innerWidth),
                    rectBottom:Math.round(window.innerHeight),
                    rectHeight:Math.round(window.innerHeight),
                    rectWidth:Math.round(window.innerWidth),
                    wheel_x:Math.round(window.innerWidth * 0.82),
                    wheel_y:Math.round(window.innerHeight * 0.58),
                };
            """)
            return result or {'type': 'document', 'pos': 0, 'clientH': 0, 'scrollH': 0, 'atBottom': False, 'bottomTip': False, 'loading': False, 'footer': '', 'tag': 'document', 'cls': '', 'container_name': 'document', 'wheel_x': 640, 'wheel_y': 520}
        except Exception as e:
            self.log(f'  读取滚动状态异常: {e}', 'warn')
            return {'type': 'document', 'pos': 0, 'clientH': 0, 'scrollH': 0, 'atBottom': False, 'bottomTip': False, 'loading': False, 'footer': '', 'tag': 'document', 'cls': '', 'container_name': 'document', 'wheel_x': 640, 'wheel_y': 520}

    def _trusted_wheel_scroll(self, p, x, y, delta_y, times=2):
        moved = False
        try:
            for _ in range(max(1, int(times))):
                try:
                    p.run_cdp('Input.dispatchMouseEvent',
                              type='mouseWheel',
                              x=max(10, int(x)),
                              y=max(10, int(y)),
                              deltaX=0,
                              deltaY=int(delta_y),
                              pointerType='mouse')
                    moved = True
                    time.sleep(0.18)
                except Exception:
                    break
        except Exception:
            return False
        return moved


    def _probe_scroll_pos(self, p, x=None, y=None):
        try:
            x_js = 'null' if x is None else str(int(x))
            y_js = 'null' if y is None else str(int(y))
            return p.run_js(f"""
                const x = {x_js};
                const y = {y_js};
                function scoreScrollable(el){{
                    if(!el || el===document.body || el===document.documentElement) return -1;
                    const r = el.getBoundingClientRect();
                    const sh = el.scrollHeight || 0;
                    const ch = el.clientHeight || 0;
                    if(r.width < 220 || r.height < 160) return -1;
                    if(sh <= ch + 8) return -1;
                    const s = getComputedStyle(el);
                    const oy = s.overflowY || s.overflow || '';
                    let score = (sh - ch) * 10 + r.height;
                    if(['auto','scroll','overlay'].includes(oy)) score += 100000;
                    return score;
                }}
                function bestFromNode(node){{
                    let cur = node, best = null, bestScore = -1;
                    for(let i=0;i<16 && cur;i++,cur=cur.parentElement){{
                        const s = scoreScrollable(cur);
                        if(s > bestScore){{ best = cur; bestScore = s; }}
                    }}
                    return best;
                }}
                let sc = null;
                if(x !== null && y !== null){{
                    const hit = document.elementFromPoint(x, y);
                    sc = bestFromNode(hit);
                }}
                if(sc){{
                    const r = sc.getBoundingClientRect();
                    return {{
                        target:'inner',
                        pos:Math.round(sc.scrollTop),
                        rectLeft:Math.round(r.left),
                        rectTop:Math.round(r.top),
                        rectRight:Math.round(r.right),
                        rectBottom:Math.round(r.bottom),
                        rectHeight:Math.round(r.height),
                        rectWidth:Math.round(r.width)
                    }};
                }}
                return {{
                    target:'document',
                    pos:Math.round(window.scrollY),
                    rectLeft:0,
                    rectTop:0,
                    rectRight:Math.round(window.innerWidth),
                    rectBottom:Math.round(window.innerHeight),
                    rectHeight:Math.round(window.innerHeight),
                    rectWidth:Math.round(window.innerWidth)
                }};
            """) or {'target':'document','pos':0}
        except Exception:
            return {'target':'document','pos':0}

    def _get_browser_screen_metrics(self, p):
        try:
            data = p.run_js("""
                return {
                    screenX: Number(window.screenX || window.screenLeft || 0),
                    screenY: Number(window.screenY || window.screenTop || 0),
                    outerWidth: Number(window.outerWidth || 0),
                    outerHeight: Number(window.outerHeight || 0),
                    innerWidth: Number(window.innerWidth || 0),
                    innerHeight: Number(window.innerHeight || 0),
                    dpr: Number(window.devicePixelRatio || 1)
                };
            """) or {}
        except Exception:
            data = {}
        outer_w = float(data.get('outerWidth') or 0)
        inner_w = float(data.get('innerWidth') or 0)
        outer_h = float(data.get('outerHeight') or 0)
        inner_h = float(data.get('innerHeight') or 0)
        side_gap = max(0.0, (outer_w - inner_w) / 2.0)
        top_gap = max(0.0, outer_h - inner_h - side_gap)
        return {
            'screenX': float(data.get('screenX') or 0),
            'screenY': float(data.get('screenY') or 0),
            'sideGap': side_gap,
            'topGap': top_gap,
            'dpr': max(1.0, float(data.get('dpr') or 1.0))
        }

    def _focus_browser_window(self):
        if os.name != 'nt':
            return False
        pid = None
        try:
            if self.browser_proc and self.browser_proc.poll() is None:
                pid = int(self.browser_proc.pid)
        except Exception:
            pid = None
        user32 = ctypes.windll.user32
        hwnd_found = ctypes.c_void_p(0)
        if pid:
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def _enum(hwnd, lparam):
                try:
                    proc_id = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
                    visible = bool(user32.IsWindowVisible(hwnd))
                    enabled = bool(user32.IsWindowEnabled(hwnd))
                    if proc_id.value == pid and visible and enabled:
                        buf = ctypes.create_unicode_buffer(256)
                        user32.GetWindowTextW(hwnd, buf, 255)
                        title = (buf.value or '').strip()
                        if title:
                            hwnd_found.value = hwnd
                            return False
                except Exception:
                    pass
                return True
            try:
                user32.EnumWindows(EnumWindowsProc(_enum), 0)
            except Exception:
                pass
        hwnd = int(hwnd_found.value or 0)
        if not hwnd:
            try:
                hwnd = int(user32.GetForegroundWindow() or 0)
            except Exception:
                hwnd = 0
        if not hwnd:
            return False
        try:
            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.08)
            return True
        except Exception:
            return False

    def _system_mouse_wheel_scroll(self, p, points, delta_y, label='winWheel'):
        if os.name != 'nt':
            return {'moved': False, 'after': 0, 'target': 'document', 'tried': label + ':skip_non_windows'}
        try:
            metrics = self._get_browser_screen_metrics(p)
            self._focus_browser_window()
            user32 = ctypes.windll.user32
            scale_list = [metrics.get('dpr', 1.0)]
            if abs(scale_list[0] - 1.0) > 0.05:
                scale_list.append(1.0)
            WHEEL_DELTA = 120
            MOUSEEVENTF_WHEEL = 0x0800
            last_probe = {'pos': 0, 'target': 'document'}
            for idx, pt in enumerate(points or []):
                vx = int(max(20, pt.get('x', 0)))
                vy = int(max(20, pt.get('y', 0)))
                before = self._probe_scroll_pos(p, vx, vy)
                last_probe = before
                steps = max(3, min(10, int(abs(delta_y) / 120) + 1))
                for scale in scale_list:
                    sx = int(round((metrics['screenX'] + metrics['sideGap'] + vx) * scale))
                    sy = int(round((metrics['screenY'] + metrics['topGap'] + vy) * scale))
                    try:
                        user32.SetCursorPos(sx, sy)
                        time.sleep(0.05)
                        for _ in range(steps):
                            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_int(-WHEEL_DELTA), 0)
                            time.sleep(0.05)
                    except Exception:
                        continue
                    time.sleep(0.18)
                    after = self._probe_scroll_pos(p, vx, vy)
                    last_probe = after
                    if int(after.get('pos', 0)) > int(before.get('pos', 0)):
                        return {
                            'moved': True,
                            'after': int(after.get('pos', 0)),
                            'target': after.get('target', 'document'),
                            'tried': f'{label}:p{idx+1}@{vx},{vy}:scale{scale:.2f}'
                        }
            return {
                'moved': False,
                'after': int(last_probe.get('pos', 0) or 0),
                'target': last_probe.get('target', 'document'),
                'tried': label + ':no_move'
            }
        except Exception as e:
            return {'moved': False, 'after': 0, 'target': 'document', 'tried': label + ':err:' + str(e)}

    def _system_drag_scrollbar(self, p, base_info, label='dragBar'):
        if os.name != 'nt':
            return {'moved': False, 'after': 0, 'target': 'document', 'tried': label + ':skip_non_windows'}
        try:
            metrics = self._get_browser_screen_metrics(p)
            self._focus_browser_window()
            user32 = ctypes.windll.user32
            LEFTDOWN = 0x0002
            LEFTUP = 0x0004
            x = int(max(24, min((base_info.get('rectRight') or 200) - 8, (base_info.get('rectRight') or 200))))
            start_y = int(max((base_info.get('rectTop') or 60) + 70, (base_info.get('rectTop') or 60) + int((base_info.get('rectHeight') or 400) * 0.45)))
            end_y = int(min((base_info.get('rectBottom') or 700) - 40, start_y + max(140, int((base_info.get('rectHeight') or 400) * 0.28))))
            before = self._probe_scroll_pos(p, x - 6, start_y)
            scale_list = [metrics.get('dpr', 1.0)]
            if abs(scale_list[0] - 1.0) > 0.05:
                scale_list.append(1.0)
            for scale in scale_list:
                sx = int(round((metrics['screenX'] + metrics['sideGap'] + x) * scale))
                sy1 = int(round((metrics['screenY'] + metrics['topGap'] + start_y) * scale))
                sy2 = int(round((metrics['screenY'] + metrics['topGap'] + end_y) * scale))
                try:
                    user32.SetCursorPos(sx, sy1)
                    time.sleep(0.06)
                    user32.mouse_event(LEFTDOWN, 0, 0, 0, 0)
                    time.sleep(0.04)
                    steps = 8
                    for i in range(steps):
                        cur_y = int(round(sy1 + (sy2 - sy1) * (i + 1) / steps))
                        user32.SetCursorPos(sx, cur_y)
                        time.sleep(0.03)
                    user32.mouse_event(LEFTUP, 0, 0, 0, 0)
                except Exception:
                    try:
                        user32.mouse_event(LEFTUP, 0, 0, 0, 0)
                    except Exception:
                        pass
                    continue
                time.sleep(0.22)
                after = self._probe_scroll_pos(p, x - 6, min(end_y, start_y + 20))
                if int(after.get('pos', 0)) > int(before.get('pos', 0)):
                    return {
                        'moved': True,
                        'after': int(after.get('pos', 0)),
                        'target': after.get('target', 'document'),
                        'tried': f'{label}@{x},{start_y}->{end_y}:scale{scale:.2f}'
                    }
            return {'moved': False, 'after': int(before.get('pos', 0) or 0), 'target': before.get('target', 'document'), 'tried': label + ':no_move'}
        except Exception as e:
            return {'moved': False, 'after': 0, 'target': 'document', 'tried': label + ':err:' + str(e)}

    def _scroll_down(self, p, px):
        try:
            before = self._get_scroll_state(p)
            info = {
                'target': before.get('type', 'document'),
                'before': int(before.get('pos', 0) or 0),
                'after': int(before.get('pos', 0) or 0),
                'x': int(before.get('wheel_x', 640) or 640),
                'y': int(before.get('wheel_y', 520) or 520),
                'tag': before.get('tag', 'document'),
                'cls': before.get('cls', ''),
                'container_name': before.get('container_name', 'document'),
                'tried': '',
            }

            try:
                p.scroll.down(px)
                info['tried'] = 'dpScroll'
            except Exception as e:
                info['tried'] = 'dpScrollErr:' + str(e)
            time.sleep(0.18)
            after1 = self._get_scroll_state(p)
            info['after'] = int(after1.get('pos', info['after']) or info['after'])
            info['target'] = after1.get('type', info['target'])
            info['container_name'] = after1.get('container_name', info['container_name'])
            if info['after'] > info['before']:
                return info

            x = int(after1.get('wheel_x', before.get('wheel_x', 640)) or 640)
            y = int(after1.get('wheel_y', before.get('wheel_y', 520)) or 520)
            self._trusted_wheel_scroll(p, x, y, px, times=4)
            info['tried'] += '+cdpWheel'
            time.sleep(0.22)
            after2 = self._get_scroll_state(p)
            info['after'] = int(after2.get('pos', info['after']) or info['after'])
            info['target'] = after2.get('type', info['target'])
            info['container_name'] = after2.get('container_name', info['container_name'])
            if info['after'] > info['before']:
                return info

            js = p.run_js(fr"""
                function getWords(){{ return ['打招呼','打个招呼','立即沟通','联系TA']; }}
                function isVisible(el){{
                    if(!el) return false;
                    const s = getComputedStyle(el);
                    if(s.display==='none' || s.visibility==='hidden' || s.opacity==='0') return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 6 && r.height > 6 && r.bottom >= 0 && r.top <= innerHeight;
                }}
                function toClickable(el){{
                    let n = el;
                    for(let i=0;i<8 && n;i++,n=n.parentElement){{
                        const tag=(n.tagName||'').toUpperCase();
                        const role=(n.getAttribute('role')||'').toLowerCase();
                        const s=getComputedStyle(n);
                        if(tag==='BUTTON' || tag==='A' || role==='button' || typeof n.onclick==='function' || s.cursor==='pointer') return n;
                    }}
                    return el;
                }}
                function scoreScrollable(el){{
                    if(!el || el===document.body || el===document.documentElement) return -1;
                    const r = el.getBoundingClientRect();
                    const sh = el.scrollHeight || 0;
                    const ch = el.clientHeight || 0;
                    if(r.width < 260 || r.height < 180) return -1;
                    if(sh <= ch + 12) return -1;
                    const s = getComputedStyle(el);
                    const oy = s.overflowY || s.overflow || '';
                    let score = (sh - ch) * 10 + r.height;
                    const name = `${{el.id || ''}} ${{el.className || ''}}`.toLowerCase();
                    if(['auto','scroll','overlay'].includes(oy)) score += 100000;
                    if(/recommend-wrap/.test(name)) score += 250000;
                    else if(/recommend|candidate|list|wrap|geek/.test(name)) score += 18000;
                    return score;
                }}
                function bestFromNode(node){{
                    let cur = node, best = null, bestScore = -1;
                    for(let i=0;i<18 && cur;i++,cur=cur.parentElement){{
                        const s = scoreScrollable(cur);
                        if(s > bestScore){{ best = cur; bestScore = s; }}
                    }}
                    return best;
                }}
                const words = getWords();
                const nodes = [...document.querySelectorAll('button,a,[role="button"],span,div')];
                const btns = [];
                const seen = new Set();
                for(const node of nodes){{
                    const txt = (node.innerText || node.textContent || '').replace(/\s+/g,' ').trim();
                    if(!words.includes(txt)) continue;
                    const clickable = toClickable(node);
                    if(!isVisible(clickable)) continue;
                    const r = clickable.getBoundingClientRect();
                    const key = `${{Math.round(r.left)}}_${{Math.round(r.top)}}_${{Math.round(r.width)}}_${{Math.round(r.height)}}`;
                    if(seen.has(key)) continue;
                    seen.add(key);
                    btns.push(clickable);
                }}
                let sc = null;
                for(const btn of btns){{
                    const cand = bestFromNode(btn);
                    if(cand && (!sc || scoreScrollable(cand) > scoreScrollable(sc))) sc = cand;
                }}
                if(sc){{
                    const before = Math.round(sc.scrollTop);
                    try{{ sc.scrollTop += {px}; }}catch(e){{}}
                    return {{ target:'inner', before: before, after: Math.round(sc.scrollTop) }};
                }}
                const before = Math.round(window.scrollY);
                try{{ window.scrollBy(0, {px}); }}catch(e){{}}
                return {{ target:'document', before: before, after: Math.round(window.scrollY) }};
            """) or {}
            info['tried'] += '+jsScrollTop'  # noqa
            final_state = self._get_scroll_state(p)
            info['after'] = max(int(js.get('after', info['after']) or info['after']), int(final_state.get('pos', info['after']) or info['after']))
            info['target'] = final_state.get('type', js.get('target', info['target']))
            info['container_name'] = final_state.get('container_name', info['container_name'])
            return info
        except Exception as e:
            self.log(f'  滚动失败: {e}', 'warn')
            return {'target': 'document', 'before': 0, 'after': 0, 'x': 640, 'y': 520, 'tag': 'document', 'cls': '', 'container_name': 'document', 'tried': 'error'}

    def _click_tab(self, p, label):
        self.log(f'查找Tab「{label}」...', 'info')
        try:
            el = p.ele(f'text:{label}', timeout=4)
            if el:
                self.log(f'  找到Tab「{label}」，点击', 'ok')
                el.click()
                return self._sleep_interruptible(2.0)
        except Exception as e:
            self.log(f'  查找Tab失败: {e}', 'warn')
        self.log(f'  未找到Tab「{label}」', 'warn')
        return False

    def _get_tab_plan(self, p):
        try:
            visible_tabs = p.run_js(r"""
                const labels = ['推荐', '最新', '精选'];
                const out = [];
                const nodes = Array.from(document.querySelectorAll('div,span,a,button'));
                for (const node of nodes) {
                    const txt = (node.innerText || node.textContent || '').replace(/\s+/g, '').trim();
                    if (!labels.includes(txt)) continue;
                    const r = node.getBoundingClientRect();
                    const s = getComputedStyle(node);
                    if (r.width < 8 || r.height < 8) continue;
                    if (r.top < -5 || r.top > 220) continue;
                    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') continue;
                    const clickable = ['BUTTON','A'].includes(node.tagName) || (node.getAttribute('role') || '').toLowerCase() === 'button' || s.cursor === 'pointer' || typeof node.onclick === 'function';
                    if (!clickable) continue;
                    if (!out.includes(txt)) out.push(txt);
                }
                return out;
            """) or []
        except Exception:
            visible_tabs = []
        plan = [x for x in ['推荐', '最新', '精选'] if x in visible_tabs]
        return plan or ['推荐', '最新']

    def _check_limit(self, p):
        marks = ['今日沟通已达上限', '打招呼次数已用完', '当日已达上限']
        try:
            body = p.ele('css:body').text or ''
            for m in marks:
                if m in body:
                    self.log(f'Boss限额提示: “{m}”，停止', 'err')
                    return True
        except Exception:
            pass
        return False

    def _handle_dialog(self, p, msg, retry_on_fail=False):
        self.log_sep('处理弹窗')
        if not self._sleep_interruptible(0.8):
            return False
        inp = None
        for sel in ['css:textarea', 'css:[contenteditable="true"]', 'css:input[type="text"]']:
            if self.stop_requested:
                return False
            try:
                el = p.ele(sel, timeout=1.0)
                if el:
                    inp = el
                    self.log(f'  找到输入框: {sel}', 'info')
                    break
            except Exception:
                pass
        if inp:
            try:
                inp.clear()
            except Exception:
                pass
            try:
                inp.input(msg)
                self.log(f'  话术已填入: "{msg[:30]}..."', 'info')
            except Exception as e:
                self.log(f'  填入话术失败: {e}', 'warn')
            if not self._sleep_interruptible(0.3):
                return False
        for word in ['发送', '确认', '打招呼', '确定', '好的', '发起沟通', '立即沟通', '联系TA']:
            if self.stop_requested:
                return False
            try:
                btn = p.ele(f'text:{word}', timeout=0.8)
                if btn:
                    self.log(f'  点击确认: "{word}"', 'info')
                    try:
                        btn.click()
                    except Exception:
                        btn.run_js('this.click()')
                    self._sleep_interruptible(0.6)
                    return not self.stop_requested
            except Exception:
                pass
        if inp and not self.stop_requested:
            try:
                inp.input('\n')
                self.log('  回车发送', 'info')
                self._sleep_interruptible(0.6)
                return not self.stop_requested
            except Exception:
                pass
        # 重试逻辑：关闭当前弹窗后换一条话术再试一次
        if not retry_on_fail:
            self.log('  首次发送失败，尝试关闭弹窗重试...', 'warn')
            try:
                for close_word in ['关闭', '取消', '×', 'x']:
                    try:
                        cb = p.ele(f'text:{close_word}', timeout=0.5)
                        if cb:
                            cb.click()
                            self._sleep_interruptible(0.5)
                            break
                    except Exception:
                        pass
            except Exception:
                pass
            self._sleep_interruptible(0.6)
            return self._handle_dialog(p, msg, retry_on_fail=True)
        self.log('  未找到确认按钮，视为未发送', 'warn')
        return False


    # ---------- browser ----------
    def _debug_port_alive(self, port=DEBUG_PORT, timeout=1.0):
        import socket
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=timeout):
                return True
        except Exception:
            return False

    def _launch_browser_process(self, browser_path: str):
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        screen_w = max(1200, self.root.winfo_screenwidth())
        screen_h = max(800, self.root.winfo_screenheight())
        half_w = max(980, int(screen_w * 0.50))
        use_h = max(720, int(screen_h * 0.94))
        cmd = [
            browser_path,
            f'--remote-debugging-port={DEBUG_PORT}',
            f'--user-data-dir={str(USER_DATA_DIR)}',
            f'--disk-cache-dir={str(CACHE_DIR)}',
            f'--window-position=0,0',
            f'--window-size={half_w},{use_h}',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-popup-blocking',
            '--disable-gpu',
            '--remote-allow-origins=*',
            REC_URL,
        ]
        self.log(f'浏览器路径: {browser_path}', 'info')
        self.log(f'调试端口: {DEBUG_PORT}', 'info')
        self.log(f'用户目录: {USER_DATA_DIR}', 'info')
        self.log(f'窗口布局: 左半屏 {half_w}x{use_h}', 'info')
        if self.browser_proc and self.browser_proc.poll() is None:
            self.log('检测到上一次浏览器进程仍在，先复用当前实例。', 'warn')
            return
        # 把浏览器的报错写进日志文件，打不开时能看到原因（不再直接丢弃）
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        browser_log = LOG_ROOT / 'browser_console.log'
        blog_fp = open(browser_log, 'a', encoding='utf-8', errors='replace')
        self.browser_proc = subprocess.Popen(cmd, stdout=blog_fp, stderr=blog_fp)
        self.log(f'浏览器控制台日志: {browser_log}', 'info')

    def _connect_browser(self):
        errs = []
        for target in (DEBUG_PORT, f'127.0.0.1:{DEBUG_PORT}'):
            try:
                self.browser = Chromium(target)
                self.page = self.browser.latest_tab
                if self.page:
                    return
                errs.append(f'Chromium({target!r}) latest_tab 为空')
            except Exception as e:
                errs.append(f'Chromium({target!r}) -> {type(e).__name__}: {e}')
        try:
            co = ChromiumOptions().set_address(f'127.0.0.1:{DEBUG_PORT}')
            self.browser = Chromium(co)
            self.page = self.browser.latest_tab
            if self.page:
                return
        except Exception as e:
            errs.append(f'ChromiumOptions -> {type(e).__name__}: {e}')
        try:
            self.page = ChromiumPage(DEBUG_PORT)
            if self.page:
                try:
                    self.browser = self.page.browser
                except Exception:
                    self.browser = None
                return
        except Exception as e:
            errs.append(f'ChromiumPage -> {type(e).__name__}: {e}')
        raise RuntimeError('已检测到调试端口，但浏览器接管失败。\n' + '\n'.join(errs[:6]))

    def _open(self):
        if self.running:
            self.log('当前正在招聘中，请先停止再重新启动浏览器。', 'warn')
            return
        if self.opening:
            self.log('浏览器正在启动中，请不要重复点击。', 'warn')
            return
        if not HAS_DP:
            messagebox.showerror('DrissionPage 导入失败', f'当前解释器：{sys.executable}\n请先运行 START_01_INSTALL.bat\n\n{DP_IMPORT_ERROR[:1200]}')
            return
        def _do():
            self._set_opening(True)
            try:
                self.log_sep('启动浏览器')
                self.page = None
                self.browser = None
                browser_path, found_browsers = find_browser_path()
                if not browser_path:
                    raise RuntimeError('未找到 Chrome 或 Edge 浏览器。')
                self.log('检测到本机浏览器: ' + (' | '.join(found_browsers) if found_browsers else '无'), 'info')
                self.root.after(0, lambda: self.card_browser.config(text='浏览器：启动中'))
                self.st('正在启动浏览器...')
                if self._debug_port_alive():
                    self.log(f'检测到调试端口 {DEBUG_PORT} 已有浏览器在运行，直接复用，不再新开窗口。', 'warn')
                else:
                    self._launch_browser_process(browser_path)
                    self.log('浏览器进程已拉起，检测调试端口...', 'info')
                ok, detail = wait_debug_port(DEBUG_PORT, timeout=18)
                if not ok:
                    raise RuntimeError(
                        '调试端口未就绪，浏览器可能没有真正打开。\n'
                        '请按 Ctrl+Shift+Esc 打开任务管理器，结束所有 Chrome/Edge 进程后重试。\n'
                        f'检测结果: {detail}\n（浏览器日志见程序目录 logs\\browser_console.log）')
                self.log('调试端口已就绪', 'ok')
                self.log(f'端口信息: {detail[:140]}...', 'info')
                self._connect_browser()
                self.log('浏览器连接成功', 'ok')
                self.log(f'当前页面: {self.page.url}', 'info')
                if 'zhipin.com' not in (self.page.url or ''):
                    self.page.get(REC_URL)
                    self.log('已导航到推荐牛人页面', 'ok')
                self.log('请在打开的浏览器里扫码登录 Boss 直聘 HR 账号', 'warn')
                self.log('登录完成后，再点「② 开始招聘」', 'info')
                self.root.after(0, lambda: self.card_browser.config(text='浏览器：已连接'))
                self.st('浏览器已就绪 — 登录后点“开始招聘”')
                self.root.after(0, lambda: self.btn_start.config(state='normal'))
            except Exception as e:
                self.page = None
                self.browser = None
                self.log(f'启动失败: {type(e).__name__}: {e}', 'err')
                self.root.after(0, lambda: self.card_browser.config(text='浏览器：失败'))
                self.st('启动失败，请查看日志')
            finally:
                self._set_opening(False)
        threading.Thread(target=_do, daemon=True).start()

    # ---------- run ----------
    def _start(self):
        if self.running:
            self.log('当前任务正在运行，请勿重复点击“开始招聘”。', 'warn')
            return
        if self.opening:
            self.log('浏览器仍在启动中，请等待“浏览器连接成功”后再开始招聘。', 'warn')
            return
        if not self.page:
            messagebox.showwarning('提示', '请先点“启动浏览器”并等待日志显示“浏览器连接成功”')
            return
        c = self._read_cfg()
        if not c['job']:
            messagebox.showwarning('提示', '请填写招聘岗位名称')
            return
        try:
            if c.get('work_start_enabled') == '1':
                self._parse_time(c['work_start'])
            if c.get('work_end_enabled') == '1':
                self._parse_time(c['work_end'])
        except Exception as e:
            messagebox.showwarning('提示', f'时间设置有误：{e}')
            return
        try:
            iMin, iMax, _auto_wait = self._resolve_interval_range(c)
            if iMin > iMax:
                messagebox.showwarning('提示', '最短间隔不能大于最长间隔')
                return
        except Exception:
            messagebox.showwarning('提示', '间隔格式不正确，请填写数字秒数或“机器自适应”')
            return
        try:
            break_after_min, break_pause_min, break_pause_max = self._resolve_break_plan(c)
            if break_after_min != 0 and break_after_min < 1:
                messagebox.showwarning('提示', '连续运行时长填写 0 表示关闭，或填写大于等于 1 的分钟数。')
                return
        except Exception:
            messagebox.showwarning('提示', '中途暂停设置格式不正确，请填写数字。')
            return
        if c.get('include_words') and c.get('include_mode') == '关闭':
            c['include_mode'] = '任一'
            self.log('检测到已填写“包含词”，已自动按“任一词命中”处理。', 'warn')
        # 打招呼与“独立模式”的自动回复、复聊唤醒共用同一个浏览器，同时开会互相抢页面、更容易触发风控。
        # 开始打招呼时，若这两个线程还在跑，先自动停掉（推荐用“同步模式”代替独立模式回复）。
        if self.ai_panel is not None and self.ai_panel.engine.reply_running:
            self.ai_panel.engine.stop_reply_loop()
            self.log('检测到“独立模式”自动回复正在运行，已自动停止（避免和打招呼抢页面）。建议改用“同步模式”。', 'warn')
        if self.ai_panel is not None and self.ai_panel.engine.reengage_running:
            self.ai_panel.engine.stop_reengage_loop()
            self.log('检测到“复聊唤醒”正在运行，已自动停止（避免和打招呼抢页面）。', 'warn')
        save_cfg(c)
        self.running = True
        self.paused = False
        self.stop_requested = False
        self.cnt = {'ok': 0, 'skip': 0, 'fail': 0, 'sniffed': 0}
        self.processed_fp = set()
        self.run_dir = None
        self.log_file_path = None
        self.journal_file_path = None
        self.matched_csv_path = None
        self.skipped_csv_path = None
        self._ensure_run_artifacts()
        self.log(f'本次运行日志目录: {self.run_dir}', 'info')
        self._record_event('run_start', job=c['job'])
        self.upd_cnt()
        self.btn_open.config(state='disabled')
        self.btn_start.config(state='disabled')
        self.btn_pause.config(state='normal')
        self.btn_stop.config(state='normal')
        self.btn_reset.config(state='disabled')
        self.st('正在执行筛选与打招呼...')
        threading.Thread(target=self._engine, daemon=True).start()

    def _pause(self):
        if self.stop_requested:
            return
        self.paused = not self.paused
        if self.paused:
            self.btn_pause.config(text='继续')
            self.log('【暂停】点“继续”恢复', 'warn')
            self.st('已暂停')
        else:
            self.btn_pause.config(text='暂停')
            self.log('【继续】恢复运行', 'ok')
            self.st('继续运行中...')

    def _stop(self):
        self.stop_requested = True
        self.running = False
        self.paused = False
        self.log('【手动停止】已请求，当前步骤会尽快中断', 'warn')
        self._record_event('manual_stop')
        self.st('正在停止...')

    def _reset_btns(self):
        def _():
            self.btn_open.config(state='normal')
            self.btn_start.config(state='normal' if self.page else 'disabled')
            self.btn_pause.config(state='disabled', text='暂停')
            self.btn_stop.config(state='disabled')
            self.btn_reset.config(state='normal')
        self.root.after(0, _)

    def _append_matched(self, tab, info, fp, matched_words, company_hits):
        self._append_csv(self.matched_csv_path, [
            datetime.datetime.now().isoformat(timespec='seconds'),
            tab,
            info.get('name', ''),
            info.get('gender', ''),
            info.get('age', ''),
            info.get('education', ''),
            info.get('active', ''),
            info.get('job', ''),
            info.get('salary', ''),
            fp,
            '|'.join(matched_words or []),
            '|'.join(company_hits or []),
        ])

    def _append_skipped(self, tab, info, fp, reason, detail=''):
        self._append_csv(self.skipped_csv_path, [
            datetime.datetime.now().isoformat(timespec='seconds'),
            tab,
            info.get('name', ''),
            info.get('gender', ''),
            info.get('age', ''),
            info.get('education', ''),
            info.get('active', ''),
            info.get('job', ''),
            info.get('salary', ''),
            fp,
            reason,
            detail,
        ])

    def _engine(self):
        c = self.cfg
        job = c['job']
        exclude_words = self._parse_words(c.get('exclude_words', ''))
        include_words = self._parse_words(c.get('include_words', ''))
        include_mode = MODE_DISPLAY_TO_INTERNAL.get(c.get('include_mode', '任一'), '任一')
        greeting_templates = self._get_greeting_templates()
        msg = self._pick_greeting(job)
        job_keywords = self._derive_job_keywords(job)
        maxN = int(c['maxN'] or 100)
        iMin, iMax, auto_wait = self._resolve_interval_range(c)
        break_after_min, break_pause_min, break_pause_max = self._resolve_break_plan(c)
        break_after_seconds = int(break_after_min * 60) if break_after_min > 0 else 0
        p = self.page
        cycle = 0
        last_break_ts = time.monotonic()
        tabs = []
        current_tab_idx = 0
        tab = '推荐'
        done_fp = self.processed_fp
        persisted_fp = self._load_dedup()
        if persisted_fp:
            self.log(f'已加载 {len(persisted_fp)} 条历史沟通记录，将自动跳过', 'info')
        skip_stats = {}
        try:
            self.log_sep('启动参数')
            self.log(f'岗位: {job}', 'ok')
            self.log(f'排除词: {exclude_words or "无"}', 'info')
            self.log(f'岗位关键词: {job_keywords or "无"}', 'info')
            self.log(f'简历关键词: {include_words or "无"} | 规则: {MODE_INTERNAL_TO_DISPLAY.get(include_mode, include_mode)}', 'info')
            self.log(f'性别: {c.get("gender", "不限")} | 未知放行={str(c.get("gender_unknown_pass", "1")) != "0"}', 'info')
            self.log(f'活跃度: {c.get("active_filter", "不限")}', 'info')
            self.log(f'目标公司词: {self._parse_words(c.get("company_include", "")) or "无"} | 屏蔽公司词: {self._parse_words(c.get("company_block", "")) or "无"}', 'info')
            self.log(f'年龄: {c.get("age_min", "不限")}-{c.get("age_max", "不限")} | 学历: {c.get("education_filter", "不限")}', 'info')
            self.log(f'话术模板: {len(greeting_templates)} 条 | 示例: {msg[:42]}...', 'info')
            wait_mode = '机器自适应' if auto_wait else '手动设置'
            self.log(f'间隔: {iMin}-{iMax}s | 模式: {wait_mode} | 单轮上限: {maxN} | 今日上限: {c.get("daily_max", "0")}', 'info')
            if break_after_seconds > 0:
                self.log(f'中途暂停: 连续运行 {break_after_min:g} 分钟后，暂停 {break_pause_min}-{break_pause_max} 秒，并模拟点击其他模块', 'info')
            else:
                self.log('中途暂停: 未启用', 'info')
            time_desc = []
            if c.get('work_start_enabled') == '1':
                time_desc.append(f'开始 {c.get("work_start")}')
            if c.get('work_end_enabled') == '1':
                time_desc.append(f'结束 {c.get("work_end")}')
            time_text = ' / '.join(time_desc) if time_desc else '未启用'
            self.log(f'定时限制: {time_text}', 'info')

            self.log('导航到推荐牛人页...', 'warn')
            p.get(REC_URL)
            if not self._sleep_interruptible(3):
                return

            self.log('等待页面加载...', 'info')
            if not self._sleep_interruptible(2):
                return
            tabs = self._get_tab_plan(p)
            current_tab_idx = tabs.index('推荐') if '推荐' in tabs else 0
            tab = tabs[current_tab_idx]
            tab_stuck_counts = {name: 0 for name in tabs}
            self.log(f'本轮Tab计划: {tabs}', 'info')
            last_synced_reply_ts = 0.0

            while self.running and not self.stop_requested:
                if self.paused and not self._wait_if_paused():
                    break
                in_window, window_desc = self._within_work_window()
                if not in_window:
                    self.log(f'当前不在打招呼时段内（{window_desc}），已自动暂停等待。', 'warn')
                    self.st('时段外暂停中...')
                    while self.running and not self.stop_requested:
                        ok, _ = self._within_work_window()
                        if ok:
                            self.log('已进入允许时段，恢复执行。', 'ok')
                            self.st('恢复执行中...')
                            break
                        time.sleep(15)
                    if not self.running or self.stop_requested:
                        break
                if break_after_seconds > 0 and (time.monotonic() - last_break_ts) >= break_after_seconds:
                    pause_seconds = random.randint(break_pause_min, break_pause_max)
                    if not self._run_scheduled_break(p, pause_seconds):
                        break
                    last_break_ts = time.monotonic()
                    tabs = self._get_tab_plan(p)
                    current_tab_idx = tabs.index('推荐') if '推荐' in tabs else 0
                    tab = tabs[current_tab_idx]
                    tab_stuck_counts = {name: 0 for name in tabs}
                daily_hit, used, limit = self._daily_limit_reached()
                if daily_hit:
                    self.log(f'已达到今日上限 {used}/{limit}，本次运行结束，次日自动重置。', 'warn')
                    break
                if self.cnt['ok'] >= maxN:
                    self.log(f'已达本次上限 {maxN} 人，停止', 'ok')
                    break
                if self._check_limit(p):
                    break

                # 同步模式：每隔一段时间，在打招呼间隙回一轮未读消息
                if self.ai_panel is not None and self.ai_panel.reply_synced_enabled():
                    try:
                        gap_min = float(self.ai_panel.cfg.get('reply_gap_minutes', '20') or '20')
                    except Exception:
                        gap_min = 20
                    gap_sec = max(5, int(gap_min * 60))
                    if time.monotonic() - last_synced_reply_ts >= gap_sec:
                        if self._try_synced_reply_during_break():
                            last_synced_reply_ts = time.monotonic()

                self.log_sep(f'扫描页面 Tab:{tab}')
                greet_btns = self._find_greet_btns(p)
                self.log(f'找到可操作按钮: {len(greet_btns)} 个', 'info')
                new_btns = []
                for btn in greet_btns:
                    try:
                        fp = self._btn_fp(btn)
                        if fp not in done_fp:
                            new_btns.append(btn)
                    except Exception:
                        pass
                self.log(f'未处理按钮: {len(new_btns)} 个', 'info')

                hit = 0
                for btn in new_btns:
                    if self.stop_requested or not self.running:
                        break
                    if self.paused and not self._wait_if_paused():
                        break
                    if break_after_seconds > 0 and (time.monotonic() - last_break_ts) >= break_after_seconds:
                        pause_seconds = random.randint(break_pause_min, break_pause_max)
                        if not self._run_scheduled_break(p, pause_seconds):
                            self.stop_requested = True
                            break
                        last_break_ts = time.monotonic()
                        tabs = self._get_tab_plan(p)
                        current_tab_idx = tabs.index('推荐') if '推荐' in tabs else 0
                        tab = tabs[current_tab_idx]
                        tab_stuck_counts = {name: 0 for name in tabs}
                    if self.cnt['ok'] >= maxN:
                        break
                    daily_hit, used, limit = self._daily_limit_reached()
                    if daily_hit:
                        self.log(f'已达到今日上限 {used}/{limit}，停止本次运行。', 'warn')
                        self.stop_requested = True
                        break
                    try:
                        fp = self._btn_fp(btn)
                        card = self._get_card_text(btn)
                        info = self._extract_profile(card)
                        info['gender'] = self._parse_gender(card)
                        info['active'] = self._parse_active(card)
                        name = info.get('name') or '候选人'
                        self.log_sep(f'候选人: {name}')
                        self.log(f'卡片文字: {card[:150]}', 'info')
                        self._record_event('candidate_seen', name=name, fp=fp, card=card[:240], tab=tab)
                        self.cnt['sniffed'] += 1
                        self.upd_cnt()

                        # 跨会话去重：历史沟通过的自动跳过
                        if fp in persisted_fp:
                            done_fp.add(fp)
                            skip_stats['already_contacted'] = skip_stats.get('already_contacted', 0) + 1
                            self.log('[跳过] 历史已沟通（跨会话去重）', 'info')
                            continue

                        if len(card) < 20 or card in {'打招呼', '打个招呼', '立即沟通', '联系TA'}:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['fake_button'] = skip_stats.get('fake_button', 0) + 1
                            self.log('[跳过] 疑似假按钮/无效卡片', 'warn')
                            self._append_skipped(tab, info, fp, 'fake_button', '')
                            self.upd_cnt()
                            continue
                        if any(m in card for m in ['已沟通', '沟通中', '已打招呼']):
                            done_fp.add(fp)
                            skip_stats['already_contacted'] = skip_stats.get('already_contacted', 0) + 1
                            self.log('[跳过] 已沟通标记', 'info')
                            self._append_skipped(tab, info, fp, 'already_contacted', '')
                            continue
                        hit_w = self._match_exclude_word(card, exclude_words)
                        if hit_w:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['exclude'] = skip_stats.get('exclude', 0) + 1
                            self.log(f'[跳过] 命中排除词 “{hit_w}”', 'warn')
                            self._append_skipped(tab, info, fp, 'exclude', hit_w)
                            self.upd_cnt()
                            continue
                        role_ok, role_hits = self._role_match(card, job_keywords)
                        if not role_ok:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['role_miss'] = skip_stats.get('role_miss', 0) + 1
                            self.log(f'[跳过] 岗位不符: 岗位命中={role_hits}', 'warn')
                            self._append_skipped(tab, info, fp, 'role_miss', f'岗位命中={role_hits}')
                            self.upd_cnt()
                            continue
                        gender_ok, actual_gender = self._gender_match(card)
                        if not gender_ok:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['gender_miss'] = skip_stats.get('gender_miss', 0) + 1
                            self.log(f'[跳过] 性别不符: 实际={actual_gender}', 'warn')
                            self._append_skipped(tab, info, fp, 'gender_miss', actual_gender)
                            self.upd_cnt()
                            continue
                        active_ok, actual_active = self._active_match(card, c.get('active_filter', '不限'))
                        if not active_ok:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['active_miss'] = skip_stats.get('active_miss', 0) + 1
                            self.log(f'[跳过] 活跃度不符: 实际={actual_active}', 'warn')
                            self._append_skipped(tab, info, fp, 'active_miss', actual_active)
                            self.upd_cnt()
                            continue
                        age_ok, actual_age = self._age_match(card)
                        if not age_ok:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['age_miss'] = skip_stats.get('age_miss', 0) + 1
                            self.log(f'[跳过] 年龄不符: 实际={actual_age}', 'warn')
                            self._append_skipped(tab, info, fp, 'age_miss', str(actual_age))
                            self.upd_cnt()
                            continue
                        edu_ok, actual_edu = self._education_match(card)
                        if not edu_ok:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['education_miss'] = skip_stats.get('education_miss', 0) + 1
                            self.log(f'[跳过] 学历不符: 实际={actual_edu}', 'warn')
                            self._append_skipped(tab, info, fp, 'education_miss', str(actual_edu))
                            self.upd_cnt()
                            continue
                        salary_ok, actual_salary = self._salary_match(card)
                        if actual_salary:
                            info['salary'] = actual_salary
                        if not salary_ok:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['salary_miss'] = skip_stats.get('salary_miss', 0) + 1
                            self.log(f'[跳过] 薪资不符: 实际={actual_salary}', 'warn')
                            self._append_skipped(tab, info, fp, 'salary_miss', str(actual_salary))
                            self.upd_cnt()
                            continue
                        hop_ok, hop_detail = self._job_hop_match(card)
                        if not hop_ok:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['hop_miss'] = skip_stats.get('hop_miss', 0) + 1
                            self.log(f'[跳过] 跳槽频率不符: {hop_detail}', 'warn')
                            self._append_skipped(tab, info, fp, 'hop_miss', str(hop_detail))
                            self.upd_cnt()
                            continue
                        company_ok, include_hits, block_hits = self._company_filter(card)
                        if not company_ok:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['company_miss'] = skip_stats.get('company_miss', 0) + 1
                            detail = f'包含={include_hits} 屏蔽={block_hits}'
                            self.log(f'[跳过] 公司筛选未通过: {detail}', 'warn')
                            self._append_skipped(tab, info, fp, 'company_miss', detail)
                            self.upd_cnt()
                            continue
                        inc_ok, inc_hits = self._include_match(card, include_words, include_mode)
                        if not inc_ok:
                            done_fp.add(fp)
                            self.cnt['skip'] += 1
                            skip_stats['include_miss'] = skip_stats.get('include_miss', 0) + 1
                            self.log(f'[跳过] 未命中包含词（{include_mode}）: 命中={inc_hits}', 'warn')
                            self._append_skipped(tab, info, fp, 'include_miss', f'命中={inc_hits}')
                            self.upd_cnt()
                            continue

                        hit += 1
                        if include_words:
                            self.log(f'[命中关键词] 命中={inc_hits} | 岗位命中={role_hits} | 活跃={actual_active} | 性别={actual_gender} | 年龄={actual_age} | 学历={actual_edu} | 薪资={actual_salary} | 跳槽={hop_detail}', 'ok')
                        else:
                            self.log(f'[通过筛选] 岗位命中={role_hits} | 活跃={actual_active} | 性别={actual_gender} | 年龄={actual_age} | 学历={actual_edu} | 薪资={actual_salary} | 跳槽={hop_detail}', 'ok')
                        self._push_marquee_message(info, status='命中', salary_override=actual_salary)
                        try:
                            btn.scroll.to_see()
                        except Exception:
                            pass
                        rt = random.uniform(0.8, 1.6)
                        self.log(f'模拟阅读简历 {rt:.1f}s...', 'info')
                        if not self._sleep_interruptible(rt):
                            break
                        self.log('点击按钮发起沟通...', 'info')
                        if not self._smart_click_btn(btn):
                            raise RuntimeError('点击按钮失败')
                        if not self._sleep_interruptible(0.9):
                            break
                        current_msg = self._pick_greeting(job, name)
                        self.log(f'本次发送话术: {current_msg[:36]}...', 'info')
                        ok = self._handle_dialog(p, current_msg)
                        done_fp.add(fp)
                        if ok:
                            self.cnt['ok'] += 1
                            self._inc_daily_count()
                            self._inc_weekly_count()
                            self._save_dedup_fp(fp)
                            self.log(f'[成功] {name}（累计{self.cnt["ok"]}人）', 'ok')
                            self._push_marquee_message(info, status='已沟通', salary_override=actual_salary)
                            self._append_matched(tab, info, fp, inc_hits if include_words else role_hits, include_hits)
                            self._record_event('candidate_ok', name=name, fp=fp, tab=tab)

                            if 'recommend' not in (p.url or ''):
                                p.get(REC_URL)
                                self._sleep_interruptible(2.0)
                        else:
                            self.cnt['fail'] += 1
                            self.log(f'[失败] {name}', 'err')
                            self._record_event('candidate_fail', name=name, fp=fp, tab=tab)
                        self.upd_cnt()
                        wait = random.uniform(iMin, iMax)
                        self.log(f'等待 {wait:.1f}s...', 'info')
                        self.st(f'Tab:{tab} | 成功:{self.cnt["ok"]} | 等待{wait:.1f}s')
                        if not self._sleep_interruptible(wait):
                            break
                    except Exception as e:
                        snap = self._take_snapshot('candidate_error')
                        self.cnt['fail'] += 1
                        self.log(f'[异常] {e}' + (f' | 截图: {snap}' if snap else ''), 'err')
                        self._record_event('candidate_exception', error=str(e), fp=locals().get('fp', ''), name=locals().get('name', ''), screenshot=snap or '')
                        self.upd_cnt()
                        try:
                            done_fp.add(fp)
                        except Exception:
                            pass

                if self.stop_requested or not self.running:
                    break
                self.log_sep('决策')
                self.log(f'本轮通过: {hit} 人', 'info')
                before = self._get_scroll_state(p)
                self.log(f'滚动状态: type={before.get("type")} pos={before.get("pos")} client={before.get("clientH")} scroll={before.get("scrollH")} bottom={before.get("atBottom")} tip={before.get("bottomTip")} loading={before.get("loading")} footer={before.get("footer","无")[:40] or "无"}', 'info')
                px = max(320, int(before.get('clientH', 420) * 0.82))
                self.log(f'向下滑动 {px}px，继续嗅探当前页签...', 'info')
                moved_info = self._scroll_down(p, px)
                container_name = str(moved_info.get('container_name') or before.get('container_name') or 'document')
                suffix = '（找到了正确容器）' if 'recommend-wrap' in container_name else ''
                self.log(f'  滚动容器: {container_name}{suffix}', 'info')
                self.log(f'  滑动目标: {moved_info.get("target")} | 位移={moved_info.get("after",0) - moved_info.get("before",0)}', 'info')
                if not self._sleep_interruptible(1.1):
                    break
                after = self._get_scroll_state(p)
                probe_btns = self._find_greet_btns(p)
                probe_new = 0
                for _b in probe_btns:
                    try:
                        if self._btn_fp(_b) not in done_fp:
                            probe_new += 1
                    except Exception:
                        pass
                moved = after.get('pos', 0) > before.get('pos', 0) or moved_info.get('after',0) > moved_info.get('before',0)
                self.log(f'滑动结果: pos {before.get("pos")} -> {after.get("pos")} | 新按钮 {probe_new} 个 | 到底={after.get("atBottom")} | 底部提示={after.get("bottomTip")} | 加载中={after.get("loading")} | 尝试={moved_info.get("tried","-")} | 目标={moved_info.get("target")}', 'info')
                if moved or probe_new > 0:
                    tab_stuck_counts[tab] = 0
                    continue
                if after.get('loading'):
                    tab_stuck_counts[tab] = 0
                    self.log(f'Tab[{tab}] 底部仍显示“正在加载中...”，继续留在当前页签等待并下滑。', 'warn')
                    if not self._sleep_interruptible(1.2):
                        break
                    continue
                tab_stuck_counts[tab] = tab_stuck_counts.get(tab, 0) + 1
                if not after.get('bottomTip') and not after.get('atBottom'):
                    self.log(f'Tab[{tab}] 尚未检测到到底提示；连续无位移第 {tab_stuck_counts[tab]} 次，继续在当前页签下滑。', 'warn')
                    if not self._sleep_interruptible(0.8):
                        break
                    continue
                if not after.get('bottomTip') and after.get('atBottom') and tab_stuck_counts[tab] < 6:
                    self.log(f'Tab[{tab}] 已接近物理底部，但还没看到明确“到底/没有更多”提示；继续留在当前页签复核第 {tab_stuck_counts[tab]} 次。', 'warn')
                    if not self._sleep_interruptible(0.8):
                        break
                    continue
                self.log(f'Tab[{tab}] 已识别到底或稳定停留在底部，切换到下一个模块。', 'warn')
                next_idx = current_tab_idx + 1
                if next_idx < len(tabs):
                    if self._click_tab(p, tabs[next_idx]):
                        current_tab_idx = next_idx
                        tab = tabs[current_tab_idx]
                        tab_stuck_counts[tab] = 0
                        if not self._sleep_interruptible(1.2):
                            break
                        continue
                cycle += 1
                self.log(f'所有Tab都已处理完成，刷新回推荐（第{cycle}轮）...', 'warn')
                try:
                    p.get(REC_URL)
                    if not self._sleep_interruptible(3):
                        break
                    tabs = self._get_tab_plan(p)
                    current_tab_idx = tabs.index('推荐') if '推荐' in tabs else 0
                    tab = tabs[current_tab_idx]
                    tab_stuck_counts = {name: 0 for name in tabs}
                except Exception as e:
                    self.log(f'刷新异常: {e}', 'warn')
                    break

            self.log_sep('运行结束')
            self.log(f'成功:{self.cnt["ok"]}  跳过:{self.cnt["skip"]}  失败:{self.cnt["fail"]}  筛选:{self.cnt.get("sniffed", 0)}', 'ok')
            self._record_event('run_end', ok=self.cnt['ok'], skip=self.cnt['skip'], fail=self.cnt['fail'])
            self.st(f'已结束 | 成功{self.cnt["ok"]}人')
            # 跳过原因统计
            if skip_stats:
                total_skip = sum(skip_stats.values())
                reason_labels = {
                    'already_contacted': '已沟通（跨会话去重）',
                    'fake_button': '假按钮/无效卡片',
                    'exclude': '命中排除词',
                    'role_miss': '岗位不符',
                    'gender_miss': '性别不符',
                    'active_miss': '活跃度不符',
                    'age_miss': '年龄不符',
                    'education_miss': '学历不符',
                    'salary_miss': '薪资不符',
                    'hop_miss': '跳槽频率不符',
                    'company_miss': '公司筛选未通过',
                    'include_miss': '未命中包含词',
                }
                self.log('--- 跳过原因分布 ---', 'sep')
                for key, label in reason_labels.items():
                    n = skip_stats.get(key, 0)
                    if n > 0:
                        pct = n / total_skip * 100
                        self.log(f'  {label}: {n} 人 ({pct:.1f}%)', 'info')
                self.log(f'  合计跳过: {total_skip} 人', 'sep')
        except Exception as e:
            self.log(f'引擎异常: {e}', 'err')
        finally:
            self.running = False
            self.stop_requested = False
            self._reset_btns()

    def on_close(self):
        self.stop_requested = True
        self.running = False
        try:
            if self.browser:
                self.browser.quit()
            elif self.page:
                self.page.quit()
        except Exception:
            pass
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    app = App(root)
    root.protocol('WM_DELETE_WINDOW', app.on_close)
    root.mainloop()
