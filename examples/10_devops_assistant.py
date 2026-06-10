"""
================================================================
EXAMPLE 10 — "The full thing: a DevOps AI" (COMPLETE)
================================================================

SCENARIO:
    The realistic kitchen-sink example: an AI DevOps assistant that uses
    kubectl + aws_cli + terraform. Production gets stricter:
      - Reads always allowed
      - Non-prod mutations dry-run first
      - Prod mutations require approval
      - Catastrophic commands (rm -rf /, rds delete, terraform destroy) DENY

    Auto-approve is used in this demo so the run completes; in real use,
    plug in cli_prompt_approval or a Slack webhook handler.

RUN WITH:
    python examples/10_devops_assistant.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from lynx import (
    FinalAnswer,
    Message,
    ToolCall,
    ToolSet,
    auto_approve,
    load_policy_file,
    run_agent,
    stdout_sink,
    tool,
)


@tool(reversible=False, scope=("k8s:exec",))
async def kubectl(command: str, namespace: str = "default") -> str:
    return f"$ kubectl --namespace={namespace} {command}"


@kubectl.shadow
async def _k_shadow(command: str, namespace: str = "default") -> dict:
    return {"would_run": f"kubectl --namespace={namespace} {command}"}


@tool(reversible=False, scope=("aws:exec",))
async def aws_cli(command: str, region: str = "us-east-1") -> str:
    return f"$ aws --region={region} {command}"


@aws_cli.shadow
async def _aws_shadow(command: str, region: str = "us-east-1") -> dict:
    return {"would_run": f"aws --region={region} {command}"}


@tool(reversible=False, scope=("iac:exec",))
async def terraform(command: str, dir: str = ".") -> str:
    return f"$ terraform -chdir={dir} {command}"


@terraform.shadow
async def _tf_shadow(command: str, dir: str = ".") -> dict:
    return {"would_run": f"terraform -chdir={dir} {command}"}


@tool(reversible=False, scope=("shell:exec",))
async def shell(cmd: str) -> str:
    return f"$ {cmd}"


@shell.shadow
async def _shell_shadow(cmd: str) -> dict:
    return {"would_run": cmd}


class DevOpsAgent:
    PLAN = [
        ("kubectl", {"command": "get pods"}),
        ("kubectl", {"command": "describe deployment app"}),
        ("aws_cli", {"command": "s3 ls"}),
        ("terraform", {"command": "plan"}),
        ("kubectl", {"command": "apply -f bug-fix.yaml"}),
        ("kubectl", {"command": "apply -f hotfix.yaml", "namespace": "production"}),
        ("aws_cli", {"command": "ec2 terminate-instances --instance-ids i-abc"}),
        ("shell", {"cmd": "rm -rf /"}),
        ("aws_cli", {"command": "rds delete-db-cluster --db-cluster-identifier prod"}),
        ("terraform", {"command": "destroy -auto-approve"}),
    ]

    def __init__(self):
        self._i = 0

    async def step(self, conv: tuple[Message, ...]):
        if self._i >= len(self.PLAN):
            return FinalAnswer(text="DevOps walkthrough complete.")
        tool_name, args = self.PLAN[self._i]
        self._i += 1
        return ToolCall(tool=tool_name, args=args, call_id=f"c{self._i}")


async def main() -> None:
    policy_path = Path(__file__).resolve().parent / "policies" / "devops.yaml"
    tools = ToolSet.from_functions(kubectl, aws_cli, terraform, shell)
    result = await run_agent(
        DevOpsAgent(),
        task="DevOps walkthrough — production environment",
        tools=tools,
        policy=load_policy_file(policy_path),
        sinks=(stdout_sink(),),
        on_approval=auto_approve(approver="sre-oncall"),
        environment="prod",
    )
    print()
    print(f"Final: {result.final_answer}")


if __name__ == "__main__":
    asyncio.run(main())
