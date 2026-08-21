package com.schoolwork.epsys.device.knowledge;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.schoolwork.epsys.device.mapper.WorkOrderKnowledgeOutboxMapper;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class WorkOrderKnowledgeResultListenerTest {

    @Test
    void resultUpdatesFinalIngestionStatus() {
        WorkOrderKnowledgeOutboxMapper mapper = mock(WorkOrderKnowledgeOutboxMapper.class);
        when(mapper.markIngestionResult(
                eq("event-1"), eq("indexed"), eq(3), eq(90), eq("[]"), eq(null)))
                .thenReturn(1);
        ObjectMapper objectMapper = new ObjectMapper().registerModule(new JavaTimeModule());
        WorkOrderKnowledgeResultListener listener =
                new WorkOrderKnowledgeResultListener(objectMapper, mapper);
        String payload = """
                {
                  "schema_version":"knowledge-ingestion-result/v1",
                  "event_id":"event-1",
                  "tenant_id":"default",
                  "work_order_id":"88",
                  "source_id":"work-order/default/88",
                  "source_version":"v2-abc",
                  "status":"indexed",
                  "chunks":3,
                  "quality_score":90,
                  "quality_issues":[],
                  "error":null,
                  "occurred_at":"2026-08-14T03:00:00Z"
                }
                """;

        listener.consume(payload.getBytes(StandardCharsets.UTF_8));

        verify(mapper).markIngestionResult(
                "event-1", "indexed", 3, 90, "[]", null);
    }
}
