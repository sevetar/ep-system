package com.schoolwork.epsys.device.outbox;

import com.schoolwork.epsys.mq.outbox.OutboxMessageStrategy;
import com.schoolwork.epsys.mq.outbox.OutboxStore;
import com.schoolwork.epsys.mq.outbox.ReliableOutboxPublisher;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
class ReliableOutboxPublisherTest {

    @Test
    void confirmedMessageIsMarkedPublished() {
        MemoryStore store = new MemoryStore();
        ReliableOutboxPublisher publisher = new ReliableOutboxPublisher(new RabbitTemplate());
        OutboxMessageStrategy<TestEvent> strategy = new TestStrategy(false);

        ReliableOutboxPublisher.BatchResult result = publisher.publishBatch(store, strategy, 10, 1000);

        assertEquals(new ReliableOutboxPublisher.BatchResult(1, 1, 0), result);
        assertTrue(store.published);
        assertFalse(store.failed);
    }

    @Test
    void sendFailureIsRecordedForRetryWithoutFailingTheWholeBatch() {
        MemoryStore store = new MemoryStore();
        ReliableOutboxPublisher publisher = new ReliableOutboxPublisher(new RabbitTemplate());

        ReliableOutboxPublisher.BatchResult result = publisher.publishBatch(store, new TestStrategy(true), 10, 1000);

        assertEquals(new ReliableOutboxPublisher.BatchResult(1, 0, 1), result);
        assertTrue(store.failed);
        assertNotNull(store.nextRetryAt);
        assertTrue(store.lastError.contains("simulated"));
    }

    private record TestEvent(String eventId, int retryCount) {
    }

    private static final class TestStrategy implements OutboxMessageStrategy<TestEvent> {
        private final boolean fail;

        private TestStrategy(boolean fail) {
            this.fail = fail;
        }

        @Override
        public String eventId(TestEvent event) {
            return event.eventId();
        }

        @Override
        public void send(RabbitTemplate rabbitTemplate, TestEvent event, CorrelationData correlationData) {
            if (fail) {
                throw new IllegalStateException("simulated send failure");
            }
            correlationData.getFuture().complete(new CorrelationData.Confirm(true, null));
        }
    }

    private static final class MemoryStore implements OutboxStore<TestEvent> {
        private final TestEvent event = new TestEvent("event-1", 0);
        private boolean published;
        private boolean failed;
        private Date nextRetryAt;
        private String lastError;

        @Override
        public List<TestEvent> findPublishable(Date now, Date staleBefore, int limit) {
            return List.of(event);
        }

        @Override
        public boolean claim(TestEvent event, Date now, Date staleBefore) {
            return true;
        }

        @Override
        public void markPublished(TestEvent event) {
            published = true;
        }

        @Override
        public void markFailed(TestEvent event, Date nextRetryAt, String lastError) {
            failed = true;
            this.nextRetryAt = nextRetryAt;
            this.lastError = lastError;
        }

        @Override
        public int retryCount(TestEvent event) {
            return event.retryCount();
        }
    }
}
