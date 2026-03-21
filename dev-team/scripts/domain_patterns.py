#!/usr/bin/env python3
"""
Domain Pattern Library — Dev Team Helper

Provides a built-in catalogue of common architectural and integration patterns
so agents don't have to re-research standard approaches from scratch.

Used by:
  - orchestrator.py — injects relevant patterns into task context
  - ba-agent / architect-agent — reference for requirement framing and design

Usage:
  from domain_patterns import get_relevant_patterns, get_pattern

  hints = get_relevant_patterns("add oauth login with google")
  # → ['OAuth 2.0 Authorization Code Flow', 'PKCE for public clients', ...]

  detail = get_pattern('oauth')
  # → full pattern dict with description, components, considerations
"""

from __future__ import annotations

# ─── Pattern Catalogue ─────────────────────────────────────────────────────────
#
# Each entry:
#   keywords   — terms that trigger this pattern (matched against task text)
#   name       — short display name
#   summary    — one-line description
#   components — key building blocks
#   tradeoffs  — pros/cons worth flagging
#   references — canonical sources or RFCs

PATTERNS: list[dict] = [

    # ── Authentication & Authorization ────────────────────────────────────────

    {
        'id': 'oauth2',
        'keywords': ['oauth', 'oauth2', 'google login', 'github login', 'sso',
                     'social login', 'authorize', 'access token'],
        'name': 'OAuth 2.0 Authorization Code Flow',
        'summary': 'Delegated authorization via authorization server; client receives short-lived access token.',
        'components': [
            'Authorization endpoint (redirect user to IdP)',
            'Token endpoint (exchange code for tokens)',
            'PKCE (Proof Key for Code Exchange) — required for public clients',
            'Refresh token rotation',
            'State parameter for CSRF protection',
        ],
        'tradeoffs': [
            '+ Industry standard; broad IdP support',
            '+ Keeps credentials off your server',
            '- Requires HTTPS everywhere',
            '- Refresh token storage needs care (httpOnly cookie recommended)',
        ],
        'references': ['RFC 6749', 'RFC 7636 (PKCE)', 'oauth.net/2/'],
    },

    {
        'id': 'jwt',
        'keywords': ['jwt', 'json web token', 'bearer token', 'stateless auth',
                     'token auth', 'api auth'],
        'name': 'JWT-based Stateless Authentication',
        'summary': 'Short-lived signed tokens carry identity claims; no server-side session store required.',
        'components': [
            'Access token (short TTL: 15–60 min)',
            'Refresh token (long TTL, stored server-side for rotation/revocation)',
            'Algorithm: RS256 or ES256 (asymmetric); avoid HS256 in distributed systems',
            'Token blacklist or jti claim for revocation',
        ],
        'tradeoffs': [
            '+ Stateless — scales horizontally without sticky sessions',
            '+ Self-contained claims reduce DB lookups',
            '- Cannot revoke without blacklist or short TTL',
            '- Algorithm confusion attacks (always validate alg header)',
        ],
        'references': ['RFC 7519', 'jwt.io'],
    },

    {
        'id': 'rbac',
        'keywords': ['role', 'permission', 'rbac', 'access control', 'authorization',
                     'admin', 'privilege'],
        'name': 'Role-Based Access Control (RBAC)',
        'summary': 'Users are assigned roles; roles carry permissions; checks happen at each resource boundary.',
        'components': [
            'User → Role assignment (many-to-many)',
            'Role → Permission assignment',
            'Permission check middleware / decorator',
            'Deny-by-default: require explicit grant',
        ],
        'tradeoffs': [
            '+ Simple mental model; easy to audit',
            '+ Scales to hundreds of roles',
            '- Coarse-grained; use ABAC when context matters (row-level security)',
        ],
        'references': ['NIST RBAC model', 'casbin.org'],
    },

    # ── Data & Persistence ────────────────────────────────────────────────────

    {
        'id': 'cqrs',
        'keywords': ['cqrs', 'command query', 'read model', 'write model',
                     'separate reads', 'event store'],
        'name': 'CQRS (Command Query Responsibility Segregation)',
        'summary': 'Separate models for reads and writes; commands mutate state, queries return projections.',
        'components': [
            'Command side: validates and applies business rules, emits events',
            'Query side: optimized read models (denormalized, cached)',
            'Event bus to sync command → query side',
            'Optional: Event Sourcing (store events, not current state)',
        ],
        'tradeoffs': [
            '+ Read and write sides can scale independently',
            '+ Query models can be optimized per use case',
            '- Eventual consistency between sides',
            '- Significant added complexity; justify before adopting',
        ],
        'references': ['martinfowler.com/bliki/CQRS.html'],
    },

    {
        'id': 'event_sourcing',
        'keywords': ['event sourcing', 'event store', 'replay', 'audit log',
                     'immutable events', 'aggregate'],
        'name': 'Event Sourcing',
        'summary': 'State is derived by replaying an immutable log of domain events rather than storing current state.',
        'components': [
            'Event store (append-only)',
            'Aggregate: applies events to rebuild state',
            'Snapshots: periodic state snapshots to speed up replay',
            'Projections: read models built from event stream',
        ],
        'tradeoffs': [
            '+ Complete audit trail; time-travel debugging',
            '+ Natural fit for CQRS',
            '- Schema migration of past events is hard',
            '- High operational complexity; use only when audit/replay is a real requirement',
        ],
        'references': ['eventstore.com', 'martinfowler.com/eaaDev/EventSourcing.html'],
    },

    {
        'id': 'repository',
        'keywords': ['repository', 'data access', 'orm', 'persistence layer',
                     'database abstraction'],
        'name': 'Repository Pattern',
        'summary': 'Abstracts persistence behind an interface; domain logic never touches raw SQL or ORM directly.',
        'components': [
            'Repository interface (domain layer)',
            'Concrete implementation (infrastructure layer)',
            'Unit of Work for transaction boundary',
        ],
        'tradeoffs': [
            '+ Swap implementations (DB, in-memory for tests)',
            '+ Keeps domain logic pure',
            '- Can become a leaky abstraction with complex queries',
        ],
        'references': ['Patterns of Enterprise Application Architecture — Fowler'],
    },

    # ── Messaging & Async ─────────────────────────────────────────────────────

    {
        'id': 'event_driven',
        'keywords': ['event driven', 'pub sub', 'message queue', 'kafka', 'rabbitmq',
                     'sqs', 'async', 'webhook', 'event bus'],
        'name': 'Event-Driven Architecture',
        'summary': 'Services communicate by publishing and subscribing to events; producers and consumers are decoupled.',
        'components': [
            'Event broker (Kafka, RabbitMQ, SQS, Redis Streams)',
            'Event schema / contract (Avro, Protobuf, JSON Schema)',
            'Dead letter queue for failed processing',
            'Idempotency key on consumers to handle redelivery',
            'Outbox pattern to avoid dual-write (DB + broker)',
        ],
        'tradeoffs': [
            '+ Services decoupled in time and space',
            '+ Natural fit for fan-out (one event, many consumers)',
            '- Eventual consistency; harder to debug distributed flows',
            '- Requires observability (correlation IDs, distributed tracing)',
        ],
        'references': ['confluent.io/learn/event-driven-architecture'],
    },

    {
        'id': 'saga',
        'keywords': ['saga', 'distributed transaction', 'compensating transaction',
                     'long running', 'multi-service transaction'],
        'name': 'Saga Pattern (Distributed Transactions)',
        'summary': 'Long-running business transactions are broken into local transactions with compensating rollbacks.',
        'components': [
            'Choreography: services react to events (no central coordinator)',
            'Orchestration: central saga orchestrator drives the steps',
            'Compensating transactions for each step',
            'Idempotent step handlers',
        ],
        'tradeoffs': [
            '+ No distributed locking; works across services',
            '+ Choreography is simple for short flows',
            '- Rollback semantics are complex and app-specific',
            '- Orchestration adds a new service to maintain',
        ],
        'references': ['microservices.io/patterns/data/saga.html'],
    },

    # ── Microservices & APIs ──────────────────────────────────────────────────

    {
        'id': 'api_gateway',
        'keywords': ['api gateway', 'gateway', 'reverse proxy', 'rate limit',
                     'bff', 'backend for frontend'],
        'name': 'API Gateway / Backend for Frontend (BFF)',
        'summary': 'Single entry point for clients; handles auth, rate limiting, routing, and response aggregation.',
        'components': [
            'Auth validation (JWT / API key) at the gateway',
            'Rate limiting per client / endpoint',
            'Request routing to upstream services',
            'Response aggregation (BFF variant)',
            'Circuit breaker for upstream failures',
        ],
        'tradeoffs': [
            '+ Centralizes cross-cutting concerns',
            '+ Shields internal topology from clients',
            '- Single point of failure if not HA',
            '- BFF proliferation if overused',
        ],
        'references': ['microservices.io/patterns/apigateway.html'],
    },

    {
        'id': 'circuit_breaker',
        'keywords': ['circuit breaker', 'resilience', 'fallback', 'retry',
                     'timeout', 'bulkhead', 'hystrix', 'resilience4j'],
        'name': 'Circuit Breaker + Retry with Backoff',
        'summary': 'Prevents cascading failures by stopping calls to a failing service and providing a fallback.',
        'components': [
            'Circuit states: Closed → Open → Half-Open',
            'Failure threshold to trip the circuit',
            'Exponential backoff with jitter for retries',
            'Bulkhead: isolate thread pools per dependency',
            'Timeout on every outbound call',
        ],
        'tradeoffs': [
            '+ Prevents thread exhaustion under partial failures',
            '+ Forces explicit fallback design',
            '- Adds latency when half-open probing',
            '- Threshold tuning requires production data',
        ],
        'references': ['martinfowler.com/bliki/CircuitBreaker.html'],
    },

    # ── Caching ───────────────────────────────────────────────────────────────

    {
        'id': 'caching',
        'keywords': ['cache', 'caching', 'redis', 'memcached', 'cdn',
                     'cache invalidation', 'ttl'],
        'name': 'Caching Strategies',
        'summary': 'Reduce latency and DB load by storing computed results closer to the consumer.',
        'components': [
            'Cache-aside (lazy loading): app checks cache, then DB on miss',
            'Write-through: write to cache and DB on every write',
            'Write-behind: write to cache; flush to DB asynchronously',
            'TTL-based expiry + explicit invalidation on write',
            'Cache stampede protection: probabilistic early expiry or locks',
        ],
        'tradeoffs': [
            '+ Massive latency reduction for read-heavy workloads',
            '+ Reduces DB connection pressure',
            '- Cache invalidation is hard; stale reads are a risk',
            '- Write-behind risks data loss on crash',
        ],
        'references': ['AWS ElastiCache caching strategies', 'redis.io/docs/manual/patterns/'],
    },

    # ── Infrastructure ────────────────────────────────────────────────────────

    {
        'id': 'twelve_factor',
        'keywords': ['twelve factor', '12 factor', 'config env', 'environment variable',
                     'heroku', 'cloud native', 'stateless app'],
        'name': 'Twelve-Factor App',
        'summary': 'Methodology for building portable, scalable, maintainable SaaS applications.',
        'components': [
            'Config in environment variables (not code)',
            'Stateless processes; no local state between requests',
            'Backing services (DB, cache, queue) as attached resources',
            'Logs as event streams (stdout, not files)',
            'Dev/prod parity — same services in all environments',
        ],
        'tradeoffs': [
            '+ Makes apps trivially deployable to any cloud platform',
            '+ Forces clean separation of code and config',
            '- Some constraints (e.g. no local disk) require rethinking file handling',
        ],
        'references': ['12factor.net'],
    },

    {
        'id': 'outbox',
        'keywords': ['outbox', 'dual write', 'transactional outbox',
                     'event consistency', 'at least once'],
        'name': 'Transactional Outbox Pattern',
        'summary': 'Write events to an outbox table in the same DB transaction as the state change; a relay publishes them.',
        'components': [
            'Outbox table in the same database as the domain entity',
            'Transaction: update entity + insert outbox row atomically',
            'Relay/poller: reads outbox and publishes to message broker',
            'Idempotency key prevents duplicate processing',
        ],
        'tradeoffs': [
            '+ Guarantees at-least-once delivery without distributed transactions',
            '+ No dual-write inconsistency',
            '- Adds a poller/relay component',
            '- Outbox table can grow if relay falls behind',
        ],
        'references': ['microservices.io/patterns/data/transactional-outbox.html'],
    },
]

# ─── Public API ────────────────────────────────────────────────────────────────

def get_relevant_patterns(task_text: str, max_results: int = 4) -> list[str]:
    """
    Return a list of short pattern hints relevant to the task description.
    Used by orchestrator to enrich task context without overwhelming the prompt.
    """
    task_lower = task_text.lower()
    matched: list[tuple[int, dict]] = []

    for pattern in PATTERNS:
        score = sum(1 for kw in pattern['keywords'] if kw in task_lower)
        if score > 0:
            matched.append((score, pattern))

    matched.sort(key=lambda x: -x[0])
    hints = []
    for _, p in matched[:max_results]:
        hint = f"{p['name']}: {p['summary']}"
        if p.get('components'):
            hint += f" Key components: {'; '.join(p['components'][:3])}."
        hints.append(hint)

    return hints


def get_pattern(pattern_id: str) -> dict | None:
    """Return the full pattern dict by ID, or None if not found."""
    for p in PATTERNS:
        if p['id'] == pattern_id:
            return p
    return None


def list_patterns() -> list[dict]:
    """Return all patterns (id + name + summary only)."""
    return [{'id': p['id'], 'name': p['name'], 'summary': p['summary']} for p in PATTERNS]


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse, sys

    parser = argparse.ArgumentParser(description='Domain Pattern Library')
    sub = parser.add_subparsers(dest='cmd')

    sub.add_parser('list', help='List all patterns')

    p = sub.add_parser('get', help='Show a specific pattern by ID')
    p.add_argument('id', help='Pattern ID (e.g. oauth2, cqrs, event_driven)')

    p = sub.add_parser('match', help='Find patterns relevant to a task description')
    p.add_argument('task', help='Task description text')

    args = parser.parse_args()

    if args.cmd == 'list':
        for p in list_patterns():
            print(f"  {p['id']:<20} {p['name']}")
            print(f"  {'':20} {p['summary']}")
            print()

    elif args.cmd == 'get':
        pattern = get_pattern(args.id)
        if not pattern:
            print(f"Pattern '{args.id}' not found. Run `list` to see available patterns.")
            sys.exit(1)
        print(f"\n{pattern['name']}")
        print(f"{'─' * 60}")
        print(f"Summary: {pattern['summary']}\n")
        print("Components:")
        for c in pattern['components']:
            print(f"  • {c}")
        print("\nTradeoffs:")
        for t in pattern['tradeoffs']:
            print(f"  {t}")
        if pattern.get('references'):
            print("\nReferences:")
            for r in pattern['references']:
                print(f"  - {r}")
        print()

    elif args.cmd == 'match':
        hints = get_relevant_patterns(args.task, max_results=6)
        if not hints:
            print("No matching patterns found.")
        else:
            print(f"\nRelevant patterns for: \"{args.task}\"\n")
            for h in hints:
                print(f"  • {h}\n")

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
