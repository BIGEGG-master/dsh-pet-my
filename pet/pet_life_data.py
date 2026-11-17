# -*- coding: utf-8 -*-
"""养成系统（Pet Life）的静态数据表：衰减速率、工作、商店、动作、动画关键词池。

**为什么数据与逻辑分开**（``pet_life.py`` 只有算法）：
数值平衡是会被反复调的东西，把它集中在一张表里，改平衡不用碰任何分支代码；
单测也能直接对着表断言（"研究相对论的精力消耗必须比基础打字高"这类契约）。

**动画为什么不写文件名**：角色素材随包变化（本机 106 段 webm，含 6 段
``工作状态-*``、15 段 ``吃*``），写死 ``"吃午餐"`` 一旦素材改名就静默失效。
这里只声明**关键词池**，运行时用 ``pet_life.pick_clip`` 在素材库的 acts 里做
子串匹配；匹配不到就不播（日志 debug），数值照常结算——素材缺一段不能拖垮功能。
这是 ``pet/sprite_feeding._pick_eating_animation`` 已在用的同一口径。
"""
from __future__ import annotations

#: 属性键（顺序即 HUD 显示顺序）
STATUS_KEYS: tuple[str, ...] = ("hunger", "thirst", "mood", "energy", "health")

#: 属性中文名（HUD / 面板 / 气泡共用）
STATUS_LABELS: dict[str, str] = {
    "hunger": "饥饿",
    "thirst": "口渴",
    "mood": "心情",
    "energy": "精力",
    "health": "健康",
}

#: 清醒时每小时的衰减（正数 = 往下掉）。mood 不自然衰减：只由事件驱动，
#: 否则"放着不管"会稳定把心情拖死，玩家永远追不上。
DECAY_PER_HOUR: dict[str, float] = {
    "hunger": 6.0,
    "thirst": 8.0,
    "energy": 5.0,
}

#: 睡觉时每小时的变化（energy 为正 = 恢复）
SLEEP_PER_HOUR: dict[str, float] = {
    "energy": 20.0,
    "hunger": -3.0,
    "thirst": -4.0,
}

#: 饥饿或口渴见底时，健康每小时的额外损失（两条同时见底则叠加）
STARVING_HEALTH_PER_HOUR: float = 2.0

#: 单次 tick 最多结算多少小时：程序关了一周再开，不该瞬间把她的血扣光。
#: 超出部分直接丢弃（离线的"那段时间"就当没发生过）。
MAX_TICK_HOURS: float = 2.0


# ---------------------------------------------------------------- 工作
#: 工作：每次固定 10 分钟。``effects`` 是**完成时**一次性结算的增量。
JOBS: dict[str, dict] = {
    "typing": {
        "name": "基础打字",
        "desc": "老老实实敲键盘，慢但不伤身。",
        "coins": 8,
        "duration_minutes": 10,
        "effects": {"energy": -8, "mood": -2},
    },
    "coding": {
        "name": "AI 编程助手",
        "desc": "帮哥哥写代码，脑子转得快，肚子也饿得快。",
        "coins": 20,
        "duration_minutes": 10,
        "effects": {"energy": -15, "hunger": -6},
    },
    "research": {
        "name": "研究狭义相对论",
        "desc": "想通了一点点，头发少了一点点。",
        "coins": 45,
        "duration_minutes": 10,
        "effects": {"energy": -25, "health": -3, "mood": -4},
    },
    "livestream": {
        "name": "直播大肥鲸表演",
        "desc": "观众很多，掌声很响，但她社恐。",
        "coins": 30,
        "duration_minutes": 10,
        "effects": {"mood": -12, "energy": -18},
    },
}

#: 工作完成后她说的话（随机取一条；``{coins}`` 会被替换成实际收入）
JOB_DONE_LINES: dict[str, tuple[str, ...]] = {
    "typing": ("敲完了嘟，手指有点酸。", "打完啦，{coins} 个嘟嘟币收好。"),
    "coding": ("代码跑通了嘟！{coins} 币到账～", "这个 bug 我抓住了，{coins} 币。"),
    "research": ("时间真的会变慢诶…脑袋要炸了嘟。", "相对论好难，不过 {coins} 币是真的。"),
    "livestream": ("好多人看我…下次不播了嘟。", "下播了，赚了 {coins} 币，好累。"),
}

#: 工作被中断（关闭养成 / 用户取消）时说的话——不结算收益
JOB_CANCELLED_LINE = "不做了嘟，白忙一场…"


# ---------------------------------------------------------------- 商店
#: 商店物品。``effects`` 是购买后立即生效的增量；``price`` 单位是嘟嘟币。
SHOP_ITEMS: dict[str, dict] = {
    "sparkling_water": {
        "name": "深海气泡水",
        "desc": "喝下去会打个带泡泡的嗝。",
        "price": 10,
        "effects": {"thirst": 50, "energy": 8},
        "quip": "咕嘟咕嘟…好凉嘟。（口渴 +50）",
    },
    "algae_smoothie": {
        "name": "深海蓝藻奶昔",
        "desc": "热量很高，喝完会圆一点。",
        "price": 25,
        "effects": {"hunger": 45, "mood": 8},
        "quip": "蓝藻味的…还行嘟。（饥饿 +45）",
    },
    "tail_massager": {
        "name": "鲸鱼尾巴按摩器",
        "desc": "嗡嗡嗡，尾巴会自己抖。",
        "price": 60,
        "effects": {"health": 30, "mood": 5},
        "quip": "呜…舒服到想睡嘟。（健康 +30）",
    },
    "quantum_snack": {
        "name": "量子纠缠零食",
        "desc": "吃下去的状态在被观测前不确定。",
        "price": 40,
        "effects": {"hunger": 30},
        # 概率触发的额外效果：25% 概率额外 +20 精力（"瞬间清醒"）
        "gamble": {"chance": 0.25, "effects": {"energy": 20}},
        "quip": "这个零食…好像同时在饱和不饱之间嘟。（饥饿 +30）",
    },
}

#: 观察者效应触发时的额外台词（量子零食）
GAMBLE_HIT_LINE = "观测结果：嘟嘟突然清醒了！"
GAMBLE_MISS_LINE = "观测结果：还是很困。"
#: 钱不够时的台词
NOT_ENOUGH_COINS_LINE = "嘟嘟币不够嘟…要先去工作赚钱。"


# ---------------------------------------------------------------- 即时动作
#: 白嫖动作的冷却（分钟）。没有冷却就是无限刷属性，养成系统立刻失去意义。
FEED_COOLDOWN_MINUTES: float = 30.0
DRINK_COOLDOWN_MINUTES: float = 20.0

#: 喂食：免费的基础补给（商店是花钱的强化版）
FEED_EFFECTS: dict[str, int] = {"hunger": 25, "mood": 3}
FEED_LINE = "谢谢哥哥～（饥饿 +25）"
FEED_COOLDOWN_LINE = "刚吃过嘟，现在还不饿。"

#: 喝水
DRINK_EFFECTS: dict[str, int] = {"thirst": 30}
DRINK_LINE = "咕嘟…（口渴 +30）"
DRINK_COOLDOWN_LINE = "刚喝过嘟，待会儿再喝。"

#: 玩耍：三种玩法，各自消耗与收益不同
PLAY_ACTS: dict[str, dict] = {
    "adventure": {
        "name": "深海大冒险",
        "desc": "游来游去，心情大好，但很耗精神。",
        "effects": {"mood": 30, "energy": -10},
        "quip": "游到好深的地方了嘟！（心情 +30）",
    },
    "training": {
        "name": "练习肥鲸拍地",
        "desc": "强身健体，费点精神。",
        "effects": {"health": 20, "energy": -5},
        "quip": "啪！啪！（健康 +20）",
    },
    "chase": {
        "name": "追逐光点",
        "desc": "追得停不下来，追上就忘了。",
        "effects": {"mood": 15, "energy": -20},
        "quip": "抓到了…诶又没了嘟。（心情 +15）",
    },
}


# ---------------------------------------------------------------- 动画关键词池
#: 每类行为的关键词池（按顺序尝试，命中素材库 acts 里任意一项就用它）。
#: 全部匹配失败 = 不播动画（静默），绝不回退到随机动作——那会让人以为功能错乱。
CLIP_POOLS: dict[str, tuple[str, ...]] = {
    "feed": ("吃午餐", "吃零食", "大口吃零食", "吃早餐", "吃晚餐", "吃"),
    "drink": ("吐泡泡", "气泡", "喝", "摇扇"),
    "play": ("可爱宅舞", "荡秋千", "骑木马", "三球抛接", "扑克魔术"),
    "work": ("工作状态",),
    # sleep：睡觉姿态。`睡觉-主` 是用户自制的主姿态（放在 videos/sleep/ 专用目录，
    # 不进随机池）；后面几个是包里原有的打盹段，缺新素材时兜底。
    "sleep": ("睡觉-主", "睡觉", "躺平睡", "原地小憩沉眠", "打瞌睡", "哈欠连天", "睡"),
    # 入睡 / 醒来过渡（v4.7.4）：从"躺→坐起"素材倒放/正放裁出的 3.2 秒单向段。
    # 它们是**一次性**动画：播完由 hold 闸门接常驻躺姿（入睡）或正常掷骰回待机（醒来）。
    "sleep_in": ("入睡过渡",),
    "sleep_out": ("醒来过渡",),
    "wake": ("超大伸懒腰", "伸懒腰"),
    "lonely": ("碎碎念", "发呆"),
}


# ---------------------------------------------------------------- 自主事件
#: 阈值：低于此值才可能触发对应的自主行为
NEED_THRESHOLDS: dict[str, float] = {
    "hunger": 20.0,
    "thirst": 20.0,
    "energy": 15.0,
    "mood": 20.0,
}

#: 同类自主事件的最小间隔（分钟）：防止刷屏。三个属性同时见底也最多各说一次。
EVENT_COOLDOWN_MINUTES: float = 30.0

#: 自主事件的台词（随机取一条）
NEED_LINES: dict[str, tuple[str, ...]] = {
    "hunger": ("哥哥…嘟嘟肚子在叫了嘟。", "有点饿了，想吃蓝藻奶昔…"),
    "thirst": ("好渴嘟，想喝水…", "嘴巴干干的，喝点什么嘛。"),
    "energy": ("好困…嘟嘟先眯一会儿可以吗？", "眼睛睁不开了嘟…"),
    "mood": ("有点闷…哥哥陪我说说话嘛。", "嘟嘟今天有点不开心嘟。"),
}

#: 精力低于此值自动进入睡眠
SLEEP_THRESHOLD: float = 15.0
#: 睡到精力回到此值自动醒（滞回，避免在阈值上反复横跳）
WAKE_THRESHOLD: float = 70.0
SLEEP_LINE = "那…嘟嘟睡了嘟。（Zzz）"
WAKE_LINE = "睡饱了嘟！伸个懒腰～"

#: 病倒（health == 0）时的交互拒绝台词
SICK_LINE = "嘟嘟病倒了嘟…先喂点吃的喝的，好吗？"


# ---------------------------------------------------------------- 睡觉（生活动作）
#: 主动小睡：点一下「去睡觉」，睡这么久，醒来一次性恢复这么多精力。
#:
#: 为什么不做成"睡到精力满"：那等于一个免费的满血按钮，精力就不再是资源了。
#: 固定时长 + 固定收益，和「工作 10 分钟赚 N 币」对称——她能靠睡回血，但每一次
#: 回血都有明确代价（半小时不能干活、也不能陪你玩）。
NAP_MINUTES: float = 30.0
NAP_ENERGY: float = 40.0

#: 提前叫醒按**实际睡的比例**结算（睡 1 分钟就想拿满 40？不给）。
NAP_START_LINE = "那嘟嘟去眯一会儿嘟…（{minutes} 分钟后精神 +{energy}）"
NAP_DONE_LINE = "睡饱了嘟！精神 +{energy}"
NAP_INTERRUPT_LINE = "唔…还想睡嘟（精神 +{energy}）"
NAP_ALREADY_LINE = "已经在睡了嘟…别吵。"
NAP_WORKING_LINE = "先把活干完再睡嘟。"
NAP_SICK_LINE = "都病倒了，先吃点东西再睡嘟…"


# ---------------------------------------------------------------- 经验与等级
#: 工作完成时给的经验。**故意比收入涨得慢**（45 币的活不给 45 经验）：
#: 否则"挑最赚钱的活"就等于"刷等级"，等级会变成收入的影子而不是成长的尺子。
JOB_XP: dict[str, int] = {
    "typing": 6,
    "coding": 12,
    "livestream": 14,
    "research": 20,
}

#: 玩耍给的经验明显少于工作（同一个动作里"玩"不该比"干活"更划算）。
PLAY_XP: dict[str, int] = {
    "adventure": 3,
    "training": 3,
    "chase": 2,
}

#: 各级所需的**累计**经验：索引 0 = Lv1（起点 0）。
#: 曲线前松后紧：前两级一两轮工作就能到，10 级要长期养。
LEVEL_THRESHOLDS: tuple[int, ...] = (0, 40, 100, 180, 280, 400, 540, 700, 880, 1080)

#: 技能表：等级达到即自动解锁（无需手动点）。``key`` 也是存档里的技能 id。
SKILLS: dict[str, dict] = {
    "self_work": {
        "name": "自己打工",
        "level": 3,
        "desc": "没钱的时候会自己去找活干，不用哥哥催。",
    },
    "self_shop": {
        "name": "自己买东西",
        "level": 5,
        "desc": "缺什么会自己去杂货铺买（会花嘟嘟币）。",
    },
}

#: 升级 / 学会技能时的台词（只在真的发生时播一次）
LEVEL_UP_LINE = "诶…嘟嘟好像变厉害了一点点嘟！（Lv{level}）"
SKILL_UNLOCK_LINES: dict[str, str] = {
    "self_work": "嘟嘟学会自己打工了嘟！没钱就自己去接活～",
    "self_shop": "嘟嘟学会自己买东西了嘟！缺什么自己去杂货铺～",
}

#: 自主行为（技能解锁后由服务在心跳里判定，用户可一键关掉 ``autonomy``）
#: 自己打工：钱低于此值才动，精力够才动，两次之间至少隔这么久
AUTO_WORK_COINS: float = 20.0
AUTO_WORK_MIN_ENERGY: float = 25.0
#: 挑活时留的精力余量：耗完这份活还剩这么多才算"做得动"
AUTO_WORK_ENERGY_RESERVE: float = 5.0
AUTO_WORK_COOLDOWN_MINUTES: float = 10.0
#: 自己买东西：这些属性低于阈值就自己去补；两次之间至少隔这么久
AUTO_BUY_THRESHOLDS: dict[str, float] = {
    "health": 40.0,
    "thirst": 25.0,
    "hunger": 25.0,
}
AUTO_BUY_COOLDOWN_MINUTES: float = 20.0

#: 自主行为的台词（``{item}`` 会被替换成商品名）
AUTO_WORK_LINE = "缺钱嘟…嘟嘟自己去打份工。"
AUTO_BUY_LINE = "缺东西了嘟，嘟嘟自己去买{item}。"