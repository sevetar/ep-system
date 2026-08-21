package com.schoolwork.epsys.device.saga;

import com.schoolwork.epsys.model.shared.DeviceBindingRequestedEventV1;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import static com.schoolwork.epsys.mq.constant.MqConst.DEVICE_BINDING_REQUEST_QUEUE;

@Component
@ConditionalOnProperty(prefix = "device-binding.saga", name = "enabled", havingValue = "true")
public class DeviceBindingRequestListener {

    private final DeviceBindingCommandService commandService;

    public DeviceBindingRequestListener(DeviceBindingCommandService commandService) {
        this.commandService = commandService;
    }

    @RabbitListener(queues = DEVICE_BINDING_REQUEST_QUEUE)
    public void consume(DeviceBindingRequestedEventV1 event) {
        commandService.handle(event);
    }
}
