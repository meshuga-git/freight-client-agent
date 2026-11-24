import json
import fitz
from freight_agent.corpus import generate


def test_corpus_structure_and_independence(tmp_path):
    manifest = generate(tmp_path, count=80)
    packs = manifest["packs"]
    assert len(packs) == 80
    assert sum(p["clean"] for p in packs) == 40
    assert sum(p["scan"] for p in packs) == 15
    assert sum(bool(p["adversarial"]) for p in packs) == 5
    assert sum(p["split"] == "dev" for p in packs) == 60
    assert {p["layout"] for p in packs} == {0, 1, 2}
    for pack in packs:
        truth = json.loads((tmp_path / pack["id"] / "ground_truth.json").read_text())
        assert len(truth["seeded_errors"]) <= 3 or pack["adversarial"] == "duplicate_number"
        for file in pack["files"]:
            with fitz.open(tmp_path / pack["id"] / file) as pdf:
                assert len(pdf) > 0
                if pack["scan"]:
                    assert not any(p.get_text().strip() for p in pdf)
    with fitz.open(tmp_path / "pack-001" / "invoice.pdf") as pdf:
        assert "COMMERCIAL INVOICE" in pdf[0].get_text()
        assert "Consignee: Example Tool Supply Ltd" in pdf[0].get_text()


def test_generator_is_reproducible(tmp_path):
    a = generate(tmp_path / "a", count=4, seed=19)
    b = generate(tmp_path / "b", count=4, seed=19)
    assert a == b


def test_evaluation_reads_only_pdf_through_extractor(tmp_path, monkeypatch):
    import docpipe
    from freight_agent.evaluation import evaluate

    generate(tmp_path / "corpus", count=4)
    real = docpipe.process_pdf
    supplied = []

    def observe(path, **kwargs):
        supplied.append(path)
        assert path.suffix == ".pdf"
        assert "ground_truth" not in str(path)
        return real(path, **kwargs)

    monkeypatch.setattr(docpipe, "process_pdf", observe)
    result = evaluate(tmp_path / "corpus", tmp_path / "reports", split="dev")
    assert result["pack_count"] == 4
    assert len(supplied) == 16
    assert result["silent_critical_errors"] == 0
    assert result["cost_usd"]["sum"] == 0
    assert result["source_sha256"]
    assert (tmp_path / "reports" / "dev.md").exists()
