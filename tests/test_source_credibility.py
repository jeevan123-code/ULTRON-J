"""Tests for source_credibility — URL -> SourceTier mapping."""
import pytest
from source_credibility import tier_for_url
from research_types import SourceTier


@pytest.mark.parametrize("url,expected", [
    ("https://arxiv.org/abs/2310.06825", SourceTier.ACADEMIC),
    ("https://pubmed.ncbi.nlm.nih.gov/12345/", SourceTier.ACADEMIC),
    ("https://www.nature.com/articles/abc", SourceTier.ACADEMIC),
    ("https://nih.gov/health/xyz", SourceTier.ACADEMIC),
    ("https://scholar.google.com/scholar?q=foo", SourceTier.ACADEMIC),
])
def test_academic_sources(url, expected):
    assert tier_for_url(url) == expected


@pytest.mark.parametrize("url,expected", [
    ("https://www.reuters.com/business/x", SourceTier.JOURNALISM),
    ("https://www.bbc.com/news/world-1", SourceTier.JOURNALISM),
    ("https://apnews.com/article/y", SourceTier.JOURNALISM),
    ("https://www.nytimes.com/2026/06/06/world", SourceTier.JOURNALISM),
    ("https://www.afp.com/en/news", SourceTier.JOURNALISM),
])
def test_journalism_sources(url, expected):
    assert tier_for_url(url) == expected


def test_wikipedia():
    assert tier_for_url("https://en.wikipedia.org/wiki/Foo") == SourceTier.WIKIPEDIA


@pytest.mark.parametrize("url,expected", [
    ("https://docs.python.org/3/library/asyncio.html", SourceTier.DOCS_OFFICIAL),
    ("https://github.com/anthropics/anthropic-sdk-python", SourceTier.DOCS_OFFICIAL),
    ("https://kubernetes.io/docs/concepts/", SourceTier.DOCS_OFFICIAL),
])
def test_docs_official(url, expected):
    assert tier_for_url(url) == expected


def test_blog_inferred_from_path():
    assert tier_for_url("https://medium.com/@someone/article") == SourceTier.BLOG
    assert tier_for_url("https://example.substack.com/p/foo") == SourceTier.BLOG


def test_unknown_for_random_domain():
    assert tier_for_url("https://random-news-site.example.com/story") == SourceTier.GENERAL


def test_unknown_for_garbage():
    assert tier_for_url("not a url") == SourceTier.UNKNOWN
    assert tier_for_url("") == SourceTier.UNKNOWN
