from copy import deepcopy
from datetime import date, timedelta

import pytest

from app.config import settings
from app.ingest import validate_corpus


def campus_corpus():
    return {
        "version": "campus-import-test",
        "permission": {
            "audience": "campus pilot",
            "approved_by": "Test reviewer",
            "security_approved_by": "Test security reviewer",
        },
        "guides": [
            {
                "id": "wifi-access",
                "title": "Test Wi-Fi access policy",
                "category": "wifi_network",
                "is_synthetic": False,
                "source_url": "https://kb.example.test/wifi",
                "content_owner": "Test support team",
                "audiences": ["campus"],
                "reviewed_at": str(date.today()),
                "review_due": str(date.today() + timedelta(days=30)),
                "applicability": {},
                "content_kind": "information",
                "request_types": ["how_to", "access"],
                "sections": [
                    {"heading": "Access", "text": "Test policy prose with no procedure.", "steps": []}
                ],
            }
        ],
    }


def enable_import(monkeypatch):
    for key, value in dict(
        app_mode="pilot",
        agent_mode="grounded",
        approved_campus_corpus_version="campus-import-test",
        campus_source_hosts=["kb.example.test"],
    ).items():
        monkeypatch.setattr(settings(), key, value)


def test_informational_article_preserves_provenance_without_fake_steps(monkeypatch):
    enable_import(monkeypatch)
    guide, _ = validate_corpus(campus_corpus())[0]
    assert guide.steps == [] and guide.workflow == [] and not guide.is_synthetic
    assert guide.content_owner == "Test support team" and guide.audiences == ["campus"]


@pytest.mark.parametrize(
    "change",
    [
        "demo",
        "unapproved_version",
        "unapproved_host",
        "no_security_review",
        "expired",
        "missing_owner",
        "missing_audience",
        "duplicate_id",
        "unknown_filter",
        "procedure_without_steps",
    ],
)
def test_rejects_unapproved_or_incomplete_campus_import(monkeypatch, change):
    enable_import(monkeypatch)
    corpus = campus_corpus()
    article = corpus["guides"][0]
    if change == "demo":
        monkeypatch.setattr(settings(), "app_mode", "demo")
    elif change == "unapproved_version":
        corpus["version"] = "unapproved"
    elif change == "unapproved_host":
        article["source_url"] = "https://unreviewed.example.test/wifi"
    elif change == "no_security_review":
        corpus["permission"].pop("security_approved_by")
    elif change == "expired":
        article["review_due"] = str(date.today() - timedelta(days=1))
    elif change == "missing_owner":
        article.pop("content_owner")
    elif change == "missing_audience":
        article.pop("audiences")
    elif change == "duplicate_id":
        corpus["guides"].append(deepcopy(article))
    elif change == "unknown_filter":
        article["applicability"] = {"invented_platform": "yes"}
    else:
        article["content_kind"] = "procedure"
    with pytest.raises(ValueError):
        validate_corpus(corpus)
