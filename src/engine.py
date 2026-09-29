"""生活技能 - 带7个bug"""
from dataclasses import dataclass, field

@dataclass
class ResourceNode:
    nid: str
    rtype: str
    tier: int
    respawn_time: float
    available: bool = True

class LifeSkillSystem:
    def __init__(self):
        self.nodes: list[ResourceNode] = []
        self.skills = {"mining": 1, "fishing": 1, "cooking": 1}
        self.exp = {"mining": 0, "fishing": 0, "cooking": 0}
        self.tools = {"pickaxe": {"tier": 1, "durability": 100}}
        self.weather = "sunny"  # bug3: 静态

    def gather(self, node_id, player_id):
        node = next(n for n in self.nodes if n.nid == node_id)
        if not node.available:
            return None
        node.available = False
        # bug1: 固定刷新
        node.respawn_time = 60
        # bug2: 失败不加经验
        self.exp[node.rtype] += 10
        # bug4: 固定耐久消耗
        self.tools["pickaxe"]["durability"] -= 1
        return {"type": node.rtype, "tier": node.tier}

    def fish(self, location):
        # bug3: 静态鱼群
        return {"fish": "common", "weight": 1.0}

    def craft(self, recipe_id):
        # bug5: 只看等级
        if self.skills["cooking"] >= 1:
            return True
        return False

    def get_exp_curve(self, skill):
        # bug6: 所有技能同曲线
        return 100
