# -*- coding: utf-8 -*-
"""
AI 功能控制器。

这一版按"新手也要看得懂 + 不占地方"的原则拆成三块：
1. build_quick_actions(parent) —— 常驻不折叠，放在"①启动浏览器②开始招聘"按钮下方：
   知识库入口（打开公司介绍/问答规则）+ 独立模式回复/复聊唤醒的启停按钮 + "更多参数"入口。
   这是日常开工前后最常点的东西，所以不折叠，直接铺开在按钮下面，不留空白。
2. build_full_panel(parent) —— 可折叠的大面板（放在原来"滚动播报"的位置），默认收起，
   只占一行状态摘要。点"展开设置"才显示：新手指引、运行模式、DeepSeek Key、招聘微信号。
   这些是"配置完基本不用天天看"的东西，收起来不占地方。
3. open_advanced()           —— 小弹窗，只放"配置一次基本不用再碰"的参数：模型名称、
   回复节奏、复聊风控数字、简历识别关键词。从 build_quick_actions 里的"更多参数"按钮打开。

三者共用同一个 AIPanel 实例里的 engine / limiter / cfg，状态是同步的。
"""
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from ai_config import load_ai_cfg, save_ai_cfg, knowledge_dir
from rate_limiter import ActionLimiter
from deepseek_client import DeepSeekClient
from knowledge_base import KnowledgeBase
from chat_ai_engine import ChatAIEngine


class AIPanel:
    """
    用法（在 boss_recruiter.py 的 App 类里，__init__ 中 _build() 之前构造）：
        from ai_panel import AIPanel
        self.ai_panel = AIPanel(self.root, get_page=lambda: self.page,
                                 job_title_getter=lambda: self.v_job.get(),
                                 main_log=self.log)
    然后在 _build() 里合适的位置：
        self.ai_panel.build_quick_actions(left).pack(fill='x', pady=(6, 4))   # 紧跟在①②按钮下方，不折叠
        self.ai_panel.build_full_panel(left_col).grid(row=1, column=0, sticky='ew')  # 原来放"滚动播报"的地方，可折叠
    """

    def __init__(self, root, get_page, job_title_getter, main_log=None, constraints_getter=None,
                 main_running_getter=None):
        self.root = root
        self.get_page = get_page
        self.job_title_getter = job_title_getter
        self.constraints_getter = constraints_getter
        self.main_log = main_log
        self.main_running_getter = main_running_getter  # 函数：返回"打招呼是否正在运行"，用于避免抢浏览器

        self.cfg = load_ai_cfg()
        self.kb = KnowledgeBase(knowledge_dir())

        self.adv_win = None
        self.full_frame = None
        self.v_status_reply = None
        self.v_status_reengage = None
        self.v_status_paused = None

        self.reply_limiter = ActionLimiter(self.cfg, 'reply_daily_max', 'reply_daily_count',
                                            'reply_daily_count_date', save_cb=save_ai_cfg)
        self.reengage_limiter = ActionLimiter(self.cfg, 'reengage_daily_max', 'reengage_daily_count',
                                               'reengage_daily_count_date', save_cb=save_ai_cfg)
        self.ai_client = DeepSeekClient(
            api_key=self.cfg.get('deepseek_api_key', ''),
            base_url=self.cfg.get('deepseek_base_url'),
            model=self.cfg.get('deepseek_model', 'deepseek-chat'),
        )
        self.engine = ChatAIEngine(
            get_page=self.get_page,
            log=self._log,
            job_title_getter=self.job_title_getter,
            knowledge_base=self.kb,
            deepseek_client=self.ai_client,
            reply_limiter=self.reply_limiter,
            reengage_limiter=self.reengage_limiter,
            cfg_getter=lambda: self.cfg,
            constraints_getter=self.constraints_getter,
        )

    # ---------------- 日志：统一走主窗口右侧的实时日志，AI面板自身不再重复显示 ----------------
    def _log(self, msg, tag='info'):
        if self.main_log:
            try:
                self.main_log(f'[AI] {msg}', tag)
            except Exception:
                pass
        self._refresh_status()

    def _refresh_status(self):
        def _do():
            try:
                mode = self.cfg.get('reply_mode', 'synced')
                if mode == 'off':
                    r_state = '已关闭'
                elif mode == 'synced':
                    r_state = '同步（随打招呼进行）'
                else:
                    r_state = '运行中' if self.engine.reply_running else '未运行'
                e_state = '运行中' if self.engine.reengage_running else '未运行'
                n_paused = len(self.engine._paused_conversations)
                if self.v_status_reply is not None:
                    self.v_status_reply.set(
                        f'AI自动回复：{r_state}  今日 {self.reply_limiter.today_count()}/{self.reply_limiter.daily_max()}')
                if self.v_status_reengage is not None:
                    self.v_status_reengage.set(
                        f'复聊唤醒：{e_state}  今日 {self.reengage_limiter.today_count()}/{self.reengage_limiter.daily_max()}')
                if self.v_status_paused is not None:
                    self.v_status_paused.set(f'已达成目标暂停的会话：{n_paused} 个')
                if getattr(self, 'v_status_summary', None) is not None:
                    self.v_status_summary.set(f'回复：{r_state}　唤醒：{e_state}　暂停会话：{n_paused}个')
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            pass

    # ================= 主面板：直接嵌在主窗口里（放原来"滚动播报"的位置） =================
    # 默认收起，只占一行高度，不会把上面的招聘功能区挤下去；点"展开"才显示完整设置。
    def build_full_panel(self, parent):
        outer = tk.Frame(parent, bg='white', highlightbackground='#e0e3e8', highlightthickness=1)
        self.full_frame = outer
        self._collapsed = True

        # ------- 折叠状态下始终显示的标题栏：标题 + 一行状态摘要 + 展开/收起按钮 -------
        header = tk.Frame(outer, bg='#f8fafc', cursor='hand2')
        header.pack(fill='x')
        tk.Label(header, text='🤖 AI自动回复 / 复聊唤醒', bg='#f8fafc', fg='#1f2937',
                 font=('微软雅黑', 10, 'bold'), cursor='hand2').pack(side='left', padx=(10, 6), pady=8)
        self.v_status_summary = tk.StringVar(value='点右边"展开设置"先配置一下')
        tk.Label(header, textvariable=self.v_status_summary, bg='#f8fafc', fg='#64748b',
                 font=('微软雅黑', 9), cursor='hand2').pack(side='left', padx=(0, 10))
        self.v_toggle_text = tk.StringVar(value='展开设置 ▾')
        btn_toggle = tk.Button(header, textvariable=self.v_toggle_text, command=self._toggle_panel,
                                bg='#7c3aed', fg='white', relief='flat', padx=10, pady=3)
        btn_toggle.pack(side='right', padx=10, pady=6)
        for w_ in (header,):
            w_.bind('<Button-1>', lambda e: self._toggle_panel())

        # ------- 展开后才显示的完整内容 -------
        content = tk.Frame(outer, bg='white', padx=12, pady=10)
        self.content_frame = content

        # 新手指引：不用看文档，面板里直接告诉你怎么用
        guide = tk.Frame(content, bg='#fff7ed', highlightbackground='#fed7aa', highlightthickness=1)
        guide.pack(fill='x', pady=(0, 10))
        tk.Label(guide, text='新手怎么用（照着下面4步来）：', bg='#fff7ed', fg='#c2410c',
                 font=('微软雅黑', 9, 'bold')).pack(anchor='w', padx=8, pady=(6, 2))
        steps = [
            '① 填好下面的 DeepSeek Key（没有的话去 platform.deepseek.com 注册申请，有免费额度）',
            '② 点"打开公司介绍/问答规则"，把里面的示例文字换成你们公司真实情况（岗位、薪资、地址等）',
            '　　同时招多个岗位？公司介绍里可以按"## 岗位：岗位名称"分段写多个岗位，AI会自动按候选人实际应聘的岗位挑对应那段回复，不会串岗位',
            '③ 填一下"招聘微信号"——AI在候选人发来简历之后，会主动把这个微信号发给对方',
            '④ 保持"回复模式=同步"，正常点主窗口上面的"②开始招聘"，AI就会在打招呼过程中自动回消息了',
        ]
        for s in steps:
            tk.Label(guide, text=s, bg='#fff7ed', fg='#9a3412', font=('微软雅黑', 9),
                     wraplength=660, justify='left').pack(anchor='w', padx=8, pady=1)
        tk.Label(guide, text='目标说明：AI会引导候选人留手机号、发简历，拿到简历后发你的微信号给对方，'
                              '微信号发出去这一条之后，这个会话就会自动暂停，不再继续追问，交给你人工接手。'
                              '配置好之后可以点右上角"收起设置"，不会占用招聘功能区的空间。',
                 bg='#fff7ed', fg='#9a3412', font=('微软雅黑', 9), wraplength=660, justify='left').pack(
            anchor='w', padx=8, pady=(2, 6))

        # 状态
        self.v_status_reply = tk.StringVar(value='AI自动回复：未运行')
        self.v_status_reengage = tk.StringVar(value='复聊唤醒：未运行')
        self.v_status_paused = tk.StringVar(value='已达成目标暂停的会话：0 个')
        srow = tk.Frame(content, bg='white')
        srow.pack(fill='x', pady=(0, 8))
        tk.Label(srow, textvariable=self.v_status_reply, bg='white', fg='#334155', font=('微软雅黑', 9)).pack(side='left')
        tk.Label(srow, text='   |   ', bg='white', fg='#cbd5e1').pack(side='left')
        tk.Label(srow, textvariable=self.v_status_reengage, bg='white', fg='#334155', font=('微软雅黑', 9)).pack(side='left')
        tk.Label(srow, text='   |   ', bg='white', fg='#cbd5e1').pack(side='left')
        tk.Label(srow, textvariable=self.v_status_paused, bg='white', fg='#334155', font=('微软雅黑', 9)).pack(side='left')
        tk.Button(srow, text='清空暂停名单', command=self._clear_paused, bg='#64748b', fg='white',
                  relief='flat', padx=6).pack(side='left', padx=(10, 0))

        # 回复模式
        mrow = tk.Frame(content, bg='white')
        mrow.pack(fill='x', pady=(0, 6))
        tk.Label(mrow, text='回复模式:', bg='white', font=('微软雅黑', 9)).pack(side='left')
        self.v_reply_mode = tk.StringVar(value=self.cfg.get('reply_mode', 'synced'))
        mode_options = [
            ('synced', '同步（推荐：跟着"开始招聘"自动回）'),
            ('standalone', '独立（自己单独轮询，不用开打招呼）'),
            ('off', '关闭'),
        ]
        for val, label in mode_options:
            tk.Radiobutton(mrow, text=label, variable=self.v_reply_mode, value=val,
                           command=self._on_mode_change, bg='white', font=('微软雅黑', 9),
                           activebackground='white').pack(side='left', padx=(0, 8))

        # DeepSeek Key
        krow = tk.Frame(content, bg='white')
        krow.pack(fill='x', pady=(0, 6))
        krow.grid_columnconfigure(1, weight=1)
        tk.Label(krow, text='DeepSeek Key:', bg='white', font=('微软雅黑', 9)).grid(row=0, column=0, sticky='w')
        self.v_key = tk.StringVar(value=self.cfg.get('deepseek_api_key', ''))
        tk.Entry(krow, textvariable=self.v_key, show='*', font=('微软雅黑', 9)).grid(row=0, column=1, sticky='ew', padx=(6, 6))
        tk.Button(krow, text='保存', command=self._save_key, bg='#1d4ed8', fg='white', relief='flat', padx=8).grid(row=0, column=2)

        # 招聘微信号（目标核心，单独突出一行）
        wrow = tk.Frame(content, bg='white')
        wrow.pack(fill='x', pady=(0, 6))
        wrow.grid_columnconfigure(1, weight=1)
        tk.Label(wrow, text='招聘微信号:', bg='white', font=('微软雅黑', 9)).grid(row=0, column=0, sticky='w')
        self.v_wechat = tk.StringVar(value=self.cfg.get('recruiter_wechat', ''))
        tk.Entry(wrow, textvariable=self.v_wechat, font=('微软雅黑', 9)).grid(row=0, column=1, sticky='ew', padx=(6, 6))
        tk.Button(wrow, text='保存', command=self._save_wechat, bg='#1d4ed8', fg='white', relief='flat', padx=8).grid(row=0, column=2)
        tk.Label(content, text='不填的话AI只会引导对方发简历，不会主动加微信这一步。',
                 bg='white', fg='#94a3b8', font=('微软雅黑', 8)).pack(anchor='w', pady=(0, 8))

        # 默认收起，不展示 content（保持面板只占标题栏这一行高度）
        self._refresh_status()
        return outer

    # ================= 常驻快捷操作：知识库入口 + 启停按钮，不折叠，紧跟在"启动浏览器/开始招聘"按钮下方 =================
    def build_quick_actions(self, parent):
        frame = tk.Frame(parent, bg='white', highlightbackground='#c4b5fd', highlightthickness=2, padx=10, pady=8)

        title_row = tk.Frame(frame, bg='white')
        title_row.pack(fill='x', pady=(0, 6))
        tk.Label(title_row, text='🤖 AI快捷操作', bg='white', fg='#7c3aed', font=('微软雅黑', 10, 'bold')).pack(side='left')
        tk.Label(title_row, text='（知识库 / 独立模式回复 / 复聊唤醒 —— 完整设置在下面左下角可展开的AI面板里）',
                 bg='white', fg='#94a3b8', font=('微软雅黑', 8)).pack(side='left', padx=(8, 0))

        kb_row = tk.Frame(frame, bg='white')
        kb_row.pack(fill='x', pady=(0, 4))
        tk.Label(kb_row, text='公司信息/常见问题:', bg='white', font=('微软雅黑', 9)).pack(side='left')
        tk.Button(kb_row, text='打开公司介绍', command=lambda: self._open_file(self.kb.company_info_path),
                  relief='flat', bg='#64748b', fg='white', padx=6).pack(side='left', padx=(8, 4))
        tk.Button(kb_row, text='打开问答规则', command=lambda: self._open_file(self.kb.qa_rules_path),
                  relief='flat', bg='#64748b', fg='white', padx=6).pack(side='left', padx=(0, 4))
        tk.Button(kb_row, text='改完点这个生效', command=self._reload_kb,
                  relief='flat', bg='#0f9d7a', fg='white', padx=6).pack(side='left')
        tk.Label(frame, text='这两个都是普通文本文件，用记事本打开直接改成你们公司真实情况就行，改完点"改完点这个生效"，不用重启程序。',
                 bg='white', fg='#94a3b8', font=('微软雅黑', 8), wraplength=660, justify='left').pack(anchor='w', pady=(0, 8))

        brow = tk.Frame(frame, bg='white')
        brow.pack(fill='x')
        tk.Label(brow, text='独立模式回复:', bg='white', font=('微软雅黑', 9)).grid(row=0, column=0, sticky='w')
        tk.Button(brow, text='▶ 启动', command=self._start_reply, bg='#0f9d7a', fg='white', relief='flat', padx=8).grid(row=0, column=1, padx=(6, 4))
        tk.Button(brow, text='■ 停止', command=self._stop_reply, bg='#dc2626', fg='white', relief='flat', padx=8).grid(row=0, column=2)
        tk.Label(brow, text='复聊唤醒:', bg='white', font=('微软雅黑', 9)).grid(row=1, column=0, sticky='w', pady=(6, 0))
        tk.Button(brow, text='▶ 启动', command=self._start_reengage, bg='#0f9d7a', fg='white', relief='flat', padx=8).grid(row=1, column=1, padx=(6, 4), pady=(6, 0))
        tk.Button(brow, text='■ 停止', command=self._stop_reengage, bg='#dc2626', fg='white', relief='flat', padx=8).grid(row=1, column=2, pady=(6, 0))
        tk.Button(brow, text='更多参数（回复节奏/复聊风控/简历关键词）...', command=self.open_advanced,
                  bg='#7c3aed', fg='white', relief='flat', padx=8).grid(row=0, column=4, rowspan=2, padx=(20, 0), sticky='ns')
        tk.Label(frame, text='注意：独立模式回复/复聊唤醒跟"打招呼"共用同一个浏览器页面，不能同时跑（会互相抢页面、乱跳转）。'
                              '想边打招呼边回复消息，用下面AI面板里的"同步"模式即可，不需要点这两个启动按钮。',
                 bg='#fff1f2', fg='#be123c', font=('微软雅黑', 8), wraplength=660, justify='left').pack(anchor='w', pady=(4, 0))

        return frame

    def _toggle_panel(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.content_frame.pack_forget()
            self.v_toggle_text.set('展开设置 ▾')
        else:
            self.content_frame.pack(fill='x')
            self.v_toggle_text.set('收起设置 ▴')

    def _clear_paused(self):
        self.engine.clear_paused()
        self._refresh_status()

    def _save_key(self):
        self.cfg['deepseek_api_key'] = self.v_key.get().strip()
        save_ai_cfg(self.cfg)
        self.ai_client.api_key = self.cfg['deepseek_api_key']
        self._log('DeepSeek Key 已保存', 'ok')

    def _save_wechat(self):
        self.cfg['recruiter_wechat'] = self.v_wechat.get().strip()
        save_ai_cfg(self.cfg)
        self._log(f'招聘微信号已保存：{self.cfg["recruiter_wechat"] or "(空，暂不主动加微信)"}', 'ok')

    # ================= 次要弹窗：只放"配置一次基本不用再碰"的参数 =================
    def open_advanced(self):
        if self.adv_win and self.adv_win.winfo_exists():
            self.adv_win.lift()
            return
        self.adv_win = tk.Toplevel(self.root)
        self.adv_win.title('更多参数设置')
        self.adv_win.geometry('640x640')
        self.adv_win.configure(bg='#f2f3f5')
        self._build_advanced_ui(self.adv_win)

    def _build_advanced_ui(self, w):
        pad = dict(padx=10, pady=6)

        sec1 = tk.LabelFrame(w, text='  DeepSeek 模型  ', bg='white', font=('微软雅黑', 9, 'bold'))
        sec1.pack(fill='x', **pad)
        sec1.grid_columnconfigure(1, weight=1)
        tk.Label(sec1, text='模型:', bg='white').grid(row=0, column=0, sticky='w', padx=6, pady=4)
        self.v_model = tk.StringVar(value=self.cfg.get('deepseek_model', 'deepseek-chat'))
        tk.Entry(sec1, textvariable=self.v_model).grid(row=0, column=1, sticky='ew', padx=6, pady=4)
        tk.Button(sec1, text='保存', command=self._save_model, bg='#1d4ed8', fg='white').grid(row=0, column=2, padx=6)
        tk.Label(sec1, text='一般不用改，默认 deepseek-chat 即可。', bg='white', fg='#94a3b8').grid(row=1, column=0, columnspan=3, sticky='w', padx=6, pady=(0, 4))

        sec2 = tk.LabelFrame(w, text='  目标判定  ', bg='white', font=('微软雅黑', 9, 'bold'))
        sec2.pack(fill='x', **pad)
        tk.Label(sec2, text='简历识别关键词(逗号分隔):', bg='white').grid(row=0, column=0, sticky='w', padx=6, pady=4)
        self.v_resume_keywords = tk.StringVar(value=self.cfg.get('resume_keywords', ''))
        tk.Entry(sec2, textvariable=self.v_resume_keywords, width=30).grid(row=0, column=1, sticky='ew', padx=6, pady=4)
        self.v_pause_after_goal = tk.BooleanVar(value=str(self.cfg.get('pause_after_goal', '1')) == '1')
        tk.Checkbutton(sec2, text='拿到简历+发过微信号后，自动暂停该会话（推荐勾选）', variable=self.v_pause_after_goal,
                       bg='white').grid(row=1, column=0, columnspan=2, sticky='w', padx=6, pady=(0, 4))

        sec3 = tk.LabelFrame(w, text='  自动回复节奏（一般不用改，默认已稳妥）  ', bg='white', font=('微软雅黑', 9, 'bold'))
        sec3.pack(fill='x', **pad)
        self._num_row(sec3, 0, '每天最多回复几条', 'reply_daily_max', '达到后当天停止，第二天自动恢复')
        self._num_row(sec3, 1, '多久检查一次新消息·最小(秒)', 'reply_poll_interval_min', '两次检查之间随机等待的最小秒数')
        self._num_row(sec3, 2, '多久检查一次新消息·最大(秒)', 'reply_poll_interval_max', '两次检查之间随机等待的最大秒数')
        self._time_row(sec3, 3, '开始回复时间', 'reply_work_start', 'reply_work_start_enabled', '到点才开始自动回复')
        self._time_row(sec3, 4, '结束回复时间', 'reply_work_end', 'reply_work_end_enabled', '到点就停止自动回复')
        self._num_row(sec3, 5, '同步模式·每隔几分钟回一轮', 'reply_gap_minutes', '打招呼过程中，每隔这么多分钟切到沟通页回一次未读消息（默认20）')

        sec4 = tk.LabelFrame(w, text='  复聊唤醒（基本不用碰）  ', bg='white', font=('微软雅黑', 9, 'bold'))
        sec4.pack(fill='x', **pad)
        self._num_row(sec4, 0, '每天最多唤醒几人', 'reengage_daily_max', '给很久没回你的候选人发一条问候')
        self._num_row(sec4, 1, '沉寂多少天才唤醒', 'reengage_dormant_days', '候选人超过N天没回消息才去唤醒')
        self._num_row(sec4, 2, '只扫最近N天会话', 'reengage_scan_window_days', '避免翻太久以前的旧账')
        self._num_row(sec4, 3, '两次唤醒最小间隔(小时)', 'reengage_min_gap_hours', '两次唤醒之间至少隔这么久')
        self._num_row(sec4, 4, '两次唤醒最大间隔(小时)', 'reengage_max_gap_hours', '两次唤醒之间最多隔这么久')

        tk.Button(w, text='保存全部设置', command=self._save_all_params,
                  bg='#0f9d7a', fg='white').pack(anchor='e', padx=16, pady=(0, 8))

    def _num_row(self, parent, row, label, key, help_text=''):
        tk.Label(parent, text=label, bg='white').grid(row=row, column=0, sticky='w', padx=6, pady=3)
        var = tk.StringVar(value=str(self.cfg.get(key, '')))
        setattr(self, f'v_{key}', var)
        tk.Entry(parent, textvariable=var, width=9).grid(row=row, column=1, sticky='w', padx=6, pady=3)
        if help_text:
            tk.Label(parent, text=help_text, bg='white', fg='#94a3b8', font=('微软雅黑', 8)).grid(row=row, column=2, sticky='w', padx=6)

    def _time_row(self, parent, row, label, time_key, enabled_key, help_text=''):
        tk.Label(parent, text=label, bg='white').grid(row=row, column=0, sticky='w', padx=6, pady=3)
        var = tk.StringVar(value=str(self.cfg.get(time_key, '')))
        setattr(self, f'v_{time_key}', var)
        tk.Entry(parent, textvariable=var, width=9).grid(row=row, column=1, sticky='w', padx=6, pady=3)
        bvar = tk.BooleanVar(value=str(self.cfg.get(enabled_key, '1')) == '1')
        setattr(self, f'v_{enabled_key}', bvar)
        tk.Checkbutton(parent, text='启用', variable=bvar, bg='white').grid(row=row, column=2, sticky='w', padx=6)
        if help_text:
            tk.Label(parent, text=help_text, bg='white', fg='#94a3b8', font=('微软雅黑', 8)).grid(row=row, column=3, sticky='w', padx=6)

    def _open_file(self, path):
        try:
            os.startfile(str(path))
        except Exception as e:
            messagebox.showinfo('提示', f'无法自动打开，请手动打开文件：\n{path}\n\n{e}')

    def _reload_kb(self):
        self.kb.reload()
        self._log('知识库已重新加载', 'ok')

    def _save_model(self):
        self.cfg['deepseek_model'] = self.v_model.get().strip() or 'deepseek-chat'
        save_ai_cfg(self.cfg)
        self.ai_client.model = self.cfg['deepseek_model']
        self._log('模型设置已保存', 'ok')

    def _save_all_params(self):
        keys = [
            'reply_daily_max', 'reply_poll_interval_min', 'reply_poll_interval_max',
            'reply_gap_minutes', 'resume_keywords',
            'reengage_daily_max', 'reengage_dormant_days', 'reengage_scan_window_days',
            'reengage_min_gap_hours', 'reengage_max_gap_hours',
        ]
        for k in keys:
            var = getattr(self, f'v_{k}', None)
            if var is not None:
                self.cfg[k] = var.get().strip()
        self.cfg['pause_after_goal'] = '1' if getattr(self, 'v_pause_after_goal', None) and self.v_pause_after_goal.get() else '0'
        time_keys = [('reply_work_start', 'reply_work_start_enabled'),
                     ('reply_work_end', 'reply_work_end_enabled')]
        for tkey, ekey in time_keys:
            tvar = getattr(self, f'v_{tkey}', None)
            evar = getattr(self, f'v_{ekey}', None)
            if tvar is not None:
                self.cfg[tkey] = tvar.get().strip()
            if evar is not None:
                self.cfg[ekey] = '1' if evar.get() else '0'
        save_ai_cfg(self.cfg)
        self._log('参数已保存', 'ok')
        self._refresh_status()

    # ================= 启停 =================
    def _on_mode_change(self):
        self.cfg['reply_mode'] = self.v_reply_mode.get()
        save_ai_cfg(self.cfg)
        self._log(f'回复模式已切换为：{self._mode_label()}', 'ok')
        self._refresh_status()

    def _mode_label(self):
        m = self.cfg.get('reply_mode', 'synced')
        return {'synced': '同步', 'standalone': '独立', 'off': '关闭'}.get(m, m)

    def reply_synced_enabled(self):
        """返回是否启用"同步模式"（打招呼中途暂停时自动回未读消息）。"""
        return self.cfg.get('reply_mode', 'synced') == 'synced'

    def _main_greeting_running(self):
        try:
            return bool(self.main_running_getter and self.main_running_getter())
        except Exception:
            return False

    def _start_reply(self):
        mode = self.cfg.get('reply_mode', 'synced')
        if mode == 'off':
            messagebox.showinfo('提示', '自动回复已关闭。请在上方"回复模式"里选择"同步"或"独立"。')
            return
        if mode == 'synced':
            self._log('同步模式已开启：点"② 开始招聘"后，会在中途暂停时自动回复未读消息，无需单独启动。', 'ok')
            self._refresh_status()
            return
        # 独立模式：跟打招呼、复聊唤醒共用同一个浏览器页面，不能同时跑，否则会互相抢页面、页面乱跳转
        if self._main_greeting_running():
            messagebox.showwarning(
                '提示',
                '"打招呼"正在运行中，不能同时启动"独立模式回复"——两个都会控制浏览器页面，'
                '同时开会互相抢，出现乱跳转。\n\n'
                '如果想边打招呼边回复消息，把上面"回复模式"切换成"同步"即可，'
                '不需要单独点启动，打招呼过程中会自动顺带回复。')
            return
        if self.engine.reengage_running:
            messagebox.showwarning('提示', '"复聊唤醒"正在运行中，会跟"独立模式回复"抢同一个浏览器页面，请先停止复聊唤醒再启动。')
            return
        if not self.get_page():
            messagebox.showwarning('提示', '请先在主窗口启动浏览器并登录')
            return
        threading.Thread(target=self.engine.start_reply_loop, daemon=True).start()
        self.root.after(500, self._refresh_status)

    def _stop_reply(self):
        self.engine.stop_reply_loop()
        self.root.after(500, self._refresh_status)

    def _start_reengage(self):
        if self._main_greeting_running():
            messagebox.showwarning(
                '提示',
                '"打招呼"正在运行中，不能同时启动"复聊唤醒"——两个都会控制浏览器页面，'
                '同时开会互相抢，出现乱跳转。请先停止打招呼，或者等打招呼这一轮结束后再启动复聊唤醒。')
            return
        if self.engine.reply_running:
            messagebox.showwarning('提示', '"独立模式回复"正在运行中，会跟"复聊唤醒"抢同一个浏览器页面，请先停止独立模式回复再启动。')
            return
        if not self.get_page():
            messagebox.showwarning('提示', '请先在主窗口启动浏览器并登录')
            return
        threading.Thread(target=self.engine.start_reengage_loop, daemon=True).start()
        self.root.after(500, self._refresh_status)

    def _stop_reengage(self):
        self.engine.stop_reengage_loop()
        self.root.after(500, self._refresh_status)
