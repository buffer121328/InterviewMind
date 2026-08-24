"""Optional semantic judges that map external metric results into local scores."""

from .deepeval import DeepEvalJudgeEvaluator

__all__ = ["DeepEvalJudgeEvaluator"]
