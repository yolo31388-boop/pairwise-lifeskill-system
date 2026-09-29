"""生活技能系统 - 七个熟练度 bug 修复版

修复点:
1. 资源刷新按玩家实例(相位)独立, 不同玩家互不抢矿, 刷新时间带随机抖动。
2. 制造/采集失败也获得部分熟练度(成功的 30%)。
3. 鱼群分布随游戏内时间与天气动态变化。
4. 工具耐久消耗按资源等级与工具等级计算。
5. 配方解锁需要 等级 + 前置任务 + 成就 + 前置配方 条件链。
6. 各生活技能拥有独立经验曲线。
7. 资源品质受工具等级、技能等级、运气多因素影响。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# ---- 经验与熟练度常量 ----
FAILURE_EXP_RATIO = 0.3        # 失败时获得成功熟练度的 30%
CRAFT_EXP = 20                 # 成功制造一次的熟练度
GATHER_EXP_PER_TIER = 10       # 成功采集熟练度 = 资源等级 * 该系数

# ---- 技能 -> 所需工具 ----
SKILL_TOOLS = {
    "mining": "pickaxe",
    "logging": "axe",
    "fishing": "fishing_rod",
    "herbalism": "sickle",
}

# ---- 各技能独立经验曲线: 升到某级所需经验 = base * multiplier ** (level-1) ----
EXP_CURVES = {
    "mining":  {"base": 100, "multiplier": 1.5},
    "fishing": {"base": 60,  "multiplier": 1.8},
    "cooking": {"base": 80,  "multiplier": 1.3},
}

# ---- 鱼群分布: (天气, 时段) -> 鱼种权重 ----
FISH_TABLE = {
    ("sunny", "day"):   {"carp": 40, "sunfish": 35, "bass": 20, "goldfish": 5},
    ("sunny", "night"): {"catfish": 40, "eel": 35, "nightcrawler": 20, "moonfish": 5},
    ("rainy", "day"):   {"catfish": 35, "eel": 30, "trout": 25, "rainbow_trout": 10},
    ("rainy", "night"): {"eel": 40, "deep_catfish": 30, "anglerfish": 20, "stormfish": 10},
    ("snowy", "day"):   {"icefish": 40, "snow_cod": 35, "frost_trout": 20, "glacierfish": 5},
    ("snowy", "night"): {"icefish": 35, "frost_eel": 30, "glacierfish": 20, "aurora_fish": 15},
}


@dataclass
class ResourceNode:
    nid: str
    rtype: str
    tier: int
    respawn_time: float
    available: bool = True


@dataclass
class Recipe:
    rid: str
    skill: str
    level_req: int = 1
    quest_req: str | None = None
    achievement_req: str | None = None
    prereq_recipes: tuple = ()
    crafted: bool = False


@dataclass
class _PlayerNodeState:
    """单个玩家对单个资源点的相位状态。"""
    available: bool = True
    depleted_at: float | None = None
    respawn_at: float | None = None


class LifeSkillSystem:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.nodes: list[ResourceNode] = []
        self.recipes: dict[str, Recipe] = {}
        self.skills = {"mining": 1, "fishing": 1, "cooking": 1}
        self.exp = {"mining": 0, "fishing": 0, "cooking": 0}
        self.tools = {"pickaxe": {"tier": 1, "durability": 100}}
        self.weather = "sunny"
        self.time_of_day = "day"
        self.clock = 0.0
        self.completed_quests: set[str] = set()
        self.achievements: set[str] = set()
        # fix1: player_id -> nid -> 相位状态, 资源对每个玩家独立刷新
        self._node_states: dict[str, dict[str, _PlayerNodeState]] = {}

    # ------------------------------------------------------------------
    # fix1: 按玩家实例(相位)的资源刷新
    # ------------------------------------------------------------------
    def _get_node(self, node_id) -> ResourceNode:
        return next(n for n in self.nodes if n.nid == node_id)

    def _state(self, player_id, nid) -> _PlayerNodeState:
        per_player = self._node_states.setdefault(player_id, {})
        state = per_player.get(nid)
        if state is None:
            state = _PlayerNodeState()
            per_player[nid] = state
        return state

    def is_available(self, node_id, player_id) -> bool:
        node = self._get_node(node_id)
        state = self._state(player_id, node.nid)
        if state.available:
            return True
        if state.respawn_at is not None and self.clock >= state.respawn_at:
            state.available = True
            state.depleted_at = None
            state.respawn_at = None
        return state.available

    def next_respawn(self, node_id, player_id):
        """该玩家视角下资源点下次可用的绝对时刻; 当前可用则返回 None。"""
        state = self._state(player_id, node_id)
        if state.available:
            return None
        return state.respawn_at

    def advance_time(self, seconds):
        """推进游戏内时间(便于玩家等待刷新)。"""
        self.clock += seconds

    # ------------------------------------------------------------------
    # fix2/fix4/fix7: 采集(失败熟练度 / 耐久 / 品质)
    # ------------------------------------------------------------------
    def gather(self, node_id, player_id, luck=0.0):
        node = self._get_node(node_id)
        if not self.is_available(node_id, player_id):
            return None

        tool = self.tools.get(SKILL_TOOLS.get(node.rtype, "pickaxe"))
        tool_tier = tool["tier"] if tool else 1
        skill_level = self.skills.get(node.rtype, 1)

        # fix2: 成功率由技能等级与资源等级决定; luck 为本次随机掷骰值
        chance = self._gather_chance(skill_level, node.tier)
        success = luck < chance

        # fix4: 耐久消耗随资源等级升高、随工具等级降低(最低 1 点)
        cost = self.durability_cost(node.tier, tool_tier)
        if tool is not None:
            tool["durability"] = max(0, tool["durability"] - cost)

        base_exp = node.tier * GATHER_EXP_PER_TIER
        gained = base_exp if success else int(base_exp * FAILURE_EXP_RATIO)
        self._gain_exp(node.rtype, gained)

        if not success:
            # 失败不消耗资源点, 之后还可再试
            return {
                "type": node.rtype,
                "tier": node.tier,
                "success": False,
                "quality": "broken",
                "exp": gained,
            }

        # 成功采集: 仅让该玩家视角的节点进入冷却
        state = self._state(player_id, node.nid)
        state.available = False
        state.depleted_at = self.clock
        # 不同玩家在不同时刻采集, 且刷新时长带 ±20% 随机抖动, 刷新时刻互不相同
        jitter = self.rng.uniform(0.8, 1.2)
        state.respawn_at = self.clock + node.respawn_time * jitter

        # fix7: 品质 = 工具等级 + 技能等级 + 运气 多因素
        quality_score = (
            tool_tier * 12
            + skill_level * 5
            + int(luck * 30)
        )
        if quality_score >= 90:
            quality = "legendary"
        elif quality_score >= 60:
            quality = "epic"
        elif quality_score >= 40:
            quality = "rare"
        else:
            quality = "common"

        return {
            "type": node.rtype,
            "tier": node.tier,
            "success": True,
            "quality": quality,
            "exp": gained,
        }

    @staticmethod
    def _gather_chance(skill_level, node_tier) -> float:
        return max(0.0, min(0.95, 0.5 + 0.1 * (skill_level - node_tier)))

    @staticmethod
    def durability_cost(node_tier, tool_tier) -> int:
        return max(1, int(round(node_tier * 2.0 / tool_tier)))

    # ------------------------------------------------------------------
    # fix3: 鱼群随时间与天气动态变化
    # ------------------------------------------------------------------
    def fish(self, location=None):
        table = FISH_TABLE.get((self.weather, self.time_of_day))
        if table is None:
            table = FISH_TABLE[("sunny", "day")]
        species = tuple(table.keys())
        weights = tuple(table.values())
        name = self.rng.choices(species, weights=weights, k=1)[0]
        weight = round(self.rng.uniform(0.3, 8.0), 2)
        return {"fish": name, "weight": weight, "location": location}

    # ------------------------------------------------------------------
    # fix5: 配方前置条件链(等级 + 任务 + 成就 + 前置配方)
    # ------------------------------------------------------------------
    def register_recipe(self, recipe: Recipe):
        self.recipes[recipe.rid] = recipe

    def can_craft(self, recipe_id) -> bool:
        recipe = self.recipes[recipe_id]
        if self.skills.get(recipe.skill, 1) < recipe.level_req:
            return False
        if recipe.quest_req and recipe.quest_req not in self.completed_quests:
            return False
        if recipe.achievement_req and recipe.achievement_req not in self.achievements:
            return False
        for prereq in recipe.prereq_recipes:
            prereq_recipe = self.recipes.get(prereq)
            if prereq_recipe is None or not prereq_recipe.crafted:
                return False
        return True

    def craft(self, recipe_id) -> bool:
        recipe = self.recipes[recipe_id]
        if not self.can_craft(recipe_id):
            # fix2: 制造失败也获得部分熟练度
            self._gain_exp(recipe.skill, int(CRAFT_EXP * FAILURE_EXP_RATIO))
            return False
        self._gain_exp(recipe.skill, CRAFT_EXP)
        recipe.crafted = True
        return True

    # ------------------------------------------------------------------
    # fix6: 各技能独立经验曲线
    # ------------------------------------------------------------------
    def get_exp_curve(self, skill, level=1):
        curve = EXP_CURVES.get(skill, {"base": 100, "multiplier": 1.5})
        return int(curve["base"] * curve["multiplier"] ** max(0, level - 1))

    # ------------------------------------------------------------------
    def _gain_exp(self, skill, amount):
        if skill not in self.exp:
            self.exp[skill] = 0
            self.skills[skill] = self.skills.get(skill, 1)
        self.exp[skill] += amount
