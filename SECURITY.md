# Security Policy

## Supported versions

Lynx is pre-1.0. We provide security fixes for the **latest minor release only**. From v1.0 onwards, we will support the latest two minor releases.

## Reporting a vulnerability

**Please do not file public GitHub issues for security vulnerabilities.**

Use **[GitHub Security Advisories](https://github.com/hadihonarvar/lynx/security/advisories/new)** to file a private vulnerability report. This is the preferred channel — it gives us a private workspace to triage the issue and coordinate disclosure.

If you cannot use GitHub for the report, open a regular issue **titled only "Security contact request"** (no details) and a maintainer will reach out with a private channel within 48 hours.

Include:

1. A description of the issue
2. Steps to reproduce
3. The version / commit hash you tested against
4. Any potential mitigations you've identified
5. Whether you'd like public credit when the fix ships

## What to expect

- **First reply within 48 hours** confirming we received the report.
- **Severity triage within 7 days.** We use a four-tier system: Critical, High, Medium, Low.
- **Fix targeted within 30 days** for Critical/High; 90 days for Medium/Low.
- **Coordinated disclosure** — we'll work with you on a public disclosure date once the fix is shipped, with a minimum 14-day window after release to let users upgrade.

## Scope

In scope:

- Memory-safety / sandbox-escape bugs in the kernel
- Audit-log tampering paths
- Policy-bypass: any input that causes the PDP to return ALLOW when policy intended otherwise
- Approval-token forgery
- Credential leaks in logs, traces, or audit events
- Regex-DoS / parser-DoS in the policy compiler
- Dependency chain attacks (typosquatting, supply-chain)

Out of scope:

- Vulnerabilities in third-party tools you wrap with `@tool` (those are your dependency's problem)
- Misconfigured policies that allow dangerous actions (this is the operator's responsibility)
- Issues in the optional adapters (`lynx/adapters/*`) that depend on bugs in the wrapped SDK
- Findings against EOL versions

## Threat model

The full threat model lives in [`docs/threat-model.md`](docs/threat-model.md). It enumerates the trust boundaries Lynx defends and the ones it does not.
