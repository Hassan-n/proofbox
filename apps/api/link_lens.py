import ipaddress
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel

from gateway import call_model

OFFICIAL_BRANDS = {
    "kingfisher bank": "kingfisherbank.co.za",
    "karoo bay metro": "karoobay.gov.za",
    "community benefits agency": "cba.gov.za",
}
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "short.test"}
SUSPICIOUS_TLDS = {".xyz", ".top", ".click", ".loan", ".work"}


class LinkVerdictSchema(BaseModel):
    verdict: Literal["dangerous", "suspicious", "no_issue_found", "could_not_check"]
    confidence: Literal["high", "medium", "low"]
    claimed_brand: str
    domain_matches_brand: bool
    reasons: list[str]
    page_tried_to: list[str]
    evidence: list[str]
    advice: str


def validate_inspection_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Enter an absolute HTTP or HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing embedded credentials are not accepted.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ValueError("Local network addresses are not accepted.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("Private or reserved IP addresses are not accepted.")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("URL contains an invalid port.") from error
    return url


def _matches_domain(host: str, official_domain: str) -> bool:
    return host == official_domain or host.endswith("." + official_domain)


def run_static_checks(initial_url: str, final_url: str, trace: dict) -> dict:
    findings = []
    parsed_initial = urlparse(initial_url)
    parsed_final = urlparse(final_url or initial_url)
    host = (parsed_final.hostname or "").lower().rstrip(".")

    try:
        ipaddress.ip_address(host)
        findings.append(f"URL uses a raw IP address ({host}) instead of a registered domain name.")
    except ValueError:
        pass

    if "xn--" in host:
        findings.append(f"Domain uses punycode ({host}), which can disguise look-alike characters.")

    redirects = trace.get("redirect_chain", [])
    initial_host = (parsed_initial.hostname or "").lower()
    if initial_host in SHORTENERS or len(redirects) >= 2:
        findings.append(f"URL redirected across {len(redirects)} hop(s) before landing on {host}.")

    if any(host.endswith(tld) for tld in SUSPICIOUS_TLDS):
        tld = next(tld for tld in SUSPICIOUS_TLDS if host.endswith(tld))
        findings.append(f"Domain uses high-risk top-level domain ({tld}).")

    inputs = trace.get("forms_and_inputs", [])
    sensitive = [
        field
        for field in inputs
        if field.get("type", "").lower() in {"password", "tel"}
        or any(
            token in " ".join(
                str(field.get(key, "")) for key in ("name", "placeholder", "id")
            ).lower()
            for token in ("pin", "otp", "password", "id_number", "cvv")
        )
    ]
    if sensitive:
        findings.append(
            f"Page asks for sensitive credentials ({len(sensitive)} password/OTP/ID field(s) detected)."
        )

    visible_text = (trace.get("visible_text") or "").lower()
    claimed_brand = "none"
    domain_matches = True
    for brand, official_domain in OFFICIAL_BRANDS.items():
        if brand in visible_text:
            claimed_brand = brand.title()
            if not _matches_domain(host, official_domain):
                domain_matches = False
                findings.append(
                    f"Page claims to be '{claimed_brand}', but actual domain '{host}' does not match official domain '{official_domain}'."
                )
            break

    return {
        "host": host,
        "claimed_brand": claimed_brand,
        "domain_matches_brand": domain_matches,
        "has_sensitive_inputs": bool(sensitive),
        "static_findings": findings,
    }


def evaluate_link(
    job_id: str, url: str, trace: dict, screenshot_b64: str, containment_events: list[str]
) -> dict:
    static = run_static_checks(url, trace.get("final_url", url), trace)
    visible_text = trace.get("visible_text") or ""

    if trace.get("load_error") and not visible_text and not containment_events:
        return {
            "verdict": "could_not_check",
            "confidence": "low",
            "claimed_brand": "Unknown",
            "domain_matches_brand": False,
            "reasons": ["The page could not be reached or automated inspection was blocked."],
            "page_tried_to": [],
            "evidence": [trace["load_error"]],
            "advice": "We could not verify this link. Do not enter personal details. Contact the organisation through its official website or a number on an official statement.",
            "what_this_does_not_mean": "This does not mean the link is safe or unsafe; it means it could not be checked.",
        }

    payload = {
        "initial_url": url,
        "final_url": trace.get("final_url"),
        "static_findings": static["static_findings"],
        "containment_events": containment_events,
        "forms_and_inputs": trace.get("forms_and_inputs", []),
        "downloads": trace.get("downloads", []),
        "visible_text_excerpt": visible_text[:1500],
    }
    system_prompt = (
        "You are Proofbox Link Lens Vision Verifier. Inspect the screenshot and sandbox trace. "
        "Never describe a link as safe. If no issues are found, use verdict no_issue_found. "
        "A claimed brand on the wrong domain together with password/OTP fields, or any "
        "network_blocked/download_quarantined event, requires verdict dangerous. Give plain-language "
        "advice directing users to the institution's official channel, never a phone number on the page."
    )
    verdict = call_model(
        role="vision_verifier",
        job_id=job_id,
        system_prompt=system_prompt,
        untrusted_data=str(payload),
        schema=LinkVerdictSchema,
        image_base64_webp=screenshot_b64 or None,
    )

    hard_danger = bool(containment_events) or (
        not static["domain_matches_brand"] and static["has_sensitive_inputs"]
    )
    if not isinstance(verdict, dict) or "error" in verdict:
        verdict = {
            "verdict": "dangerous" if hard_danger else (
                "suspicious" if static["static_findings"] else "no_issue_found"
            ),
            "confidence": "high" if hard_danger else "low",
            "claimed_brand": static["claimed_brand"],
            "domain_matches_brand": static["domain_matches_brand"],
            "reasons": static["static_findings"] + containment_events
            or ["No suspicious indicators were detected during inspection."],
            "page_tried_to": containment_events,
            "evidence": static["static_findings"],
            "advice": "Do not enter your password or PIN. Contact the organisation through its official website or the number on the back of your card.",
        }
    elif hard_danger:
        verdict["verdict"] = "dangerous"
        verdict["confidence"] = "high"
        verdict["claimed_brand"] = static["claimed_brand"]
        verdict["domain_matches_brand"] = static["domain_matches_brand"]
        verdict["advice"] = "Do not enter your password or PIN. Contact the organisation through its official website or the number on the back of your card."
        verdict["reasons"] = list(verdict.get("reasons", []))
        for finding in static["static_findings"] + containment_events:
            if finding not in verdict["reasons"]:
                verdict["reasons"].append(finding)
    elif static["static_findings"] and verdict["verdict"] == "no_issue_found":
        verdict["verdict"] = "suspicious"
        verdict["reasons"] = list(verdict.get("reasons", []))
        for finding in static["static_findings"]:
            if finding not in verdict["reasons"]:
                verdict["reasons"].append(finding)

    verdict["what_this_does_not_mean"] = (
        "No automated check can guarantee a site is completely safe. Always verify the web address before entering personal details."
    )
    if verdict["verdict"] == "no_issue_found":
        verdict["advice"] = verdict["advice"].replace(
            "safe", "free of obvious threats during this check"
        )
    return verdict