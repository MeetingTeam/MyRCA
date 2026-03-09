from collections import defaultdict

def count_abnormal_downstream_nodes(trace, abnormal_invocations, kb):
    """
    CORE LOGIC: Counts abnormal downstream nodes ONLY if the relationship is Synchronous.
    If Async, the failure chain is broken because the parent doesn't wait for the child.
    """
    adjacency = trace["adjacency"]
    nodes = trace["nodes"]
    abnormal_set = set(abnormal_invocations)
    downstream_count = {}

    def dfs(u_idx, visited):
        cnt = 0
        for v_idx in adjacency.get(u_idx, []):
            if v_idx in visited: continue
            visited.add(v_idx)
            
            # 1. Determine Relationship (Sync vs Async)
            parent = nodes[u_idx]
            child = nodes[v_idx]
            
            # Check by Span Kind first (Standard protocols)
            if parent["kind"]==3 and child["kind"]==2:
                is_sync = True
            elif parent["kind"]==4 and child["kind"]==5:
                is_sync = False
            else:
                # 2. Consult Knowledge Base for INTERNAL/DYNAMIC flows
                pair_key = f"{parent['service']}/{parent['operation']}//{child['service']}/{child['operation']}"
                is_sync = kb.get(pair_key, False)

            # Only propagate causal score if the child is abnormal AND relationship is SYNC
            if is_sync and v_idx in abnormal_set:
                cnt += 1
                cnt += dfs(v_idx, visited)
            # If ASYNC: Do nothing. The child's abnormality doesn't "cause" the parent's delay.
        return cnt

    for inv_id in abnormal_invocations:
        # We start DFS for each abnormal node to calculate its specific causal impact
        downstream_count[inv_id] = dfs(inv_id, {inv_id})

    return downstream_count

def convert_span_scores_to_services(trace, invocation_scores):
    """
    Aggregates scores from individual API calls (invocations) to the Service level.
    """
    score_sum = defaultdict(float)
    count = defaultdict(int)
    
    for inv_id, score in invocation_scores.items():
        service = trace["nodes"][inv_id]["service"]
        score_sum[service] += score
        count[service] += 1
    
    return {s: score_sum[s] / count[s] for s in score_sum}

def compute_causal_scores(traces, kb):
    """
    Calculates average causal scores for each service across all abnormal traces.
    """
    score_sum = defaultdict(float)
    appearance_in_abnormal = defaultdict(int)

    for trace in traces:
        if trace.get("label") != 1: continue 

        abnormal_span_ids = [sid for sid,n in trace["nodes"].items() if n["abnormal"]]
        if not abnormal_span_ids: continue

        downstream_count = count_abnormal_downstream_nodes(trace, abnormal_span_ids, kb)
        span_scores = {inv_id: 1.0 / (1 + 2*cnt) for inv_id, cnt in downstream_count.items()}
        
        # Now returns { "service_name": max_score }
        service_scores = convert_span_scores_to_services(trace, span_scores)

        for s, score in service_scores.items():
            score_sum[s] += score
            appearance_in_abnormal[s] += 1

    causal_scores = {s: score_sum[s] / appearance_in_abnormal[s] for s in score_sum}
    return causal_scores, appearance_in_abnormal

def compute_jaccard_scores(traces, appearance_in_abnormal):
    """
    Jaccard Index = (Service in Abnormal Traces) / (Total Abnormal Traces + Normal Traces with Service)
    Reduces noise from services that are abnormal but not part of the primary fault.
    """
    jaccard = {}
    for s, abnormal_count in appearance_in_abnormal.items():
        # Union set: All traces that are either abnormal OR contain the service
        total_relevant_traces = sum(
            1 for t in traces if (t["label"] == 1 or s in t.get("services", []))
        )
        jaccard[s] = abnormal_count / total_relevant_traces if total_relevant_traces > 0 else 0
    return jaccard

def rank_root_causes(traces, kb):
    """
    Main entry point for the RCA engine.
    Final Score = Causal Score * Jaccard Score.
    """
    causal_scores, appearance_in_abnormal = compute_causal_scores(traces, kb)
    jaccard_scores = compute_jaccard_scores(traces, appearance_in_abnormal)

    final_results = {}
    for s in causal_scores:
        final_results[s] = causal_scores[s] * jaccard_scores.get(s, 0)
        print(s, causal_scores[s], jaccard_scores[s])

    # Sort services by final score descending
    return sorted(final_results.items(), key=lambda x: x[1], reverse=True)