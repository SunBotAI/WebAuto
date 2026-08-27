"""Evidence-based PageState verifier."""

from __future__ import annotations

from webauto.domain import PageState, VerificationResult, VerificationStatus, VerifierSpec


class StateVerifier:
    async def verify(self, spec: VerifierSpec, state: PageState) -> VerificationResult:
        expectation = spec.expectation
        checks: list[tuple[str, bool]] = []
        if "url_contains" in expectation:
            value = str(expectation["url_contains"])
            checks.append((f"url contains {value}", value in state.url))
        if "dom_contains" in expectation:
            value = str(expectation["dom_contains"])
            checks.append((f"DOM contains {value}", value in (state.dom_snapshot or "")))
        if "title_contains" in expectation:
            value = str(expectation["title_contains"])
            checks.append((f"title contains {value}", value in state.title))
        if "form_equals" in expectation:
            expected = dict(expectation["form_equals"])
            checks.append(
                (
                    "form values match",
                    all(state.form_values.get(k) == v for k, v in expected.items()),
                )
            )
        if expectation.get("dom_nonempty"):
            checks.append(("DOM is non-empty", bool((state.dom_snapshot or "").strip())))
        evidence = [state.screenshot_artifact_id] if state.screenshot_artifact_id else []
        if not checks:
            return VerificationResult(
                status=VerificationStatus.AMBIGUOUS,
                summary="verifier has no supported assertion",
                evidence_ids=evidence,
            )
        passed = all(value for _, value in checks)
        failed = [name for name, value in checks if not value]
        return VerificationResult(
            status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            summary="all assertions passed" if passed else "failed: " + ", ".join(failed),
            evidence_ids=evidence,
            observed={"url": state.url, "title": state.title},
        )
