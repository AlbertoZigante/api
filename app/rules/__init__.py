"""Business rules live here (joints, hardware selection, assembly sequencing).

RULES_VERSION must be bumped whenever a rule change can alter any response
(hardware choice, step order, nesting heuristics...). It is sent to the client
in the `X-Rules-Version` header and by `GET /v1/version`, so cached results
can be invalidated.
"""

RULES_VERSION = "0.4.0"
CONTRACT_VERSION = "1"  # bump on any breaking change of request/response schemas
