package com.schoolwork.epsys.mq.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

import java.util.Date;
import java.util.concurrent.TimeUnit;

/**
 * 固定 find -> claim -> send -> confirm -> mark 的模板流程，差异通过 Store 与消息策略注入。
 */
@Component
public class ReliableOutboxPublisher {

    private static final Logger log = LoggerFactory.getLogger(ReliableOutboxPublisher.class);

    private final RabbitTemplate rabbitTemplate;

    public ReliableOutboxPublisher(RabbitTemplate rabbitTemplate) {
        this.rabbitTemplate = rabbitTemplate;
    }

    public <T> BatchResult publishBatch(OutboxStore<T> store,
                                        OutboxMessageStrategy<T> messageStrategy,
                                        int batchSize,
                                        long confirmTimeoutMs) {
        Date now = new Date();
        Date staleBefore = new Date(now.getTime() - Math.max(confirmTimeoutMs * 2, 10_000));
        int claimed = 0;
        int published = 0;
        int failed = 0;
        for (T event : store.findPublishable(now, staleBefore, batchSize)) {
            if (!store.claim(event, now, staleBefore)) {
                continue;
            }
            claimed++;
            CorrelationData correlation = new CorrelationData(messageStrategy.eventId(event));
            try {
                messageStrategy.send(rabbitTemplate, event, correlation);
                CorrelationData.Confirm confirm = correlation.getFuture()
                        .get(confirmTimeoutMs, TimeUnit.MILLISECONDS);
                if (!confirm.isAck()) {
                    throw new IllegalStateException("RabbitMQ nack: " + confirm.getReason());
                }
                if (correlation.getReturned() != null) {
                    throw new IllegalStateException("RabbitMQ unroutable: "
                            + correlation.getReturned().getReplyText());
                }
                store.markPublished(event);
                published++;
            } catch (Exception exception) {
                if (exception instanceof InterruptedException) {
                    Thread.currentThread().interrupt();
                }
                failed++;
                long delaySeconds = Math.min(300, 1L << Math.min(store.retryCount(event) + 1, 8));
                String error = exception.getClass().getSimpleName() + ": " + exception.getMessage();
                String truncated = error.substring(0, Math.min(error.length(), 500));
                store.markFailed(event,
                        new Date(System.currentTimeMillis() + delaySeconds * 1000), truncated);
                log.warn("outbox publish failed eventId={} retryCount={} error={}",
                        messageStrategy.eventId(event), store.retryCount(event), truncated);
            }
        }
        return new BatchResult(claimed, published, failed);
    }

    public record BatchResult(int claimed, int published, int failed) {
    }
}
