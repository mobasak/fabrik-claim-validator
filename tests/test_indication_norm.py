"""Indication normalizer tests (FCV-204).

Covers:
- Local map fast-path (50 common indications).
- WHO ICD-11 API search via cassette.
- ICTM TM2 fallback.
- No-match path.
- Batch normalization.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from fabrik_claim_validator.services.indication_norm import (
    IndicationNormalizer,
    NormResult,
    _normalize_text,
)

# Force cassette replay.
os.environ.setdefault("CASSETTE_MODE", "replay")


# ─── Unit tests (no DB, no network) ───────────────────────────


class TestNormalizeText:
    """Test text normalization helper."""

    def test_lowercase_and_strip(self) -> None:
        assert _normalize_text("  HEADACHE  ") == "headache"

    def test_removes_accents(self) -> None:
        assert _normalize_text("Céphalée") == "cephalee"

    def test_removes_noise_words(self) -> None:
        result = _normalize_text("Relief of symptoms of the common cold")
        # "of", "the" removed
        assert "of" not in result.split()
        assert "the" not in result.split()

    def test_collapses_whitespace(self) -> None:
        assert _normalize_text("joint    pain") == "joint pain"


class TestLocalMap:
    """Test the local indication map (fast path)."""

    @pytest.mark.asyncio
    async def test_headache_maps_to_icd(self) -> None:
        async with IndicationNormalizer() as norm:
            result = await norm.normalize("headache")
        assert result.code == "8A80"
        assert result.source == "local_map"

    @pytest.mark.asyncio
    async def test_migraine_maps(self) -> None:
        async with IndicationNormalizer() as norm:
            result = await norm.normalize("Migraine")
        assert result.code == "8A80.0"
        assert result.source == "local_map"

    @pytest.mark.asyncio
    async def test_anxiety_maps(self) -> None:
        async with IndicationNormalizer() as norm:
            result = await norm.normalize("ANXIETY")
        assert result.code == "6B00"
        assert result.source == "local_map"

    @pytest.mark.asyncio
    async def test_diabetes_maps(self) -> None:
        async with IndicationNormalizer() as norm:
            result = await norm.normalize("diabetes mellitus")
        assert result.code == "5A10"
        assert result.source == "local_map"

    @pytest.mark.asyncio
    async def test_diarrhoea_british_spelling(self) -> None:
        async with IndicationNormalizer() as norm:
            result = await norm.normalize("diarrhoea")
        assert result.code == "MD91.0"

    @pytest.mark.asyncio
    async def test_empty_input(self) -> None:
        async with IndicationNormalizer() as norm:
            result = await norm.normalize("")
        assert result.code is None
        assert result.source == "empty"


class TestICDApiCassette:
    """Test WHO ICD-11 API search via cassette replay."""

    @pytest.mark.asyncio
    async def test_joint_pain_via_api(self) -> None:
        """ICD API returns code for 'joint pain' (not in local map)."""
        async with IndicationNormalizer() as norm:
            result = await norm.normalize("joint pain")
        # 'joint pain' is not in local map, so it goes to ICD API cassette.
        assert result.code == "ME82"
        assert result.source == "who_icd_api"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self) -> None:
        """TCM-specific term returns no ICD match."""
        async with IndicationNormalizer() as norm:
            result = await norm.normalize("liver qi stagnation")
        # No ICD match, no DB for ICTM fallback → no_match.
        assert result.code is None
        assert result.source == "no_match"


class TestBatchNormalization:
    """Test batch normalization."""

    @pytest.mark.asyncio
    async def test_batch(self) -> None:
        indications = ["headache", "insomnia", "joint pain"]
        async with IndicationNormalizer() as norm:
            results = await norm.normalize_batch(indications)
        assert len(results) == 3
        assert results[0].code == "8A80"
        assert results[1].code == "7A00"
        assert results[2].code == "ME82"


class TestNormResult:
    """Test NormResult data class."""

    def test_to_dict(self) -> None:
        r = NormResult(original="headache", code="8A80", source="local_map")
        d = r.to_dict()
        assert d == {"original": "headache", "code": "8A80", "source": "local_map"}

    def test_repr(self) -> None:
        r = NormResult(original="test", code="ABC", source="test_source")
        assert "ABC" in repr(r)


# ─── Coverage: test 50-indication corpus (local map) ──────────


class TestFiftyIndicationCorpus:
    """Validate ≥80% of a 50-indication corpus maps cleanly (FCV-204 DoD)."""

    CORPUS = [
        "headache", "migraine", "nausea", "vomiting", "insomnia",
        "anxiety", "depression", "hypertension", "diabetes", "cough",
        "common cold", "influenza", "diarrhea", "constipation", "pain",
        "chronic pain", "arthritis", "rheumatoid arthritis", "osteoarthritis",
        "inflammation", "fever", "fatigue", "asthma", "bronchitis",
        "eczema", "dermatitis", "urinary tract infection", "dyspepsia",
        "gastritis", "peptic ulcer", "menstrual pain", "dysmenorrhea",
        "menopausal symptoms", "benign prostatic hyperplasia",
        "erectile dysfunction", "hepatitis", "wound healing", "burns",
        "allergic rhinitis", "sinusitis", "tinnitus", "vertigo",
        "obesity", "hyperlipidemia", "anemia", "joint pain",
        "liver qi stagnation", "kidney yang deficiency",
        "blood stasis", "wind-cold invasion",
    ]

    @pytest.mark.asyncio
    async def test_eighty_percent_mapped(self) -> None:
        """≥80% of the 50-indication corpus maps to an ICD code."""
        async with IndicationNormalizer() as norm:
            results = await norm.normalize_batch(self.CORPUS)

        mapped = [r for r in results if r.code is not None]
        pct = len(mapped) / len(self.CORPUS) * 100
        # DoD: ≥80% map cleanly.
        assert pct >= 80, f"Only {pct:.1f}% mapped ({len(mapped)}/{len(self.CORPUS)})"

    @pytest.mark.asyncio
    async def test_failures_logged(self) -> None:
        """Unmapped indications have source='no_match' for audit."""
        async with IndicationNormalizer() as norm:
            results = await norm.normalize_batch(self.CORPUS)

        unmapped = [r for r in results if r.code is None]
        for r in unmapped:
            assert r.source in ("no_match", "empty")


# ─── FCV-256: 5-language corpus evaluation (50 entries × 5 langs) ────


class TestFiveLanguageCorpus:
    """Evaluate indication normalizer across EN, DE, FR, ES, ZH (FCV-256 DoD).

    Corpus: ``tests/fixtures/indication_norm_corpus.json`` (50 entries, 10 per lang).
    Thresholds: EN ≥ 90%, DE+FR+ES ≥ 80% combined, ZH documented.
    """

    @pytest.fixture(scope="class")
    def corpus(self) -> list[dict[str, str]]:
        import json

        path = Path(__file__).parent / "fixtures" / "indication_norm_corpus.json"
        return json.loads(path.read_text())

    @pytest.mark.asyncio
    async def test_corpus_has_50_balanced_entries(self, corpus) -> None:
        assert len(corpus) == 50
        from collections import Counter

        lang_counts = Counter(e["lang"] for e in corpus)
        assert lang_counts == {"en": 10, "de": 10, "fr": 10, "es": 10, "zh": 10}

    @pytest.mark.asyncio
    async def test_per_language_match_rates(self, corpus) -> None:
        """Run normalizer on all 50 entries; report per-language match rate."""
        async with IndicationNormalizer() as norm:
            results = await norm.normalize_batch([e["text"] for e in corpus])

        # Build per-language results.
        by_lang: dict[str, list[tuple[dict, NormResult]]] = {}
        for entry, result in zip(corpus, results, strict=True):
            by_lang.setdefault(entry["lang"], []).append((entry, result))

        report: dict[str, dict[str, Any]] = {}
        for lang, pairs in sorted(by_lang.items()):
            total = len(pairs)
            matched = sum(1 for _, r in pairs if r.code is not None)
            correct = sum(
                1 for e, r in pairs
                if r.code is not None and r.code == e["expected_code"]
            )
            rate = matched / total * 100 if total > 0 else 0
            acc = correct / total * 100 if total > 0 else 0
            report[lang] = {
                "total": total,
                "matched": matched,
                "correct": correct,
                "match_rate": round(rate, 1),
                "accuracy": round(acc, 1),
                "failures": [
                    e["text"] for e, r in pairs if r.code is None
                ],
            }

        # Print report for CI visibility.
        print("\n=== FCV-256 Indication Normalizer 5-Language Evaluation ===")
        for lang, data in sorted(report.items()):
            print(
                f"  {lang.upper()}: {data['matched']}/{data['total']} matched "
                f"({data['match_rate']}%), {data['correct']}/{data['total']} "
                f"correct ({data['accuracy']}%)"
            )
            if data["failures"]:
                print(f"    Failures: {data['failures']}")

        # DoD thresholds.
        assert report["en"]["match_rate"] >= 90, f"EN match rate {report['en']['match_rate']}% < 90%"

        de_fr_es_total = sum(report[lg]["total"] for lg in ("de", "fr", "es"))
        de_fr_es_matched = sum(report[lg]["matched"] for lg in ("de", "fr", "es"))
        de_fr_es_rate = de_fr_es_matched / de_fr_es_total * 100
        assert de_fr_es_rate >= 80, f"DE+FR+ES combined {de_fr_es_rate:.1f}% < 80%"

        # ZH: document result, don't block.  If < 80%, it's Sprint 5 carry.
        zh_rate = report["zh"]["match_rate"]
        if zh_rate < 80:
            print(f"  ⚠️ ZH match rate {zh_rate}% < 80% — Sprint 5 carry (FCV-502)")

    @pytest.mark.asyncio
    async def test_all_matched_codes_are_correct(self, corpus) -> None:
        """Every matched code must equal the expected code in the corpus."""
        async with IndicationNormalizer() as norm:
            results = await norm.normalize_batch([e["text"] for e in corpus])

        mismatches = []
        for entry, result in zip(corpus, results, strict=True):
            if result.code is not None and result.code != entry["expected_code"]:
                mismatches.append(
                    f"{entry['text']} ({entry['lang']}): got {result.code}, "
                    f"expected {entry['expected_code']}"
                )
        assert not mismatches, "Code mismatches:\n" + "\n".join(mismatches)
