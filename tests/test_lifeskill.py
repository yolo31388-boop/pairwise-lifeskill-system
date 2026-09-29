"""生活技能系统七个熟练度 bug 的修复验证"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.engine import LifeSkillSystem, ResourceNode, Recipe, FAILURE_EXP_RATIO, CRAFT_EXP


def make_system(**kwargs):
    ls = LifeSkillSystem(seed=kwargs.pop("seed", 42))
    ls.nodes = [ResourceNode("n1", "mining", 1, 60),
                ResourceNode("n2", "mining", 3, 60)]
    return ls


class TestRespawnPerPlayer:
    def test_players_have_independent_refresh(self):
        ls = make_system()
        assert ls.gather("n1", "alice", luck=0.0) is not None
        # alice 采过后该节点对她进入刷新，但 bob 仍可见可采
        assert not ls.is_available("n1", "alice")
        assert ls.is_available("n1", "bob")
        assert ls.gather("n1", "bob", luck=0.0) is not None

    def test_respawn_times_differ_between_players(self):
        ls = make_system()
        ls.gather("n1", "alice", luck=0.0)
        ls.gather("n1", "bob", luck=0.0)
        t_a = ls.next_respawn("n1", "alice")
        t_b = ls.next_respawn("n1", "bob")
        assert t_a is not None and t_b is not None
        assert t_a != t_b, "所有玩家刷新时间相同，导致抢矿"


class TestFailureExp:
    def test_craft_failure_grants_partial_exp(self):
        ls = make_system()
        ls.register_recipe(Recipe("r1", "cooking", level_req=5))
        before = ls.exp["cooking"]
        assert ls.craft("r1") is False
        assert ls.exp["cooking"] == before + int(CRAFT_EXP * FAILURE_EXP_RATIO)

    def test_gather_failure_grants_partial_exp(self):
        ls = make_system()
        ls.nodes = [ResourceNode("hard", "mining", 10, 60)]
        before = ls.exp["mining"]
        result = ls.gather("hard", "alice", luck=0.99)  # 必失败
        assert result["success"] is False
        assert ls.exp["mining"] == before + int(10 * 10 * FAILURE_EXP_RATIO)


class TestDynamicFish:
    def test_fish_distribution_changes_with_weather_and_time(self):
        rainy = LifeSkillSystem(seed=1)
        rainy.weather = "rainy"
        rainy_catch = {rainy.fish("pond")["fish"] for _ in range(50)}
        sunny = LifeSkillSystem(seed=1)
        sunny.weather = "sunny"
        sunny_catch = {sunny.fish("pond")["fish"] for _ in range(50)}
        assert rainy_catch != sunny_catch, "鱼群分布不随天气变化"
        night = LifeSkillSystem(seed=1)
        night.time_of_day = "night"
        night_catch = {night.fish("pond")["fish"] for _ in range(50)}
        assert night_catch != sunny_catch, "鱼群分布不随时间变化"


class TestDurability:
    def test_durability_scales_with_node_and_tool_tier(self):
        ls = make_system()
        d0 = ls.tools["pickaxe"]["durability"]
        ls.gather("n1", "alice", luck=0.0)  # tier1 节点, tier1 工具
        cheap = d0 - ls.tools["pickaxe"]["durability"]
        d1 = ls.tools["pickaxe"]["durability"]
        ls.gather("n2", "alice", luck=0.0)  # tier3 节点
        costly = d1 - ls.tools["pickaxe"]["durability"]
        assert costly > cheap, "高级资源和低级资源耐久消耗一样"
        ls.tools["pickaxe"]["tier"] = 5
        d2 = ls.tools["pickaxe"]["durability"]
        ls.gather("n2", "bob", luck=0.0)  # 高级工具采同级资源
        assert d2 - ls.tools["pickaxe"]["durability"] < costly, "工具等级不影响耐久消耗"


class TestRecipePrereqChain:
    def test_recipe_requires_level_quest_achievement_and_prereq(self):
        ls = make_system()
        ls.register_recipe(Recipe("basic", "cooking", level_req=1))
        ls.register_recipe(Recipe("feast", "cooking", level_req=3,
                                  quest_req="q1", achievement_req="a1",
                                  prereq_recipes=("basic",)))
        ls.skills["cooking"] = 3  # 只有等级不够
        assert not ls.can_craft("feast")
        ls.completed_quests.add("q1")
        assert not ls.can_craft("feast")
        ls.achievements.add("a1")
        assert not ls.can_craft("feast")  # 还差前置配方
        assert ls.craft("basic") is True
        assert ls.can_craft("feast")
        assert ls.craft("feast") is True


class TestExpCurves:
    def test_each_skill_has_own_curve(self):
        ls = make_system()
        curves = {s: ls.get_exp_curve(s) for s in ("mining", "fishing", "cooking")}
        assert len(set(curves.values())) == 3, "不同生活技能经验曲线相同"


class TestQuality:
    def test_quality_depends_on_tool_skill_and_luck(self):
        ls = make_system()
        low = ls.gather("n1", "alice", luck=0.5)["quality"]
        ls.tools["pickaxe"]["tier"] = 5
        ls.skills["mining"] = 10
        high = ls.gather("n1", "bob", luck=0.5)["quality"]
        assert low != high, "资源品质不受工具等级和技能等级影响"
