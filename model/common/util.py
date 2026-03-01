import re

def map_status_group(code):
    code = int(code)
    if code == 0:
        return 0
    return code // 100

# Normalise operation string
UUID_RE = re.compile(
    r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{12}\b'
)
HEX_ID_RE = re.compile(r'\b[0-9a-fA-F]{8,}\b')
NUM_ID_RE = re.compile(r'/(?<![a-zA-Z])[0-9]{2,}')
ALPHA_NUM_ID_RE = re.compile(r'/[a-zA-Z]+-[0-9]+')

def normalize_operation(op: str) -> str:
    op = op.strip()
    op = UUID_RE.sub('{uuid}', op)
    op = ALPHA_NUM_ID_RE.sub('/{id}', op)
    op = HEX_ID_RE.sub('{id}', op)
    op = NUM_ID_RE.sub('/{id}', op)
    return op
