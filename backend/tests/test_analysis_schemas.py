"""Validate provider JSON without calling an AI API or connecting to PostgreSQL."""

import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.models.finding import FindingCategory, FindingConfidence, FindingSeverity
from app.schemas.analysis import (
    InvalidReviewOutput,
    ReviewAnalysis,
    ReviewFinding,
    parse_review_analysis,
)


@pytest.fixture
def payload() -> dict:
    return {
        "summary": "One possible empty-input issue in the supplied changes.",
        "findings": [
            {
                "severity": "medium",
                "category": "bug",
                "file_path": "src/users.py",
                "line": 12,
                "title": "Possible empty-list access",
                "explanation": "Accessing the first item fails when the list is empty.",
                "evidence": "    return users[0]\n",
                "suggestion": "    return users[0] if users else None\n",
                "confidence": "high",
            }
        ],
    }


@pytest.mark.parametrize("as_bytes", [False, True])
def test_parses_complete_json_and_preserves_evidence(payload: dict, as_bytes: bool) -> None:
    raw = json.dumps(payload)
    result = parse_review_analysis(raw.encode() if as_bytes else raw)
    assert result.summary == payload["summary"]
    finding = result.findings[0]
    assert finding.severity is FindingSeverity.MEDIUM
    assert finding.category is FindingCategory.BUG
    assert finding.confidence is FindingConfidence.HIGH
    assert finding.line == 12
    assert finding.evidence == "    return users[0]\n"
    assert finding.suggestion == payload["findings"][0]["suggestion"]
    assert result.model_dump(mode="json") == payload
    assert json.loads(result.model_dump_json()) == payload
    assert finding.evidence not in repr(result)
    assert finding.evidence not in repr(finding)


def test_provider_python_dictionary_is_also_supported(payload: dict) -> None:
    result = ReviewAnalysis.model_validate(payload)
    assert result.findings[0].severity is FindingSeverity.MEDIUM


def test_no_findings_is_a_valid_result() -> None:
    result = parse_review_analysis(
        '{"summary":"No supported findings in the supplied changes.","findings":[]}'
    )
    assert result.findings == []


def test_line_can_be_explicitly_unknown(payload: dict) -> None:
    payload["findings"][0]["line"] = None
    result = parse_review_analysis(json.dumps(payload))
    assert result.findings[0].line is None


@pytest.mark.parametrize(
    "field",
    [
        "severity",
        "category",
        "file_path",
        "line",
        "title",
        "explanation",
        "evidence",
        "suggestion",
        "confidence",
    ],
)
def test_every_finding_field_is_required(payload: dict, field: str) -> None:
    del payload["findings"][0][field]
    with pytest.raises(InvalidReviewOutput):
        parse_review_analysis(json.dumps(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("severity", "severe"),
        ("severity", "HIGH"),
        ("severity", True),
        ("category", "style"),
        ("category", None),
        ("confidence", "certain"),
        ("line", 0),
        ("line", -1),
        ("line", True),
        ("line", 1.5),
        ("line", "12"),
        ("line", 2_147_483_648),
        ("title", ""),
        ("title", " " * 20),
        ("title", "x" * 201),
        ("title", 42),
        ("explanation", None),
        ("evidence", ""),
        ("evidence", {}),
        ("suggestion", "\n\t "),
        ("suggestion", "x" * 4001),
        ("file_path", "x" * 4097),
    ],
)
def test_rejects_invalid_finding_fields(payload: dict, field: str, value: object) -> None:
    payload["findings"][0][field] = value
    with pytest.raises(InvalidReviewOutput):
        parse_review_analysis(json.dumps(payload))


@pytest.mark.parametrize("field", ["severity", "category", "confidence"])
def test_python_bytes_are_not_coerced_to_enum_values(payload: dict, field: str) -> None:
    payload["findings"][0][field] = payload["findings"][0][field].encode()
    with pytest.raises(ValidationError):
        ReviewAnalysis.model_validate(payload)


@pytest.mark.parametrize(
    ("severity", "category", "confidence"),
    [
        ("critical", "security", "high"),
        ("high", "performance", "medium"),
        ("low", "maintainability", "low"),
        ("info", "bug", "high"),
    ],
)
def test_enum_values_remain_compatible_with_database_models(
    payload: dict, severity: str, category: str, confidence: str
) -> None:
    payload["findings"][0].update(severity=severity, category=category, confidence=confidence)
    finding = ReviewAnalysis.model_validate(payload).findings[0]
    assert finding.severity is FindingSeverity(severity)
    assert finding.category is FindingCategory(category)
    assert finding.confidence is FindingConfidence(confidence)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../secret",
        "/src/users.py",
        "src/../secret",
        "./users.py",
        "src//users.py",
        "src/users.py/",
        "C:/users.py",
        "src\\users.py",
        "a\x00b.py",
        "a\nb.py",
        "a\x7fb.py",
    ],
)
def test_rejects_unsafe_paths(payload: dict, path: str) -> None:
    payload["findings"][0]["file_path"] = path
    with pytest.raises(InvalidReviewOutput):
        parse_review_analysis(json.dumps(payload))


def test_preserves_case_spaces_and_unicode_in_paths(payload: dict) -> None:
    path = "src/日本語/My Users.py"
    payload["findings"][0]["file_path"] = path
    assert parse_review_analysis(json.dumps(payload)).findings[0].file_path == path


@pytest.mark.parametrize(
    "extra",
    [
        {"id": "model-chosen-id"},
        {"model": "model-chosen-name"},
        {"status": "completed"},
        {"pr_url": "https://evil.example"},
    ],
)
def test_model_cannot_supply_backend_review_metadata(payload: dict, extra: dict) -> None:
    payload.update(extra)
    with pytest.raises(InvalidReviewOutput):
        parse_review_analysis(json.dumps(payload))


def test_rejects_extra_finding_fields(payload: dict) -> None:
    payload["findings"][0]["action"] = "post_a_comment"
    with pytest.raises(InvalidReviewOutput):
        parse_review_analysis(json.dumps(payload))


@pytest.mark.parametrize("field", ["summary", "findings"])
def test_top_level_fields_are_required(payload: dict, field: str) -> None:
    del payload[field]
    with pytest.raises(InvalidReviewOutput):
        parse_review_analysis(json.dumps(payload))


@pytest.mark.parametrize("summary", ["", " \n\t", None, 42, "x" * 4001])
def test_rejects_invalid_summaries(payload: dict, summary: object) -> None:
    payload["summary"] = summary
    with pytest.raises(InvalidReviewOutput):
        parse_review_analysis(json.dumps(payload))


@pytest.mark.parametrize("findings", [None, {}, "not-a-list"])
def test_requires_a_list_of_findings(payload: dict, findings: object) -> None:
    payload["findings"] = findings
    with pytest.raises(InvalidReviewOutput):
        parse_review_analysis(json.dumps(payload))


@pytest.mark.parametrize("count", [50, 51])
def test_finding_count_limit(payload: dict, count: int) -> None:
    payload["findings"] *= count
    if count == 50:
        assert len(parse_review_analysis(json.dumps(payload)).findings) == count
    else:
        with pytest.raises(InvalidReviewOutput):
            parse_review_analysis(json.dumps(payload))


def test_text_and_line_limits_are_inclusive(payload: dict) -> None:
    payload["summary"] = "s" * 4000
    payload["findings"][0].update(
        title="t" * 200,
        explanation="e" * 4000,
        evidence="e" * 4000,
        suggestion="s" * 4000,
        line=2_147_483_647,
    )
    result = parse_review_analysis(json.dumps(payload))
    assert result.findings[0].line == 2_147_483_647


@pytest.mark.parametrize(
    "output",
    [
        "not JSON fake-review-secret",
        '{"summary":"fake-review-secret","findings":[]',
        '```json\n{"summary":"example","findings":[]}\n```',
        "null",
        "[]",
        "42",
        b"\xff",
        b"[" * 2000 + b"]" * 2000,
        {"summary": "fake-review-secret"},
    ],
)
def test_invalid_output_has_a_stable_safe_error(output: object) -> None:
    with pytest.raises(InvalidReviewOutput) as caught:
        parse_review_analysis(output)
    assert caught.value.code == "invalid_review_output"
    assert "fake-review-secret" not in str(caught.value)
    assert "fake-review-secret" not in repr(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("output", [b"x" * 1_048_577, "é" * 600_000])
def test_response_byte_limit_is_checked_before_parsing(
    output: str | bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = Mock(side_effect=AssertionError("Oversized output must not reach JSON parsing"))
    monkeypatch.setattr(ReviewAnalysis, "model_validate_json", parser)
    with pytest.raises(InvalidReviewOutput):
        parse_review_analysis(output)
    parser.assert_not_called()


def test_exact_response_byte_limit_is_allowed() -> None:
    raw = b'{"summary":"No supported findings.","findings":[]}'
    raw += b" " * (1_048_576 - len(raw))
    assert parse_review_analysis(raw).findings == []


def test_json_schema_can_be_used_for_structured_model_output() -> None:
    schema = ReviewAnalysis.model_json_schema()
    json.dumps(schema)  # Must contain only JSON-compatible values.
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"summary", "findings"}
    finding_schema = schema["$defs"]["ReviewFinding"]
    assert finding_schema["additionalProperties"] is False
    assert set(finding_schema["required"]) == set(ReviewFinding.model_fields)
    assert {"type": "null"} in finding_schema["properties"]["line"]["anyOf"]


def test_direct_validation_error_does_not_print_generated_text(payload: dict) -> None:
    payload["findings"][0]["severity"] = "fake-review-secret"
    with pytest.raises(ValidationError) as caught:
        ReviewAnalysis.model_validate(payload)
    assert "fake-review-secret" not in str(caught.value)
