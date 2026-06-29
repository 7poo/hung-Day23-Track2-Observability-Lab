"""Prometheus + OTel + structlog wiring.

Single source of truth for the metric/span/log namespace.
"""
from __future__ import annotations

import logging
import os
import sys

import structlog
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram

# ── Prometheus metrics ────────────────────────────────────────
INFERENCE_REQUESTS = Counter(
    "inference_requests_total",
    "Total inference requests",
    ["model", "status"],
)
INFERENCE_LATENCY = Histogram(
    "inference_latency_seconds",
    "Inference end-to-end latency",
    ["model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)
INFERENCE_ACTIVE = Gauge(
    "inference_active_gauge",
    "In-flight inference requests",
)
INFERENCE_TOKENS = Counter(
    "inference_tokens_total",
    "Tokens processed (input/output)",
    ["model", "direction"],
)
INFERENCE_QUALITY = Gauge(
    "inference_quality_score",
    "Latest eval-as-metric quality score [0,1]",
    ["model"],
)
GPU_UTIL = Gauge(
    "gpu_utilization_percent",
    "Simulated GPU utilization [0,100]",
)

tracer = trace.get_tracer(__name__)


def setup_otel() -> None:
    """Configure OTLP trace/log export + FastAPI auto-instrumentation."""
    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "inference-api"),
            "service.namespace": "aicb",
            "deployment.environment": os.getenv(
                "DEPLOY_ENV",
                "lab",
            ),
        }
    )
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True))
    )
    set_logger_provider(logger_provider)
    # Auto-instrument FastAPI handlers (creates server spans for every route)
    from fastapi import FastAPI  # local import: only needed at setup

    FastAPIInstrumentor().instrument()
    _configure_logging(logger_provider)


def _add_trace_context(
    _: object,
    __: str,
    event_dict: dict[str, object],
) -> dict[str, object]:
    """Add the active trace/span IDs to every structured log event."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict


def _configure_logging(logger_provider: LoggerProvider) -> None:
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_trace_context,
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    otel = LoggingHandler(level=level, logger_provider=logger_provider)

    class _RemoveStructlogInternals(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            # ProcessorFormatter needs these for the console handler, but OTLP
            # attributes only accept primitive values.
            for attribute in ("_logger", "_name"):
                if hasattr(record, attribute):
                    delattr(record, attribute)
            return True

    otel.addFilter(_RemoveStructlogInternals())

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(otel)

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind_log(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
