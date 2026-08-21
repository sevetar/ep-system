package com.schoolwork.epsys.device.dispatch.trigger;

import com.schoolwork.epsys.device.mapper.DispatchEventOutboxMapper;
import com.schoolwork.epsys.model.device.DispatchEventOutbox;
import com.schoolwork.epsys.mq.outbox.ReliableOutboxPublisher;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class DispatchOutboxPublisher {

    public static final String EXCHANGE = "flowfix.agent";
    public static final String ROUTING_KEY = "flowfix.dispatch.requested.v1";

    private final ReliableOutboxPublisher publisher;
    private final DispatchOutboxStore store;
    private final DispatchOutboxMessageStrategy messageStrategy;
    private final boolean enabled;
    private final int batchSize;
    private final long confirmTimeoutMs;

    public DispatchOutboxPublisher(ReliableOutboxPublisher publisher,
                                   DispatchOutboxStore store,
                                   DispatchOutboxMessageStrategy messageStrategy,
                                   @Value("${dispatch.auto.enabled:false}") boolean enabled,
                                   @Value("${dispatch.auto.publish-batch-size:50}") int batchSize,
                                   @Value("${dispatch.auto.confirm-timeout-ms:5000}") long confirmTimeoutMs) {
        this.publisher = publisher;
        this.store = store;
        this.messageStrategy = messageStrategy;
        this.enabled = enabled;
        this.batchSize = batchSize;
        this.confirmTimeoutMs = confirmTimeoutMs;
    }

    @Scheduled(fixedDelayString = "${dispatch.auto.publish-delay-ms:2000}")
    public void publishPending() {
        if (!enabled) {
            return;
        }
        publisher.publishBatch(store, messageStrategy, batchSize, confirmTimeoutMs);
    }
}
