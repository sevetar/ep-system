package com.schoolwork.epsys.device.knowledge;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;

/** Java 与 Agent 间的脱敏工单案例事件合同。 */
public record WorkOrderCompletedEventV1(
        @JsonProperty("schema_version") String schemaVersion,
        @JsonProperty("event_id") String eventId,
        @JsonProperty("tenant_id") String tenantId,
        @JsonProperty("work_order_id") String workOrderId,
        @JsonProperty("work_order_version") int workOrderVersion,
        @JsonProperty("device_id") String deviceId,
        String description,
        @JsonProperty("repair_process") String repairProcess,
        String solution,
        @JsonProperty("completed_at") Instant completedAt,
        @JsonProperty("trace_id") String traceId,
        @JsonProperty("occurred_at") Instant occurredAt
) {
}
