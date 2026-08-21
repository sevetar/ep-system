package com.schoolwork.epsys.device.knowledge;

import com.schoolwork.epsys.device.mapper.WorkOrderKnowledgeOutboxMapper;
import com.schoolwork.epsys.model.device.WorkOrderKnowledgeOutbox;
import com.schoolwork.epsys.mq.outbox.ReliableOutboxPublisher;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** 可靠发布工单完成知识事件，失败按指数退避重试。 */
@Component
public class WorkOrderKnowledgeOutboxPublisher {

    public static final String EXCHANGE = "flowfix.agent";
    public static final String ROUTING_KEY = "flowfix.knowledge.work-order-completed.v1";

    private final ReliableOutboxPublisher publisher;
    private final WorkOrderKnowledgeOutboxStore store;
    private final WorkOrderKnowledgeMessageStrategy messageStrategy;
    private final boolean enabled;
    private final int batchSize;
    private final long confirmTimeoutMs;

    public WorkOrderKnowledgeOutboxPublisher(
            ReliableOutboxPublisher publisher,
            WorkOrderKnowledgeOutboxStore store,
            WorkOrderKnowledgeMessageStrategy messageStrategy,
            @Value("${knowledge.work-order-ingestion.enabled:false}") boolean enabled,
            @Value("${knowledge.work-order-ingestion.publish-batch-size:50}") int batchSize,
            @Value("${knowledge.work-order-ingestion.confirm-timeout-ms:5000}") long confirmTimeoutMs) {
        this.publisher = publisher;
        this.store = store;
        this.messageStrategy = messageStrategy;
        this.enabled = enabled;
        this.batchSize = batchSize;
        this.confirmTimeoutMs = confirmTimeoutMs;
    }

    @Scheduled(fixedDelayString = "${knowledge.work-order-ingestion.publish-delay-ms:2000}")
    public void publishPending() {
        if (!enabled) {
            return;
        }
        publisher.publishBatch(store, messageStrategy, batchSize, confirmTimeoutMs);
    }
}
