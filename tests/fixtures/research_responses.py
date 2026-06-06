"""Canned dicts matching the shape of research_engine.research() return value.

Used to mock the pipeline in delivery/executor tests so they don't need
network access or live LLM keys.
"""
from typing import Any, Dict


def wheat_rust_report() -> Dict[str, Any]:
    return {
        "answer": (
            "Wheat leaf rust is a fungal disease caused by Puccinia triticina [1][2]. "
            "It spreads via airborne urediniospores and thrives in humid, warm conditions [3]. "
            "Resistant cultivars and timely fungicide application are the primary controls [1][3]."
        ),
        "sources": [
            {"n": 1, "url": "https://en.wikipedia.org/wiki/Wheat_leaf_rust",
             "title": "Wheat leaf rust — Wikipedia"},
            {"n": 2, "url": "https://www.nature.com/articles/leafrust",
             "title": "Genetic structure of Puccinia triticina — Nature"},
            {"n": 3, "url": "https://www.reuters.com/world/agriculture/wheat-rust-outbreak",
             "title": "Global wheat rust outbreak — Reuters"},
        ],
        "sub_queries": ["what causes wheat leaf rust", "how to control wheat leaf rust"],
        "contradictions": [],
        "cached": False,
        "ms": 28412,
    }


def cached_report() -> Dict[str, Any]:
    return {
        "answer": "Cached answer: x is y [1].",
        "sources": [{"n": 1, "url": "https://wikipedia.org/wiki/x", "title": "x"}],
        "sub_queries": ["q"],
        "contradictions": [],
        "cached": True,
        "ms": 42,
    }


def report_with_contradictions() -> Dict[str, Any]:
    return {
        "answer": "Source A says X [1]. Source B says not-X [2].",
        "sources": [
            {"n": 1, "url": "https://reuters.com/a", "title": "A"},
            {"n": 2, "url": "https://bbc.com/b", "title": "B"},
        ],
        "sub_queries": ["q"],
        "contradictions": [{"claim": "X", "supports": [1], "denies": [2]}],
        "cached": False,
        "ms": 30000,
    }
