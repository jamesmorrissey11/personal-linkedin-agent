"""Run the invitation-decision evals: `uv run python -m evals.run` (backend from MODEL_BACKEND)."""

from dotenv import load_dotenv
from pydantic_evals import Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, IsInstance

from linkedin_agent import invitations
from linkedin_agent.linkedin.models import InvitationDecision

# Define test cases for the LinkedIn invitation agent


class CorrectDecisionEvaluator(Evaluator[str, InvitationDecision]):
    def evaluate(self, ctx: EvaluatorContext[str, InvitationDecision]) -> float:
        if ctx.expected_output and ctx.output.action == ctx.expected_output.action:
            return 1.0
        else:
            return 0.0


# Load cases from YAML file
dataset = Dataset[str, InvitationDecision, dict].from_file(invitations.EVAL_CASES_PATH)
dataset.evaluators = [IsInstance(type_name="InvitationDecision"), CorrectDecisionEvaluator()]


async def agent_decision(input_str: str) -> InvitationDecision:
    result = await invitations.get_agent().run(input_str)
    return result.output


def main():
    load_dotenv()
    report = dataset.evaluate_sync(agent_decision)
    report.print(include_input=True, include_output=True, include_durations=False)


if __name__ == "__main__":
    main()
