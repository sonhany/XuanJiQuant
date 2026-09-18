from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_retired_execution_source_is_absent():
    assert not list((ROOT / "quant" / "execution").glob("*.py"))
    assert not (ROOT / "scripts" / "smoke_test.py").exists()
    assert not (ROOT / "scripts" / "verify_paper_rules.py").exists()


def test_api_verification_is_read_only_unless_explicitly_destructive():
    source = (ROOT / "scripts" / "test_api.py").read_text(encoding="utf-8")

    assert 'ap.add_argument("--destructive"' in source
    assert 'if args.reset and not args.destructive:' in source
    assert 'if args.destructive:' in source
    assert "place_order/fill_order 跳过（默认只读）" in source
