package com.schoolwork.epsys.device.knowledge;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schoolwork.epsys.device.mapper.WorkOrderKnowledgeOutboxMapper;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.io.IOException;

/** 接收 Agent 最终摄取结果，让 Java 区分“已发布”和“已入库”。 */
@Component
@ConditionalOnProperty(prefix = "knowledge.work-order-ingestion", name = "enabled", havingValue = "true")
public class WorkOrderKnowledgeResultListener {

    public static final String RESULT_QUEUE = "flowfix.java.knowledge.ingestion-results";
    public static final String RESULT_ROUTING_KEY = "flowfix.knowledge.ingestion-result.v1";

    private final ObjectMapper objectMapper;
    private final WorkOrderKnowledgeOutboxMapper outboxMapper;

    public WorkOrderKnowledgeResultListener(ObjectMapper objectMapper,
                                            WorkOrderKnowledgeOutboxMapper outboxMapper) {
        this.objectMapper = objectMapper;
        this.outboxMapper = outboxMapper;
    }

    @RabbitListener(queues = RESULT_QUEUE)
    public void consume(Message message) {
        WorkOrderKnowledgeOutcomeEventV1 outcome;
        try {
            outcome = objectMapper.readValue(message.getBody(), WorkOrderKnowledgeOutcomeEventV1.class);
        } catch (IOException exception) {
            throw new IllegalArgumentException("无效的知识摄取结果合同", exception);
        }
        if (!"knowledge-ingestion-result/v1".equals(outcome.schemaVersion())) {
            throw new IllegalArgumentException("不支持的知识摄取结果版本");
        }
        String issues;
        try {
            issues = objectMapper.writeValueAsString(outcome.qualityIssues());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("无法序列化知识质量问题", exception);
        }
        int updated = outboxMapper.markIngestionResult(
                outcome.eventId(), outcome.status(), outcome.chunks(), outcome.qualityScore(),
                issues, truncate(outcome.error(), 1000));
        if (updated != 1) {
            throw new IllegalStateException("找不到知识事件 Outbox: " + outcome.eventId());
        }
    }

    private static String truncate(String value, int maximum) {
        if (value == null || value.length() <= maximum) {
            return value;
        }
        return value.substring(0, maximum);
    }
}
