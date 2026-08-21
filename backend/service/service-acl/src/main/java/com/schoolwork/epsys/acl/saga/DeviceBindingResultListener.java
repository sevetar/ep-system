package com.schoolwork.epsys.acl.saga;

import com.schoolwork.epsys.model.shared.DeviceBindingResultEventV1;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import static com.schoolwork.epsys.mq.constant.MqConst.DEVICE_BINDING_RESULT_QUEUE;

@Component
@ConditionalOnProperty(prefix = "device-binding.saga", name = "enabled", havingValue = "true")
public class DeviceBindingResultListener {

    private final DeviceBindingSagaService sagaService;

    public DeviceBindingResultListener(DeviceBindingSagaService sagaService) {
        this.sagaService = sagaService;
    }

    @RabbitListener(queues = DEVICE_BINDING_RESULT_QUEUE)
    public void consume(DeviceBindingResultEventV1 event) {
        sagaService.applyResult(event);
    }
}
