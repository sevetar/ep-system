package com.schoolwork.epsys.device.knowledge;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schoolwork.epsys.device.mapper.MaintainRecordMapper;
import com.schoolwork.epsys.device.mapper.WorkOrderKnowledgeOutboxMapper;
import com.schoolwork.epsys.device.order.MaintainOrderEvent;
import com.schoolwork.epsys.device.order.OrderLifecycleService;
import com.schoolwork.epsys.device.order.OrderStateMachine;
import com.schoolwork.epsys.device.order.OrderTransitionContext;
import com.schoolwork.epsys.model.device.MaintainRecord;
import com.schoolwork.epsys.model.device.WorkOrderKnowledgeOutbox;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.Date;
import java.util.HexFormat;
import java.util.Arrays;
import java.util.List;

/** 原子完成工单并生成知识事件；RabbitMQ 与 Elasticsearch 不参与数据库事务。 */
@Service
public class WorkOrderCompletionService {

    private static final String IN_PROGRESS = "维护中";

    private final MaintainRecordMapper maintainRecordMapper;
    private final WorkOrderKnowledgeOutboxMapper outboxMapper;
    private final ObjectMapper objectMapper;
    private final OrderLifecycleService lifecycleService;
    private final OrderStateMachine stateMachine;

    public WorkOrderCompletionService(MaintainRecordMapper maintainRecordMapper,
                                      WorkOrderKnowledgeOutboxMapper outboxMapper,
                                      ObjectMapper objectMapper,
                                      OrderLifecycleService lifecycleService,
                                      OrderStateMachine stateMachine) {
        this.maintainRecordMapper = maintainRecordMapper;
        this.outboxMapper = outboxMapper;
        this.objectMapper = objectMapper;
        this.lifecycleService = lifecycleService;
        this.stateMachine = stateMachine;
    }

    @Transactional
    public CompletionResult complete(Integer orderId, String repairProcess, String solution,
                                     String rootCause, String verificationResult,
                                     String replacedParts, String knowledgeTags) {
        if (orderId == null || length(repairProcess) < 8 || length(solution) < 8
                || length(verificationResult) < 4) {
            return new CompletionResult(false, null,
                    "知识入库要求：处理过程和解决方案至少 8 个字符，修复验证至少 4 个字符");
        }
        MaintainRecord order = maintainRecordMapper.selectById(orderId);
        if (order == null || !stateMachine.canTransition(order.getStatus(), MaintainOrderEvent.COMPLETE)) {
            return new CompletionResult(false, null, "工单不存在或当前状态不可完成");
        }
        if (length(order.getDescription()) < 4) {
            return new CompletionResult(false, null, "原始故障描述过短，无法形成可信维修案例");
        }

        lifecycleService.apply(order, MaintainOrderEvent.COMPLETE,
                OrderTransitionContext.completion(new Date(), repairProcess.trim(), solution.trim(),
                        safe(rootCause), verificationResult.trim(), safe(replacedParts), safe(knowledgeTags)));
        if (maintainRecordMapper.updateById(order) != 1) {
            return new CompletionResult(false, null, "工单状态已变化，请刷新后重试");
        }

        MaintainRecord completed = maintainRecordMapper.selectById(orderId);
        WorkOrderKnowledgeOutbox outbox = buildOutbox(completed);
        if (outboxMapper.insert(outbox) != 1) {
            throw new IllegalStateException("无法写入工单知识 Outbox");
        }
        return new CompletionResult(true, outbox.getEventId(), "更新成功！");
    }

    private WorkOrderKnowledgeOutbox buildOutbox(MaintainRecord order) {
        int version = order.getVersion() == null ? 0 : order.getVersion();
        String tenantId = isBlank(order.getTenantId()) ? "default" : order.getTenantId().trim();
        String material = tenantId + ":" + order.getId() + ":" + version + ":"
                + order.getRepairProcess() + ":" + order.getSolution() + ":"
                + safe(order.getRootCause()) + ":" + order.getVerificationResult();
        String suffix = sha256(material).substring(0, 24);
        String eventId = "knowledge-event-" + suffix;
        String traceId = "knowledge-trace-" + suffix;
        Instant completedAt = order.getEndTime().toInstant();
        WorkOrderKnowledgeMetadata metadata = maintainRecordMapper.selectKnowledgeMetadata(order.getId());
        if (metadata == null) {
            metadata = WorkOrderKnowledgeMetadata.unknown();
        }
        WorkOrderCompletedEventV2 event = new WorkOrderCompletedEventV2(
                "work-order-completed/v2", eventId, tenantId,
                String.valueOf(order.getId()), version,
                order.getDeviceId() == null ? "unknown" : String.valueOf(order.getDeviceId()),
                safe(order.getDescription()), order.getRepairProcess(), order.getSolution(),
                safe(order.getRootCause()), order.getVerificationResult(), safe(order.getReplacedParts()),
                safe(metadata.deviceCategory()), safe(metadata.deviceModel()), tags(order.getKnowledgeTags()),
                completedAt, traceId, Instant.now()
        );

        WorkOrderKnowledgeOutbox outbox = new WorkOrderKnowledgeOutbox();
        outbox.setEventId(eventId);
        outbox.setTenantId(tenantId);
        outbox.setOrderId(order.getId());
        outbox.setOrderVersion(version);
        outbox.setTraceId(traceId);
        outbox.setPayload(toJson(event));
        outbox.setPublishStatus("PENDING");
        outbox.setIngestionStatus("PENDING");
        outbox.setRetryCount(0);
        outbox.setNextRetryAt(new Date());
        outbox.setCreatedAt(new Date());
        outbox.setUpdatedAt(new Date());
        return outbox;
    }

    public KnowledgeStatusResult getKnowledgeStatus(String eventId) {
        if (isBlank(eventId)) {
            return null;
        }
        WorkOrderKnowledgeOutbox outbox = outboxMapper.findByEventId(eventId.trim());
        if (outbox == null) {
            return null;
        }
        return new KnowledgeStatusResult(
                outbox.getEventId(), outbox.getOrderId(), outbox.getPublishStatus(),
                outbox.getIngestionStatus(), outbox.getChunkCount(), outbox.getQualityScore(),
                outbox.getQualityIssues(), outbox.getIngestionError(), outbox.getPublishedAt(),
                outbox.getIngestedAt());
    }

    private String toJson(WorkOrderCompletedEventV2 event) {
        try {
            return objectMapper.writeValueAsString(event);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("无法序列化工单知识事件", exception);
        }
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private static int length(String value) {
        return value == null ? 0 : value.trim().length();
    }

    private static List<String> tags(String value) {
        if (isBlank(value)) {
            return List.of();
        }
        return Arrays.stream(value.split("[,，]"))
                .map(String::trim)
                .filter(item -> !item.isEmpty())
                .distinct()
                .limit(30)
                .toList();
    }

    private static String safe(String value) {
        return value == null ? "" : value.trim();
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("JVM 缺少 SHA-256", exception);
        }
    }

    public record CompletionResult(boolean completed, String eventId, String message) {
    }

    public record KnowledgeStatusResult(
            String eventId,
            Integer orderId,
            String publishStatus,
            String ingestionStatus,
            Integer chunkCount,
            Integer qualityScore,
            String qualityIssues,
            String ingestionError,
            Date publishedAt,
            Date ingestedAt
    ) {
    }
}
