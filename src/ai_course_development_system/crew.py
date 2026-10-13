"""Thin 10% Python assembly. 90% of behaviour lives in agents/*_agent/ prompts+YAML."""
from pathlib import Path

import yaml
from crewai import LLM, Agent, Crew, Process, Task
from crewai_tools import FileReadTool, ScrapeWebsiteTool, SerplyWebSearchTool

BASE = Path(__file__).parent / "agents"

TOOL_REGISTRY = {
    "FileReadTool": FileReadTool,
    "SerplyWebSearchTool": SerplyWebSearchTool,
    "ScrapeWebsiteTool": ScrapeWebsiteTool,
}

from ai_course_development_system.task_order import TASK_ORDER


def _yaml(path: Path):
    return yaml.safe_load(path.read_text()) or {}


def _build_agents() -> dict:
    agents = {}
    for folder in sorted(BASE.iterdir()):
        agent_file = folder / "agent.yaml"
        if not folder.is_dir() or not agent_file.exists():
            continue
        name, cfg = next(iter(_yaml(agent_file).items()))
        settings = _yaml(folder / "config.yaml") if (folder / "config.yaml").exists() else {}
        tool_names = _yaml(folder / "tools" / "tools.yaml").get("tools", []) if (folder / "tools" / "tools.yaml").exists() else []
        prompts = (folder / "prompts.md").read_text() if (folder / "prompts.md").exists() else ""
        agents[name] = Agent(
            role=cfg["role"],
            goal=cfg["goal"],
            backstory=cfg["backstory"] + (f"\n\nOperating instructions:\n{prompts}" if prompts else ""),
            tools=[TOOL_REGISTRY[t]() for t in tool_names],
            llm=LLM(model=settings.get("llm", {}).get("model", "openai/gpt-4o")),
            reasoning=settings.get("reasoning", False),
            inject_date=settings.get("inject_date", True),
            allow_delegation=settings.get("allow_delegation", False),
            max_iter=settings.get("max_iter", 25),
            max_rpm=settings.get("max_rpm"),
            max_execution_time=settings.get("max_execution_time"),
        )
    return agents


def _collect_task_defs() -> dict:
    defs = {}
    for folder in sorted(BASE.iterdir()):
        tasks_file = folder / "tasks.yaml"
        if folder.is_dir() and tasks_file.exists():
            defs.update(_yaml(tasks_file))
    return defs


class AiCourseDevelopmentSystemCrew:
    """AiCourseDevelopmentSystem crew (thin loader over agents/*_agent/)."""

    def crew(self) -> Crew:
        agents = _build_agents()
        defs = _collect_task_defs()
        built = {}
        for task_name in TASK_ORDER:
            spec = defs[task_name]
            built[task_name] = Task(
                description=spec["description"],
                expected_output=spec["expected_output"],
                agent=agents[spec["agent"]],
                context=[built[c] for c in (spec.get("context") or [])],
                async_execution=spec.get("async_execution", False),
                markdown=False,
            )
        return Crew(
            agents=list(agents.values()),
            tasks=[built[t] for t in TASK_ORDER],
            process=Process.sequential,
            verbose=True,
            chat_llm=LLM(model="openai/gpt-4o"),
        )
