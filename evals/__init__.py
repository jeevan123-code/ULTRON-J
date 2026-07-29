"""Live evaluation harness — fixed questions with known-correct answers.

Run against a running Ultron, not in-process. The 1516-test suite was green
throughout the day Ultron was answering the gold price with a scraped table
and a stranger's byline: those bugs lived in the wiring between components,
and only a real request over HTTP goes through all of it.
"""
