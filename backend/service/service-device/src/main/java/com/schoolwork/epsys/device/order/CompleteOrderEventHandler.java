package com.schoolwork.epsys.device.order;

import com.schoolwork.epsys.model.device.MaintainRecord;
import org.springframework.stereotype.Component;

@Component
public class CompleteOrderEventHandler implements OrderEventHandler {

    @Override
    public MaintainOrderEvent supports() {
        return MaintainOrderEvent.COMPLETE;
    }

    @Override
    public void apply(MaintainRecord order, OrderTransitionContext context) {
        order.setRepairProcess(context.repairProcess());
        order.setSolution(context.solution());
        order.setRootCause(context.rootCause());
        order.setVerificationResult(context.verificationResult());
        order.setReplacedParts(context.replacedParts());
        order.setKnowledgeTags(context.knowledgeTags());
        order.setEndTime(context.occurredAt());
    }
}
