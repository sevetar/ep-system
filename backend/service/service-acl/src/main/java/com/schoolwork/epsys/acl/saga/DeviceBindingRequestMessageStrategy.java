package com.schoolwork.epsys.acl.saga;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schoolwork.epsys.model.acl.DeviceBindingOutbox;
import com.schoolwork.epsys.model.shared.DeviceBindingRequestedEventV1;
import com.schoolwork.epsys.mq.outbox.OutboxMessageStrategy;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

import static com.schoolwork.epsys.mq.constant.MqConst.DEVICE_BINDING_EXCHANGE;
import static com.schoolwork.epsys.mq.constant.MqConst.DEVICE_BINDING_REQUEST_ROUTING_KEY;

@Component
public class DeviceBindingRequestMessageStrategy
        implements OutboxMessageStrategy<DeviceBindingOutbox> {

    private final ObjectMapper objectMapper;

    public DeviceBindingRequestMessageStrategy(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public String eventId(DeviceBindingOutbox event) {
        return event.getEventId();
    }

    @Override
    public void send(RabbitTemplate rabbitTemplate, DeviceBindingOutbox event,
                     CorrelationData correlationData) {
        try {
            DeviceBindingRequestedEventV1 payload = objectMapper.readValue(
                    event.getPayload(), DeviceBindingRequestedEventV1.class);
            rabbitTemplate.convertAndSend(DEVICE_BINDING_EXCHANGE,
                    DEVICE_BINDING_REQUEST_ROUTING_KEY, payload, correlationData);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("无效的设备领用请求事件", exception);
        }
    }
}
