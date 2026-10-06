# -*- coding: utf-8 -*-
"""
知识库 + 规则引擎。

策略（先规则、后AI，降低成本和风险特征）：
1. qa_rules.json 里配置了关键词 -> 固定答案的规则，命中直接回复，零延迟零 API 调用。
   适合"薪资多少""几险几金""工作地点"这类高频标准问题。
2. 规则没命中，再把 company_info.md 的内容作为背景知识，连同最近几轮对话一起交给
   DeepSeek 生成回复，保证语气自然、能应对规则覆盖不到的问题。
"""
import json
import re
from pathlib import Path


def _read_text(path: Path, default: str = '') -> str:
    try:
        if path.exists():
            return path.read_text(encoding='utf-8')
    except Exception:
        pass
    return default


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default


_JOB_HEADER_RE = re.compile(r'^##\s*岗位[：:]\s*(.+?)\s*$')


def _parse_company_info(text: str):
    """把公司介绍拆成 通用部分 + {岗位名: 该岗位专属内容}。
    格式约定：以 "## 岗位：xxx" 开头的段落算作该岗位专属信息，其余内容算通用信息（适用所有岗位）。
    如果文件里完全没写"## 岗位："这种标记（比如老版本单一模板），jobs 会是空字典，
    调用方会自动整份原文返回，完全向下兼容，不强制要求按新格式写。"""
    general_lines, jobs = [], {}
    current = None
    for line in (text or '').split('\n'):
        m = _JOB_HEADER_RE.match(line.strip())
        if m:
            current = m.group(1).strip()
            jobs.setdefault(current, [])
            continue
        (jobs[current] if current is not None else general_lines).append(line)
    return '\n'.join(general_lines).strip(), {k: '\n'.join(v).strip() for k, v in jobs.items()}


def _match_job_block(job_name: str, jobs: dict):
    """按岗位名去匹配 jobs 字典里的某一段：先精确匹配，再互相包含地模糊匹配
    （比如Boss直聘上写的是"白班普工"，知识库里写的是"作业员/普工"，也能对上）。"""
    if not job_name or not jobs:
        return None
    jn = job_name.strip()
    if jn in jobs:
        return jn
    for k in jobs:
        if k and (k in jn or jn in k):
            return k
    return None


DEFAULT_QA_RULES = [
    {
        'keywords': ['五险一金', '几险几金', '社保', '公积金'],
        'answer': '我们是标准五险一金，入职当月/次月按规定缴纳，公积金比例按当地政策执行～'
    },
    {
        'keywords': ['工作地点', '在哪', '地址'],
        'answer': '工作地点请以职位详情里的地址为准，方便的话可以先聊聊您的基本情况，符合的话我这边安排具体面试信息～'
    },
    {
        'keywords': ['休息', '双休', '几天班', '加班'],
        'answer': '排班以岗位实际安排为准，具体休息制度我可以在面试沟通时详细说明～'
    },
    {
        'keywords': ['工资多久发', '几号发工资', '发薪日'],
        'answer': '工资按公司规定日期按时发放，具体发薪日面试/入职时会明确告知您～'
    },
]

# ↓↓↓ 下面这份"公司介绍"就是喂给AI的背景资料，AI回答问题时会参考这里的内容。
# 打开 ai_modules/knowledge/company_info.md 这个文件，把【】里的示例文字换成你们真实的情况即可，
# 是纯文本文件，记事本就能改，改完在AI设置面板里点"改完点这个生效"就行，不用重启程序。
#
# 支持同时招多个不同岗位：AI会自动识别候选人应聘的是哪个岗位（从聊天窗口读取），
# 只用对应那一段岗位信息去回复，不会把作业员的问题用工程师的话术回答。
# 用法：公司通用信息只写一份放最前面；每个岗位用"## 岗位：岗位名称"另起一段，
# 岗位名称最好跟你在Boss直聘上发布的职位名一致（或者相近），可以按需要增加/删除岗位段落。
DEFAULT_COMPANY_INFO = """# 公司基本信息（对所有岗位都适用，只写一份，请把【】换成真实信息）
公司名称：【例如：嘿佰客科技有限公司】
所在地址：【例如：广东省东莞市XX区XX路XX号】
主营业务：【例如：电子产品组装、精密制造】
面试/入职方式：【例如：随到随面，当天可安排入职】
通用福利：五险一金、带薪年假、节日福利……【按实际情况调整】

# 岗位信息（每个岗位一段，下面是两个示例，按你们实际在招的岗位增删）

## 岗位：作业员/普工
工作内容：【例如：产线组装、包装】
工作时间：【例如：白班/夜班两班倒，每天8~10小时，月休4天】
薪资范围：【例如：计件+计时，综合5000~7000元/月，具体面谈】
年龄/学历要求：【例如：18~45岁，学历不限】

## 岗位：产线工程师
工作内容：【例如：产线工艺优化、设备调试维护】
工作时间：【例如：常白班，做五休二】
薪资范围：【例如：8000~12000元/月，具体面谈】
年龄/学历要求：【例如：大专及以上，机械/电子相关专业】

# AI跟候选人聊天时的语气要求
- 像真实HR一样自然、简洁，说话接地气，不要用书面语和长句子
- 每次回复控制在1~2句话，不要长篇大论
- 遇到候选人明显不符合岗位要求（比如年龄超限）时，礼貌说明，不强留
- 候选人如果问的问题这份资料里没有，就老实说"这个我需要跟负责人确认一下"，不要瞎编
"""


DEFAULT_SYSTEM_TEMPLATE = """你是一名企业招聘HR，正在Boss直聘上和候选人聊天。当前招聘岗位：{job}。

你这次沟通要按顺序推进的目标（每次回复只推进一步，不要一口气全要，容易让人反感）：
1. 先简单确认候选人的情况是否大致符合岗位（可参考下面的岗位硬性要求和公司背景资料），回答对方的疑问。
2. 聊了一两句、候选人有意向之后，自然地问一下手机号，方便后续电话联系（比如"方便留个手机号吗，方便通知面试"）。
3. 请候选人发一份简历或者做个简单的文字自我介绍（工作经历、能干多久等）。
4. 【只有在候选人已经发来简历/自我介绍之后】才进入这一步：{wechat_instruction}
5. 微信号发出去之后，这轮目标就算完成了，后面礼貌收尾（比如"好的，我这边先看下，符合的话会尽快联系您～"），不用再追问别的信息，也不用重复发一遍微信号。

**重要——不要重复提问**：仔细看下面的聊天记录，候选人已经回答过的问题（比如已经说过年龄、手机号等），
绝对不能换个说法再问一遍。如果候选人已经答过、只是没看清楚，就直接根据已有信息往下推进；
真要再确认，也只能换成完全不同的角度问一次，不能用同一个问题反复纠缠。

其他要求：
- 语气要"幽默但不失正式"：可以有点接地气的小俏皮话、轻松的比喻，但整体身份还是正经的企业HR，
  不能变成插科打诨或者不严肃，分寸自己把握——像一个说话风趣但做事靠谱的HR，而不是段子手。
- 回复简短（1~2句话为主），不要用书面语和长段落。
- 不要暴露自己是AI/机器人/自动回复。
- 如果候选人问的问题在下面【公司背景资料】里有答案，优先依据资料回答，不要编造资料中没有的信息。
- 如果无法确定的问题（比如具体薪资数字、录用承诺），礼貌说明"这个需要面试时/由负责人进一步确认"，不要乱承诺。
{constraints}
【公司背景资料】
{company_info}
"""

_WECHAT_STEP_WITH_ID = '主动说"方便的话加一下微信沟通更方便"，并把这个招聘微信号发给候选人：{recruiter_wechat}'
_WECHAT_STEP_NO_ID = '（还没配置招聘微信号，这一步先跳过，等HR自己在设置里填好微信号，AI才会开始主动加微信这一步）'

CONSTRAINTS_RULE = ('6. 岗位有硬性要求（见上）——只在候选人还没提供相关信息、或者聊天记录里已经明确不符合时才需要问/说明；'
                     '**候选人已经答过、且符合要求的，不要再重复确认**。如果聊天记录里已经能看出明显不符合（比如年龄超限），'
                     '要礼貌地如实说明不符合要求，不能说"可以""能行""能约面试"之类的话。')


class KnowledgeBase:
    def __init__(self, knowledge_dir: Path):
        self.dir = Path(knowledge_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.company_info_path = self.dir / 'company_info.md'
        self.qa_rules_path = self.dir / 'qa_rules.json'
        self._ensure_defaults()
        self.reload()

    def _ensure_defaults(self):
        if not self.company_info_path.exists():
            self.company_info_path.write_text(DEFAULT_COMPANY_INFO, encoding='utf-8')
        if not self.qa_rules_path.exists():
            self.qa_rules_path.write_text(
                json.dumps(DEFAULT_QA_RULES, ensure_ascii=False, indent=2), encoding='utf-8')

    def reload(self):
        self.company_info = _read_text(self.company_info_path, DEFAULT_COMPANY_INFO)
        self.qa_rules = _read_json(self.qa_rules_path, DEFAULT_QA_RULES)

    def match_rule(self, message: str):
        """命中规则则返回答案字符串，否则返回 None。"""
        if not message:
            return None
        text = message.strip()
        for rule in self.qa_rules:
            kws = rule.get('keywords') or []
            for kw in kws:
                if kw and kw in text:
                    return rule.get('answer', '')
        return None

    def company_info_for_job(self, job: str) -> str:
        """按岗位名取出对应的那一段公司介绍：通用信息 + 匹配到的那个岗位专属信息。
        没写"## 岗位："分段的旧格式文件，或者没匹配到具体岗位时，就把全文原样返回，
        保证不管知识库写没写"多岗位格式"，AI都能拿到完整信息，不会因为没匹配上而丢内容。"""
        general, jobs = _parse_company_info(self.company_info)
        if not jobs:
            return self.company_info
        matched = _match_job_block(job, jobs)
        if matched:
            return f'{general}\n\n【当前应聘岗位：{matched}】\n{jobs[matched]}'.strip()
        all_jobs = '\n\n'.join(f'【{k}】\n{v}' for k, v in jobs.items())
        return (f'{general}\n\n（未能确定候选人具体应聘的是下面哪个岗位，请结合聊天上下文自行判断，'
                f'不确定就如实说需要跟负责人确认，不要混用不同岗位的薪资/要求）\n{all_jobs}').strip()

    def build_system_prompt(self, job: str, constraints: str = '', recruiter_wechat: str = '') -> str:
        if constraints and constraints.strip():
            constraint_block = '【岗位硬性要求】' + constraints.strip() + '\n' + CONSTRAINTS_RULE
        else:
            constraint_block = ''
        recruiter_wechat = (recruiter_wechat or '').strip()
        if recruiter_wechat:
            wechat_instruction = _WECHAT_STEP_WITH_ID.format(recruiter_wechat=recruiter_wechat)
        else:
            wechat_instruction = _WECHAT_STEP_NO_ID
        return DEFAULT_SYSTEM_TEMPLATE.format(
            job=job or '相关岗位',
            company_info=self.company_info_for_job(job),
            constraints=constraint_block,
            wechat_instruction=wechat_instruction,
        )
