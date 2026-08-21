package com.schoolwork.epsys.device.knowledge;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.List;

/** Agent 完成最终摄取后回传给 Java 的结果合同。 */
public record WorkOrderKnowledgeOutcomeEventV1(
        @JsonProperty("schema_version") String schemaVersion,
        @JsonProperty("event_id") String eventId,
        @JsonProperty("tenant_id") String tenantId,
        @JsonProperty("work_order_id") String workOrderId,
        @JsonProperty("source_id") String sourceId,
        @JsonProperty("source_version") String sourceVersion,
        String status,
        int chunks,
        @JsonProperty("quality_score") int qualityScore,
        @JsonProperty("quality_issues") List<String> qualityIssues,
        String error,
        @JsonProperty("occurred_at") Instant occurredAt
) {
}
