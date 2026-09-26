"""The corpus gate must expose tradeoffs that a hard-finding count hides."""

from copy import deepcopy
import hashlib

from scripts.layout_compare import BASE_HEAD, BASE_STEMS, HARD_KEYS, RULES, compare


def _hard() -> dict[str, int]:
    """Create a zero-valued hard-finding record for a test variant.

    Returns
    -------
    dict[str, int]
        All release-gate hard counters initialized to zero.
    """
    return dict.fromkeys(HARD_KEYS, 0)


def _hash(path) -> str:
    """Hash a temporary preview used by a comparison test.

    Parameters
    ----------
    path : pathlib.Path
        Preview file to read.

    Returns
    -------
    str
        SHA-256 digest of the file bytes.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_recovered_fallback_does_not_hide_a_new_crossing():
    """Reject a new crossing even when a routing fallback disappears.

    Returns
    -------
    None
        The test succeeds when the sheet is classified as regressed.
    """
    variants = []
    for number in range(21):
        stem = f"sheet_{number:02d}"
        for auto in (False, True):
            variants.append(
                {
                    "stem": stem,
                    "auto": auto,
                    "hard": _hard(),
                    "metrics": {"crossings": 0, "bends": 4, "length": 400.0, "area": 10000.0},
                    "proxies": {},
                    "fingerprint": stem,
                    "author_intent": {},
                }
            )
    baseline = {"head": "base", "variants": variants}
    candidate = deepcopy(baseline)
    baseline["variants"][1]["hard"]["fallback"] = 1
    candidate["variants"][1]["metrics"]["crossings"] = 1
    review = {
        "sheet_00": {
            "G1": {
                "verdict": "better",
                "reason": "clear exit",
                "before": "before.svg",
                "after": "after.svg",
            }
        }
    }

    result = compare(baseline, candidate, review)

    assert not result.passed
    assert "sheet_00" in result.regressed
    assert any("crossing" in reason for reason in result.reasons["sheet_00"])


def test_a_visual_win_must_match_the_measured_rule(tmp_path):
    """Require a visual improvement to match the improved numeric rule.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest directory for the paired review images.

    Returns
    -------
    None
        The test succeeds when the unrelated visual claim stays unchanged.
    """
    before_image = tmp_path / "before.svg"
    after_image = tmp_path / "after.svg"
    before_image.write_text("before", encoding="utf-8")
    after_image.write_text("after", encoding="utf-8")
    baseline = {
        "variants": [
            {
                "stem": "example",
                "auto": auto,
                "hard": _hard(),
                "metrics": {"crossings": 0, "bends": 5, "length": 400.0, "area": 10000.0},
                "proxies": {"S1.claim_direction_violations": {"status": "measured", "value": 2}},
                "fingerprint": "same",
                "author_intent": {},
                "images": {"svg": str(before_image)},
                "image_hashes": {"svg": _hash(before_image)},
            }
            for auto in (False, True)
        ]
    }
    candidate = deepcopy(baseline)
    candidate["variants"][1]["proxies"]["S1.claim_direction_violations"]["value"] = 1
    candidate["variants"][1]["fingerprint"] = "changed"
    candidate["variants"][1]["images"] = {"svg": str(after_image)}
    candidate["variants"][1]["image_hashes"] = {"svg": _hash(after_image)}
    review = {
        "example": {
            **{
                rule: {
                    "verdict": "same",
                    "reason": "no visible change to this rule",
                    "before": str(before_image),
                    "after": str(after_image),
                }
                for rule in RULES
            },
            "G3": {
                "verdict": "better",
                "reason": "more balanced",
                "before": str(before_image),
                "after": str(after_image),
            },
        }
    }

    result = compare(baseline, candidate, review)

    assert result.improved == []
    assert result.unchanged == ["example"]


def test_release_pass_requires_real_corpus_evidence_and_authored_intent(tmp_path):
    """Reject missing image evidence, changed author intent, and wrong baseline heads.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest directory for the paired review images.

    Returns
    -------
    None
        The test succeeds when only the complete candidate passes the gate.
    """
    before_image = tmp_path / "before.svg"
    after_image = tmp_path / "after.svg"
    before_image.write_text("before", encoding="utf-8")
    after_image.write_text("after", encoding="utf-8")
    baseline = {
        "head": BASE_HEAD,
        "variants": [
            {
                "stem": stem,
                "auto": auto,
                "hard": _hard(),
                "metrics": {"crossings": 1, "bends": 5, "length": 400.0, "area": 10000.0},
                "proxies": {},
                "fingerprint": f"{stem}-{auto}",
                "images": {"svg": str(before_image)},
                "image_hashes": {"svg": _hash(before_image)},
                "author_intent": {"pins": "exact"},
            }
            for stem in BASE_STEMS
            for auto in (False, True)
        ],
    }
    candidate = deepcopy(baseline)
    review = {}
    for stem in BASE_STEMS[:11]:
        row = next(v for v in candidate["variants"] if v["stem"] == stem and v["auto"])
        row["metrics"]["crossings"] = 0
        row["metrics"]["area"] = 9700.0
        row["fingerprint"] += "-changed"
        row["images"] = {"svg": str(after_image)}
        row["image_hashes"] = {"svg": _hash(after_image)}
        review[stem] = {
            **{
                rule: {
                    "verdict": "same",
                    "reason": "no visible change to this rule",
                    "before": str(before_image),
                    "after": str(after_image),
                }
                for rule in RULES
            },
            "G2": {
                "verdict": "better",
                "reason": "fewer crossings",
                "before": str(before_image),
                "after": str(after_image),
            },
        }

    assert compare(baseline, candidate, review).passed

    candidate["variants"][0]["author_intent"] = {"pins": "moved"}
    assert not compare(baseline, candidate, review).passed
    candidate["variants"][0]["author_intent"] = {"pins": "exact"}

    review[BASE_STEMS[0]]["G2"]["after"] = str(tmp_path / "missing.svg")
    assert not compare(baseline, candidate, review).passed
    review[BASE_STEMS[0]]["G2"]["after"] = str(after_image)

    review[BASE_STEMS[0]]["G2"]["after"] = str(before_image)
    assert not compare(baseline, candidate, review).passed
    review[BASE_STEMS[0]]["G2"]["after"] = str(after_image)

    baseline["head"] = "another revision"
    assert not compare(baseline, candidate, review).passed
