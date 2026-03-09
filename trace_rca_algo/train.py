import json
import pandas as pd
from train import get_service_name

def calculate_lsi(samples):
    """
    samples: list các tuple (parent_dur, child_dur)
    """
    if len(samples) < 10: return 1.0 # Không đủ mẫu thì coi như không tương quan
    
    # Sắp xếp theo duration của child
    samples.sort(key=lambda x: x[1])
    mid = len(samples) // 2
    p90_idx = int(len(samples) * 0.9)

    # 1. Lấy trung bình cha khi con bình thường (dưới median)
    normal_parent_avg = sum(s[0] for s in samples[:mid]) / mid
    
    # 2. Lấy trung bình cha khi con chậm (trên p90)
    slow_count = len(samples) - p90_idx
    slow_parent_avg = sum(s[0] for s in samples[p90_idx:]) / slow_count

    # 3. Calculate LSI
    lsi = slow_parent_avg / normal_parent_avg


    return lsi

def train_knowledge_base(data_set_path, output_file="knowledge_base.json"):
    """
    Learn the normal traces to define Sync/Async invocation relationships
    """
    df = pd.read_csv(data_set_path, keep_default_na=False, na_values=[])
    df["service"] = df.apply(get_service_name, axis=1)
    span_dict = (
        df.set_index("spanId").to_dict(orient="index")
    )

    # Khởi tạo bộ đếm: (parent_service, child_service, op) -> {sync_votes, total}
    kb_samples = {}

    for span in span_dict.values():
        # Skip root span
        if span["parentSpanId"] is None or span["parentSpanId"] not in span_dict:
            continue

        parent_span = span_dict.get(span["parentSpanId"])
        # Skip for CLIENT-SERVER and PRODUCER-CONSUMER kind pairs
        if (parent_span["kind"]==3 and span["kind"]==2) or (parent_span["kind"]==4 and span["kind"]==5):
            continue   
        
        parent_key=f"{parent_span['service']}/{parent_span['operation']}"
        child_key=f"{span['service']}/{span['operation']}"
        pair_key=f"{parent_key}//{child_key}"
                
        if pair_key not in kb_samples:
            kb_samples[pair_key] = []
        kb_samples[pair_key].append((parent_span["duration"], span["duration"]))

    # Convert to Knowledge Base
    knowledge_base = {}
    for pair, samples in kb_samples.items():
        lsi_score = calculate_lsi(samples)
        
        # Calculate the ratio of samples that have parent_dur >= child_dur.
        valid_sync_samples = sum(1 for p_dur, c_dur in samples if p_dur >= c_dur)
        validity_ratio = valid_sync_samples / len(samples)
        
        if lsi_score > 1.0 and validity_ratio > 0.95:
            is_sync=True
        else:
            is_sync=False

        knowledge_base[pair] = is_sync

    # Lưu ra file JSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(knowledge_base, f, indent=4)
    
    print(f"✅ Build knowledge successfully with {len(knowledge_base)} relationships. Save at {output_file}")
    return knowledge_base