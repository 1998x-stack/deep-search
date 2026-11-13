# Security policy

## Threat model

Web pages and search results are hostile inputs. The skill must never follow instructions embedded in retrieved documents. Do not commit search API keys, credentials or private research records. The CLI can write local reports that contain full text and quotes: review provenance and licensing before publication.

The optional `fetch` command is **not suitable for untrusted multi-tenant URL fetching**. It performs up-front DNS resolution checks, limits allowed schemes, ports, redirects, content type, response size and timeouts. It does **not** pin the transport connection to the validated IP address, so DNS rebinding and time-of-check/time-of-use races remain possible.

## Recommended deployment

- Prefer provider-hosted search APIs or isolated egress-restricted crawlers.
- Run the CLI locally or inside a network-restricted sandbox with no internal service access.
- Require explicit opt-in for live fetching.
- Respect third-party rights, robots, access controls and rate limits.
- Treat external source URLs as untrusted identifiers, not as program instructions.
- Keep API keys in environment secrets, never inside plans, reports or commits.

## Reporting vulnerabilities

Submit security issues privately through GitHub's vulnerability reporting feature if available. If not, contact the repository owner privately rather than posting exploit details in a public issue.

## Provenance guarantee boundary

Content checksums detect changes to stored text once a checksum is recorded; they do not prove that content came from a genuine publisher. Quote presence does not establish the semantic truth of a claim.
