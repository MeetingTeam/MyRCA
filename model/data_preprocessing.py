import json
import os
import signal
import logging
from confluent_kafka import Consumer, Producer, KafkaError, KafkaException
from common.util import normalize_operation
from configs.constants import UNKNOWN

# ── Configuration (from environment variables) ────────────────────────────────

KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "redpanda.redpanda.svc.cluster.local:9093")
INPUT_TOPIC = os.getenv("INPUT_TOPIC", "traces")
OUTPUT_TOPIC = os.getenv("OUTPUT_TOPIC", "preprocess-data")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "preprocessing-group")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("preprocessing")

# ── Graceful shutdown ─────────────────────────────────────────────────────────

running = True

def _stop(signum, frame):
    global running
    log.info("Received signal %s, shutting down…", signum)
    running = False

signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

# ── Feature extraction helpers (kept from original) ──────────────────────────

def get_resource_attribute(resource, key):
    """Extract a value from resource.attributes by key."""
    for attr in resource.get("attributes", []):
        if attr.get("key") == key:
            value = attr.get("value", {})
            return next(iter(value.values()), UNKNOWN)
    return UNKNOWN


def get_service_name(resource):
    return get_resource_attribute(resource, "service.name")


def get_service_instance_id(resource):
    return get_resource_attribute(resource, "service.instance.id")


def get_span_attributes(span):
    fields = {}
    for attr in span.get("attributes", []):
        if attr["key"] == "http.response.status_code":
            value = attr.get("value", {})
            fields["http_status"] = next(iter(value.values()), "0")
        elif attr["key"] == "http.status_code":
            value = attr.get("value", {})
            fields["http_status"] = next(iter(value.values()), "0")
    return fields


def filter_span(lib, span):
    match lib:
        case "io.opentelemetry.java-http-client":
            return True
        case "io.opentelemetry.tomcat-10.0":
            return True
        case "nginx":
            return True
        case "io.opentelemetry.rabbitmq-2.7":
            if span["name"] == "basic.ack":
                return False
            return True
        case "io.opentelemetry.spring-rabbit-1.0":
            return True
        case "io.opentelemetry.mongo-3.1":
            if span["kind"] == 3:
                return True
        case "io.opentelemetry.spring-data-1.8":
            if span["kind"] == 1:
                return True
        case _:
            return False

# ── OTLP JSON → flat feature records ────────────────────────────────────────

def extract_records(otlp_json: dict) -> list[dict]:
    """
    Parse an OTLP JSON message (as exported by otel-collector kafka exporter)
    and return a list of flat feature dicts, one per qualifying span.

    Expected top-level key: "resourceSpans"
    """
    records = []
    for resource_span in otlp_json.get("resourceSpans", []):
        resource = resource_span.get("resource", {})
        service_name = get_service_name(resource)
        instance_id = get_service_instance_id(resource)

        for scope_span in resource_span.get("scopeSpans", []):
            lib = scope_span.get("scope", {}).get("name", "")

            for raw_span in scope_span.get("spans", []):
                if not filter_span(lib, raw_span):
                    continue

                operation = normalize_operation(raw_span.get("name", UNKNOWN))
                http_attrs = get_span_attributes(raw_span)
                http_status = http_attrs.get("http_status", "0")

                record = {
                    "instrumentation_library": lib,
                    "service": service_name,
                    "service_instance_id": instance_id,
                    "traceId": raw_span["traceId"],
                    "parentSpanId": raw_span.get("parentSpanId"),
                    "spanId": raw_span["spanId"],
                    "operation": operation,
                    "kind": raw_span["kind"],
                    "startTime": raw_span["startTimeUnixNano"],
                    "duration": int(raw_span["endTimeUnixNano"]) - int(raw_span["startTimeUnixNano"]),
                    "span_status": raw_span.get("status", {}).get("code", 1),
                    "http_status": http_status,
                }

                records.append(record)
    return records


def build_partition_key(record: dict) -> str:
    """Build partition key: <service>/<operation>/<http_status>/<service.instance.id>"""
    return f"{record['service']}/{record['operation']}/{record['http_status']}/{record['service_instance_id']}"

# ── Kafka producer callback ──────────────────────────────────────────────────

def _delivery_report(err, msg):
    if err:
        log.error("Delivery failed for key=%s: %s", msg.key(), err)


# ── Main consumer loop ───────────────────────────────────────────────────────

def main():
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })

    producer = Producer({
        "bootstrap.servers": KAFKA_BROKERS,
        "linger.ms": 50,
        "batch.num.messages": 500,
    })

    consumer.subscribe([INPUT_TOPIC])
    log.info("Preprocessing Service started — consuming [%s], producing [%s]", INPUT_TOPIC, OUTPUT_TOPIC)

    total_consumed = 0
    total_produced = 0

    try:
        while running:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                producer.poll(0)  # trigger delivery callbacks
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("Consumer error: %s", msg.error())
                continue

            # Parse OTLP JSON message
            try:
                otlp_data = json.loads(msg.value())
            except json.JSONDecodeError as e:
                log.warning("Skipping malformed JSON message: %s", e)
                continue

            total_consumed += 1
            records = extract_records(otlp_data)

            for record in records:
                key = build_partition_key(record)
                producer.produce(
                    topic=OUTPUT_TOPIC,
                    key=key.encode("utf-8"),
                    value=json.dumps(record).encode("utf-8"),
                    callback=_delivery_report,
                )
                total_produced += 1

            # Periodic flush + log
            if total_consumed % 100 == 0:
                producer.flush()
                log.info("Progress: consumed=%d  produced=%d", total_consumed, total_produced)

            producer.poll(0)

    except KafkaException as e:
        log.error("Kafka exception: %s", e)
    finally:
        log.info("Flushing producer…")
        producer.flush(timeout=10)
        consumer.close()
        log.info("Shutdown complete. consumed=%d  produced=%d", total_consumed, total_produced)


if __name__ == "__main__":
    main()