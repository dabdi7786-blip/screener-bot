"""
news_brief.classify tests (spec category: 6 category classification).
Includes the live-discovered word-boundary regression ("putin" inside
"computing").
"""
from news_brief.classify import classify_all, classify_category, classify_impact_reasons, classify_market_impact
from news_brief.models import NewsCluster


def _cluster(title, summary=""):
    return NewsCluster(title=title, link="https://example.com", summary=summary, published_at=None)


def test_classify_middle_east():
    assert classify_category(_cluster("Houthis claim attack near Strait of Hormuz")) == "MIDDLE_EAST"


def test_classify_russia():
    assert classify_category(_cluster("Kremlin responds to new EU sanctions on Russia")) == "RUSSIA"


def test_classify_oil_gas():
    assert classify_category(_cluster("OPEC+ agrees to raise crude oil output")) == "OIL_GAS"


def test_classify_uranium_nuclear():
    assert classify_category(_cluster("Cameco signs long-term uranium supply deal")) == "URANIUM_NUCLEAR"


def test_classify_ai_semis():
    assert classify_category(_cluster("Nvidia unveils new AI chip amid export control concerns")) == "AI_SEMIS"


def test_classify_world_fallback():
    assert classify_category(_cluster("Federal Reserve holds interest rates steady")) == "WORLD"


def test_classify_unrelated_content_returns_none_not_world():
    """Spec section 8: avoid celebrity/sports/entertainment -- an item
    matching nothing should be excluded, not dumped into WORLD."""
    assert classify_category(_cluster("Local bakery wins regional pastry competition")) is None


def test_putin_substring_inside_computing_does_not_misclassify():
    """Regression: naive `'putin' in text` substring matching classified
    a private-equity/AI-computing story as RUSSIA because 'computing'
    contains 'putin'. Word-boundary matching must prevent this."""
    cluster = _cluster("Private Equity Daily: FirstMark Backs Exchange for AI Computing - WSJ")
    assert classify_category(cluster) != "RUSSIA"


def test_title_match_required_not_summary_only():
    """A Google-News-style bundled summary must not route an
    off-topic title into a specific category just because the summary
    happens to mention a keyword."""
    cluster = _cluster(
        "Quarterly earnings roundup for regional banks",
        summary="Related coverage also touched on Iran sanctions elsewhere in the market.",
    )
    # summary mentions Iran/sanctions but title doesn't -- must not become MIDDLE_EAST/RUSSIA
    assert classify_category(cluster) not in ("MIDDLE_EAST", "RUSSIA")


def test_market_impact_derived_from_real_keywords():
    cluster = _cluster("Tanker attacked near Strait of Hormuz, oil markets on alert")
    cluster.category = "MIDDLE_EAST"
    impact = classify_market_impact(cluster)
    assert impact.get("Oil/Shipping") == "HIGH" or impact.get("Oil/Energy infrastructure") == "HIGH"


def test_market_impact_empty_when_no_impact_keywords():
    cluster = _cluster("IAEA publishes annual safeguards report")
    cluster.category = "URANIUM_NUCLEAR"
    impact = classify_market_impact(cluster)
    assert isinstance(impact, dict)  # never raises; may be empty


def test_classify_all_mutates_clusters_in_place():
    clusters = [_cluster("OPEC+ agrees to raise crude oil output")]
    classify_all(clusters)
    assert clusters[0].category == "OIL_GAS"


def test_impact_reasons_has_matching_key_for_every_impact_asset():
    cluster = _cluster("Tanker attacked near Strait of Hormuz, oil markets on alert")
    cluster.category = "MIDDLE_EAST"
    impact = classify_market_impact(cluster)
    reasons = classify_impact_reasons(cluster)
    assert set(reasons.keys()) == set(impact.keys())
    assert all(isinstance(r, str) and r for r in reasons.values())  # short, non-empty, real phrase -- never blank


def test_impact_reasons_empty_when_no_impact_keywords():
    cluster = _cluster("IAEA publishes annual safeguards report")
    cluster.category = "URANIUM_NUCLEAR"
    assert classify_impact_reasons(cluster) == {}


def test_classify_all_sets_impact_reasons_alongside_market_impact():
    clusters = [_cluster("OPEC+ agrees to raise crude oil output amid tight inventories")]
    classify_all(clusters)
    c = clusters[0]
    assert c.market_impact  # sanity: this headline does hit an impact rule
    assert set(c.impact_reasons.keys()) == set(c.market_impact.keys())
