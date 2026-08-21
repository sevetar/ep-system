package com.schoolwork.epsys.device.dispatch.trigger;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schoolwork.epsys.device.mapper.DispatchEventOutboxMapper;
import com.schoolwork.epsys.device.mapper.MaintainRecordMapper;
import com.schoolwork.epsys.device.order.MaintainOrderEvent;
import com.schoolwork.epsys.device.order.OrderLifecycleService;
import com.schoolwork.epsys.device.order.OrderStateMachine;
import com.schoolwork.epsys.device.order.OrderTransitionContext;
import com.schoolwork.epsys.model.device.DispatchEventOutbox;
import com.schoolwork.epsys.model.device.MaintainRecord;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.Date;
import java.util.HexFormat;

@Service
public class DispatchTriggerService {

    private static final String WAITING_FOR_CLAIM = "待领取";

    private final MaintainRecordMapper maintainRecordMapper;
    private final DispatchEventOutboxMapper outboxMapper;
    private final ObjectMapper objectMapper;
    private final OrderLifecycleService lifecycleService;
    private final OrderStateMachine stateMachine;
    private final long claimWindowMillis;
    private final int agentDeadlineSeconds;

    public DispatchTriggerService(MaintainRecordMapper maintainRecordMapper,
                                  DispatchEventOutboxMapper outboxMapper,
                                  ObjectMapper objectMapper,
                                  OrderLifecycleService lifecycleService,
                                  OrderStateMachine stateMachine,
                                  @Value("${dispatch.auto.claim-window-seconds:600}") long claimWindowSeconds,
                                  @Value("${dispatch.auto.agent-deadline-seconds:60}") int agentDeadlineSeconds) {
        this.maintainRecordMapper = maintainRecordMapper;
        this.outboxMapper = outboxMapper;
        this.objectMapper = objectMapper;
        this.lifecycleService = lifecycleService;
        this.stateMachine = stateMachine;
        this.claimWindowMillis = claimWindowSeconds * 1000L;
        this.agentDeadlineSeconds = agentDeadlineSeconds;
    }

    /** 审批通过与抢单窗口初始化、紧急事件写入必须在同一数据库事务中完成。 */
    @Transactional
    public ApprovalResult approve(MaintainRecord order, Integer approverId, boolean approved) {
        Date now = new Date();
        Date claimDeadline = approved ? new Date(now.getTime() + claimWindowMillis) : null;
        lifecycleService.apply(order,
                approved ? MaintainOrderEvent.APPROVE : MaintainOrderEvent.REJECT,
                OrderTransitionContext.approval(approverId, now, claimDeadline));
        if (maintainRecordMapper.updateById(order) != 1) {
            return new ApprovalResult(false, false);
        }
        TriggerReceipt urgentReceipt = approved && isUrgent(order)
                ? createEvent(order, DispatchTriggerType.URGENT, "approval") : null;
        boolean urgentTriggered = urgentReceipt != null;
        return new ApprovalResult(true, urgentTriggered);
    }

    @Transactional
    public TriggerReceipt trigger(Integer orderId, DispatchTriggerType trigger, String sourceKey) {
        MaintainRecord order = maintainRecordMapper.selectById(orderId);
        if (!isDispatchable(order)) {
            return null;
        }
        return createEvent(order, trigger, sourceKey);
    }

    public boolean isDispatchable(MaintainRecord order) {
        return order != null
                && order.getMiantainId() == null
                && stateMachine.canTransition(order.getStatus(), MaintainOrderEvent.AUTO_ASSIGN);
    }

    private TriggerReceipt createEvent(MaintainRecord order, DispatchTriggerType trigger, String sourceKey) {
        int version = order.getVersion() == null ? 0 : order.getVersion();
        String material = order.getId() + ":" + version + ":" + trigger.wireValue() + ":" + sourceKey;
        String suffix = sha256(material).substring(0, 24);
        String eventId = "dispatch-event-" + suffix;
        String dispatchId = "dispatch-" + suffix;
        String traceId = "trace-" + suffix;
        String tenantId = order.getTenantId() == null || order.getTenantId().isBlank()
                ? "default" : order.getTenantId();
        Instant occurredAt = Instant.now();
        DispatchRequestEventV1 event = new DispatchRequestEventV1(
                "dispatch-request/v1", eventId, dispatchId, tenantId,
                String.valueOf(order.getId()), traceId, trigger.wireValue(),
                agentDeadlineSeconds, occurredAt
        );
        DispatchEventOutbox outbox = new DispatchEventOutbox();
        outbox.setEventId(eventId);
        outbox.setDispatchId(dispatchId);
        outbox.setTenantId(tenantId);
        outbox.setOrderId(order.getId());
        outbox.setTraceId(traceId);
        outbox.setTriggerType(trigger.wireValue());
        outbox.setOrderVersion(version);
        outbox.setPayload(toJson(event));
        outbox.setPublishStatus("PENDING");
        outbox.setRetryCount(0);
        outbox.setNextRetryAt(new Date());
        outbox.setCreatedAt(new Date());
        outbox.setUpdatedAt(new Date());
        try {
            if (outboxMapper.insert(outbox) != 1) {
                return null;
            }
        } catch (DuplicateKeyException ignored) {
            // 相同业务触发重放视为幂等成功，不产生第二条消息。
        }
        return new TriggerReceipt(eventId, dispatchId, "dispatch:" + tenantId + ":" + dispatchId);
    }

    private boolean isUrgent(MaintainRecord order) {
        return "URGENT".equalsIgnoreCase(order.getPriority());
    }

    private String toJson(DispatchRequestEventV1 event) {
        try {
            return objectMapper.writeValueAsString(event);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("无法序列化自动派单事件", exception);
        }
    }

    private static String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("JVM 缺少 SHA-256", exception);
        }
    }

    public record ApprovalResult(boolean updated, boolean urgentTriggered) {
    }

    public record TriggerReceipt(String eventId, String dispatchId, String threadId) {
    }
}
