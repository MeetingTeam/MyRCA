def get_service_name(span):
    if 'service' in span:
        return span['service']
    return "unknown-service"

def calculate_lsi(samples):
    """
    samples: list các tuple (parent_dur, child_dur)
    """
    if len(samples) < 10: return 1.0 # Không đủ mẫu thì coi như không tương quan
    
    # Sắp xếp theo duration_ns của child
    samples.sort(key=lambda x: x[1])
    mid = len(samples) // 2
    p90_idx = int(len(samples) * 0.9)

    # 1. Lấy trung bình cha khi db_con bình thường (dưới median)
    normal_parent_avg = sum(s[0] for s in samples[:mid]) / mid
    
    # 2. Lấy trung bình cha khi db_con chậm (trên p90)
    slow_count = len(samples) - p90_idx
    slow_parent_avg = sum(s[0] for s in samples[p90_idx:]) / slow_count

    # 3. Calculate LSI
    lsi = slow_parent_avg / normal_parent_avg


    return lsi

def train_knowledge_base(df):
    """
    Learn the normal traces to define Sync/Async invocation relationships
    """
    df["service"] = df.apply(get_service_name, axis=1)
    span_dict = (
        df.drop_duplicates(subset="span_id", keep="first")
        .set_index("span_id")
        .to_dict(orient="index")
    )

    # Khởi tạo bộ đếm: (parent_service, child_service, op) -> {sync_votes, total}
    kb_samples = {}

    for span in span_dict.values():
        # Skip root span
        if span["parent_span_id"] is None or span["parent_span_id"] not in span_dict:
            continue

        parent_span = span_dict.get(span["parent_span_id"])
        # Skip for CLIENT-SERVER and PRODUCER-CONSUMER kind pairs
        if (parent_span["kind"]==3 and span["kind"]==2) or (parent_span["kind"]==4 and span["kind"]==5):
            continue   
        
        parent_key=f"{parent_span['service']}/{parent_span['operation']}"
        child_key=f"{span['service']}/{span['operation']}"
        pair_key=f"{parent_key}//{child_key}"
                
        if pair_key not in kb_samples:
            kb_samples[pair_key] = []
        kb_samples[pair_key].append((parent_span["duration_ns"], span["duration_ns"]))

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
    
    print(f"✅ Build knowledge successfully with {len(knowledge_base)} relationships")
    return knowledge_base