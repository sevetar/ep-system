package com.schoolwork.epsys.device.dispatch.trigger;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;

/** 与 Python DispatchEvent 冻结的 RabbitMQ 合同。 */
public record DispatchRequestEventV1(
        @JsonProperty("schema_version") String schemaVersion,
        @JsonProperty("event_id") String eventId,
        @JsonProperty("dispatch_id") String dispatchId,
        @JsonProperty("tenant_id") String tenantId,
        @JsonProperty("work_order_id") String workOrderId,
        @JsonProperty("trace_id") String traceId,
        String trigger,
        @JsonProperty("deadline_seconds") int deadlineSeconds,
        @JsonProperty("occurred_at") Instant occurredAt
) {
}
