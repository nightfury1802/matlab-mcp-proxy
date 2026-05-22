# Proxy v2 Benchmark Results
Generated: 2026-05-22 09:12 UTC
Branch: proxy-improvements-v2

## Raw Metrics
```json
{
  "routing_WHOS_classify_ms": 0.001,
  "routing_WHOS_route_ms": 0.009,
  "routing_WHOS_reduction_pct": 64.9,
  "routing_ERROR_classify_ms": 0.0035,
  "routing_ERROR_route_ms": 0.0122,
  "routing_ERROR_reduction_pct": 45.3,
  "routing_WARNING x5_classify_ms": 0.0055,
  "routing_WARNING x5_route_ms": 0.0546,
  "routing_WARNING x5_reduction_pct": 79.0,
  "routing_SIM_RESULT_classify_ms": 0.0152,
  "routing_SIM_RESULT_route_ms": 0.0137,
  "routing_SIM_RESULT_reduction_pct": 0.0,
  "routing_DOE (15pt)_classify_ms": 0.0308,
  "routing_DOE (15pt)_route_ms": 0.0871,
  "routing_DOE (15pt)_reduction_pct": 0.0,
  "routing_BUILD_classify_ms": 0.0069,
  "routing_BUILD_route_ms": 0.0121,
  "routing_BUILD_reduction_pct": 73.6,
  "oracle_query_Derivative not finite_ms": 7.44,
  "oracle_query_Derivative not finite_score": 0.9249738454818726,
  "oracle_query_Algebraic loop_ms": 6.7,
  "oracle_query_Algebraic loop_score": 0,
  "oracle_query_Init var failed_ms": 6.43,
  "oracle_query_Init var failed_score": 0,
  "oracle_query_Step size too small_ms": 5.62,
  "oracle_query_Step size too small_score": 0.8673099279403687,
  "oracle_query_No match (Python error)_ms": 7.17,
  "oracle_query_No match (Python error)_score": 0,
  "oracle_size": 8,
  "handle_store_ms": 0.5939,
  "handle_expand_ms": 0.0206,
  "handle_reduction_pct": 51.4,
  "handle_input_chars": 177,
  "handle_output_chars": 86,
  "e2e_WHOS_active_ms": 0.018,
  "e2e_WHOS_bypass_ms": 0.0001,
  "e2e_WHOS_overhead_ms": 0.0179,
  "e2e_ERROR_active_ms": 16.7192,
  "e2e_ERROR_bypass_ms": 0.0001,
  "e2e_ERROR_overhead_ms": 16.7191,
  "e2e_WARNING_active_ms": 6.3925,
  "e2e_WARNING_bypass_ms": 0.0001,
  "e2e_WARNING_overhead_ms": 6.3924,
  "e2e_DOE_active_ms": 0.0887,
  "e2e_DOE_bypass_ms": 0.0001,
  "e2e_DOE_overhead_ms": 0.0886,
  "e2e_BUILD_active_ms": 0.0102,
  "e2e_BUILD_bypass_ms": 0.0001,
  "e2e_BUILD_overhead_ms": 0.0101
}
```

## Summary
- Oracle KB size: 8 entries
- Handle token reduction: 51.4%
- Handle creation latency: 0.5939ms
- Oracle warm query latency: 7.44ms
- Best routing reduction: 79.0% (WARNING x5)
