import networkx as nx

from app.services.communities import community_id, detect_communities


def _two_topics() -> nx.Graph:
    g = nx.Graph()
    # Topic A: two tight sub-groups with a moderate bridge (one topic, two sub-topics).
    for group in (["a1", "a2", "a3", "a4", "a5"], ["a6", "a7", "a8", "a9", "a10"]):
        for i, x in enumerate(group):
            for y in group[i + 1 :]:
                g.add_edge(x, y, weight=1.0)
    for a, b in [("a1", "a6"), ("a2", "a7"), ("a3", "a8"), ("a4", "a9")]:  # moderate bridge
        g.add_edge(a, b, weight=1.0)
    # Topic B: small clique, weakly linked to A.
    for i, x in enumerate(["b1", "b2", "b3", "b4"]):
        for y in ["b1", "b2", "b3", "b4"][i + 1 :]:
            g.add_edge(x, y, weight=1.0)
    g.add_edge("a1", "b1", weight=0.05)
    # A pair too small to be a community.
    g.add_edge("x1", "x2", weight=1.0)
    return g


def test_two_level_hierarchy():
    comms = detect_communities(_two_topics(), seed=7)
    top = [c for c in comms if c.level == 1]
    sub = [c for c in comms if c.level == 0]
    assert all(len(c.members) >= 3 for c in comms)
    assert {"b1", "b2", "b3", "b4"} in [set(c.members) for c in top]
    assert not any({"x1", "x2"} <= set(c.members) for c in comms)
    big = next(c for c in top if "a1" in c.members)
    children = [c for c in sub if c.parent_id == big.id]
    assert len(children) == 2
    assert {frozenset(c.members) for c in children} == {
        frozenset(f"a{i}" for i in range(1, 6)),
        frozenset(f"a{i}" for i in range(6, 11)),
    }


def test_ids_are_stable_hashes_of_membership():
    assert community_id(1, ["b", "a"]) == community_id(1, ["a", "b"])
    assert community_id(1, ["a", "b"]) != community_id(0, ["a", "b"])
    a = detect_communities(_two_topics(), seed=7)
    b = detect_communities(_two_topics(), seed=7)
    assert [c.id for c in a] == [c.id for c in b]


def test_empty_graph():
    assert detect_communities(nx.Graph()) == []
