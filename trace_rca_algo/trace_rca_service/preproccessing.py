import pandas as pd
from utils import get_service_name, get_operation_name

def handle_df_row(row, traces):
    tid = row["trace_id"]
    sid = row["span_id"]
    pid = row.get("parent_span_id")

    if tid not in traces:
        traces[tid] = {
            "trace_id": tid,
            "label": 0,
            "services": set(),
            "nodes": {}, 
            "edges": []  # Stores (parent_sid, child_sid)
        }

    is_abnormal = bool(row["is_anomaly"])
    service = get_service_name(row)
    
    trace = traces[tid]
    trace["services"].add(service)

    node = {
        "sid": sid,
        "service": service,
        "operation": get_operation_name(row),
        "abnormal": is_abnormal,
        "kind": row.get("kind") 
    }
    
    trace["nodes"][sid] = node
    trace["label"] = max(trace["label"], int(is_abnormal))
    
    # Chỉ add vào edges nếu có parent hợp lệ
    if pd.notna(pid) and pid != "" and pid != 0:
        trace["edges"].append((pid, sid))

def finalize_trace(trace):
    """
    Chuyển đổi edges thành adjacency list (danh sách kề).
    Mỗi node lưu danh sách các span con của nó.
    """
    if len(trace["nodes"]) <= 1:
        return None

    nodes_dict = trace["nodes"]
    # Khởi tạo adjacency list trống cho tất cả các node hiện có
    adjacency = {sid: [] for sid in nodes_dict.keys()}
    
    for p_sid, c_sid in trace["edges"]:
        # 1. Cập nhật adjacency list (quan hệ xuôi: parent -> children)
        if p_sid in adjacency:
            adjacency[p_sid].append(c_sid)
        
        # 2. Giữ logic parent_service để phục vụ RCA nếu cần
        if p_sid in nodes_dict and c_sid in nodes_dict:
            nodes_dict[c_sid]["parent_service"] = nodes_dict[p_sid]["service"]

    # Đảm bảo các node gốc có parent_service là None
    for node in nodes_dict.values():
        if "parent_service" not in node:
            node["parent_service"] = None
    
    return {
        "trace_id": trace["trace_id"],
        "label": trace["label"],
        "services": list(trace["services"]),
        "nodes": nodes_dict,
        "adjacency": adjacency
    }

def build_trace_dags_from_csv(df):
    traces_dict={}

    # Bước 1: Gom nhóm và xây dựng node/edge
    for _, row in df.iterrows():
        handle_df_row(row, traces_dict)

    # Bước 2: Finalize (Chuyển dict tạm thời thành DAG chuẩn)
    final_output = [res for t in traces_dict.values() if (res := finalize_trace(t)) is not None]

    return final_output