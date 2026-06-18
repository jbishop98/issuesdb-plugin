"""Hybrid Python pilot — delivery planner and executor for issuesdb.

The pilot loads issues from the issuesdb tracker, classifies their risk tier,
maps dependencies, sequences them into delivery batches, writes a DELIVERY_PLAN,
then executes each batch by dispatching ``/orchestrate``.

Deterministic plumbing (loading, dependency parsing, sequencing, plan I/O,
dispatch, outcome parsing) lives in Python. Three narrow judgment calls
(readiness, tier, dependency inference) delegate to an LLM. The heavyweight
delivery work stays behind ``/orchestrate``, which the pilot shells out to.
"""

__version__ = "0.1.0"
