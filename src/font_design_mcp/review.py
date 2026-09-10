"""Immutable agent attestations and explicit release requirements; never human approval."""

import json

from .domain import require
from .quality import expects_ink


def owned_report(store, uri, project_id, revision):
    require(
        uri.startswith(f"font-design://{project_id}/{revision}/"),
        "stale_evidence",
        "Evidence must belong to this project and exact revision; render and review again",
    )
    raw, mime = store.read_resource(uri)
    require(
        mime == "application/json", "invalid_evidence", "Use the proof/review report_uri, not an image URI"
    )
    return json.loads(raw)


def proof_scope(store, uri, project_id, revision, manifest, allow_incomplete=False):
    proof = owned_report(store, uri, project_id, revision)
    require(
        proof.get("mime_type") == "image/png" and "parameters" in proof,
        "invalid_evidence",
        "Evidence must be a persisted render, not an analysis or build report",
    )
    image_uri = (
        f"font-design://{project_id}/{revision}/{proof['artifact_id']}/image.png?sha256={proof['sha256']}"
    )
    store.read_resource(image_uri)
    parameters = proof["parameters"]
    require(
        allow_incomplete or (not proof.get("warnings") and not proof.get("missing_glyphs")),
        "incomplete_proof",
        "A proof with missing glyphs or rendering warnings cannot support release",
    )
    glyphs, location, master_id = [], None, parameters.get("master_id", "default")
    if "text" in parameters:
        defaults = {a["tag"]: a["default"] for a in manifest.get("variation", {}).get("axes", [])}
        location = {**defaults, **parameters.get("location", {})}
        masters = manifest.get("variation", {}).get("masters", [{"id": "default", "location": {}}])
        master_id = next((m["id"] for m in masters if m["location"] == location), None)
        kind = "text"
    elif "glyph_ids" in parameters:
        glyphs = [g["glyph_id"] for g in proof["glyphs"]]
        kind = "glyphs"
    else:
        require("glyph_id" in parameters and "metrics" in proof, "invalid_evidence", "Unknown proof kind")
        glyphs, kind = [parameters["glyph_id"]], "glyphs"
    return {
        "proof_uri": uri,
        "image_uri": image_uri,
        "master_id": master_id,
        "kind": kind,
        "glyphs": glyphs,
        "location": location,
        "sizes": parameters.get("sizes", []),
        "kern": parameters.get("kern"),
        "reference_id": parameters.get("reference_id"),
        "binary_sha256": proof.get("build", {}).get("files", {}).get("ttf", {}).get("sha256"),
    }


def record_review(store, project_id, revision, manifest, request):
    require(
        len(set(request.proof_uris)) == len(request.proof_uris), "invalid_input", "Proof URIs must be unique"
    )
    scopes = [
        proof_scope(store, uri, project_id, revision, manifest, request.verdict == "revise")
        for uri in request.proof_uris
    ]
    report = {
        "kind": "proof_review",
        "reviewer": "agent",
        "artistic_approval": False,
        "verdict": request.verdict,
        "observation": request.observation,
        "proofs": scopes,
        "resolutions": [r.model_dump() for r in request.resolutions],
        "limitations": [
            "Records the caller's visual assessment; cannot prove the client displayed or understood the image.",
            "Valid only for this exact revision and the listed proofs; never human approval.",
        ],
    }
    return {**report, "report_uri": store.save_report(project_id, revision, report)}


def release_check(
    store, project_id, revision, manifest, fonts, spec, reports, review_uris, binary_sha256=None
):
    """Evaluate requirements without mutating sources or silently waiving review candidates."""
    reviewed = {mid: set() for mid in fonts}
    usage = {mid: {True: set(), False: set()} for mid in fonts}
    reference_ids, locations, resolutions = set(), [], {}
    reasons = []
    for uri in dict.fromkeys(review_uris):
        review = owned_report(store, uri, project_id, revision)
        require(
            review.get("kind") == "proof_review" and review.get("reviewer") == "agent",
            "invalid_evidence",
            "Use a report returned by proof_review",
        )
        if review["verdict"] != "accept":
            reasons.append({"kind": "revision_requested", "review_uri": uri})
            continue
        coverage = {mid: set() for mid in fonts}
        for cached in review["proofs"]:
            evidence = proof_scope(store, cached["proof_uri"], project_id, revision, manifest)
            if evidence["kind"] == "text" and evidence["binary_sha256"] != binary_sha256:
                reasons.append(
                    {
                        "kind": "proof_binary_mismatch",
                        "proof_uri": evidence["proof_uri"],
                        "message": "Text proof uses a different compiler output; render and review again",
                    }
                )
                continue
            mid = evidence["master_id"]
            if mid in fonts:
                reviewed[mid].update(evidence["glyphs"])
                coverage[mid].update(evidence["glyphs"])
                if evidence["kind"] == "text":
                    usage[mid][evidence["kern"]].update(evidence["sizes"])
                if mid == "default" and evidence["reference_id"]:
                    reference_ids.add(evidence["reference_id"])
            if evidence["location"] is not None:
                locations.append(evidence["location"])
        for resolution in review["resolutions"]:
            # A waiver can only address a finding on glyphs actually shown by this review.
            resolutions.setdefault(resolution["finding_id"], []).append((coverage, resolution["reason"]))
    if not spec.required_characters:
        reasons.append({"kind": "design_contract_missing", "message": "Declare the required repertoire"})
    if not spec.reference_glyphs:
        reasons.append(
            {
                "kind": "structural_glyphs_missing",
                "message": "Declare and measure structural reference glyphs",
            }
        )
    masters = {}
    known_findings = set()
    for mid, font in fonts.items():
        report = reports[mid]
        required = {
            g.name
            for g in font
            if g.name != ".notdef"
            and (g.contours or g.components or any(expects_ink(cp) for cp in g.unicodes))
        }
        unreviewed = sorted(required - reviewed[mid])
        shape_missing = report["design_coverage"]["unprobed_structural_glyphs"]
        unresolved = []
        for finding in report["review_candidates"]:
            identifier = finding["finding_id"]
            known_findings.add(identifier)
            involved = set(finding.get("glyphs", [finding.get("glyph")]))
            if not any(involved <= covered[mid] for covered, _ in resolutions.get(identifier, [])):
                unresolved.append(identifier)
        if report["review_candidates_truncated"]:
            reasons.append(
                {
                    "kind": "review_details_truncated",
                    "master_id": mid,
                    "message": "Repair findings and rerun; undisplayed findings cannot be waived",
                }
            )
        if not report["checks_passed"]:
            reasons.append(
                {"kind": "design_checks_failed", "master_id": mid, "count": report["counts"]["issues"]}
            )
        if unreviewed:
            reasons.append({"kind": "glyph_reviews_missing", "master_id": mid, "count": len(unreviewed)})
        if shape_missing:
            reasons.append(
                {"kind": "structural_measurements_missing", "master_id": mid, "glyphs": shape_missing}
            )
        if unresolved:
            reasons.append({"kind": "unresolved_findings", "master_id": mid, "count": len(unresolved)})
        for kern, sizes in usage[mid].items():
            if not sizes or min(sizes) > 32 or max(sizes) < 48:
                reasons.append(
                    {
                        "kind": "usage_proofs_missing",
                        "master_id": mid,
                        "kern": kern,
                        "message": "Review shaped text at <=32 px and >=48 px, with and without kerning",
                    }
                )
        masters[mid] = {
            "counts": report["counts"],
            "checks_passed": report["checks_passed"],
            "outline_integrity_passed": report["outline_integrity_passed"],
            "unreviewed_glyphs": unreviewed,
            "unprobed_structural_glyphs": shape_missing,
            "unresolved_findings": unresolved,
            "usage_sizes": {str(k): sorted(v) for k, v in usage[mid].items()},
        }
    unknown = sorted(set(resolutions) - known_findings)
    if unknown:
        reasons.append(
            {
                "kind": "unknown_finding_resolutions",
                "finding_ids": unknown,
                "message": "Use finding IDs from the current analysis and master",
            }
        )
    for reference in manifest.get("design", {}).get("references", []):
        if reference["id"] not in reference_ids:
            reasons.append({"kind": "reference_comparison_missing", "reference_id": reference["id"]})
    for axis in manifest.get("variation", {}).get("axes", []):
        if not any(
            axis["minimum"] < loc.get(axis["tag"], axis["default"]) < axis["maximum"] for loc in locations
        ):
            reasons.append({"kind": "intermediate_axis_review_missing", "axis_tag": axis["tag"]})
    return {
        "kind": "release_readiness",
        "ready": not reasons,
        "artistic_approval": False,
        "review_basis": "Agent attestations on immutable proofs and explicit design checks",
        "compiled_ttf_sha256": binary_sha256,
        "reasons": reasons,
        "masters": masters,
        "review_uris": list(dict.fromkeys(review_uris)),
        "limitations": [
            "Passing this contract is not a guarantee of aesthetic perfection or human approval.",
            "Visual judgments are caller attestations; arbitrary Unicode identity is not recognized automatically.",
            "Only recorded sizes, locations and references are reviewed; no continuous-axis or cross-platform certification.",
        ],
    }
