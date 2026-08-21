package com.schoolwork.epsys.device.dispatch.trigger;

import com.schoolwork.epsys.model.device.DispatchEventOutbox;
import com.schoolwork.epsys.mq.outbox.OutboxMessageStrategy;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;

@Component
public class DispatchOutboxMessageStrategy implements OutboxMessageStrategy<DispatchEventOutbox> {

    @Override
    public String eventId(DispatchEventOutbox event) {
        return event.getEventId();
    }

    @Override
    public void send(RabbitTemplate rabbitTemplate, DispatchEventOutbox event,
                     CorrelationData correlationData) {
        MessageProperties properties = new MessageProperties();
        properties.setContentType(MessageProperties.CONTENT_TYPE_JSON);
        properties.setContentEncoding(StandardCharsets.UTF_8.name());
        properties.setDeliveryMode(MessageDeliveryMode.PERSISTENT);
        properties.setMessageId(event.getEventId());
        Message message = new Message(event.getPayload().getBytes(StandardCharsets.UTF_8), properties);
        rabbitTemplate.send(DispatchOutboxPublisher.EXCHANGE,
                DispatchOutboxPublisher.ROUTING_KEY, message, correlationData);
    }
}
