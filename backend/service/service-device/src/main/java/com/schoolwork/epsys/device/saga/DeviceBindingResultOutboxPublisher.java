package com.schoolwork.epsys.device.saga;

import com.schoolwork.epsys.mq.outbox.ReliableOutboxPublisher;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "device-binding.saga", name = "enabled", havingValue = "true")
public class DeviceBindingResultOutboxPublisher {

    private final ReliableOutboxPublisher publisher;
    private final DeviceBindingResultOutboxStore store;
    private final DeviceBindingResultMessageStrategy strategy;
    private final int batchSize;
    private final long confirmTimeoutMs;

    public DeviceBindingResultOutboxPublisher(ReliableOutboxPublisher publisher,
                                              DeviceBindingResultOutboxStore store,
                                              DeviceBindingResultMessageStrategy strategy,
                                              @Value("${device-binding.saga.publish-batch-size:50}") int batchSize,
                                              @Value("${device-binding.saga.confirm-timeout-ms:5000}") long confirmTimeoutMs) {
        this.publisher = publisher;
        this.store = store;
        this.strategy = strategy;
        this.batchSize = batchSize;
        this.confirmTimeoutMs = confirmTimeoutMs;
    }

    @Scheduled(fixedDelayString = "${device-binding.saga.publish-delay-ms:2000}")
    public void publishPending() {
        publisher.publishBatch(store, strategy, batchSize, confirmTimeoutMs);
    }
}
