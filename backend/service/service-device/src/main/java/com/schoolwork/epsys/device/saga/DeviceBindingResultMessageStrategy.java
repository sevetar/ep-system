package com.schoolwork.epsys.device.saga;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schoolwork.epsys.model.device.DeviceBindingResultOutbox;
import com.schoolwork.epsys.model.shared.DeviceBindingResultEventV1;
import com.schoolwork.epsys.mq.outbox.OutboxMessageStrategy;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

import static com.schoolwork.epsys.mq.constant.MqConst.DEVICE_BINDING_EXCHANGE;
import static com.schoolwork.epsys.mq.constant.MqConst.DEVICE_BINDING_RESULT_ROUTING_KEY;

@Component
public class DeviceBindingResultMessageStrategy
        implements OutboxMessageStrategy<DeviceBindingResultOutbox> {

    private final ObjectMapper objectMapper;

    public DeviceBindingResultMessageStrategy(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public String eventId(DeviceBindingResultOutbox event) {
        return event.getEventId();
    }

    @Override
    public void send(RabbitTemplate rabbitTemplate, DeviceBindingResultOutbox event,
                     CorrelationData correlationData) {
        try {
            DeviceBindingResultEventV1 payload = objectMapper.readValue(
                    event.getPayload(), DeviceBindingResultEventV1.class);
            rabbitTemplate.convertAndSend(DEVICE_BINDING_EXCHANGE,
                    DEVICE_BINDING_RESULT_ROUTING_KEY, payload, correlationData);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("无效的设备领用结果事件", exception);
        }
    }
}
