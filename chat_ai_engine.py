# -*- coding: utf-8 -*-
"""
AI 聊天引擎：会话监听 + AI自动回复 + 复聊唤醒。

!!! 重要说明 !!!
本模块里的 CSS/XPath 选择器（SELECTORS 字典）是基于 Boss直聘 常见页面结构写的"首版最佳猜测"，
不是从真实页面抓包出来的。第一次跑起来大概率有些选择器对不上（页面会改版、不同账号布局也可能不同）。
这是正常的，也是为什么要"先全部搭起来，再用真实日志细化"——

排查方法：
1. 启动后观察 AI 面板里的实时日志，哪一步找不到元素，日志会明确打印"未找到xxx"。
2. 打开浏览器开发者工具（F12），在对应页面上右键目标元素 -> 检查，对照 SELECTORS 里同名的条目手动改。
3. 改完不用重启程序，重新点一次"开始AI回复"即可生效（模块内没有缓存选择器）。

这样比"我猜一版你完全不能用"更实用：框架、风控节流、规则引擎、DeepSeek调用这些和页面结构无关的部分
已经是可以直接工作的，需要磨合的只是选择器这一层。
"""
import random
import re
import time
import datetime
from pathlib import Path

CHAT_LIST_URL = 'https://www.zhipin.com/web/chat/index'

PHONE_RE = re.compile(r'1[3-9]\d{9}')

# 选择器集中放这里，方便对照真实页面调整，不用去翻整个引擎逻辑。
# 已按 Boss直聘 网页版「沟通」页真实 DOM 校准（直接从真实登录后的页面抓取核对）。
SELECTORS = {
    # 会话列表里的每一个会话条目（真实页面类名 .geek-item）
    'conversation_item': [
        'css:.geek-item',
        'css:.friend-content',
        'css:.conversation-item',
    ],
    # 会话条目里的未读数字角标（真实页面 .badge-count，只有未读会话才有；
    # 注意不要用 [class*="badge"]，因为每条会话都有一个空的 .badge 会被误判）
    'unread_badge': [
        'css:.badge-count',
        'css:[class*="unread-count"]',
        'css:.unread-count',
    ],
    # 会话条目里的候选人姓名（真实页面 .geek-name）
    'conversation_name': [
        'css:.geek-name',
        'css:[class*="name"]',
        'css:.name',
    ],
    # 会话条目里的最后一条消息时间戳（真实页面 .time）
    'conversation_time': [
        'css:.time',
        'css:[class*="time"]',
    ],
    # 聊天窗口里的消息气泡：.item-myself=我方发的，.item-friend=候选人发的（真实页面）
    'message_bubble': [
        'css:.item-friend',
        'css:.item-myself',
        'css:.message-item',
    ],
    # 消息气泡里用来区分"对方发的"还是"我方发的"的 class 关键字
    'message_from_candidate_class_hint': 'item-friend',
    'message_from_self_class_hint': 'item-myself',
    # 消息气泡里的正文（真实页面 .text-content）
    'message_text': [
        'css:.text-content',
        'css:.text',
    ],
    # 聊天输入框：真实页面是 contenteditable 的 div（class=boss-chat-editor-input）
    'chat_input': [
        'css:.boss-chat-editor-input',
        'css:[contenteditable="true"]',
        'css:textarea',
    ],
    # 发送按钮（真实页面 .submit，文字是"发送"）
    'send_button': [
        'css:.submit',
    ],
    'send_button_texts': ['发送'],
    # 聊天面板里显示"该候选人应聘/沟通的职位名称"的元素——这个是新增的，还没有拿真实页面校准过，
    # 是按常见命名习惯猜的候选项。如果发现AI回复串岗位（比如给普工回了工程师话术），
    # 大概率是这里没匹配上，导致退回用顶部搜索框里的职位名。校准方法：
    # 打开一个会话，F12看候选人姓名旁边/上方显示岗位名称的元素是什么class，加进下面列表最前面即可。
    'conversation_position': [
        'css:.position-name',
        'css:.job-title',
        'css:[class*="position"]',
        'css:[class*="job-name"]',
    ],
}


def _first_match(p, selector_list, timeout=1.0):
    for sel in selector_list:
        try:
            el = p.ele(sel, timeout=timeout)
            if el:
                return el, sel
        except Exception:
            continue
    return None, None


def _all_match(p, selector_list, timeout=1.0):
    for sel in selector_list:
        try:
            els = p.eles(sel, timeout=timeout)
            if els:
                return els, sel
        except Exception:
            continue
    return [], None


class ChatAIEngine:
    """
    依赖注入方式使用，方便复用主程序已经登录好的浏览器会话，不需要重新登录：
        engine = ChatAIEngine(get_page=lambda: app.page, log=app.log, ...)
    get_page: 返回当前 DrissionPage 的 page 对象的函数（不要直接传 page，
              因为主程序可能会在启动浏览器时重新赋值 self.page）。
    """

    def __init__(self, get_page, log, job_title_getter,
                 knowledge_base, deepseek_client,
                 reply_limiter, reengage_limiter, cfg_getter,
                 constraints_getter=None):
        self.get_page = get_page
        self.log = log
        self.job_title_getter = job_title_getter  # 函数：返回当前岗位名，用于system prompt
        self.constraints_getter = constraints_getter  # 函数：返回岗位硬性要求（年龄/性别/学历等），可选
        self.kb = knowledge_base
        self.ai = deepseek_client
        self.reply_limiter = reply_limiter
        self.reengage_limiter = reengage_limiter
        self.cfg_getter = cfg_getter  # 函数：返回最新 ai_cfg dict（实时读取，方便中途调参数生效）

        self.reply_running = False
        self.reengage_running = False
        self._reply_stop = False
        self._reengage_stop = False
        # 简单的对话历史缓存，key=会话指纹，value=最近几轮 [{'role','content'}]
        self._history_cache = {}
        # 已经"拿到简历+发过招聘微信号"、判定目标达成、AI不再自动回复的会话名单（程序重启后会清空）
        self._paused_conversations = set()

    def clear_paused(self):
        """清空"已暂停"名单，让AI重新开始处理所有会话（比如你手动确认过某个会话其实还需要继续跟）。"""
        n = len(self._paused_conversations)
        self._paused_conversations.clear()
        self.log(f'已清空暂停名单（共{n}个会话恢复为可自动回复）', 'ok')

    def _detect_resume(self, p, keywords):
        """在聊天窗口里粗略判断"候选人是否发过简历"。用文本关键词匹配（比选择器更不容易因改版失效），
        keywords 是逗号分隔的字符串，比如 '简历,附件简历,在线简历'。"""
        kws = [k.strip() for k in (keywords or '').split(',') if k.strip()]
        if not kws:
            return False
        bubbles, _ = _all_match(p, SELECTORS['message_bubble'], timeout=0.8)
        friend_hint = SELECTORS['message_from_candidate_class_hint']
        for b in bubbles[-15:]:  # 只看最近15条，避免翻到很早以前的无关内容
            try:
                cls = (b.attr('class') or '')
                if friend_hint not in cls:
                    continue
                t = self._bubble_text(b)
                if any(k in t for k in kws):
                    return True
            except Exception:
                continue
        return False


    def _sleep_interruptible(self, seconds, stop_flag_getter, step=0.2):
        elapsed = 0.0
        while elapsed < seconds:
            if stop_flag_getter():
                return False
            time.sleep(min(step, seconds - elapsed))
            elapsed += step
        return not stop_flag_getter()

    def _conv_fingerprint(self, name, extra=''):
        return f'{name}|{extra}'

    # ---------------- AI自动回复 ----------------
    def start_reply_loop(self):
        if self.reply_running:
            self.log('AI自动回复已在运行中', 'warn')
            return
        self._reply_stop = False
        self.reply_running = True
        try:
            self._reply_loop()
        finally:
            self.reply_running = False

    def stop_reply_loop(self):
        self._reply_stop = True

    def reply_once(self):
        """在当前页面上做一轮未读消息扫描+回复（由调用方负责先把页面切到沟通页）。"""
        p = self.get_page()
        if not p:
            return False
        if self.reply_limiter.limit_reached():
            self.log('今日AI回复已达上限，本轮跳过', 'info')
            return False
        try:
            self._scan_and_reply_once(p)
            return True
        except Exception as e:
            self.log(f'单次回复扫描异常: {e}', 'err')
            return False

    def _reply_loop(self):
        from rate_limiter import within_work_window, human_delay, typing_delay_for_text
        self.log('=== AI自动回复 启动 ===', 'sep')
        p = self.get_page()
        if not p:
            self.log('浏览器未连接，无法启动AI自动回复', 'err')
            return
        try:
            p.get(CHAT_LIST_URL)
        except Exception as e:
            self.log(f'打开会话列表失败: {e}', 'err')
            return
        self._sleep_interruptible(3.0, lambda: self._reply_stop)

        while not self._reply_stop:
            c = self.cfg_getter()
            if self.reply_limiter.limit_reached():
                self.log(f'今日AI回复已达上限（{self.reply_limiter.daily_max()}），暂停，明日自动恢复。', 'warn')
                return
            if not within_work_window(c.get('reply_work_start_enabled'), c.get('reply_work_start', '09:00'),
                                        c.get('reply_work_end_enabled'), c.get('reply_work_end', '21:30')):
                self.log('当前不在AI回复工作时段内，等待60秒后重新检查...', 'info')
                if not self._sleep_interruptible(60, lambda: self._reply_stop):
                    break
                continue

            try:
                self._scan_and_reply_once(p)
            except Exception as e:
                self.log(f'AI回复扫描异常: {e}', 'err')

            imin = float(c.get('reply_poll_interval_min', 25))
            imax = float(c.get('reply_poll_interval_max', 55))
            wait = random.uniform(imin, imax)
            self.log(f'本轮扫描完成，等待 {wait:.1f}s 后继续巡检未读消息...', 'info')
            if not human_delay(imin, imax, sleep_check=lambda: not self._reply_stop):
                break
        self.log('=== AI自动回复 已停止 ===', 'sep')

    def _scan_and_reply_once(self, p):
        items, sel = _all_match(p, SELECTORS['conversation_item'])
        if not items:
            self.log('未找到会话列表条目：请确认①已扫码登录HR账号②当前停在“消息”页③左侧确有会话。若都正常则可能是页面改版，需要校准选择器。', 'warn')
            return
        self.log(f'扫描到 {len(items)} 个会话（选择器: {sel}）', 'info')

        unread_items = []
        for it in items:
            badge, _ = _first_match(it, SELECTORS['unread_badge'], timeout=0.3)
            if not badge:
                continue
            # 角标里必须有数字才算未读（空角标不算）
            try:
                badge_text = (badge.text or '').strip()
            except Exception:
                badge_text = ''
            if badge_text:
                unread_items.append(it)
        if not unread_items:
            self.log('本轮没有检测到未读消息。', 'info')
            return
        self.log(f'检测到 {len(unread_items)} 个未读会话，开始处理...', 'ok')

        from rate_limiter import human_delay, typing_delay_for_text
        for it in unread_items:
            if self._reply_stop:
                return
            if self.reply_limiter.limit_reached():
                self.log('处理过程中触达今日上限，停止本轮剩余会话。', 'warn')
                return
            name_el, _ = _first_match(it, SELECTORS['conversation_name'], timeout=0.3)
            name = (name_el.text if name_el else '未知候选人').strip()
            fp = self._conv_fingerprint(name)
            if fp in self._paused_conversations:
                continue  # 已达成目标（拿到简历+发过微信号），AI不再自动回复，等人工跟进
            try:
                it.click()
            except Exception:
                try:
                    it.click(by_js=True)
                except Exception:
                    self.log(f'[{name}] 点击会话失败，跳过', 'warn')
                    continue
            if not self._sleep_interruptible(random.uniform(0.6, 1.2), lambda: self._reply_stop):
                return

            last_msg = self._read_last_candidate_message(p)
            if not last_msg:
                self.log(f'[{name}] 未能读取到对方最新消息，跳过（可能选择器需要校准）', 'warn')
                continue
            self.log(f'[{name}] 收到消息: {last_msg[:40]}', 'info')

            conv_job = self._read_conversation_position(p)
            if conv_job:
                self.log(f'[{name}] 本次对话职位: {conv_job}', 'info')
            else:
                self.log(f'[{name}] 未识别到该会话的职位标签，暂用顶部搜索框里的职位名兜底（可能不准，见文件头说明校准 conversation_position）', 'warn')

            c = self.cfg_getter()
            recruiter_wechat = (c.get('recruiter_wechat', '') or '').strip()
            resume_keywords = c.get('resume_keywords', '简历,附件简历,在线简历,查看简历')
            resume_before = self._detect_resume(p, resume_keywords)

            reply_text, source = self._decide_reply(name, last_msg, job_override=conv_job,
                                                       recruiter_wechat=recruiter_wechat)
            if not reply_text:
                self.log(f'[{name}] 未能生成回复，跳过', 'warn')
                continue

            # 模拟真人打字延迟，规则命中的也走一遍延迟，避免"规则回复"和"AI回复"在速度上被区分出模式
            delay = typing_delay_for_text(
                reply_text,
                float(c.get('reply_typing_delay_per_char', 0.18)),
                float(c.get('reply_typing_delay_min', 1.2)),
                float(c.get('reply_typing_delay_max', 6.0)),
            )
            self.log(f'[{name}] 模拟打字 {delay:.1f}s（来源: {source}）...', 'info')
            if not self._sleep_interruptible(delay, lambda: self._reply_stop):
                return

            ok = self._send_message(p, reply_text)
            if ok:
                self.reply_limiter.record_action()
                self.log(f'[{name}] 已回复: {reply_text[:40]}', 'ok')
                hist = self._history_cache.setdefault(fp, [])
                hist.append({'role': 'user', 'content': last_msg})
                hist.append({'role': 'assistant', 'content': reply_text})
                self._history_cache[fp] = hist[-14:]  # 保留最近7轮，避免窗口太短导致AI"忘记"已回答的问题而重复追问

                # 目标判定：简历已拿到（发送前检测到的） + 这条回复里包含了招聘微信号 -> 视为目标达成，暂停该会话
                wechat_just_sent = bool(recruiter_wechat) and (recruiter_wechat in reply_text)
                if str(c.get('pause_after_goal', '1')) == '1' and resume_before and wechat_just_sent:
                    self._paused_conversations.add(fp)
                    self.log(f'🎯 [{name}] 已获取简历，且本轮已发送招聘微信号，判定目标达成，'
                              f'此会话AI自动回复已暂停，请转人工跟进。', 'ok')
            else:
                self.log(f'[{name}] 发送失败', 'err')

    def _read_last_candidate_message(self, p):
        bubbles, _ = _all_match(p, SELECTORS['message_bubble'], timeout=1.5)
        if not bubbles:
            return None
        friend_hint = SELECTORS['message_from_candidate_class_hint']
        for b in reversed(bubbles):
            try:
                cls = (b.attr('class') or '')
                if friend_hint in cls:
                    txt = self._bubble_text(b)
                    if txt:
                        return txt
            except Exception:
                continue
        # 兜底：选择器分不清正反方时，直接取最后一条消息文本（可能包含自己发的，准确度较低）
        try:
            return self._bubble_text(bubbles[-1])
        except Exception:
            return None

    def _bubble_text(self, b):
        """优先取消息正文（.text-content），避免把时间戳/已读回执/卡片按钮混进正文。"""
        txt_el, _ = _first_match(b, SELECTORS.get('message_text', []), timeout=0.3)
        if txt_el:
            t = (txt_el.text or '').strip()
            if t:
                return t
        return (b.text or '').strip()

    def _read_conversation_position(self, p):
        """读取当前打开会话对应的职位名称（用于区分'该候选人应聘的是哪个岗位'，
        而不是笼统用顶部搜索框里唯一的职位名）。找不到返回 None，调用方会自动兜底。"""
        el, _ = _first_match(p, SELECTORS.get('conversation_position', []), timeout=0.5)
        if not el:
            return None
        try:
            t = (el.text or '').strip()
            return t or None
        except Exception:
            return None

    def _decide_reply(self, name, last_msg, job_override=None, recruiter_wechat=''):
        rule_ans = self.kb.match_rule(last_msg)
        if rule_ans:
            return rule_ans, '规则库'
        if not self.ai.available():
            self.log(f'[{name}] DeepSeek 未配置，且规则未命中，无法生成AI回复', 'warn')
            return None, ''
        try:
            job = job_override or (self.job_title_getter() or '')
            constraints = ''
            if self.constraints_getter:
                try:
                    constraints = self.constraints_getter() or ''
                except Exception:
                    constraints = ''
            system_prompt = self.kb.build_system_prompt(job, constraints, recruiter_wechat)
            fp = self._conv_fingerprint(name)
            history = self._history_cache.get(fp, [])
            reply = self.ai.chat(system_prompt, last_msg, history=history)
            return reply, 'DeepSeek'
        except Exception as e:
            self.log(f'[{name}] 调用DeepSeek失败: {e}', 'err')
            return None, ''

    def _send_message(self, p, text):
        inp, _ = _first_match(p, SELECTORS['chat_input'], timeout=1.5)
        if not inp:
            self.log('  未找到聊天输入框（选择器可能需要校准）', 'warn')
            return False
        # 1. 可靠写入文本（contenteditable + Vue，用 execCommand / input 事件）
        if not self._write_editor_text(inp, text):
            self.log('  写入输入框失败', 'warn')
            return False
        time.sleep(0.4)
        # 2. 校验文本真的在编辑器里。之前“报告成功却没发出去”的根因，就是文本没写进去就点了发送
        if not self._editor_has_text(inp, text):
            if not self._write_editor_text(inp, text):
                return False
            time.sleep(0.4)
            if not self._editor_has_text(inp, text):
                self.log('  文本未写入输入框，放弃发送', 'warn')
                return False
        # 3. 点发送
        time.sleep(0.3)
        if not self._click_send(p):
            self.log('  未找到发送按钮', 'warn')
            return False
        # 4. 确认真的发出去了（看最新一条自己消息，或输入框被清空）
        time.sleep(1.2)
        if self._last_self_message_contains(p, text) or self._editor_is_empty(inp):
            return True
        self.log('  发送结果未确认，请留意聊天窗口是否发出', 'warn')
        return True

    def _write_editor_text(self, inp, text):
        """把文本可靠写入 contenteditable 编辑器，并触发 Vue 能识别的 input/change 事件。"""
        js = """
            const el = this;
            el.focus();
            let ok = false;
            try {
                if (document.execCommand) {
                    document.execCommand('selectAll', false, null);
                    ok = document.execCommand('insertText', false, arguments[0]);
                }
            } catch (e) { ok = false; }
            if (!ok || (el.textContent || '').indexOf(arguments[0]) < 0) {
                el.textContent = arguments[0];
            }
            el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:arguments[0]}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            return (el.textContent || el.innerText || '').trim();
        """
        try:
            result = inp.run_js(js, text) or ''
            return bool(result)
        except Exception:
            return False

    def _editor_has_text(self, inp, text):
        try:
            cur = (inp.text or '').strip()
        except Exception:
            cur = ''
        probe = (text or '').strip()[:8]
        return bool(probe) and probe in cur

    def _editor_is_empty(self, inp):
        try:
            return not (inp.text or '').strip()
        except Exception:
            return False

    def _last_self_message_contains(self, p, text):
        try:
            bubbles = p.eles('css:.item-myself', timeout=1.0)
            if not bubbles:
                return False
            last = bubbles[-1]
            txt_el = last.ele('css:.text-content', timeout=0.3)
            t = (txt_el.text if txt_el else (last.text or '')).strip()
            probe = (text or '').strip()[:10]
            return bool(probe) and probe in t
        except Exception:
            return False

    def _click_send(self, p):
        send_btn, _ = _first_match(p, SELECTORS['send_button'], timeout=0.8)
        if send_btn:
            try:
                send_btn.click()
            except Exception:
                try:
                    send_btn.run_js('this.click()')
                except Exception:
                    return False
            return True
        for word in SELECTORS['send_button_texts']:
            try:
                btn = p.ele(f'text:{word}', timeout=0.6)
                if btn:
                    try:
                        btn.click()
                    except Exception:
                        btn.run_js('this.click()')
                    return True
            except Exception:
                pass
        return False

    # ---------------- 复聊唤醒 ----------------
    def start_reengage_loop(self):
        if self.reengage_running:
            self.log('复聊唤醒已在运行中', 'warn')
            return
        self._reengage_stop = False
        self.reengage_running = True
        try:
            self._reengage_loop()
        finally:
            self.reengage_running = False

    def stop_reengage_loop(self):
        self._reengage_stop = True

    def _reengage_loop(self):
        from rate_limiter import human_delay
        self.log('=== 复聊唤醒 启动（稳妥模式：低频） ===', 'sep')
        p = self.get_page()
        if not p:
            self.log('浏览器未连接，无法启动复聊唤醒', 'err')
            return

        while not self._reengage_stop:
            c = self.cfg_getter()
            if self.reengage_limiter.limit_reached():
                self.log(f'今日复聊唤醒已达上限（{self.reengage_limiter.daily_max()}），暂停，明日自动恢复。', 'warn')
                return

            try:
                did_one = self._reengage_one_candidate(p, c)
            except Exception as e:
                self.log(f'复聊唤醒异常: {e}', 'err')
                did_one = False

            gap_min = float(c.get('reengage_min_gap_hours', 2)) * 3600
            gap_max = float(c.get('reengage_max_gap_hours', 6)) * 3600
            if did_one:
                self.log(f'本次唤醒完成，间隔 {gap_min/3600:.1f}~{gap_max/3600:.1f} 小时后再唤醒下一位（稳妥模式，不批量操作）。', 'info')
            else:
                gap_min, gap_max = 600, 1200  # 没找到沉寂对象时，短一点重试
                self.log('本轮未找到符合条件的沉寂会话，10~20分钟后重新扫描。', 'info')
            if not human_delay(gap_min, gap_max, sleep_check=lambda: not self._reengage_stop, step=1.0):
                break
        self.log('=== 复聊唤醒 已停止 ===', 'sep')

    def _reengage_one_candidate(self, p, c):
        try:
            p.get(CHAT_LIST_URL)
        except Exception as e:
            self.log(f'打开会话列表失败: {e}', 'err')
            return False
        time.sleep(1.5)
        items, _ = _all_match(p, SELECTORS['conversation_item'])
        if not items:
            return False

        dormant_days = float(c.get('reengage_dormant_days', 3))
        window_days = float(c.get('reengage_scan_window_days', 14))
        now = datetime.datetime.now()

        candidate_item = None
        candidate_name = ''
        for it in items:
            time_el, _ = _first_match(it, SELECTORS['conversation_time'], timeout=0.3)
            if not time_el:
                continue
            days_ago = self._parse_relative_days(time_el.text)
            if days_ago is None:
                continue
            if dormant_days <= days_ago <= window_days:
                name_el, _ = _first_match(it, SELECTORS['conversation_name'], timeout=0.3)
                candidate_item = it
                candidate_name = (name_el.text if name_el else '未知候选人').strip()
                break

        if not candidate_item:
            return False

        self.log(f'[{candidate_name}] 符合沉寂唤醒条件（{dormant_days}~{window_days}天未互动），准备发送唤醒消息', 'info')
        try:
            candidate_item.click()
        except Exception:
            try:
                candidate_item.click(by_js=True)
            except Exception:
                self.log(f'[{candidate_name}] 点击会话失败', 'warn')
                return False
        time.sleep(random.uniform(0.8, 1.5))

        conv_job = self._read_conversation_position(p)
        job = conv_job or (self.job_title_getter() or '')
        reengage_msg = self._build_reengage_message(job)
        ok = self._send_message(p, reengage_msg)
        if ok:
            self.reengage_limiter.record_action()
            self.log(f'[{candidate_name}] 已发送唤醒消息: {reengage_msg[:40]}', 'ok')
        else:
            self.log(f'[{candidate_name}] 唤醒消息发送失败', 'err')
        return True

    def _build_reengage_message(self, job):
        # 复聊话术保持简短、非推销感，降低被举报骚扰的概率
        templates = [
            f'您好，之前聊过{job}这个岗位，最近还在看机会吗？方便的话可以继续聊聊～',
            f'Hi，好久没联系啦，{job}岗位现在还有名额，您那边情况有更新吗？',
        ]
        return random.choice(templates)

    def _parse_relative_days(self, text):
        """粗略解析会话列表里的时间文案，例如'3天前''昨天''刚刚''09-12'。解析失败返回None。"""
        if not text:
            return None
        text = text.strip()
        try:
            if '刚刚' in text or '分钟' in text or '小时' in text:
                return 0
            if '昨天' in text:
                return 1
            if '天前' in text:
                num = ''.join(ch for ch in text if ch.isdigit())
                return float(num) if num else None
            # 形如 'MM-DD' 的日期
            if '-' in text and len(text) <= 6:
                today = datetime.date.today()
                m, d = text.split('-')
                target = datetime.date(today.year, int(m), int(d))
                delta = (today - target).days
                return float(max(0, delta))
        except Exception:
            return None
        return None
