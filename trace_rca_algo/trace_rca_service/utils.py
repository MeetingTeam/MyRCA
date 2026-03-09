def get_service_name(span_row):
    if "raw_service" in span_row:
        return span_row["raw_service"]
    else:
        return span_row["service"]
        
def get_operation_name(span_row):
    if "raw_operation" in span_row:
        return span_row["raw_operation"]
    else:
        return span_row["operation"]