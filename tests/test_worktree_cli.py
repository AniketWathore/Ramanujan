"""CLI worktree spawn + claim post — Phase 4 engine surface."""

import json
from pathlib import Path

from click.testing import CliRunner

from ramanujan.cli import main

PRIME_CARD = {
    "card_id": "c_0001",
    "statement_informal": "For every integer n >= 0, n^2 + n + 41 is prime.",
    "claim_type": ["inequality-estimate"],
    "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "is_prime(n**2 + n + 41)", "sympy_parseable": True},
    "set_vars": [],
}

TRUE_CARD = {
    "card_id": "c_0001",
    "statement_informal": "For every integer n >= 0, n + 1 > n.",
    "claim_type": ["inequality-estimate"],
    "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "n + 1 > n", "sympy_parseable": True},
    "set_vars": [],
}


def test_cli_worktree_spawn_and_claim_post(tmp_path: Path):
    j = tmp_path / "journal.jsonl"
    runner = CliRunner()
    # spawn wt_001
    res = runner.invoke(
        main,
        [
            "worktree",
            "spawn",
            "--provider",
            "test",
            "--model-id",
            "test/model",
            "--family",
            "family:test",
            "--model-ref",
            "test/model",
            "--journal",
            str(j),
            "--json",
        ],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["status"] == "ok" and data["worktree_id"] == "wt_001"
    # card files
    p1 = tmp_path / "c1.json"
    p2 = tmp_path / "c2.json"
    p1.write_text(json.dumps(PRIME_CARD), encoding="utf-8")
    p2.write_text(json.dumps(TRUE_CARD), encoding="utf-8")
    # first claim via wt_001 -> refuted, tier0, linted
    res2 = runner.invoke(main, ["claim", "post", "--worktree-id", "wt_001", "--card-file", str(p1), "--journal", str(j), "--json"])
    assert res2.exit_code == 0, res2.output
    c1 = json.loads(res2.output)
    assert c1["status"] == "ok" and c1["claim_id"] == "c_001"
    assert c1["verification_path"] == "tier0"
    assert c1["tier0"]["verdict"] == "REFUTED"
    assert c1["tier1"]["linted"] is True
    # second claim -> survived
    res3 = runner.invoke(main, ["claim", "post", "--worktree-id", "wt_001", "--card-file", str(p2), "--journal", str(j), "--json"])
    assert res3.exit_code == 0, res3.output
    c2 = json.loads(res3.output)
    assert c2["claim_id"] == "c_002" and c2["tier0"]["verdict"] == "SURVIVED"
    # replay validates 4 new event types and board folds to 2 claims
    from ramanujan.claims import fold_claims
    from ramanujan.journal import replay

    evs = replay(j)
    assert fold_claims(evs).keys() >= {"c_001", "c_002"}
    assert any(e["type"] == "worktree_spawned" for e in evs)
    assert any(e["type"] == "claim_posted" for e in evs)
