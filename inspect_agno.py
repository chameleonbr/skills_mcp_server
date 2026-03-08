import inspect
from agno.skills.agent_skills import Skills
from agno.skills.skill import Skill

print(inspect.getsource(Skill.get_script))
try:
    print(inspect.getsource(Skills._get_skill_script))
except Exception as e:
    print("Error:", e)
