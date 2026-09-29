"""生活技能系统"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


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
    level_req: int
    quest_req: str | None = None
    achievement_req: str | None = None
    prereq_recipes: tuple[str, ...] = ()


# fix6: 各技能独立经验曲线 skill -> (base, exponent)
EXP_CURVES = {
    "mining": (100, 1.5),
    "fishing": (80, 1.8),
    "cooking": (120, 1.3),
}

# fix3: 鱼群分布随天气与昼夜变化: weather -> time_of_day -> [(fish, weight)]
FISH_TABLE = {
    "sunny": {
        "day": [("carp", 0.5), ("bass", 0.3), ("common", 0.2)],
        "night": [("catfish", 0.5), ("common", 0.5)],
    },
    "rainy": {
        "day": [("salmon", 0.4), ("trout", 0.4), ("common", 0.2)],
        "night": [("eel", 0.6), ("catfish", 0.4)],
    },
}

FISH_WEIGHTS = {
    "common": 1.0, "carp": 1.5, "bass": 2.0, "catfish": 2.5,
    "salmon": 3.0, "trout": 2.5, "eel": 3.5,
}

QUALITY_LADDER = ["poor", "common", "fine", "rare", "epic"]

FAILURE_EXP_RATIO = 0.3  # fix2: 失败获得成功经验的 30%
CRAFT_EXP = 25


class LifeSkillSystem:
    def __init__(self, seed=None):
        self.nodes: list[ResourceNode] = []
        self.skills = {"mining": 1, "fishing": 1, "cooking": 1}
        self.exp = {"mining": 0, "fishing": 0, "cooking": 0}
        self.tools = {"pickaxe": {"tier": 1, "durability": 100}}
        self.weather = "sunny"
        self.time_of_day = "day"
        self.hour = 8.0
        self.recipes: dict[str, Recipe] = {}
        self.completed_quests: set[str] = set()
        self.achievements: set[str] = set()
        self.crafted: set[str] = set()
        self._clock = 0.0
        self._respawn_at: dict[tuple[str, str], float] = {}  # fix1: (player, node) -> 刷新时刻
        self._rng = random.Random(seed)

    # ---------- 时间 / 天气 (fix3) ----------
    def advance_time(self, hours):
        self._clock += hours * 3600
        self.hour = (self.hour + hours) % 24
        self.time_of_day = "day" if 6 <= self.hour < 18 else "night"
        if self._rng.random() < 0.3:
            self.weather = "rainy" if self.weather == "sunny" else "sunny"

    # ---------- 采集 ----------
    def is_available(self, node_id, player_id):
        """fix1: 刷新按玩家相位计算，每个玩家看到独立的可用状态。"""
        ready = self._respawn_at.get((player_id, node_id))
        return ready is None or ready <= self._clock

    def next_respawn(self, node_id, player_id):
        return self._respawn_at.get((player_id, node_id))

    def _schedule_respawn(self, node, player_id):
        # fix1: 同一节点对不同玩家生成不同的刷新时间
        jitter = self._rng.uniform(0.5, 1.5)
        self._respawn_at[(player_id, node.nid)] = self._clock + node.respawn_time * jitter

    @staticmethod
    def durability_cost(node, tool):
        """fix4: 耐久消耗 = f(资源等级, 工具等级)。"""
        return max(1, node.tier * 2 - tool["tier"])

    def _gather_success(self, node, luck):
        chance = min(1.0, max(0.05, 0.5 + 0.1 * (self.skills.get(node.rtype, 1) - node.tier)))
        return luck < chance

    def _roll_quality(self, node, tool, luck):
        """fix7: 品质由工具等级、技能等级、运气共同决定。"""
        skill = self.skills.get(node.rtype, 1)
        score = tool["tier"] * 2 + skill + luck * 5
        idx = min(int(score // 4), len(QUALITY_LADDER) - 1)
        return QUALITY_LADDER[idx]

    def gather(self, node_id, player_id, luck=None):
        node = next(n for n in self.nodes if n.nid == node_id)
        if not self.is_available(node_id, player_id):
            return None
        tool = self.tools["pickaxe"]
        if tool["durability"] <= 0:
            return None
        if luck is None:
            luck = self._rng.random()
        tool["durability"] -= self.durability_cost(node, tool)  # fix4
        base_exp = 10 * node.tier
        if not self._gather_success(node, luck):
            # fix2: 失败也给 30% 熟练度，节点不消耗
            self._add_exp(node.rtype, base_exp * FAILURE_EXP_RATIO)
            return {"success": False, "type": node.rtype, "tier": node.tier, "quality": None}
        self._add_exp(node.rtype, base_exp)
        quality = self._roll_quality(node, tool, luck)  # fix7
        self._schedule_respawn(node, player_id)  # fix1
        return {"success": True, "type": node.rtype, "tier": node.tier, "quality": quality}

    # ---------- 钓鱼 (fix3) ----------
    def fish(self, location, weather=None, time_of_day=None):
        weather = weather or self.weather
        tod = time_of_day or self.time_of_day
        table = FISH_TABLE.get(weather, FISH_TABLE["sunny"])
        entries = table.get(tod, table["day"])
        names = [name for name, _ in entries]
        weights = [w for _, w in entries]
        name = self._rng.choices(names, weights=weights, k=1)[0]
        weight = FISH_WEIGHTS.get(name, 1.0) * self._rng.uniform(0.5, 1.5)
        self._add_exp("fishing", 5)
        return {"fish": name, "weight": round(weight, 2)}

    # ---------- 制造 (fix5) ----------
    def register_recipe(self, recipe: Recipe):
        self.recipes[recipe.rid] = recipe

    def can_craft(self, recipe_id):
        """fix5: 解锁条件链 = 技能等级 + 前置任务 + 成就 + 前置配方。"""
        recipe = self.recipes.get(recipe_id)
        if recipe is None:
            return False
        if self.skills.get(recipe.skill, 0) < recipe.level_req:
            return False
        if recipe.quest_req and recipe.quest_req not in self.completed_quests:
            return False
        if recipe.achievement_req and recipe.achievement_req not in self.achievements:
            return False
        return all(p in self.crafted for p in recipe.prereq_recipes)

    def craft(self, recipe_id):
        recipe = self.recipes.get(recipe_id)
        if recipe is None:
            return False
        if not self.can_craft(recipe_id):
            # fix2: 制造失败也给部分熟练度
            self._add_exp(recipe.skill, CRAFT_EXP * FAILURE_EXP_RATIO)
            return False
        self.crafted.add(recipe_id)
        self._add_exp(recipe.skill, CRAFT_EXP)
        return True

    # ---------- 经验 (fix6) ----------
    def get_exp_curve(self, skill):
        """各技能独立的升级经验曲线。"""
        base, exponent = EXP_CURVES[skill]
        return int(base * self.skills[skill] ** exponent)

    def _add_exp(self, skill, amount):
        self.exp[skill] += int(amount)
        while self.exp[skill] >= self.get_exp_curve(skill):
            self.exp[skill] -= self.get_exp_curve(skill)
            self.skills[skill] += 1
