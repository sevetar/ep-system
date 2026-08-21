package com.schoolwork.epsys.device.knowledge;

import com.schoolwork.epsys.model.device.WorkOrderKnowledgeOutbox;
import com.schoolwork.epsys.mq.outbox.OutboxMessageStrategy;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;

@Component
public class WorkOrderKnowledgeMessageStrategy
        implements OutboxMessageStrategy<WorkOrderKnowledgeOutbox> {

    @Override
    public String eventId(WorkOrderKnowledgeOutbox event) {
        return event.getEventId();
    }

    @Override
    public void send(RabbitTemplate rabbitTemplate, WorkOrderKnowledgeOutbox event,
                     CorrelationData correlationData) {
        MessageProperties properties = new MessageProperties();
        properties.setContentType(MessageProperties.CONTENT_TYPE_JSON);
        properties.setContentEncoding(StandardCharsets.UTF_8.name());
        properties.setDeliveryMode(MessageDeliveryMode.PERSISTENT);
        properties.setMessageId(event.getEventId());
        Message message = new Message(event.getPayload().getBytes(StandardCharsets.UTF_8), properties);
        rabbitTemplate.send(WorkOrderKnowledgeOutboxPublisher.EXCHANGE,
                WorkOrderKnowledgeOutboxPublisher.ROUTING_KEY, message, correlationData);
    }
}
