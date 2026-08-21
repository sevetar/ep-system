package com.schoolwork.epsys.device.knowledge;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.List;

/** Java 与 Agent 间的工单知识事件 v2，补充质量门禁和设备过滤所需字段。 */
public record WorkOrderCompletedEventV2(
        @JsonProperty("schema_version") String schemaVersion,
        @JsonProperty("event_id") String eventId,
        @JsonProperty("tenant_id") String tenantId,
        @JsonProperty("work_order_id") String workOrderId,
        @JsonProperty("work_order_version") int workOrderVersion,
        @JsonProperty("device_id") String deviceId,
        String description,
        @JsonProperty("repair_process") String repairProcess,
        String solution,
        @JsonProperty("root_cause") String rootCause,
        @JsonProperty("verification_result") String verificationResult,
        @JsonProperty("replaced_parts") String replacedParts,
        @JsonProperty("device_category") String deviceCategory,
        @JsonProperty("device_model") String deviceModel,
        @JsonProperty("knowledge_tags") List<String> knowledgeTags,
        @JsonProperty("completed_at") Instant completedAt,
        @JsonProperty("trace_id") String traceId,
        @JsonProperty("occurred_at") Instant occurredAt
) {
}
