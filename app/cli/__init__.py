"""Interactive command-line front end for InferRouter-LLM.

Runs one intent through the whole pipeline and prints what happened at each
stage: complexity estimation, routing decision, model call, judge scoring.
Entry point: ``python -m app.cli "<intent>"``.
"""
